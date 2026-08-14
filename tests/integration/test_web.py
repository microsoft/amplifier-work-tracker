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
    assert r.headers["location"].startswith(f"/projects/{name}?msg=added%20")

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
    assert "not found" in r.text.lower() or "no items" in r.text.lower()


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
