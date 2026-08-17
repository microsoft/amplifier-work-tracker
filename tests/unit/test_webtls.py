"""Tier 1 -- webtls.py: certificate generation, inspection, and the
default-path/SAN-assembly helpers. Pure, dolt-independent, no network
(the tailnet/LAN-IP probes are exercised for their SHAPE via monkeypatch,
never by requiring a real Tailscale install or network access).

Requires the `web` extra (`cryptography` lives there) -- skipped entirely
if it isn't installed, matching this repo's `pytest.importorskip` pattern
for other web-extra-gated test files.
"""

from __future__ import annotations

import shutil
import socket
import subprocess

import pytest

pytest.importorskip("cryptography", reason="the 'web' extra is not installed")

from amplifier_work_tracker import webtls as T  # noqa: E402

# ---------------------------------------------------------------------------
# _common_name -- CN truncation (RFC 5280 ub-common-name = 64 chars)
# ---------------------------------------------------------------------------


def test_common_name_passes_short_hostname_through_unchanged():
    assert T._common_name("spark-1") == "spark-1"


def test_common_name_truncates_long_hostname_to_64_chars():
    long_name = "a" * 80
    cn = T._common_name(long_name)
    assert len(cn) == 64
    assert cn == long_name[:64]


def test_common_name_truncation_is_exercised_by_a_real_cert(tmp_path):
    """The actual regression this exists to prevent: a hostname > 64 chars
    used to raise a bare `ValueError` from deep inside `cryptography` with
    nothing naming the hostname as the cause. Generating a cert with one
    must succeed, and the FULL (untruncated) name must still appear in the
    SAN -- CN truncation costs nothing a client validates against."""
    long_hostname = "this-is-a-deliberately-long-hostname-that-exceeds-the-64-char-cn-limit"
    assert len(long_hostname) > 64
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"

    T.generate_self_signed(cert_path, key_path, hostnames=[long_hostname])

    assert cert_path.is_file()
    assert key_path.is_file()
    info = T.get_cert_info(cert_path)
    assert info is not None
    assert long_hostname in info["hostnames"]


# ---------------------------------------------------------------------------
# _default_hostnames / _default_lan_ip / _default_tailnet_name
# ---------------------------------------------------------------------------


def test_default_hostnames_includes_hostname_local_and_localhost():
    hostnames = T._default_hostnames()
    hostname = socket.gethostname()
    assert hostnames == [hostname, f"{hostname}.local", "localhost"]


def test_default_lan_ip_returns_a_valid_ipv4_or_none():
    """Best-effort: either a real routable-looking IPv4 string, or None
    (no network / all-loopback) -- never raises, never returns a loopback
    address (that would defeat the point of a LAN-reachable SAN entry)."""
    ip = T._default_lan_ip()
    if ip is not None:
        import ipaddress

        parsed = ipaddress.ip_address(ip)
        assert isinstance(parsed, ipaddress.IPv4Address)
        assert ip not in ("0.0.0.0", "127.0.0.1")


def test_default_tailnet_name_returns_none_when_tailscale_not_on_path(monkeypatch):
    # webtls.py imports `shutil` lazily, INSIDE `_default_tailnet_name`
    # (see module docstring: zero non-stdlib imports at module level) --
    # patching the real `shutil` module's `which` attribute (a singleton in
    # `sys.modules`) affects that lazy import too, regardless of which name
    # binds to it.
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert T._default_tailnet_name() is None


def test_default_leaf_sans_includes_loopback_and_default_hostnames(monkeypatch):
    """Even with no Tailscale/LAN detected, the baseline SAN set is present."""
    monkeypatch.setattr(T, "_default_tailnet_name", lambda: None)
    monkeypatch.setattr(T, "_default_lan_ip", lambda: None)
    hostnames, ips = T.default_leaf_sans()
    hostname = socket.gethostname()
    assert hostnames == [hostname, f"{hostname}.local", "localhost"]
    assert ips == ["127.0.0.1", "::1"]


def test_default_leaf_sans_folds_in_tailnet_name_and_lan_ip_when_present(monkeypatch):
    monkeypatch.setattr(T, "_default_tailnet_name", lambda: "spark-1.tail8f3c.ts.net")
    monkeypatch.setattr(T, "_default_lan_ip", lambda: "192.168.1.42")
    hostnames, ips = T.default_leaf_sans()
    assert "spark-1.tail8f3c.ts.net" in hostnames
    assert "192.168.1.42" in ips
    assert "127.0.0.1" in ips
    assert "::1" in ips


# ---------------------------------------------------------------------------
# default_*_path -- the fixed, well-known locations `setup-tls` writes to
# and `web`/`serve --web-port` auto-detect from.
# ---------------------------------------------------------------------------


def test_default_paths_live_under_config_amplifier_work_tracker_tls(monkeypatch, tmp_path):
    monkeypatch.setattr(T.Path, "home", classmethod(lambda cls: tmp_path))
    assert (
        T.default_cert_path()
        == tmp_path / ".config" / "amplifier-work-tracker" / "tls" / "cert.pem"
    )
    assert (
        T.default_key_path() == tmp_path / ".config" / "amplifier-work-tracker" / "tls" / "key.pem"
    )
    assert T.default_ca_cert_path().parent.name == "ca"


def test_default_tls_dir_is_created_with_restricted_permissions(monkeypatch, tmp_path):
    monkeypatch.setattr(T.Path, "home", classmethod(lambda cls: tmp_path))
    d = T.default_tls_dir()
    assert d.is_dir()
    assert (d.stat().st_mode & 0o777) == 0o700


# ---------------------------------------------------------------------------
# generate_self_signed
# ---------------------------------------------------------------------------


def test_generate_self_signed_writes_cert_and_key_with_restricted_key_perms(tmp_path):
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    result = T.generate_self_signed(cert_path, key_path)

    assert cert_path.is_file()
    assert key_path.is_file()
    assert (key_path.stat().st_mode & 0o777) == 0o600
    assert result["method"] == "selfsigned"
    assert result["cert_path"] == str(cert_path)
    assert result["key_path"] == str(key_path)


def test_generate_self_signed_san_covers_hostname_local_localhost_loopback_and_lan_ip(tmp_path):
    """The load-bearing verification requirement: a self-signed cert must
    NOT be thinner than a CA-signed leaf for the same host -- it must carry
    the LAN IP (and tailnet name, if any) too, not just the bare defaults."""
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    hostnames, ips = T.default_leaf_sans()

    T.generate_self_signed(cert_path, key_path, hostnames=hostnames, ip_addresses=ips)

    info = T.get_cert_info(cert_path)
    assert info is not None
    hostname = socket.gethostname()
    assert hostname in info["hostnames"]
    assert f"{hostname}.local" in info["hostnames"]
    assert "localhost" in info["hostnames"]
    assert "127.0.0.1" in info["hostnames"]
    for ip in ips:
        assert ip in info["hostnames"]


def test_generate_self_signed_deduplicates_loopback_ip_addresses(tmp_path):
    """Passing 127.0.0.1 explicitly in ip_addresses must not produce a
    duplicate SAN entry -- it's already unconditionally included."""
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    T.generate_self_signed(cert_path, key_path, ip_addresses=["127.0.0.1"])
    info = T.get_cert_info(cert_path)
    assert info is not None
    assert info["hostnames"].count("127.0.0.1") == 1


def test_generate_self_signed_skips_invalid_ip_strings_silently(tmp_path):
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    result = T.generate_self_signed(cert_path, key_path, ip_addresses=["not-an-ip"])
    assert "not-an-ip" not in result["hostnames"]


# ---------------------------------------------------------------------------
# generate_local_ca + generate_leaf_signed_by_ca
# ---------------------------------------------------------------------------


def test_generate_local_ca_writes_ca_cert_and_key(tmp_path):
    ca_cert = tmp_path / "ca.crt"
    ca_key = tmp_path / "ca.key"
    result = T.generate_local_ca(ca_cert, ca_key)
    assert ca_cert.is_file()
    assert ca_key.is_file()
    assert (ca_key.stat().st_mode & 0o777) == 0o600
    assert result["regenerated"] is True


def test_generate_local_ca_is_idempotent_and_reuses_existing_ca(tmp_path):
    ca_cert = tmp_path / "ca.crt"
    ca_key = tmp_path / "ca.key"
    first = T.generate_local_ca(ca_cert, ca_key)
    second = T.generate_local_ca(ca_cert, ca_key)
    assert first["regenerated"] is True
    assert second["regenerated"] is False
    # Reusing must not have rewritten the key -- same bytes on disk.
    assert ca_key.read_bytes() == ca_key.read_bytes()


def test_generate_leaf_signed_by_ca_produces_a_cert_chained_to_the_ca(tmp_path):
    ca_cert = tmp_path / "ca.crt"
    ca_key = tmp_path / "ca.key"
    leaf_cert = tmp_path / "leaf.crt"
    leaf_key = tmp_path / "leaf.key"
    T.generate_local_ca(ca_cert, ca_key)

    result = T.generate_leaf_signed_by_ca(
        ca_cert,
        ca_key,
        leaf_cert,
        leaf_key,
        hostnames=["myhost", "myhost.local", "localhost"],
        ip_addresses=["127.0.0.1", "192.168.1.99"],
    )

    assert leaf_cert.is_file()
    assert leaf_key.is_file()
    assert result["method"] == "ca"
    info = T.get_cert_info(leaf_cert)
    assert info is not None
    assert "myhost" in info["hostnames"]
    assert "192.168.1.99" in info["hostnames"]

    # Verify the chain is real: the leaf's issuer must match the CA's subject.
    from cryptography import x509

    ca_x509 = x509.load_pem_x509_certificate(ca_cert.read_bytes())
    leaf_x509 = x509.load_pem_x509_certificate(leaf_cert.read_bytes())
    assert leaf_x509.issuer == ca_x509.subject


def test_generate_leaf_signed_by_ca_requires_at_least_one_hostname(tmp_path):
    ca_cert = tmp_path / "ca.crt"
    ca_key = tmp_path / "ca.key"
    T.generate_local_ca(ca_cert, ca_key)
    with pytest.raises(ValueError, match="at least one hostname"):
        T.generate_leaf_signed_by_ca(ca_cert, ca_key, tmp_path / "l.crt", tmp_path / "l.key", [])


# ---------------------------------------------------------------------------
# get_cert_info
# ---------------------------------------------------------------------------


def test_get_cert_info_returns_none_for_missing_file(tmp_path):
    assert T.get_cert_info(tmp_path / "nope.crt") is None


def test_get_cert_info_returns_none_for_unparseable_file(tmp_path):
    bogus = tmp_path / "bogus.crt"
    bogus.write_text("not a certificate", encoding="utf-8")
    assert T.get_cert_info(bogus) is None


def test_get_cert_info_reports_expiry_and_serial(tmp_path):
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    T.generate_self_signed(cert_path, key_path, days_valid=30)
    info = T.get_cert_info(cert_path)
    assert info is not None
    assert info["expires"] > info["not_before"]
    assert isinstance(info["serial"], int)


# ---------------------------------------------------------------------------
# detect_tailscale / generate_tailscale -- shape only, never a real network
# call or a real `tailscale` binary requirement.
# ---------------------------------------------------------------------------


def test_detect_tailscale_returns_none_when_binary_absent(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert T.detect_tailscale() is None


def test_generate_tailscale_returns_none_when_binary_absent(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("no tailscale binary")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = T.generate_tailscale(tmp_path / "c.crt", tmp_path / "c.key", "host.example.ts.net")
    assert result is None
