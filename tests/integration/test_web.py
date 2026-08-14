"""Integration tests for the web dashboard (`webapp.py` / `webauth.py`).

Real `bd` + the shared dolt server are required (same tier-2 contract as the
rest of `tests/integration`), driven in-process via
`starlette.testclient.TestClient` against `webapp.create_app` -- no real
network port is opened, but every request travels the real ASGI app, the
real auth middleware, and the real `adapter.Workspace`/`Beads` seam against
the isolated `workspace_root` this suite already uses (see conftest.py's
module docstring for the isolation model). None of this touches the
developer's real `~/.amplifier-work-tracker`.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

pytest.importorskip("fastapi", reason="the 'web' extra is not installed")

from starlette.testclient import TestClient  # noqa: E402

from amplifier_work_tracker import adapter as A  # noqa: E402
from amplifier_work_tracker import webapp  # noqa: E402
from amplifier_work_tracker import webauth as WA  # noqa: E402

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


# --------------------------------------------------------------------- auth


def test_unauthenticated_request_to_dashboard_is_refused_json(client):
    resp = client.get("/", headers={"accept": "application/json"})
    assert resp.status_code == 401, resp.text


def test_unauthenticated_request_to_dashboard_redirects_browser(client):
    resp = client.get("/")
    assert resp.status_code == 307
    assert resp.headers["location"].startswith("/login")


def test_healthz_is_exempt_from_auth(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_login_wrong_password_is_rejected_and_sets_no_cookie(client):
    resp = client.post("/login", data={"username": "operator", "password": "definitely-wrong"})
    assert resp.status_code == 303
    assert "login" in resp.headers["location"]
    assert WA.SESSION_COOKIE_NAME not in resp.cookies


def test_login_success_sets_cookie_and_grants_dashboard_access(client):
    _login(client)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Projects" in resp.text


def test_logout_clears_session(client):
    _login(client)
    resp = client.get("/auth/logout")
    assert resp.status_code == 303
    resp2 = client.get("/", headers={"accept": "application/json"})
    assert resp2.status_code == 401


# ---------------------------------------------------------- dashboard data


def test_dashboard_shows_real_project_from_the_shared_workspace(client, shared_project_name):
    _login(client)
    resp = client.get("/")
    assert resp.status_code == 200
    assert shared_project_name in resp.text


def test_project_view_shows_items_with_holder_and_status(client, shared_bd, unique_lane):
    shared_bd.create("web ui probe item", tags=[unique_lane, A.LANE_WORK])
    _login(client)
    project_name = shared_bd._dir.parent.name  # noqa: SLF001 -- test-only introspection
    resp = client.get(f"/projects/{project_name}")
    assert resp.status_code == 200
    assert "web ui probe item" in resp.text


# ------------------------------------------------------------- write flow


def test_full_write_flow_create_add_claim_resolve_remove(client, unique_project_name, unique_actor):
    _login(client)
    name = unique_project_name

    r = client.post("/projects", data={"name": name}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/?msg=created%20project%20%27{name}%27"

    r = client.post(
        f"/projects/{name}/items",
        data={"title": "do the thing", "description": "desc", "acceptance": "given/when/then"},
    )
    assert r.status_code == 303
    # Adding an item lands you on that item's own detail page (where its
    # description/acceptance criteria actually live), not back on the bare
    # listing -- see webapp.py's module docstring.
    assert r.headers["location"].startswith(f"/projects/{name}/items/{name}-")
    assert "msg=added" in r.headers["location"]

    r = client.get(f"/projects/{name}")
    assert r.status_code == 200
    assert "do the thing" in r.text

    r = client.post(
        f"/projects/{name}/claim",
        data={"mode": "next", "actor": unique_actor, "lane": A.LANE_WORK},
    )
    assert r.status_code == 303, r.text
    assert "claimed" in r.headers["location"]

    r = client.get(f"/projects/{name}")
    assert unique_actor in r.text  # holder column shows the claiming actor

    # Extract the claimed item id from the project listing page (id cells
    # are the only <td> content matching the project's id prefix).
    import re

    m = re.search(rf"{re.escape(name)}-\w+", r.text)
    assert m, r.text
    item_id = m.group(0)

    r = client.post(
        f"/projects/{name}/items/{item_id}/resolve",
        data={"reason": "done via web ui test", "actor": unique_actor},
    )
    assert r.status_code == 303
    assert "resolved" in r.headers["location"]

    r = client.post(f"/projects/{name}/remove", data={"confirm_name": name})
    assert r.status_code == 303
    assert r.headers["location"] == f"/?msg=removed%20project%20%27{name}%27"

    r = client.get(f"/projects/{name}")
    assert r.status_code == 200
    assert "doesn't exist" in r.text.lower()
    # The friendly copy must never leak the local filesystem path or the
    # CLI-only instruction that the raw adapter exception carries.
    assert ".beads" not in r.text
    assert "amplifier-work-tracker new" not in r.text


def test_remove_refuses_when_item_is_held_and_project_survives(
    client, project_factory, unique_actor
):
    _login(client)
    name, bd = project_factory("heldproj")
    bd.create("held probe", tags=[A.LANE_WORK])
    bd.claim_next(lane=A.LANE_WORK, actor=unique_actor)

    r = client.post(f"/projects/{name}/remove", data={"confirm_name": name})
    assert r.status_code == 303
    assert "remove" in r.headers["location"]
    assert "error=" in r.headers["location"]

    r = client.get(f"/projects/{name}")
    assert r.status_code == 200  # project still exists -- refusal did not remove it


def test_remove_requires_typed_name_to_match(client, project_factory):
    _login(client)
    name, _bd = project_factory("mismatchproj")
    r = client.post(f"/projects/{name}/remove", data={"confirm_name": "not-the-right-name"})
    assert r.status_code == 303
    assert f"/projects/{name}/remove" in r.headers["location"]
    assert "error=" in r.headers["location"]

    r = client.get(f"/projects/{name}")
    assert r.status_code == 200  # still exists


def test_directed_claim_by_id(client, project_factory, unique_actor):
    _login(client)
    name, bd = project_factory("directedproj")
    item_id = bd.create("directed probe", tags=[A.LANE_WORK])

    r = client.post(
        f"/projects/{name}/claim",
        data={"mode": "id", "actor": unique_actor, "item_id": item_id},
    )
    assert r.status_code == 303
    assert "claimed" in r.headers["location"]

    r = client.get(f"/projects/{name}")
    assert unique_actor in r.text


def test_claim_with_no_ready_work_reports_error(client, project_factory, unique_actor):
    _login(client)
    name, _bd = project_factory("emptyqueueproj")
    r = client.post(
        f"/projects/{name}/claim",
        data={"mode": "next", "actor": unique_actor, "lane": "lane:nonexistent"},
    )
    assert r.status_code == 303
    assert "error=" in r.headers["location"]


# ----------------------------------------------------------- item detail


def test_item_detail_shows_description_and_acceptance_criteria(client, project_factory):
    _login(client)
    name, bd = project_factory("detailproj")
    item_id = bd.create(
        "read the docs",
        tags=[A.LANE_WORK],
        description="a very specific description body",
        acceptance="given/when/then criteria text",
    )
    r = client.get(f"/projects/{name}/items/{item_id}")
    assert r.status_code == 200
    assert "a very specific description body" in r.text
    assert "given/when/then criteria text" in r.text


def test_item_detail_reachable_from_project_listing(client, project_factory):
    """The headline finding: every item id/title in the project table must
    be a real link to its own detail page -- not inert text."""
    _login(client)
    name, bd = project_factory("linkproj")
    item_id = bd.create("clickable row", tags=[A.LANE_WORK])
    r = client.get(f"/projects/{name}")
    assert r.status_code == 200
    assert f'href="/projects/{name}/items/{item_id}"' in r.text


def test_item_detail_open_item_shows_claim_not_resolve(client, project_factory):
    _login(client)
    name, bd = project_factory("openitemproj")
    item_id = bd.create("unclaimed item", tags=[A.LANE_WORK])
    r = client.get(f"/projects/{name}/items/{item_id}")
    assert r.status_code == 200
    assert "Claim this item" in r.text
    assert "Resolve" not in r.text


def test_item_detail_held_item_shows_resolve_not_claim(client, project_factory, unique_actor):
    _login(client)
    name, bd = project_factory("helditemproj")
    bd.create("about to be held", tags=[A.LANE_WORK])
    item = bd.claim_next(lane=A.LANE_WORK, actor=unique_actor)
    r = client.get(f"/projects/{name}/items/{item.id}")
    assert r.status_code == 200
    assert "Resolve" in r.text
    assert "Claim this item" not in r.text
    assert unique_actor in r.text  # "held by <actor>" chip


def test_item_detail_resolved_item_shows_resolution_and_no_action_controls(
    client, project_factory, unique_actor
):
    _login(client)
    name, bd = project_factory("resolveditemproj")
    bd.create("will be resolved", tags=[A.LANE_WORK])
    item = bd.claim_next(lane=A.LANE_WORK, actor=unique_actor)
    long_resolution = "x" * 950  # exercise a long resolution body, not just a short one
    bd.resolve(item.id, long_resolution, actor=unique_actor)

    r = client.get(f"/projects/{name}/items/{item.id}")
    assert r.status_code == 200
    assert long_resolution in r.text
    assert "Claim this item" not in r.text
    # No resolve control either -- absent, not merely disabled, once resolved.
    assert "<textarea" not in r.text
    assert 'name="reason"' not in r.text


def test_item_detail_nonexistent_item_shows_friendly_error(client, shared_project_name):
    _login(client)
    r = client.get(f"/projects/{shared_project_name}/items/does-not-exist-123")
    assert r.status_code == 200
    assert "doesn't exist" in r.text.lower()
    assert ".beads" not in r.text


def test_directed_claim_redirects_to_item_detail_page(client, project_factory, unique_actor):
    _login(client)
    name, bd = project_factory("claimredirectproj")
    item_id = bd.create("directed claim redirect probe", tags=[A.LANE_WORK])

    r = client.post(
        f"/projects/{name}/claim",
        data={"mode": "id", "actor": unique_actor, "item_id": item_id},
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith(f"/projects/{name}/items/{item_id}")


# --------------------------------------------------- honest dashboard signals


def test_dashboard_shows_held_by_chip_for_a_held_item(client, project_factory, unique_actor):
    _login(client)
    name, bd = project_factory("dashboardheldproj")
    bd.create("held for dashboard signal", tags=[A.LANE_WORK])
    bd.claim_next(lane=A.LANE_WORK, actor=unique_actor)

    r = client.get("/")
    assert r.status_code == 200
    assert unique_actor in r.text


def test_dashboard_never_shows_a_static_health_ok_badge(client, shared_project_name):
    """The redesign's whole point: no column that can only ever read one
    value (see webapp.py's module docstring)."""
    _login(client)
    r = client.get("/")
    assert r.status_code == 200
    assert "badge-ok" not in r.text
    assert ">ok<" not in r.text


# ------------------------------------------------------------- empty states


def test_project_view_empty_filter_state_names_the_filter_and_offers_clear(client, project_factory):
    _login(client)
    name, bd = project_factory("emptyfilterproj")
    bd.create("only an open item", tags=[A.LANE_WORK])

    r = client.get(f"/projects/{name}", params={"status": "blocked"})
    assert r.status_code == 200
    assert "No items match" in r.text
    assert "blocked" in r.text
    assert f'href="/projects/{name}"' in r.text  # clear-filter link


def test_add_item_error_on_nonexistent_project_does_not_leak_path_or_cli(client):
    _login(client)
    r = client.post(
        "/projects/this-project-does-not-exist-anywhere/items",
        data={"title": "orphaned item"},
    )
    assert r.status_code == 303
    assert "error=" in r.headers["location"]
    assert ".beads" not in r.headers["location"]
    assert "amplifier-work-tracker" not in r.headers["location"]
