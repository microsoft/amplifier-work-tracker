"""Plain-HTTP trust-bootstrap: install this host's local CA WITHOUT first
hitting an untrusted-cert warning or a login.

The problem this fixes
-----------------------
The dashboard serves HTTPS-only once a certificate is configured. A brand
new device's first visit is otherwise the worst-ordered bootstrap possible:
scary cert warning -> click through -> log in -> find `/setup` -> download
the CA -> install. The trust anchor (the CA certificate) was being handed
out *over the very certificate it establishes trust for*, and behind auth.

A CA certificate is PUBLIC -- a trust anchor, not a secret (the private key
never leaves this host; see `webtls.default_ca_key_path()`, never served
anywhere). So it should be handed out over an origin that needs no trust
and no login at all: plain HTTP.

This module is that origin. It is a SEPARATE, tiny, deliberately
minimal ASGI app -- never the dashboard's own `webapp.create_app()` -- run
on a companion plain-HTTP port ALONGSIDE the HTTPS dashboard (see
`webapp.run` / `supervisor.web_server_loop` for how the two listeners are
wired up together). It carries NO auth middleware (there is nothing here
worth gating) and exposes exactly four things:

  GET /trust               an on-theme onboarding page: OS-detected install
                           steps, a CA download button, an iOS/macOS
                           "Install profile" button, and a "Continue to the
                           app" link to the real HTTPS origin.
  GET /ca.crt              the CA certificate bytes, unauthenticated.
  GET /trust.mobileconfig  the same CA wrapped as an Apple configuration
                           profile, for iOS/macOS's guided install flow.
  everything else          301/302 (well, 302) redirect to the HTTPS
                           origin, same host, same path -- so a stray bookmark
                           or link to the plain-http port still lands
                           somewhere useful instead of a dead end.

Honesty over convenience: `/trust`, `/ca.crt`, and `/trust.mobileconfig`
only ever offer a REAL local-CA download when the certificate this server
is actually serving over HTTPS was signed by a local CA (`--method ca`,
see `webtls.generate_leaf_signed_by_ca`). A Tailscale/public-CA cert is
already trusted -- nothing to install, and the page says so plainly. A
self-signed cert has no CA at all -- the page says that too, honestly,
rather than offering a bogus download. See `_classify_trust_state`.

No new runtime dependencies: the Apple profile is built with stdlib
`plistlib` (a plist is just XML; `cryptography` -- already a `web`-extra
dependency, see `webtls.py` -- supplies the DER bytes and fingerprint).
There is deliberately no QR code image here: neither `qrcode` nor `Pillow`
is a project dependency, and adding either just for a "scan this to hop to
your phone" nicety is not worth a new dependency for a nicety `/trust`
already achieves another way -- the URL itself, rendered large and
selectable, right on the page.
"""

from __future__ import annotations

import html
import plistlib
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.responses import Response

from . import webtheme as T
from . import webtls as WT

# ---------------------------------------------------------------------------
# Cert classification -- mirrors webapp.py's `_tls_status_html` classification
# (self-signed / CA-signed / externally-issued) exactly, so `/trust` and
# `/setup` can never disagree about what kind of certificate is active.
# Deliberately re-derived here rather than imported from webapp.py: this
# module must stay importable (and this app runnable) with NO dependency on
# webapp.py's auth/session machinery -- see this module's own docstring on
# why the trust-bootstrap listener carries no auth at all.
# ---------------------------------------------------------------------------


@dataclass
class TrustState:
    kind: str  # "none" | "ca" | "selfsigned" | "public"
    ca_cert_path: Path | None = None


def _classify_trust_state(tls_cert_path: str | None) -> TrustState:
    """Classify the certificate actually being served over HTTPS right now.

    Reads fresh from disk on every call (cheap: a stat + a parse) rather
    than caching at app-creation time, so a cert rotated without a restart
    of THIS listener (unlikely, but the primary HTTPS server already can't
    hot-swap its own TLS material either -- see webapp.py's `/setup/tls`
    docstring) is still reflected honestly the next time someone loads
    `/trust`.
    """
    if not tls_cert_path:
        return TrustState(kind="none")
    cert_path = Path(tls_cert_path)
    info = WT.get_cert_info(cert_path)
    if info is None:
        return TrustState(kind="none")
    ca_cert_path = WT.default_ca_cert_path()
    ca_signed = ca_cert_path.exists() and WT.is_signed_by_ca(cert_path, ca_cert_path)
    if info["self_signed"]:
        return TrustState(kind="selfsigned")
    if ca_signed:
        return TrustState(kind="ca", ca_cert_path=ca_cert_path)
    return TrustState(kind="public")


# ---------------------------------------------------------------------------
# OS detection -- coarse, best-effort, User-Agent substring matching. Wrong
# in rare edge cases (a UA-spoofing browser, an unusual embedded webview)
# costs nothing worse than showing generic instructions instead of the
# exact-right ones; every OS's instructions are always available in the
# "other devices" section regardless of what was detected. Order matters:
# Android UAs also contain "Linux" and must be checked first; iOS UAs are
# checked before macOS for the same reason (some iPadOS UAs report as Mac).
# ---------------------------------------------------------------------------


def _detect_os(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if "iphone" in ua or "ipad" in ua or "ipod" in ua:
        return "ios"
    if "android" in ua:
        return "android"
    if "windows" in ua:
        return "windows"
    if "macintosh" in ua or "mac os x" in ua:
        return "macos"
    if "linux" in ua:
        return "linux"
    return "unknown"


_OS_INSTRUCTIONS: dict[str, tuple[str, str]] = {
    "ios": (
        "iOS",
        "Tap <b>Install profile</b> below. Safari opens the profile installer directly -- "
        "tap Install, then finish by enabling full trust for it under "
        "Settings &rsaquo; General &rsaquo; About &rsaquo; Certificate Trust Settings.",
    ),
    "android": (
        "Android",
        "Tap <b>Download CA certificate</b> below, then open "
        "Settings &rsaquo; Security &rsaquo; Encryption &amp; credentials &rsaquo; "
        "Install a certificate &rsaquo; CA certificate, and select the downloaded file.",
    ),
    "macos": (
        "macOS",
        "Tap <b>Install profile</b> below (or download the certificate and double-click it "
        "in Keychain Access), then set it to <i>Always Trust</i> in "
        "System Settings &rsaquo; Privacy &amp; Security &rsaquo; Certificates.",
    ),
    "windows": (
        "Windows",
        "Tap <b>Download CA certificate</b> below, then run in PowerShell "
        "(no admin needed): <code>Import-Certificate -FilePath &lt;path-to-ca.crt&gt; "
        "-CertStoreLocation Cert:\\CurrentUser\\Root</code>",
    ),
    "linux": (
        "Linux",
        "Tap <b>Download CA certificate</b> below, then run: "
        "<code>sudo cp &lt;path-to-ca.crt&gt; /usr/local/share/ca-certificates/ "
        "&amp;&amp; sudo update-ca-certificates</code>",
    ),
    "unknown": (
        "This device",
        "Tap <b>Download CA certificate</b> below and install it via your device's "
        "certificate/trust settings.",
    ),
}


# ---------------------------------------------------------------------------
# Apple configuration profile (.mobileconfig) -- a plist wrapping the CA
# certificate as a `com.apple.security.root` payload, so iOS/macOS offer
# their own guided install flow instead of a bare certificate file. Built
# entirely from stdlib `plistlib` + `cryptography` (already a dependency of
# the `web` extra for TLS generation itself) -- no new runtime dependency.
# ---------------------------------------------------------------------------

# An arbitrary, FIXED namespace UUID for this app's own deterministic UUID5
# derivations -- never regenerated, never random. Its only job is to seed
# `uuid.uuid5` so the SAME CA certificate always produces the SAME
# PayloadUUIDs (see `_stable_uuid`'s docstring for why that matters).
_MOBILECONFIG_NAMESPACE = uuid.UUID("a3f1c2d4-5b6e-4a7f-8c9d-0e1f2a3b4c5d")


def _stable_uuid(fingerprint_hex: str, suffix: str) -> str:
    """A PayloadUUID derived deterministically from the CA certificate's own
    SHA-256 fingerprint, never `uuid.uuid4()`.

    Re-downloading `/trust.mobileconfig` for the SAME CA must produce byte-
    identical PayloadUUIDs every time -- iOS/macOS treat a profile's
    PayloadUUID as its identity; a random UUID on every download would make
    every re-download look like a brand new, unrelated profile to install
    (and never let a device recognise "I already have this one").
    """
    return str(uuid.uuid5(_MOBILECONFIG_NAMESPACE, f"{fingerprint_hex}:{suffix}")).upper()


def _build_mobileconfig(ca_cert_path: Path) -> bytes:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization

    pem_bytes = ca_cert_path.read_bytes()
    cert = x509.load_pem_x509_certificate(pem_bytes)
    der_bytes = cert.public_bytes(serialization.Encoding.DER)
    fingerprint_hex = cert.fingerprint(hashes.SHA256()).hex()

    cert_uuid = _stable_uuid(fingerprint_hex, "cert")
    profile_uuid = _stable_uuid(fingerprint_hex, "profile")

    profile = {
        "PayloadContent": [
            {
                "PayloadCertificateFileName": "ca.crt",
                "PayloadContent": der_bytes,
                "PayloadDescription": (
                    "Adds amplifier-work-tracker's local CA root certificate so this "
                    "device trusts its HTTPS certificate."
                ),
                "PayloadDisplayName": "amplifier-work-tracker Local CA",
                "PayloadIdentifier": f"com.amplifier-work-tracker.trust.cert.{fingerprint_hex}",
                "PayloadType": "com.apple.security.root",
                "PayloadUUID": cert_uuid,
                "PayloadVersion": 1,
            }
        ],
        "PayloadDescription": (
            "Installs the amplifier-work-tracker local CA certificate. You will still need "
            "to enable full trust for it under Settings \u203a General \u203a About \u203a "
            "Certificate Trust Settings (iOS) or Keychain Access (macOS) -- Apple requires "
            "that explicit step for any newly-installed root certificate."
        ),
        "PayloadDisplayName": "amplifier-work-tracker Trust",
        "PayloadIdentifier": f"com.amplifier-work-tracker.trust.{fingerprint_hex}",
        "PayloadOrganization": "amplifier-work-tracker",
        "PayloadRemovalDisallowed": False,
        "PayloadType": "Configuration",
        "PayloadUUID": profile_uuid,
        "PayloadVersion": 1,
    }
    return plistlib.dumps(profile)


# ---------------------------------------------------------------------------
# Page rendering. This module ships NO stylesheet of its own.
#
# It used to: an inline stylesheet block right here re-declaring the whole
# role set (--ground / --raise / --ink / --mid / --quiet / --amber / --rule /
# --rule-hi) as its own literal near-black-and-warm-amber values -- the
# retired pre-blend-3 palette -- explicitly so it would not have to import
# `webtheme`. That independence bought one import edge and cost a second
# source of visual truth, which then drifted three palette generations behind
# the live `--color-ground:#05070f` without anyone noticing. operator-surface.v1
# Core 4 forbids exactly that -- a stylesheet block outside the token module.
#
# The sheet now lives in `webtheme.TRUST_CSS`, composed from the SAME
# `TOKENS_CSS` the dashboard uses, and `webtheme.trust_style_tag()` emits the
# whole style element -- so there is no stylesheet, and no style tag, anywhere
# in this file. `webtheme` is a leaf module (stdlib only, no FastAPI,
# no `webapp`), so importing it costs this app nothing at import time.
#
# The page stays SELF-CONTAINED, which it must: the sheet is INLINED into the
# document, never fetched. A device reading this page has not installed the CA
# yet -- an external asset link would be a broken fetch at the worst possible
# moment.
# ---------------------------------------------------------------------------


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _ca_install_section(*, os_hint: str) -> str:
    primary_label, primary_instr = _OS_INSTRUCTIONS.get(os_hint, _OS_INSTRUCTIONS["unknown"])
    other_rows = "".join(
        f'<div class="formsec"><span class="flegend">{_esc(label)}</span>'
        f'<p class="subtle">{instr}</p></div>'
        for key, (label, instr) in _OS_INSTRUCTIONS.items()
        if key not in (os_hint, "unknown")
    )
    mobileconfig_btn = (
        '<a class="btn secondary" href="/trust.mobileconfig">Install profile (recommended)</a>'
        if os_hint in ("ios", "macos")
        else ""
    )
    return f"""
    <div class="formsec highlight">
      <span class="flegend">Detected: {_esc(primary_label)}</span>
      <p class="subtle">{primary_instr}</p>
      <p class="mt-4">
        <a class="btn" href="/ca.crt">Download CA certificate</a>
        {mobileconfig_btn}
      </p>
    </div>
    <details>
      <summary>Other devices / operating systems</summary>
      {other_rows}
    </details>
    """


def _trust_page_html(
    *, state: TrustState, hostname: str, https_port: int, os_hint: str, request_url: str
) -> str:
    https_url = f"https://{hostname}:{https_port}/"
    continue_btn = (
        f'<p class="mt-5"><a class="btn" href="{_esc(https_url)}">'
        "Continue to the app &rarr;</a></p>"
    )

    if state.kind == "none":
        body = (
            '<p class="lead">No certificate is configured on this server yet -- there is '
            "nothing to trust. Once HTTPS is set up, revisit this page to install its "
            "certificate.</p>" + continue_btn
        )
    elif state.kind == "public":
        body = (
            '<p class="lead">Good news &mdash; this server\u2019s certificate is already '
            "publicly trusted. Your browser accepts it with no warning and nothing to "
            "install.</p>" + continue_btn
        )
    elif state.kind == "selfsigned":
        body = (
            '<p class="lead">This server uses a self-signed certificate &mdash; there is no '
            "CA to install. Continue to the app and click through the one-time browser "
            "security warning (needed once per browser, not per visit).</p>" + continue_btn
        )
    else:  # "ca"
        body = _ca_install_section(os_hint=os_hint) + continue_btn

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trust this server &middot; amplifier-work-tracker</title>
{T.trust_style_tag()}
</head>
<body>
  <main>
    <h1>Trust this server</h1>
    <p class="subtle">Install this certificate to trust <code>{_esc(hostname)}</code> on this
      device. This is a one-time step per device &mdash; not per visit.</p>
    {body}
    <p class="subtle mt-8">On another device? Open this same page there:</p>
    <p class="url-box">{_esc(request_url)}</p>
  </main>
</body>
</html>"""


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_trust_app(*, https_port: int, tls_cert_path: str | None) -> FastAPI:
    """Build the standalone, unauthenticated plain-HTTP trust-bootstrap app.

    `https_port` is the port the REAL dashboard serves HTTPS on -- baked in
    at creation time (it does not change without a restart, which already
    rebuilds this app). `tls_cert_path` is the resolved certificate path the
    HTTPS server is ACTUALLY using (whatever `resolve_web_config` decided --
    explicit `--tls-cert` or the auto-detected default), so `/trust`'s
    classification can never drift from what is really being served.

    Deliberately never imports `webapp.py` or adds any auth middleware --
    see this module's own docstring.
    """
    app = FastAPI(title="amplifier-work-tracker trust bootstrap", docs_url=None, redoc_url=None)

    @app.get("/trust", response_class=HTMLResponse)
    async def trust_page(request: Request):  # type: ignore[no-untyped-def]
        state = _classify_trust_state(tls_cert_path)
        os_hint = _detect_os(request.headers.get("user-agent", ""))
        hostname = request.url.hostname or "this-server"
        html_body = _trust_page_html(
            state=state,
            hostname=hostname,
            https_port=https_port,
            os_hint=os_hint,
            request_url=str(request.url),
        )
        return Response(html_body, media_type="text/html", headers={"Cache-Control": "no-cache"})

    @app.get("/ca.crt")
    async def ca_download():  # type: ignore[no-untyped-def]
        state = _classify_trust_state(tls_cert_path)
        if state.kind != "ca" or state.ca_cert_path is None:
            return JSONResponse(
                {"detail": "no local CA certificate is configured on this host"}, status_code=404
            )
        return Response(
            state.ca_cert_path.read_bytes(),
            media_type="application/x-x509-ca-cert",
            headers={
                "Content-Disposition": 'attachment; filename="amplifier-work-tracker-ca.crt"',
                "Cache-Control": "no-cache",
            },
        )

    @app.get("/trust.mobileconfig")
    async def mobileconfig():  # type: ignore[no-untyped-def]
        state = _classify_trust_state(tls_cert_path)
        if state.kind != "ca" or state.ca_cert_path is None:
            return JSONResponse(
                {"detail": "no local CA certificate is configured on this host"}, status_code=404
            )
        data = _build_mobileconfig(state.ca_cert_path)
        return Response(
            data,
            media_type="application/x-apple-aspen-config",
            headers={
                "Content-Disposition": (
                    'attachment; filename="amplifier-work-tracker-trust.mobileconfig"'
                ),
                "Cache-Control": "no-cache",
            },
        )

    # Everything else -- the redirect. Declared LAST so it never shadows the
    # three routes above (FastAPI/Starlette match in declaration order).
    # Matches "/" itself too: Starlette's `path` converter accepts a
    # zero-length capture, so `full_path == ""` for the bare root.
    @app.api_route("/{full_path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
    async def redirect_to_https(request: Request, full_path: str):  # type: ignore[no-untyped-def]
        hostname = request.url.hostname or "localhost"
        path = full_path if full_path.startswith("/") else f"/{full_path}"
        target = f"https://{hostname}:{https_port}{path}"
        if request.url.query:
            target = f"{target}?{request.url.query}"
        return RedirectResponse(url=target, status_code=302)

    return app


__all__ = [
    "TrustState",
    "create_trust_app",
]
