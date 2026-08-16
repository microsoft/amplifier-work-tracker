"""Authentication for `amplifier-work-tracker web` -- ported from muxplex's
pattern (`muxplex/muxplex/auth.py`, the reference implementation this was
built against, per explicit request) and adapted to this package.

Kept identical to muxplex, deliberately:
  - PAM when available (`pam_available`), restricted to the running process
    owner (`authenticate_pam`) -- the same safety property muxplex enforces,
    unchanged: PAM proves *a* system password, but only for the account this
    server itself runs as, never an arbitrary username a caller supplies.
  - A generated password file (0600) as the fallback when PAM isn't
    importable, or when an operator explicitly asks for it.
  - Signed, timestamped session cookies via `itsdangerous.TimestampSigner`,
    with the signing secret persisted at a 0600 path.
  - An explicit, exact-path auth-exempt set for the middleware -- never
    prefix matching (see muxplex's own incident, documented in its
    `_is_real_static_asset` docstring, for why a suffix/prefix check on a
    path is a real vulnerability class, not theoretical).
  - `validate_next_path` / `build_login_redirect_url`, verbatim in logic --
    the sole guard against the post-login redirect becoming an open
    redirect.

Deliberate differences from muxplex, stated once here rather than scattered
as inline comments:
  - No localhost bypass. muxplex exempts client sockets at 127.0.0.1/::1
    from auth entirely -- a reasonable convenience for muxplex's single
    local trusted user. This service is explicitly meant to serve more than
    one person on the LAN (that is the entire feature request), and the
    task's own acceptance bar requires *observing* a real, enforced refusal
    from an unauthenticated caller -- a bypass that quietly waives auth for
    same-host requests would make that observation meaningless. Auth is
    therefore enforced identically regardless of client address.
  - Own config directory, `~/.config/amplifier-work-tracker/` -- never
    muxplex's `~/.config/muxplex/`. These are two independent services;
    sharing a directory would let one project's password/secret rotation
    silently affect the other.
  - Session cookies carry an *identity* string (the PAM username, or a
    fixed marker for password-mode logins) rather than muxplex's constant
    signed payload -- so the web UI can default the `actor` field on
    claim/resolve/add forms to whoever is actually logged in, without a
    separate identity store.
"""

from __future__ import annotations

import base64
import os
import pwd
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

CONFIG_DIR_NAME = "amplifier-work-tracker"

# The identity recorded in the session cookie for a password-mode login --
# there is no per-user distinction in that mode (see module docstring), so
# every successful password login is attributed to this fixed marker.
PASSWORD_MODE_IDENTITY = "operator"

SESSION_COOKIE_NAME = "amplifier_work_tracker_session"


# ---------------------------------------------------------------------------
# ?next= redirect validation -- verbatim logic from muxplex.auth, the sole
# guard against the post-login redirect becoming an open redirect.
# ---------------------------------------------------------------------------


def validate_next_path(next_value: str | None) -> str:
    """Validate a client-or-request-supplied ``?next=`` redirect target.

    Fails CLOSED to "/" on anything not unambiguously a same-origin,
    path-only value. See muxplex's `auth.validate_next_path` for the full
    enumeration of rejected shapes (protocol-relative, embedded scheme,
    backslash normalization tricks, path traversal) -- this is the same
    check, unchanged, because the hazard it defends against is identical
    here: an attacker-controlled `next` riding a real login redirect.
    """
    if not next_value or not isinstance(next_value, str):
        return "/"
    if any(ord(c) < 0x20 for c in next_value):
        return "/"
    if "\\" in next_value:
        return "/"
    if not next_value.startswith("/") or next_value.startswith("//"):
        return "/"
    lowered = next_value.lower()
    if "://" in lowered:
        return "/"
    for scheme in ("javascript:", "data:", "http:", "https:", "vbscript:", "file:"):
        if scheme in lowered:
            return "/"
    parsed = urlsplit(next_value)
    if parsed.scheme or parsed.netloc:
        return "/"
    if ".." in parsed.path.split("/"):
        return "/"
    return next_value


def build_login_redirect_url(next_value: str | None) -> str:
    """Build the `/login` redirect target, appending a validated `?next=`."""
    safe_next = validate_next_path(next_value)
    if safe_next == "/":
        return "/login"
    return f"/login?next={quote(safe_next, safe='')}"


# ---------------------------------------------------------------------------
# Config directory / password file / signing secret
# ---------------------------------------------------------------------------


def config_dir() -> Path:
    """`~/.config/amplifier-work-tracker/`, created (mode 0700) if needed."""
    d = Path.home() / ".config" / CONFIG_DIR_NAME
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    return d


def password_path() -> Path:
    return Path.home() / ".config" / CONFIG_DIR_NAME / "password"


def load_password() -> str | None:
    """Read the password file if it exists, return None otherwise."""
    path = password_path()
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip()


def generate_and_save_password() -> str:
    """Generate a random password, write it to the password file (0600),
    return it. Idempotent in effect only in the sense that a caller who
    wants "the current password" should prefer `load_password()` first --
    this always mints a *new* one."""
    pw = secrets.token_urlsafe(20)
    path = password_path()
    config_dir()  # ensures dir exists with mode 0700
    path.write_text(pw + "\n", encoding="utf-8")
    path.chmod(0o600)
    return pw


def secret_path() -> Path:
    return Path.home() / ".config" / CONFIG_DIR_NAME / "secret"


def load_or_create_secret() -> str:
    """Load the signing secret from file, or create one if it doesn't exist."""
    path = secret_path()
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    secret = secrets.token_urlsafe(32)
    config_dir()  # ensures dir exists with mode 0700
    path.write_text(secret + "\n", encoding="utf-8")
    path.chmod(0o600)
    return secret


# ---------------------------------------------------------------------------
# Session cookie signing / verification -- carries an identity string.
# ---------------------------------------------------------------------------

_SALT = "amplifier-work-tracker-session"


def create_session_cookie(secret: str, identity: str) -> str:
    """Create a signed, timestamped session cookie value carrying *identity*
    (the PAM username, or `PASSWORD_MODE_IDENTITY`)."""
    signer = TimestampSigner(secret, salt=_SALT)
    return signer.sign(identity).decode()


def verify_session_cookie(secret: str, cookie: str, ttl_seconds: int) -> str | None:
    """Verify a session cookie's signature and expiry, returning the
    identity string it carries if valid, or None if invalid/expired.

    `ttl_seconds<=0` means no server-side expiry check (session cookie
    only) -- same convention as muxplex.
    """
    signer = TimestampSigner(secret, salt=_SALT)
    try:
        max_age = ttl_seconds if ttl_seconds > 0 else None
        return signer.unsign(cookie, max_age=max_age).decode()
    except (BadSignature, SignatureExpired):
        return None


# ---------------------------------------------------------------------------
# PAM authentication
# ---------------------------------------------------------------------------


def pam_available() -> bool:
    """Check whether the python-pam module is importable."""
    try:
        import pam  # noqa: F401

        return True
    except ImportError:
        return False


def authenticate_pam(username: str, password: str) -> bool:
    """Authenticate via PAM. `username` must equal the running process
    owner -- this server proves only its own account's password, never an
    arbitrary system account a caller names."""
    import pam

    running_user = pwd.getpwuid(os.getuid()).pw_name
    if username != running_user:
        return False
    return bool(pam.authenticate(username, password, service="login"))


def running_user() -> str:
    """The account this process runs as -- the only username PAM mode will
    ever accept. Exposed so the login page can tell the human which
    username to type, instead of them having to guess."""
    return pwd.getpwuid(os.getuid()).pw_name


# ---------------------------------------------------------------------------
# Auth mode resolution
# ---------------------------------------------------------------------------

AuthMode = str  # "pam" | "password"


@dataclass
class AuthConfig:
    """Everything the auth middleware and /login route need, resolved once
    at startup (see `webapp.create_app`)."""

    mode: AuthMode
    secret: str
    ttl_seconds: int
    password: str = ""  # only meaningful when mode == "password"


def resolve_auth_mode(requested: str) -> AuthMode:
    """`requested` is one of "auto" | "pam" | "password" (the CLI's
    `--auth-mode`). "auto" picks PAM when importable, else password --
    never silently guesses past an explicit request."""
    if requested == "pam":
        if not pam_available():
            raise RuntimeError(
                "--auth-mode pam requested but the `pam` module is not importable "
                "-- install the `web` extra (`pip install amplifier-work-tracker[web]`), "
                "which pulls in python-pam"
            )
        return "pam"
    if requested == "password":
        return "password"
    if requested == "auto":
        return "pam" if pam_available() else "password"
    raise ValueError(f"unknown auth mode {requested!r}")


def check_credentials(
    auth_mode: AuthMode, username: str, password: str, config: AuthConfig
) -> str | None:
    """Validate credentials against the configured auth mode. Returns the
    identity string to store in the session cookie on success, or None on
    failure -- never raises for a bad credential (only for a genuine
    programming error, e.g. an unknown mode)."""
    if auth_mode == "pam":
        if authenticate_pam(username, password):
            return username
        return None
    if auth_mode == "password":
        if secrets.compare_digest(password.encode("utf-8"), config.password.encode("utf-8")):
            return PASSWORD_MODE_IDENTITY
        return None
    raise ValueError(f"unknown auth mode {auth_mode!r}")


def decode_basic_auth(header_value: str) -> tuple[str, str] | None:
    """Decode an `Authorization: Basic ...` header value to (username,
    password), or None if malformed. Never raises."""
    if not header_value.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(header_value[6:]).decode("utf-8")
    except Exception:  # noqa: BLE001 -- malformed header is just "not authenticated"
        return None
    username, sep, pw = decoded.partition(":")
    if not sep:
        return None
    return username, pw


__all__ = [
    "PASSWORD_MODE_IDENTITY",
    "SESSION_COOKIE_NAME",
    "AuthConfig",
    "AuthMode",
    "authenticate_pam",
    "build_login_redirect_url",
    "check_credentials",
    "config_dir",
    "create_session_cookie",
    "decode_basic_auth",
    "generate_and_save_password",
    "load_or_create_secret",
    "load_password",
    "pam_available",
    "password_path",
    "resolve_auth_mode",
    "running_user",
    "secret_path",
    "validate_next_path",
    "verify_session_cookie",
]
