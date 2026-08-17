"""Integration tests for the PWA surface (`webpwa.py`'s content, served by
the five routes `webapp.create_app` wires: `/manifest.json`, `/sw.js`,
`/pwa-192.png`, `/pwa-512.png`, `/apple-touch-icon.png`).

Same isolation model as `test_web.py`: real `bd` + the shared (isolated)
dolt server via `conftest.py`'s session-scoped `workspace` fixture, driven
in-process via `starlette.testclient.TestClient` -- no real network port,
no touching the developer's real `~/.amplifier-work-tracker`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest

pytest.importorskip("fastapi", reason="the 'web' extra is not installed")

from starlette.testclient import TestClient  # noqa: E402

from amplifier_work_tracker import webapp  # noqa: E402
from amplifier_work_tracker import webauth as WA  # noqa: E402
from amplifier_work_tracker import webpwa as PWA  # noqa: E402

pytestmark = pytest.mark.integration

TEST_PASSWORD = "test-password-not-a-secret"  # noqa: S105 -- test fixture, not a real credential


@pytest.fixture
def auth_config() -> WA.AuthConfig:
    return WA.AuthConfig(
        mode="password",
        secret="test-signing-secret-do-not-use-in-prod",  # noqa: S106
        ttl_seconds=3600,
        password=TEST_PASSWORD,
    )


@pytest.fixture
def client(workspace, auth_config) -> Iterator[TestClient]:
    app = webapp.create_app(workspace, auth_config)
    with TestClient(app, follow_redirects=False) as c:
        yield c


def _login(client: TestClient) -> None:
    resp = client.post(
        "/login",
        data={"username": "operator", "password": TEST_PASSWORD, "next": "/"},
    )
    assert resp.status_code == 303, resp.text
    assert WA.SESSION_COOKIE_NAME in resp.cookies


# ------------------------------------------------------- auth-exempt fetches
#
# The whole point: a browser must be able to fetch every one of these
# WITHOUT a session cookie or Authorization header, or install/registration
# breaks before any login ever happens. No `_login(client)` call appears
# anywhere in this section -- that omission IS the test.


@pytest.mark.parametrize(
    "path",
    ["/manifest.json", "/sw.js", "/pwa-192.png", "/pwa-512.png", "/apple-touch-icon.png"],
)
def test_pwa_asset_is_reachable_without_authentication(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, resp.text


# -------------------------------------------------------------- manifest.json


def test_manifest_content_type_and_cache_header(client):
    resp = client.get("/manifest.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/manifest+json")
    assert resp.headers["cache-control"] == "no-cache"


def test_manifest_is_valid_json_with_scope_root_and_standalone_display(client):
    resp = client.get("/manifest.json")
    data = json.loads(resp.text)
    assert data["scope"] == "/"
    assert data["start_url"] == "/"
    assert data["display"] == "standalone"
    assert data["name"]
    assert data["short_name"]


def test_manifest_lists_both_icon_sizes_with_a_maskable_purpose(client):
    resp = client.get("/manifest.json")
    data = json.loads(resp.text)
    srcs = {icon["src"] for icon in data["icons"]}
    assert srcs == {"/pwa-192.png", "/pwa-512.png"}
    purposes = {icon["purpose"] for icon in data["icons"]}
    assert "maskable" in purposes
    assert "any" in purposes


# -------------------------------------------------------------------- sw.js


def test_service_worker_content_type_and_cache_header(client):
    resp = client.get("/sw.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]
    assert resp.headers["cache-control"] == "no-cache"


def test_service_worker_caches_nothing():
    """The load-bearing property (see webpwa.py's module docstring): this
    service worker must never call `caches.open` or `cache.put` -- a
    caching SW on a live, auto-refreshing dashboard would serve stale
    snapshots straight through the poll meant to catch a real alarm."""
    body = PWA.SERVICE_WORKER_JS
    assert "caches.open" not in body
    assert ".put(" not in body
    assert "cache.match" not in body


def test_service_worker_passes_every_fetch_straight_to_the_network(client):
    resp = client.get("/sw.js")
    assert "addEventListener('fetch'" in resp.text
    assert "fetch(event.request)" in resp.text
    assert "caches.open" not in resp.text
    assert ".put(" not in resp.text


def test_service_worker_skips_waiting_and_claims_clients(client):
    resp = client.get("/sw.js")
    assert "skipWaiting()" in resp.text
    assert "clients.claim()" in resp.text


# ------------------------------------------------------------------- icons


@pytest.mark.parametrize(
    ("path", "magic"),
    [
        ("/pwa-192.png", b"\x89PNG\r\n\x1a\n"),
        ("/pwa-512.png", b"\x89PNG\r\n\x1a\n"),
        ("/apple-touch-icon.png", b"\x89PNG\r\n\x1a\n"),
    ],
)
def test_icon_is_a_real_png_with_correct_content_type_and_cache_header(client, path, magic):
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.content.startswith(magic)


# ------------------------------------------------------------- page head


def test_authenticated_dashboard_head_includes_pwa_tags(client):
    _login(client)
    resp = client.get("/")
    assert resp.status_code == 200
    assert '<link rel="manifest" href="/manifest.json">' in resp.text
    assert 'name="theme-color"' in resp.text
    assert '<link rel="apple-touch-icon" href="/apple-touch-icon.png">' in resp.text
    assert "navigator.serviceWorker.register('/sw.js')" in resp.text


def test_login_page_head_also_includes_pwa_tags(client):
    """The login page itself renders through the same `T.page()` shell, so
    a browser can discover the manifest/service-worker even before the
    user has authenticated at all."""
    resp = client.get("/login")
    assert resp.status_code == 200
    assert '<link rel="manifest" href="/manifest.json">' in resp.text
    assert "navigator.serviceWorker.register('/sw.js')" in resp.text
