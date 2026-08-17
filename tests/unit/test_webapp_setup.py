"""Tier 1 -- the `/setup` page (`webapp.py`'s "setup / TLS" section):
auth-gating, TLS status rendering, the method-options card, the in-process
`POST /setup/tls` generate action, and `GET /setup/ca.crt`.

Driven in-process via `starlette.testclient.TestClient` against
`webapp.create_app`, exactly like `tests/integration/test_web.py` -- but
this file needs no real `bd`/dolt project at all (`/setup` never touches
`workspace`), so it lives in `tests/unit/` alongside `test_webapp_tls.py`,
whose `_isolated_home` fixture this file reuses verbatim: every
`webauth`/`webtls` path is `Path.home()`-relative, so `Path.home()` is
monkeypatched to an isolated `tmp_path` for both modules, and no test here
ever reads or writes the developer's real
`~/.config/amplifier-work-tracker/tls/`.

Tailscale availability is never left to this host's actual connection
state (this box may itself be tailnet-connected) -- every test that cares
about the available/unavailable branch monkeypatches
`webapp.WT.detect_tailscale` directly, so behavior here is independent of
whatever `tailscale status` would say if actually invoked.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="the 'web' extra is not installed")
pytest.importorskip("cryptography", reason="the 'web' extra is not installed")

from starlette.testclient import TestClient  # noqa: E402

from amplifier_work_tracker import adapter as A  # noqa: E402
from amplifier_work_tracker import webapp  # noqa: E402
from amplifier_work_tracker import webauth as WA  # noqa: E402
from amplifier_work_tracker import webtls as WT  # noqa: E402

TEST_PASSWORD = "test-password-not-a-secret"  # noqa: S105 -- test fixture, not a real credential


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    """Every webauth/webtls path (`config_dir()`, `default_cert_path()`,
    etc.) is `Path.home()`-relative -- point BOTH modules' `Path.home()`
    (two independent module-level imports of `pathlib.Path`, not a shared
    object) at an isolated tmp_path so this file never touches the
    developer's real `~/.config/amplifier-work-tracker/`."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(WA.Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(WT.Path, "home", classmethod(lambda cls: fake_home))
    return fake_home


@pytest.fixture
def auth_config() -> WA.AuthConfig:
    return WA.AuthConfig(
        mode="password",
        secret="test-signing-secret-do-not-use-in-prod",  # noqa: S106
        ttl_seconds=3600,
        password=TEST_PASSWORD,
    )


@pytest.fixture
def client(tmp_path, auth_config, _isolated_home):
    """A plain-HTTP TestClient -- `request.url.scheme` reads "http", the
    same default `starlette.testclient.TestClient` always uses unless a
    caller overrides `base_url`, matching the `https_client` fixture below.
    Never touches a real `bd`/dolt project -- `/setup` doesn't read
    `workspace` at all, so a bare, never-`.create()`d `Workspace` is
    sufficient (same technique `test_webapp_tls.py`'s `run()` tests use)."""
    ws = A.Workspace(tmp_path / "root")
    app = webapp.create_app(ws, auth_config)
    with TestClient(app, follow_redirects=False) as c:
        yield c


@pytest.fixture
def https_client(tmp_path, auth_config, _isolated_home):
    """Same as `client`, but `request.url.scheme` reads "https" -- proves
    the TLS status card derives its SCHEME line from the actual request,
    never from whether a cert happens to exist on disk."""
    ws = A.Workspace(tmp_path / "root")
    app = webapp.create_app(ws, auth_config)
    with TestClient(app, base_url="https://testserver", follow_redirects=False) as c:
        yield c


def _login(client: TestClient) -> None:
    resp = client.post(
        "/login",
        data={"username": "operator", "password": TEST_PASSWORD, "next": "/"},
    )
    assert resp.status_code == 303, resp.text
    assert WA.SESSION_COOKIE_NAME in resp.cookies


# ---------------------------------------------------------------------------
# Auth gating -- /setup, /setup/tls, /setup/ca.crt are all authenticated,
# NOT in `_AUTH_EXEMPT_PATHS`, unlike the PWA asset routes.
# ---------------------------------------------------------------------------


def test_unauthenticated_get_setup_redirects_to_login(client):
    resp = client.get("/setup")
    assert resp.status_code == 307
    assert resp.headers["location"].startswith("/login")


def test_unauthenticated_get_setup_refused_json(client):
    resp = client.get("/setup", headers={"accept": "application/json"})
    assert resp.status_code == 401


def test_unauthenticated_post_setup_tls_refused_json(client):
    resp = client.post(
        "/setup/tls", data={"method": "selfsigned"}, headers={"accept": "application/json"}
    )
    assert resp.status_code == 401
    assert not WT.default_cert_path().exists()


def test_unauthenticated_get_ca_crt_refused_json(client):
    resp = client.get("/setup/ca.crt", headers={"accept": "application/json"})
    assert resp.status_code == 401


def test_authenticated_get_setup_succeeds(client):
    _login(client)
    resp = client.get("/setup")
    assert resp.status_code == 200
    assert "Setup" in resp.text


def test_dashboard_chrome_links_to_setup_when_authenticated(client):
    """The subtle top-bar link this task asked for -- present once signed
    in, alongside Logout."""
    _login(client)
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'href="/setup"' in resp.text


# ---------------------------------------------------------------------------
# TLS status card
# ---------------------------------------------------------------------------


def test_setup_status_shows_http_and_no_cert_note_when_nothing_configured(client):
    _login(client)
    resp = client.get("/setup")
    assert resp.status_code == 200
    assert "HTTP" in resp.text
    assert "not a secure origin" in resp.text
    # No CA download section when no CA is configured.
    assert "/setup/ca.crt" not in resp.text


def test_setup_status_reports_https_scheme_from_the_real_request(https_client):
    """Scheme is derived from the request, not guessed from cert presence
    -- HTTPS-scheme request, no cert on disk at all, must still say HTTPS
    (there is simply nothing else to report about the cert)."""
    _login(https_client)
    resp = https_client.get("/setup")
    assert resp.status_code == 200
    assert "HTTPS" in resp.text


def test_setup_status_labels_self_signed_certificate(client):
    WT.generate_self_signed(WT.default_cert_path(), WT.default_key_path())
    _login(client)
    resp = client.get("/setup")
    assert "Self-signed" in resp.text
    assert "not a secure origin" not in resp.text


def test_setup_status_flags_stale_cert_when_scheme_is_still_http(client):
    """A cert exists on disk (e.g. freshly generated via the POST route
    below) but the live scheme is still http -- the running server cannot
    hot-swap; that mismatch must be surfaced, not hidden."""
    WT.generate_self_signed(WT.default_cert_path(), WT.default_key_path())
    _login(client)
    resp = client.get("/setup")
    assert "cannot hot-swap" in resp.text
    assert "Restart the service" in resp.text


def test_setup_status_labels_local_ca_signed_certificate_and_offers_download(client):
    ca_cert, ca_key = WT.default_ca_cert_path(), WT.default_ca_key_path()
    WT.generate_local_ca(ca_cert, ca_key)
    leaf_hostnames, leaf_ips = WT.default_leaf_sans()
    WT.generate_leaf_signed_by_ca(
        ca_cert,
        ca_key,
        WT.default_cert_path(),
        WT.default_key_path(),
        hostnames=leaf_hostnames,
        ip_addresses=leaf_ips,
    )
    _login(client)
    resp = client.get("/setup")
    assert "Local CA" in resp.text
    assert "/setup/ca.crt" in resp.text
    assert "Import-Certificate" in resp.text  # Windows install instructions present


def test_setup_status_expiring_soon_certificate_is_flagged(client):
    WT.generate_self_signed(WT.default_cert_path(), WT.default_key_path(), days_valid=5)
    _login(client)
    resp = client.get("/setup")
    assert "expires in" in resp.text


def test_setup_status_expired_certificate_is_flagged(client, monkeypatch):
    """Generating an already-expired cert trips cryptography's own
    notValidBefore<notValidAfter invariant, so the EXPIRED branch is
    exercised via a monkeypatched `get_cert_info` instead of a real
    generated certificate -- the rendering logic under test never cares
    how the info dict was produced."""
    from datetime import UTC, datetime, timedelta

    WT.generate_self_signed(WT.default_cert_path(), WT.default_key_path())
    real_info = WT.get_cert_info(WT.default_cert_path())
    assert real_info is not None
    fake_info = dict(real_info)
    fake_info["expires"] = datetime.now(UTC) - timedelta(days=1)
    monkeypatch.setattr(webapp.WT, "get_cert_info", lambda _path: fake_info)
    _login(client)
    resp = client.get("/setup")
    assert "EXPIRED" in resp.text


# ---------------------------------------------------------------------------
# Method options -- availability probing, never host-state-dependent here.
# ---------------------------------------------------------------------------


def test_setup_shows_all_three_real_methods_and_never_mkcert(client):
    _login(client)
    resp = client.get("/setup")
    assert "Tailscale" in resp.text
    assert "Local CA" in resp.text
    assert "Self-signed" in resp.text
    assert "mkcert" not in resp.text.lower()


def test_setup_shows_tailscale_disabled_when_unavailable(client, monkeypatch):
    monkeypatch.setattr(webapp.WT, "detect_tailscale", lambda: None)
    _login(client)
    resp = client.get("/setup")
    assert "disabled" in resp.text
    assert "Not available on this host" in resp.text


def test_setup_shows_tailscale_available_with_detected_hostname(client, monkeypatch):
    monkeypatch.setattr(
        webapp.WT,
        "detect_tailscale",
        lambda: {"hostname": "probe-host.tail1234.ts.net", "ips": [], "cert_domains": ["x"]},
    )
    _login(client)
    resp = client.get("/setup")
    assert "probe-host.tail1234.ts.net" in resp.text


# ---------------------------------------------------------------------------
# POST /setup/tls -- functional, in-process generation.
# ---------------------------------------------------------------------------


def test_post_setup_tls_selfsigned_generates_a_real_cert_in_the_isolated_home(client):
    cert_path, key_path = WT.default_cert_path(), WT.default_key_path()
    assert not cert_path.exists()  # before

    _login(client)
    resp = client.post("/setup/tls", data={"method": "selfsigned"})

    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/setup")
    assert cert_path.is_file()  # after
    assert key_path.is_file()

    info = WT.get_cert_info(cert_path)
    assert info is not None
    assert info["self_signed"] is True

    follow = client.get(resp.headers["location"])
    assert "Generated a selfsigned certificate" in follow.text
    assert "expires" in follow.text
    assert "amplifier-work-tracker service restart" in follow.text


def test_post_setup_tls_ca_generates_both_ca_and_leaf(client):
    assert not WT.default_ca_cert_path().exists()

    _login(client)
    resp = client.post("/setup/tls", data={"method": "ca"})

    assert resp.status_code == 303
    assert WT.default_ca_cert_path().is_file()
    assert WT.default_cert_path().is_file()
    assert WT.is_signed_by_ca(WT.default_cert_path(), WT.default_ca_cert_path())


def test_post_setup_tls_unknown_method_is_refused_with_400(client):
    _login(client)
    resp = client.post("/setup/tls", data={"method": "bogus"})
    assert resp.status_code == 400
    assert "unknown TLS method" in resp.json()["detail"]
    assert not WT.default_cert_path().exists()


def test_post_setup_tls_tailscale_unavailable_is_refused_with_400(client, monkeypatch):
    """Same refusal whether or not the button was rendered disabled -- this
    is the real gate, exercised directly."""
    monkeypatch.setattr(webapp.WT, "detect_tailscale", lambda: None)
    _login(client)
    resp = client.post("/setup/tls", data={"method": "tailscale"})
    assert resp.status_code == 400
    assert "Tailscale is not installed" in resp.json()["detail"]
    assert not WT.default_cert_path().exists()


def test_post_setup_tls_does_not_touch_the_real_developer_home(client, _isolated_home):
    """The isolated-home fixture is the enforcement mechanism for the hard
    limit ("never touch the real ~/.config/.../tls/ cert") -- this test
    makes that guarantee explicit rather than merely implicit in every
    other test's passing.
    """
    import pathlib

    real_home = pathlib.Path(pathlib.Path.home().anchor).parent  # sentinel, never used for I/O
    assert _isolated_home != real_home  # the fixture's fake home is not the real filesystem root

    _login(client)
    client.post("/setup/tls", data={"method": "selfsigned"})

    assert str(WT.default_cert_path()).startswith(str(_isolated_home))


# ---------------------------------------------------------------------------
# GET /setup/ca.crt
# ---------------------------------------------------------------------------


def test_ca_crt_route_404s_when_no_ca_is_configured(client):
    _login(client)
    resp = client.get("/setup/ca.crt")
    assert resp.status_code == 404


def test_ca_crt_route_serves_a_valid_pem_when_ca_is_configured(client):
    WT.generate_local_ca(WT.default_ca_cert_path(), WT.default_ca_key_path())
    _login(client)
    resp = client.get("/setup/ca.crt")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/x-x509-ca-cert"
    assert resp.content.startswith(b"-----BEGIN CERTIFICATE-----")
