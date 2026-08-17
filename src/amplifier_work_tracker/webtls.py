"""TLS certificate generation and inspection for `amplifier-work-tracker web`
/ `serve --web-port`.

Ported from muxplex's `tls.py` (the reference implementation this was built
against, per explicit request) and adapted to this package. Kept identical
to muxplex, deliberately:

  - `generate_self_signed` / `generate_local_ca` + `generate_leaf_signed_by_ca`
    / `get_cert_info` -- same shapes, same return dict keys.
  - The SAN-list construction: every generated cert carries a
    `subjectAlternativeName` covering hostname + `.local` + `localhost` +
    loopback IPs -- modern clients validate SAN, not CN, so this is the part
    that actually matters for a browser to accept the cert at all.
  - `_common_name`'s CN truncation to <=64 chars (RFC 5280 `ub-common-name`)
    -- `cryptography` raises rather than truncates, and real hostnames
    (Tailscale MagicDNS names, corporate FQDNs, CI runner names) routinely
    exceed 64 characters. See that function's own docstring for why
    truncating is safe: CN stopped being what clients validate against once
    RFC 6125 superseded RFC 2818, and the full name is always in the SAN
    list built alongside it.
  - `_default_lan_ip`'s connected-UDP-socket trick (no packets sent) and
    `_default_tailnet_name`'s best-effort, silent-on-failure `tailscale
    status --self --json` probe.

Deliberately different from muxplex, stated once here rather than scattered:

  - Own config directory, `~/.config/amplifier-work-tracker/tls/` -- never
    muxplex's `~/.config/muxplex/`. Deliberately does NOT import
    `webauth.py` for this (even though `webauth.CONFIG_DIR_NAME` names the
    same directory) so that importing THIS module never requires
    `itsdangerous` -- every import in this module is stdlib, and the
    `cryptography` import needed to actually generate a certificate happens
    lazily, inside each `generate_*` function, exactly like muxplex's own
    `tls.py` -- so `import webtls` alone never requires the `web` extra to
    be installed.
  - `generate_self_signed` additionally accepts an optional `ip_addresses`
    parameter (muxplex's version only takes `hostnames`, hardcoding the two
    loopback IPs). This package's `setup-tls --method selfsigned` wants the
    detected LAN IP (and tailnet name, folded into `hostnames`) in the SAN
    too, so a self-signed cert is not thinner than a CA-signed leaf for the
    same host -- see `default_leaf_sans()`.
  - No `mkcert`/full Tailscale-managed-cert auto-detection chain -- this
    package's `setup-tls --method auto` tries Tailscale, then falls back to
    self-signed. `--method ca` (a persistent local CA signing a short-lived
    leaf, for browser-trusted HTTPS without a public domain) is supported
    exactly as muxplex implements it.

Provides:
  generate_self_signed(cert_path, key_path, hostnames=None, ip_addresses=None, days_valid=3650)
  generate_local_ca(ca_cert_path, ca_key_path, days_valid=3650, common_name=...)
  generate_leaf_signed_by_ca(ca_cert_path, ca_key_path, leaf_cert_path,
                             leaf_key_path, hostnames, ip_addresses,
                             days_valid=397)
  get_cert_info(cert_path)
  detect_tailscale() / generate_tailscale(cert_path, key_path, hostname)
  default_tls_dir() / default_cert_path() / default_key_path()
  default_ca_dir() / default_ca_cert_path() / default_ca_key_path()
  default_leaf_sans()
"""

from __future__ import annotations

import ipaddress
import socket
from datetime import UTC, datetime
from pathlib import Path

# Own config directory -- see module docstring for why this is a local
# constant rather than an import of webauth.CONFIG_DIR_NAME.
CONFIG_DIR_NAME = "amplifier-work-tracker"


def default_tls_dir() -> Path:
    """`~/.config/amplifier-work-tracker/tls/`, created (mode 0700) if needed."""
    d = Path.home() / ".config" / CONFIG_DIR_NAME / "tls"
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    return d


def default_cert_path() -> Path:
    """Where `setup-tls` writes the leaf/self-signed certificate, and where
    `web`/`serve --web-port` auto-detect one from if `--tls-cert`/
    `--tls-key` (or `--web-tls-cert`/`--web-tls-key`) are not given."""
    return default_tls_dir() / "cert.pem"


def default_key_path() -> Path:
    return default_tls_dir() / "key.pem"


def default_ca_dir() -> Path:
    """`~/.config/amplifier-work-tracker/tls/ca/`, created (mode 0700) if needed."""
    d = default_tls_dir() / "ca"
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    return d


def default_ca_cert_path() -> Path:
    return default_ca_dir() / "ca.crt"


def default_ca_key_path() -> Path:
    return default_ca_dir() / "ca.key"


def _default_hostnames() -> list[str]:
    hostname = socket.gethostname()
    return [hostname, f"{hostname}.local", "localhost"]


# RFC 5280 caps a CommonName at 64 characters (ub-common-name), and
# `cryptography` enforces it by raising rather than truncating. Real
# hostnames do exceed it: long Tailscale MagicDNS names, corporate FQDNs,
# and cloud instance names all get there.
_CN_MAX_LEN = 64


def _common_name(hostname: str) -> str:
    """Fit *hostname* into an X.509 CommonName.

    Truncating is safe, and is the right trade here. CN stopped being the
    field clients validate against when RFC 2818 was superseded by RFC 6125
    -- every modern TLS client reads subjectAltName, and the FULL hostname
    is always in the SAN list this module builds alongside the subject. So
    a shortened CN costs nothing a client will ever notice, whereas the
    alternative costs the user their certificate: cert generation raises a
    bare `ValueError: Attribute's length must be >= 1 and <= 64` from deep
    inside cryptography, with nothing naming the hostname as the cause.
    """
    return hostname[:_CN_MAX_LEN]


def _default_lan_ip() -> str | None:
    """Detect the primary outbound IPv4 address.

    Returns the local IP that would be used to reach an external host (no
    packets are actually sent -- a connected UDP socket just asks the
    kernel which interface would route the traffic). Returns None on
    failure (no network, all-loopback configuration, etc.).
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 8.8.8.8:80 is a routing target; UDP connect doesn't transmit.
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
    if ip in ("0.0.0.0", "127.0.0.1"):
        return None
    return ip


def _default_tailnet_name() -> str | None:
    """Return this host's MagicDNS name (e.g. 'spark-1.tail8f3c4e.ts.net'),
    or None if Tailscale is not installed / not connected / has no DNSName.

    Best-effort and short-timeout -- failure is silent and returns None.
    """
    import json
    import shutil
    import subprocess

    if not shutil.which("tailscale"):
        return None
    try:
        result = subprocess.run(
            ["tailscale", "status", "--self", "--json"],
            timeout=5,
            capture_output=True,
            text=True,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    self_info = data.get("Self") or {}
    dns_name = self_info.get("DNSName", "") or data.get("DNSName", "")
    if not dns_name:
        return None
    return dns_name.rstrip(".")


def default_leaf_sans() -> tuple[list[str], list[str]]:
    """Assemble the full SAN inputs for a locally-generated certificate:
    hostname + `.local` + `localhost` + the tailnet MagicDNS name (if
    reachable) for DNS names, and `127.0.0.1` + `::1` + the detected LAN IP
    (if any) for IP addresses.

    Shared by both `setup-tls --method selfsigned` and `--method ca`, so a
    self-signed certificate is not artificially thinner (missing the LAN IP
    a browser on another device would actually connect to) than a
    CA-signed leaf for the identical host.
    """
    hostnames = list(_default_hostnames())
    tailnet_name = _default_tailnet_name()
    if tailnet_name and tailnet_name not in hostnames:
        hostnames.append(tailnet_name)

    ips = ["127.0.0.1", "::1"]
    lan_ip = _default_lan_ip()
    if lan_ip and lan_ip not in ips:
        ips.append(lan_ip)

    return hostnames, ips


def generate_self_signed(
    cert_path,
    key_path,
    hostnames: list[str] | None = None,
    ip_addresses: list[str] | None = None,
    days_valid: int = 3650,
) -> dict:
    """Generate a self-signed TLS certificate and private key.

    Args:
        cert_path: Destination path for the certificate PEM file.
        key_path:  Destination path for the private key PEM file.
        hostnames: DNS names to include. Defaults to [hostname, hostname.local, localhost].
        ip_addresses: Additional IPv4/IPv6 strings for SAN IP entries (beyond
            the always-included 127.0.0.1/::1). Invalid or duplicate entries
            are skipped silently.
        days_valid: Certificate validity period in days. Default 3650 (~10 years).

    Returns:
        dict with keys: method, cert_path, key_path, hostnames, expires.
        `hostnames` in the return value is DNS names + any valid IP strings
        combined, for display purposes.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    if hostnames is None:
        hostnames = _default_hostnames()

    cert_path = Path(cert_path)
    key_path = Path(key_path)

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, _common_name(hostnames[0])),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "amplifier-work-tracker"),
        ]
    )

    san_entries: list[x509.GeneralName] = [x509.DNSName(h) for h in hostnames]
    loopback: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = [
        ipaddress.IPv4Address("127.0.0.1"),
        ipaddress.IPv6Address("::1"),
    ]
    for addr in loopback:
        san_entries.append(x509.IPAddress(addr))

    valid_ips: list[str] = []
    if ip_addresses:
        for ip_str in ip_addresses:
            try:
                addr = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if addr in loopback:
                continue
            san_entries.append(x509.IPAddress(addr))
            valid_ips.append(ip_str)

    now = datetime.now(UTC)

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(datetime.fromtimestamp(now.timestamp() + days_valid * 86400, tz=UTC))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .sign(private_key, hashes.SHA256())
    )

    try:
        expires = cert.not_valid_after_utc  # type: ignore[attr-defined]
    except AttributeError:
        expires = cert.not_valid_after  # type: ignore[attr-defined]

    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path.touch(mode=0o600, exist_ok=True)
    key_path.write_bytes(key_pem)
    key_path.chmod(0o600)

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    cert_path.write_bytes(cert_pem)

    return {
        "method": "selfsigned",
        "cert_path": str(cert_path),
        "key_path": str(key_path),
        "hostnames": list(hostnames) + valid_ips,
        "expires": expires,
    }


def generate_local_ca(
    ca_cert_path,
    ca_key_path,
    days_valid: int = 3650,
    common_name: str = "amplifier-work-tracker Local CA",
) -> dict:
    """Generate (or reuse) a persistent local CA for signing leaf certs.

    The CA is suitable for installation into OS / browser trust stores:
    BasicConstraints CA:TRUE (path_length=0), KeyUsage keyCertSign+cRLSign,
    SubjectKeyIdentifier present.

    Idempotent: if both ca_cert_path and ca_key_path already exist, this
    function does nothing and returns metadata for the existing CA. To
    regenerate, delete the files first.

    Returns:
        dict with keys: ca_cert_path, ca_key_path, common_name, expires,
        regenerated (True if newly generated, False if reused).
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    ca_cert_path = Path(ca_cert_path)
    ca_key_path = Path(ca_key_path)

    if ca_cert_path.exists() and ca_key_path.exists():
        info = get_cert_info(ca_cert_path)
        return {
            "ca_cert_path": str(ca_cert_path),
            "ca_key_path": str(ca_key_path),
            "common_name": common_name,
            "expires": info["expires"] if info else None,
            "regenerated": False,
        }

    ca_cert_path.parent.mkdir(parents=True, exist_ok=True)
    ca_key_path.parent.mkdir(parents=True, exist_ok=True)

    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, _common_name(common_name)),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "amplifier-work-tracker"),
        ]
    )

    now = datetime.now(UTC)

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(datetime.fromtimestamp(now.timestamp() + days_valid * 86400, tz=UTC))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )

    # Write key with restricted permissions (touch 0o600 BEFORE write to
    # avoid the world-readable window during file creation).
    key_pem = ca_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    ca_key_path.touch(mode=0o600, exist_ok=True)
    ca_key_path.write_bytes(key_pem)
    ca_key_path.chmod(0o600)

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    ca_cert_path.write_bytes(cert_pem)

    try:
        expires = cert.not_valid_after_utc  # type: ignore[attr-defined]
    except AttributeError:
        expires = cert.not_valid_after  # type: ignore[attr-defined]

    return {
        "ca_cert_path": str(ca_cert_path),
        "ca_key_path": str(ca_key_path),
        "common_name": common_name,
        "expires": expires,
        "regenerated": True,
    }


def generate_leaf_signed_by_ca(
    ca_cert_path,
    ca_key_path,
    leaf_cert_path,
    leaf_key_path,
    hostnames: list[str],
    ip_addresses: list[str] | None = None,
    days_valid: int = 397,
) -> dict:
    """Generate a leaf TLS certificate signed by a local CA.

    The leaf is suitable for serving HTTPS: KeyUsage digitalSignature +
    keyEncipherment, ExtendedKeyUsage serverAuth, SAN populated from
    hostnames + ip_addresses, AuthorityKeyIdentifier linked to the CA.

    Args:
        ca_cert_path:   Path to the CA certificate PEM.
        ca_key_path:    Path to the CA private key PEM.
        leaf_cert_path: Destination for the leaf certificate.
        leaf_key_path:  Destination for the leaf private key.
        hostnames:      DNS names to include in SAN. The first is also used
                        as the leaf's CN.
        ip_addresses:   Optional IPv4/IPv6 strings to include as IP SAN
                        entries. Invalid entries are skipped silently.
        days_valid:     Leaf validity in days. Default 397 -- just under
                        the CA/B Forum 398-day enforcement ceiling that
                        Apple/Chrome also apply to privately-installed
                        roots in many recent versions.

    Returns:
        dict with keys: method, cert_path, key_path, hostnames, expires.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    if not hostnames:
        raise ValueError("at least one hostname is required for leaf certificate")

    ca_cert_path = Path(ca_cert_path)
    ca_key_path = Path(ca_key_path)
    leaf_cert_path = Path(leaf_cert_path)
    leaf_key_path = Path(leaf_key_path)

    leaf_cert_path.parent.mkdir(parents=True, exist_ok=True)
    leaf_key_path.parent.mkdir(parents=True, exist_ok=True)

    ca_cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
    ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)

    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, _common_name(hostnames[0])),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "amplifier-work-tracker"),
        ]
    )

    san_entries: list[x509.GeneralName] = [x509.DNSName(h) for h in hostnames]
    valid_ips: list[str] = []
    if ip_addresses:
        for ip_str in ip_addresses:
            try:
                addr = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            san_entries.append(x509.IPAddress(addr))
            valid_ips.append(ip_str)

    now = datetime.now(UTC)

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(datetime.fromtimestamp(now.timestamp() + days_valid * 86400, tz=UTC))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()),  # type: ignore[arg-type]
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())  # type: ignore[arg-type]
    )

    key_pem = leaf_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    leaf_key_path.touch(mode=0o600, exist_ok=True)
    leaf_key_path.write_bytes(key_pem)
    leaf_key_path.chmod(0o600)

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    leaf_cert_path.write_bytes(cert_pem)

    try:
        expires = cert.not_valid_after_utc  # type: ignore[attr-defined]
    except AttributeError:
        expires = cert.not_valid_after  # type: ignore[attr-defined]

    display_hostnames = list(hostnames) + valid_ips

    return {
        "method": "ca",
        "cert_path": str(leaf_cert_path),
        "key_path": str(leaf_key_path),
        "hostnames": display_hostnames,
        "expires": expires,
    }


def detect_tailscale() -> dict | None:
    """Probe for Tailscale and return connection info if available.

    Checks whether the Tailscale CLI is installed, verifies the node is
    connected, and confirms HTTPS certificate domains are enabled.

    Returns:
        dict with keys: hostname (str), ips (list[str]), cert_domains (list[str])
        if Tailscale is installed, connected, and cert domains are configured.
        Returns None if any of these conditions are not met.
    """
    import json
    import shutil
    import subprocess

    if not shutil.which("tailscale"):
        return None

    try:
        result = subprocess.run(
            ["tailscale", "status", "--self", "--json"],
            timeout=10,
            capture_output=True,
            text=True,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    if result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    self_info = data.get("Self") or {}
    dns_name = self_info.get("DNSName", "") or data.get("DNSName", "")
    cert_domains = data.get("CertDomains") or []
    ips = data.get("TailscaleIPs") or []

    if not dns_name or not cert_domains:
        return None

    return {
        "hostname": dns_name.rstrip("."),
        "ips": ips,
        "cert_domains": cert_domains,
    }


def generate_tailscale(cert_path, key_path, hostname: str) -> dict | None:
    """Obtain a Let's Encrypt certificate via Tailscale.

    Args:
        cert_path: Destination path for the certificate PEM file.
        key_path:  Destination path for the private key PEM file.
        hostname:  Tailscale hostname to request a certificate for.

    Returns:
        dict with keys: method, cert_path, key_path, hostnames, expires.
        Returns None on failure (non-zero exit, timeout, OS error, or missing files).
    """
    import subprocess

    cert_path = Path(cert_path)
    key_path = Path(key_path)

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            [
                "tailscale",
                "cert",
                "--cert-file",
                str(cert_path),
                "--key-file",
                str(key_path),
                hostname,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    if result.returncode != 0:
        return None

    if not cert_path.exists() or not key_path.exists():
        return None

    key_path.chmod(0o600)

    info = get_cert_info(cert_path)
    if info is None:
        return None

    return {
        "method": "tailscale",
        "cert_path": str(cert_path),
        "key_path": str(key_path),
        "hostnames": info["hostnames"],
        "expires": info["expires"],
    }


def get_cert_info(cert_path) -> dict | None:
    """Inspect a PEM certificate and return metadata.

    Args:
        cert_path: Path to the PEM certificate file.

    Returns:
        dict with expires, not_before, hostnames (DNS names + IPs from SANs),
        serial, issuer_common_name (the issuer's CN, or None if it has none),
        and self_signed (True when issuer == subject -- the same check
        `generate_self_signed` itself produces, since that function sets
        both Names to the identical `x509.Name` object).
        Returns None if the file is missing or cannot be parsed.
    """
    from cryptography import x509
    from cryptography.x509.extensions import ExtensionNotFound
    from cryptography.x509.oid import NameOID

    cert_path = Path(cert_path)

    try:
        pem_data = cert_path.read_bytes()
    except (FileNotFoundError, PermissionError, OSError):
        return None

    try:
        cert = x509.load_pem_x509_certificate(pem_data)
    except Exception:
        return None

    hostnames: list[str] = []
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        for entry in san.value:
            if isinstance(entry, x509.DNSName):
                hostnames.append(entry.value)
            elif isinstance(entry, x509.IPAddress):
                hostnames.append(str(entry.value))
    except ExtensionNotFound:
        pass

    try:
        expires = cert.not_valid_after_utc  # type: ignore[attr-defined]
    except AttributeError:
        expires = cert.not_valid_after  # type: ignore[attr-defined]

    try:
        not_before = cert.not_valid_before_utc  # type: ignore[attr-defined]
    except AttributeError:
        not_before = cert.not_valid_before  # type: ignore[attr-defined]

    try:
        issuer_cn = cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    except IndexError:
        issuer_cn = None

    return {
        "expires": expires,
        "not_before": not_before,
        "hostnames": hostnames,
        "serial": cert.serial_number,
        "issuer_common_name": issuer_cn,
        "self_signed": cert.issuer == cert.subject,
    }


def is_signed_by_ca(cert_path, ca_cert_path) -> bool:
    """Return True if the certificate at `cert_path` was signed by the CA at
    `ca_cert_path` -- i.e. its issuer Name matches the CA's subject Name.

    The same real chain check `tests/unit/test_webtls.py`'s own
    `test_generate_leaf_signed_by_ca_produces_a_cert_chained_to_the_ca`
    already performs by hand (`leaf_x509.issuer == ca_x509.subject`),
    promoted to a first-class helper so a display surface (`/setup`'s TLS
    status card) can classify an on-disk certificate without re-deriving
    that comparison inline. This is a DISPLAY classification, not a
    cryptographic verification of the chain (no signature is checked) --
    returns False (never raises) if either file is missing or unparseable.
    """
    from cryptography import x509

    cert_path = Path(cert_path)
    ca_cert_path = Path(ca_cert_path)
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        ca_cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
    except (FileNotFoundError, PermissionError, OSError, ValueError):
        return False
    return cert.issuer == ca_cert.subject


__all__ = [
    "default_ca_cert_path",
    "default_ca_dir",
    "default_ca_key_path",
    "default_cert_path",
    "default_key_path",
    "default_leaf_sans",
    "default_tls_dir",
    "detect_tailscale",
    "generate_leaf_signed_by_ca",
    "generate_local_ca",
    "generate_self_signed",
    "generate_tailscale",
    "get_cert_info",
    "is_signed_by_ca",
]
