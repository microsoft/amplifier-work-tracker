"""Tier 1 -- the plain-HTTP trust-bootstrap listener (`webtrust.py`):
`/trust`, `/ca.crt`, `/trust.mobileconfig`, and the everything-else redirect
to https.

Driven in-process via `starlette.testclient.TestClient` against
`webtrust.create_trust_app`, matching `tests/unit/test_webapp_setup.py`'s
own conventions. No bd, no dolt, no network -- this app never touches
`workspace` at all. Certificates are generated fresh under an isolated
`tmp_path` for every test (never the developer's real
`~/.config/amplifier-work-tracker/tls/`).
"""

from __future__ import annotations

import plistlib

import pytest

pytest.importorskip("fastapi", reason="the 'web' extra is not installed")
pytest.importorskip("cryptography", reason="the 'web' extra is not installed")

from starlette.testclient import TestClient  # noqa: E402

from amplifier_work_tracker import webtls as WT  # noqa: E402
from amplifier_work_tracker import webtrust as WTR  # noqa: E402

# ---------------------------------------------------------------------------
# _detect_os
# ---------------------------------------------------------------------------

_IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
_IPAD_UA = (
    "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
_ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)
_WINDOWS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_MACOS_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
_LINUX_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


@pytest.mark.parametrize(
    ("ua", "expected"),
    [
        (_IPHONE_UA, "ios"),
        (_IPAD_UA, "ios"),
        (_ANDROID_UA, "android"),
        (_WINDOWS_UA, "windows"),
        (_MACOS_UA, "macos"),
        (_LINUX_UA, "linux"),
        ("", "unknown"),
        ("some-unrecognizable-bot/1.0", "unknown"),
    ],
)
def test_detect_os(ua, expected):
    assert WTR._detect_os(ua) == expected  # noqa: SLF001 -- exercising the pure helper directly


def test_detect_os_checks_android_before_linux():
    """Android UAs also contain the substring 'Linux' -- must classify as
    android, never linux."""
    assert "linux" in _ANDROID_UA.lower()
    assert WTR._detect_os(_ANDROID_UA) == "android"  # noqa: SLF001


# ---------------------------------------------------------------------------
# _classify_trust_state
# ---------------------------------------------------------------------------


def test_classify_trust_state_none_when_no_cert_path_given():
    assert WTR._classify_trust_state(None).kind == "none"  # noqa: SLF001


def test_classify_trust_state_none_when_cert_file_missing(tmp_path):
    missing = tmp_path / "nope.pem"
    assert WTR._classify_trust_state(str(missing)).kind == "none"  # noqa: SLF001


def test_classify_trust_state_selfsigned(tmp_path):
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    WT.generate_self_signed(cert_path, key_path)
    state = WTR._classify_trust_state(str(cert_path))  # noqa: SLF001
    assert state.kind == "selfsigned"
    assert state.ca_cert_path is None


def test_classify_trust_state_public_when_not_self_signed_and_no_ca(tmp_path, monkeypatch):
    """An externally-issued cert (e.g. Tailscale/Let's Encrypt): not
    self-signed, and no local CA is configured on this host at all -- must
    classify as 'public' (already trusted), never offer a bogus CA
    download."""
    # A leaf signed by a throwaway CA that this test then makes
    # unreachable (default_ca_cert_path points elsewhere) mimics "issuer !=
    # subject, but not signed by any CA WE know about" without needing a
    # real external CA.
    ca_cert_path = tmp_path / "unrelated_ca.crt"
    ca_key_path = tmp_path / "unrelated_ca.key"
    WT.generate_local_ca(ca_cert_path, ca_key_path)
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    WT.generate_leaf_signed_by_ca(
        ca_cert_path, ca_key_path, cert_path, key_path, hostnames=["example.test"]
    )

    # Point default_ca_cert_path() somewhere that does NOT exist, so
    # `_classify_trust_state` cannot find any local CA on "this host".
    monkeypatch.setattr(WT, "default_ca_cert_path", lambda: tmp_path / "no-ca-here.crt")

    state = WTR._classify_trust_state(str(cert_path))  # noqa: SLF001
    assert state.kind == "public"
    assert state.ca_cert_path is None


def test_classify_trust_state_ca(tmp_path, monkeypatch):
    ca_cert_path = tmp_path / "ca.crt"
    ca_key_path = tmp_path / "ca.key"
    WT.generate_local_ca(ca_cert_path, ca_key_path)
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    WT.generate_leaf_signed_by_ca(
        ca_cert_path, ca_key_path, cert_path, key_path, hostnames=["example.test"]
    )
    monkeypatch.setattr(WT, "default_ca_cert_path", lambda: ca_cert_path)

    state = WTR._classify_trust_state(str(cert_path))  # noqa: SLF001
    assert state.kind == "ca"
    assert state.ca_cert_path == ca_cert_path


# ---------------------------------------------------------------------------
# _build_mobileconfig -- stdlib plistlib, real cryptography CA cert
# ---------------------------------------------------------------------------


@pytest.fixture
def ca_cert(tmp_path):
    ca_cert_path = tmp_path / "ca.crt"
    ca_key_path = tmp_path / "ca.key"
    WT.generate_local_ca(ca_cert_path, ca_key_path)
    return ca_cert_path


def test_build_mobileconfig_produces_a_parseable_plist(ca_cert):
    data = WTR._build_mobileconfig(ca_cert)  # noqa: SLF001
    parsed = plistlib.loads(data)
    assert parsed["PayloadType"] == "Configuration"
    assert isinstance(parsed["PayloadUUID"], str) and parsed["PayloadUUID"]


def test_build_mobileconfig_carries_a_root_cert_payload_with_the_real_ca_bytes(ca_cert):
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    data = WTR._build_mobileconfig(ca_cert)  # noqa: SLF001
    parsed = plistlib.loads(data)
    payloads = parsed["PayloadContent"]
    assert len(payloads) == 1
    cert_payload = payloads[0]
    assert cert_payload["PayloadType"] == "com.apple.security.root"

    expected_der = x509.load_pem_x509_certificate(ca_cert.read_bytes()).public_bytes(
        serialization.Encoding.DER
    )
    assert bytes(cert_payload["PayloadContent"]) == expected_der


def test_build_mobileconfig_is_idempotent_across_downloads(ca_cert):
    """Re-downloading `/trust.mobileconfig` for the SAME CA must produce
    byte-identical PayloadUUIDs every time -- see `_stable_uuid`'s own
    docstring for why (iOS/macOS treat PayloadUUID as identity)."""
    first = plistlib.loads(WTR._build_mobileconfig(ca_cert))  # noqa: SLF001
    second = plistlib.loads(WTR._build_mobileconfig(ca_cert))  # noqa: SLF001
    assert first["PayloadUUID"] == second["PayloadUUID"]
    assert first["PayloadContent"][0]["PayloadUUID"] == second["PayloadContent"][0]["PayloadUUID"]


def test_build_mobileconfig_differs_for_a_different_ca(tmp_path, ca_cert):
    other_ca_cert = tmp_path / "other_ca.crt"
    other_ca_key = tmp_path / "other_ca.key"
    WT.generate_local_ca(other_ca_cert, other_ca_key, common_name="a different CA")

    first = plistlib.loads(WTR._build_mobileconfig(ca_cert))  # noqa: SLF001
    second = plistlib.loads(WTR._build_mobileconfig(other_ca_cert))  # noqa: SLF001
    assert first["PayloadUUID"] != second["PayloadUUID"]


# ---------------------------------------------------------------------------
# App-level: TestClient against create_trust_app
# ---------------------------------------------------------------------------


@pytest.fixture
def ca_signed_cert(tmp_path, monkeypatch):
    """A full local-CA + leaf pair, with `webtls.default_ca_cert_path`
    monkeypatched so `webtrust._classify_trust_state` finds it -- the
    "offer the real CA download" state."""
    ca_cert_path = tmp_path / "ca.crt"
    ca_key_path = tmp_path / "ca.key"
    WT.generate_local_ca(ca_cert_path, ca_key_path)
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    WT.generate_leaf_signed_by_ca(
        ca_cert_path, ca_key_path, cert_path, key_path, hostnames=["testserver"]
    )
    monkeypatch.setattr(WT, "default_ca_cert_path", lambda: ca_cert_path)
    return cert_path


@pytest.fixture
def selfsigned_cert(tmp_path):
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    WT.generate_self_signed(cert_path, key_path)
    return cert_path


def _client(https_port: int, tls_cert_path) -> TestClient:
    app = WTR.create_trust_app(https_port=https_port, tls_cert_path=str(tls_cert_path))
    return TestClient(app, follow_redirects=False)


# ---- /trust ----------------------------------------------------------------


def test_trust_page_is_reachable_unauthenticated_over_plain_http(ca_signed_cert):
    with _client(8095, ca_signed_cert) as c:
        resp = c.get("/trust")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Trust this server" in resp.text
    assert "Download CA certificate" in resp.text


def test_trust_page_offers_install_profile_button_for_ios_ua(ca_signed_cert):
    with _client(8095, ca_signed_cert) as c:
        resp = c.get("/trust", headers={"user-agent": _IPHONE_UA})
    assert resp.status_code == 200
    assert "Install profile" in resp.text
    assert "iOS" in resp.text


def test_trust_page_honest_about_selfsigned_no_ca_to_install(selfsigned_cert):
    with _client(8095, selfsigned_cert) as c:
        resp = c.get("/trust")
    assert resp.status_code == 200
    assert "no CA to" in resp.text
    assert "Download CA certificate" not in resp.text


def test_trust_page_honest_about_no_cert_configured():
    with _client(8095, None) as c:
        resp = c.get("/trust")
    assert resp.status_code == 200
    assert "nothing to" in resp.text
    assert "Download CA certificate" not in resp.text


def test_trust_page_continue_link_points_at_https_origin(ca_signed_cert):
    with _client(8095, ca_signed_cert) as c:
        resp = c.get("/trust")
    assert "https://testserver:8095/" in resp.text


# ---- /ca.crt -----------------------------------------------------------


def test_ca_crt_download_unauthenticated_when_ca_active(ca_signed_cert):
    with _client(8095, ca_signed_cert) as c:
        resp = c.get("/ca.crt")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/x-x509-ca-cert"
    assert resp.content.startswith(b"-----BEGIN CERTIFICATE-----")


def test_ca_crt_404_honest_when_no_ca(selfsigned_cert):
    with _client(8095, selfsigned_cert) as c:
        resp = c.get("/ca.crt")
    assert resp.status_code == 404
    assert "no local CA" in resp.json()["detail"]


def test_ca_crt_404_when_no_cert_at_all():
    with _client(8095, None) as c:
        resp = c.get("/ca.crt")
    assert resp.status_code == 404


# ---- /trust.mobileconfig ------------------------------------------------


def test_trust_mobileconfig_download_unauthenticated_when_ca_active(ca_signed_cert):
    with _client(8095, ca_signed_cert) as c:
        resp = c.get("/trust.mobileconfig")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/x-apple-aspen-config"
    parsed = plistlib.loads(resp.content)
    assert parsed["PayloadContent"][0]["PayloadType"] == "com.apple.security.root"


def test_trust_mobileconfig_404_honest_when_no_ca(selfsigned_cert):
    with _client(8095, selfsigned_cert) as c:
        resp = c.get("/trust.mobileconfig")
    assert resp.status_code == 404


# ---- redirect ------------------------------------------------------------


def test_redirect_for_arbitrary_path_to_https_origin(ca_signed_cert):
    with _client(8095, ca_signed_cert) as c:
        resp = c.get("/projects")
    assert resp.status_code in (301, 302, 307, 308)
    assert resp.headers["location"] == "https://testserver:8095/projects"


def test_redirect_preserves_query_string(ca_signed_cert):
    with _client(8095, ca_signed_cert) as c:
        resp = c.get("/projects?status=held")
    assert resp.headers["location"] == "https://testserver:8095/projects?status=held"


def test_redirect_for_bare_root(ca_signed_cert):
    with _client(8095, ca_signed_cert) as c:
        resp = c.get("/")
    assert resp.status_code in (301, 302, 307, 308)
    assert resp.headers["location"] == "https://testserver:8095/"


def test_redirect_never_fires_for_the_three_trust_routes(ca_signed_cert):
    """Sanity check the route declaration order: the catch-all must never
    shadow /trust, /ca.crt, or /trust.mobileconfig."""
    with _client(8095, ca_signed_cert) as c:
        assert c.get("/trust").status_code == 200
        assert c.get("/ca.crt").status_code == 200
        assert c.get("/trust.mobileconfig").status_code == 200
