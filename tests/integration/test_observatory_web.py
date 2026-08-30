"""wt-v4 Observatory (Lane C: obs-pages) -- build-phase test gaps not
already covered by `test_web.py`'s deliberately-updated v3-fidelity tests
or `test_webbrowse_route.py`'s L1/L2 mounting tests: L0 Mission Control
rendering against real data, the confirm-gate on the destructive resolve
POST, and server-rendered window/status-tab state changes.

Real `bd` + the shared dolt server (same tier-2 contract as the rest of
`tests/integration`), driven in-process via `starlette.testclient.
TestClient` against `webapp.create_app`.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="the 'web' extra is not installed")

from starlette.testclient import TestClient  # noqa: E402

from amplifier_work_tracker import adapter as A  # noqa: E402
from amplifier_work_tracker import webapp  # noqa: E402
from amplifier_work_tracker import webauth as WA  # noqa: E402

pytestmark = pytest.mark.integration


@pytest.fixture
def auth_config() -> WA.AuthConfig:
    return WA.AuthConfig(
        mode="password",
        secret="test-secret-not-real",  # noqa: S106
        ttl_seconds=3600,
        password="test-password-not-real",  # noqa: S106
    )


@pytest.fixture
def client(workspace, auth_config):
    app = webapp.create_app(workspace, auth_config)
    with TestClient(app, follow_redirects=False) as c:
        yield c


def _login(client: TestClient) -> None:
    resp = client.post(
        "/login",
        data={"username": "operator", "password": "test-password-not-real", "next": "/"},
    )
    assert resp.status_code == 303, resp.text


# --------------------------------------------------------- L0 Mission Control


def test_l0_renders_environment_kpis_and_fleet_from_real_data(
    client, project_factory, unique_actor
):
    _login(client)
    name, bd = project_factory("obsl0proj")
    bd.create("ready item for l0", tags=[A.LANE_WORK])
    held_id = bd.create("held item for l0", tags=[A.LANE_WORK])
    bd.claim_item(held_id, actor=unique_actor)

    r = client.get("/")
    assert r.status_code == 200
    assert 'class="wt-observatory"' in r.text  # body_class threading confirmed
    assert 'class="kpi-strip"' in r.text
    assert 'class="fleet-row"' in r.text
    assert f'href="/projects/{name}"' in r.text
    assert "Mission Control" in r.text


def test_l0_window_tabs_are_real_server_rendered_links_with_active_state(
    client, shared_project_name
):
    _login(client)
    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/?window=24h"' in r.text
    assert 'href="/?window=30d"' in r.text

    r7 = client.get("/", params={"window": "7d"})
    assert r7.status_code == 200
    assert 'class="window-tab is-active">7D</a>' in r7.text

    r30 = client.get("/", params={"window": "30d"})
    assert r30.status_code == 200
    assert 'class="window-tab is-active">30D</a>' in r30.text
    assert 'class="window-tab is-active">7D</a>' not in r30.text


def test_l0_unknown_window_param_falls_back_to_7d_not_a_500(client, shared_project_name):
    _login(client)
    r = client.get("/", params={"window": "bogus"})
    assert r.status_code == 200
    assert 'class="window-tab is-active">7D</a>' in r.text


# --------------------------------------------------------- L1 status/window tabs


def test_l1_status_tab_changes_server_side_filter_state(client, project_factory, unique_lane):
    _login(client)
    name, bd = project_factory("obsl1tabsproj")
    bd.create("ready one", tags=[unique_lane, A.LANE_WORK])

    ready_view = client.get(f"/projects/{name}", params={"status": "ready"})
    assert ready_view.status_code == 200
    assert "ready one" in ready_view.text

    resolved_view = client.get(f"/projects/{name}", params={"status": "resolved"})
    assert resolved_view.status_code == 200
    assert "ready one" not in resolved_view.text
    assert "No items match this filter" in resolved_view.text


# --------------------------------------------------------- confirm-gate


def test_resolve_post_without_confirm_field_is_refused(client, project_factory, unique_actor):
    """The destructive resolve action REQUIRES `confirm=yes` -- a direct
    POST that skips the L2 confirm sub-state (bypassing the UI entirely)
    must be refused, never silently resolve the item."""
    _login(client)
    name, bd = project_factory("obsconfirmproj")
    bd.create("must not resolve without confirm", tags=[A.LANE_WORK])
    item = bd.claim_next(lane=A.LANE_WORK, actor=unique_actor)

    r = client.post(
        f"/projects/{name}/items/{item.id}/resolve",
        data={"reason": "sneaky resolve attempt", "actor": unique_actor},
    )
    assert r.status_code == 422  # FastAPI rejects the missing required field

    fresh = bd.get(item.id)
    assert fresh.status == "held"  # never resolved


def test_resolve_post_with_wrong_confirm_value_is_refused(client, project_factory, unique_actor):
    _login(client)
    name, bd = project_factory("obsconfirmwrongproj")
    bd.create("must not resolve with wrong confirm", tags=[A.LANE_WORK])
    item = bd.claim_next(lane=A.LANE_WORK, actor=unique_actor)

    r = client.post(
        f"/projects/{name}/items/{item.id}/resolve",
        data={"reason": "sneaky resolve attempt", "actor": unique_actor, "confirm": "no"},
    )
    assert r.status_code == 303
    assert "error=" in r.headers["location"]

    fresh = bd.get(item.id)
    assert fresh.status == "held"  # never resolved


def test_resolve_post_with_confirm_yes_succeeds(client, project_factory, unique_actor):
    _login(client)
    name, bd = project_factory("obsconfirmyesproj")
    bd.create("resolves with real confirm", tags=[A.LANE_WORK])
    item = bd.claim_next(lane=A.LANE_WORK, actor=unique_actor)

    r = client.post(
        f"/projects/{name}/items/{item.id}/resolve",
        data={"reason": "confirmed resolve", "actor": unique_actor, "confirm": "yes"},
    )
    assert r.status_code == 303
    assert "resolved" in r.headers["location"]

    fresh = bd.get(item.id)
    assert fresh.status == "resolved"


def test_l2_confirm_resolve_query_param_reveals_the_confirm_form(
    client, project_factory, unique_actor
):
    """`?confirm_resolve=1` is what the Actions drawer's own "Resolve" link
    navigates to -- it reveals the real confirm sub-state's form (with the
    hidden `confirm=yes` field), rather than resolving directly."""
    _login(client)
    name, bd = project_factory("obsconfirmreveal")
    item_id = bd.create("about to be held", tags=[A.LANE_WORK])
    item = bd.claim_next(lane=A.LANE_WORK, actor=unique_actor) or bd.get(item_id)

    plain = client.get(f"/projects/{name}/items/{item.id}")
    assert plain.status_code == 200
    assert 'name="confirm" value="yes"' not in plain.text
    assert "?confirm_resolve=1" in plain.text

    confirming = client.get(f"/projects/{name}/items/{item.id}", params={"confirm_resolve": "1"})
    assert confirming.status_code == 200
    assert 'name="confirm" value="yes"' in confirming.text
    assert f'action="/projects/{name}/items/{item.id}/resolve"' in confirming.text
