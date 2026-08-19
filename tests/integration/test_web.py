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

import re
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
    assert "amplifier-work-tracker" in resp.text


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


def test_full_write_flow_create_add_resolve_remove(
    client, unique_project_name, unique_actor, workspace
):
    """The write flow minus claiming: this web UI has no claim affordance at
    all (agents claim via the `work_claim` tool -- see webapp.py's module
    docstring and `test_no_claim_affordance_anywhere_in_the_web_ui` below).
    The item is claimed directly through the adapter here only so the test
    can reach a HELD item to resolve -- exactly like `unique_actor` claiming
    it out-of-band before an operator resolves it through the browser.
    """
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

    # Extract the item id from the project listing page (id cells are the
    # only <td> content matching the project's id prefix).
    import re

    m = re.search(rf"{re.escape(name)}-\w+", r.text)
    assert m, r.text
    item_id = m.group(0)

    bd = workspace.project(name)
    bd.claim_item(item_id, actor=unique_actor)  # out-of-band, like a real agent's work_claim

    r = client.get(f"/projects/{name}")
    assert unique_actor in r.text  # holder column shows the real, current holder

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


def test_no_claim_route_exists(client, project_factory, unique_actor):
    """There is no `/projects/{name}/claim` route at all -- claiming is an
    agent action taken through the `work_claim` tool, never this browser
    UI. Posting to the old route must 404, not silently do nothing with a
    200/303."""
    _login(client)
    name, _bd = project_factory("noclaimrouteproj")
    r = client.post(
        f"/projects/{name}/claim",
        data={"mode": "next", "actor": unique_actor, "lane": A.LANE_WORK},
    )
    assert r.status_code == 404


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
    """The headline finding: every item in the project's split-pane list
    must be a real link -- not inert text -- reachable through to its own
    editable detail page.

    goal wtv3/project-page: the list row's own href now SELECTS the item
    inline (matching the already-shipped `/browse` split-pane view), and
    the populated detail pane's "Open full item" link is the second hop to
    the real, editable `/items/<id>` page. Both hops are real, clickable
    navigation -- never a guessed/typed URL."""
    _login(client)
    name, bd = project_factory("linkproj")
    item_id = bd.create("clickable row", tags=[A.LANE_WORK])

    r = client.get(f"/projects/{name}")
    assert r.status_code == 200
    assert f"item={item_id}" in r.text  # row's own selection href

    selected = client.get(f"/projects/{name}", params={"item": item_id})
    assert selected.status_code == 200
    assert f'href="/projects/{name}/items/{item_id}"' in selected.text


def test_item_detail_open_item_shows_no_lifecycle_action(client, project_factory):
    """An open (unclaimed) item has no lifecycle action control at all on
    this page -- no Claim (agents claim via `work_claim`, never a browser)
    and no Resolve (only a held item's own holder resolves it)."""
    _login(client)
    name, bd = project_factory("openitemproj")
    item_id = bd.create("unclaimed item", tags=[A.LANE_WORK])
    r = client.get(f"/projects/{name}/items/{item_id}")
    assert r.status_code == 200
    assert "Claim this item" not in r.text
    assert "Claim</button>" not in r.text
    assert "Resolve" not in r.text
    # But it IS editable -- the save form is present for every status.
    assert 'action="/projects/' in r.text
    assert "/update" in r.text


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
    # The edit form's OWN textareas (description/acceptance/design) are still
    # present -- a resolved item stays editable, only its lifecycle state
    # (status/holder/timestamps) is locked -- so the resolve-specific
    # "reason" field is what must be absent, not every textarea.
    assert 'name="reason"' not in r.text
    assert f'action="/projects/{name}/items/{item.id}/update"' in r.text


def test_item_detail_nonexistent_item_shows_friendly_error(client, shared_project_name):
    _login(client)
    r = client.get(f"/projects/{shared_project_name}/items/does-not-exist-123")
    assert r.status_code == 200
    assert "doesn't exist" in r.text.lower()
    assert ".beads" not in r.text


# ---------------------------------------------- item detail: blocker chain


def test_item_detail_shows_blocked_by_chain_with_status_and_holder(
    client, project_factory, unique_actor
):
    """The headline finding for Beadbox idea #7: a blocked item's detail
    page names its blocker's id/title, status, and who holds it."""
    _login(client)
    name, bd = project_factory("blockerchainproj")
    blocker_id = bd.create("upstream blocker item", tags=[A.LANE_WORK])
    blocked_id = bd.create("downstream blocked item", tags=[A.LANE_WORK])
    r = bd._run(["dep", blocker_id, "--blocks", blocked_id])  # noqa: SLF001 -- test setup
    assert r.returncode == 0, r.stderr
    bd.claim_item(blocker_id, actor=unique_actor)

    resp = client.get(f"/projects/{name}/items/{blocked_id}")
    assert resp.status_code == 200
    assert "Blocked by" in resp.text
    assert blocker_id in resp.text
    assert "upstream blocker item" in resp.text
    assert "blocker-item unsatisfied" in resp.text
    assert unique_actor in resp.text  # held-by owner


def test_item_detail_blocker_chain_clears_once_blocker_resolved(
    client, project_factory, unique_actor
):
    _login(client)
    name, bd = project_factory("blockerclearsproj")
    blocker_id = bd.create("clears: blocker item", tags=[A.LANE_WORK])
    blocked_id = bd.create("clears: blocked item", tags=[A.LANE_WORK])
    r = bd._run(["dep", blocker_id, "--blocks", blocked_id])  # noqa: SLF001
    assert r.returncode == 0, r.stderr

    before = client.get(f"/projects/{name}/items/{blocked_id}")
    assert "blocker-item unsatisfied" in before.text

    bd.claim_item(blocker_id, actor=unique_actor)
    bd.resolve(blocker_id, "cleared", actor=unique_actor)

    after = client.get(f"/projects/{name}/items/{blocked_id}")
    assert after.status_code == 200
    assert "blocker-item satisfied" in after.text
    assert "blocker-item unsatisfied" not in after.text
    assert "&#10003;" in after.text  # the check mark on the cleared chain


def test_item_detail_shows_discovered_from_provenance(client, project_factory):
    _login(client)
    name, bd = project_factory("discoveredproj")
    origin_id = bd.create("origin report", tags=[A.LANE_WORK])
    found_id = bd.create(
        "discovered while working origin", tags=[A.LANE_WORK], discovered_from=[origin_id]
    )
    resp = client.get(f"/projects/{name}/items/{found_id}")
    assert resp.status_code == 200
    assert "Discovered while working" in resp.text
    assert origin_id in resp.text
    # A discovered-from link never blocks -- must never render as a blocker.
    # Checks the actual rendered HEADING/ATTRIBUTE markup, not a bare
    # substring: both "Blocked by" and "blocker-item" also appear inside
    # webtheme.py's own CSS (a comment, and the `.blocker-item.unsatisfied`/
    # `.blocker-item.satisfied` selectors respectively) which is present on
    # every page via the shared <style> block, so a bare substring check
    # would false-positive on the stylesheet rather than real content. A
    # rendered `<li>` always carries `class="blocker-item ..."` (a space,
    # not the CSS selector's dot) -- that's the precise, unambiguous signal.
    assert '<h2 class="eyebrow am" style="display:block;margin-top:30px">Blocked by</h2>' not in (
        resp.text
    )
    assert 'class="blocker-item' not in resp.text


def test_item_detail_shows_blocks_inverse(client, project_factory):
    _login(client)
    name, bd = project_factory("blocksinverseproj")
    blocker_id = bd.create("inverse: blocker", tags=[A.LANE_WORK])
    blocked_id = bd.create("inverse: blocked", tags=[A.LANE_WORK])
    r = bd._run(["dep", blocker_id, "--blocks", blocked_id])  # noqa: SLF001
    assert r.returncode == 0, r.stderr

    resp = client.get(f"/projects/{name}/items/{blocker_id}")
    assert resp.status_code == 200
    assert "Blocks" in resp.text
    assert blocked_id in resp.text


# ---------------------------------------------- item detail: activity feed


def test_item_detail_shows_activity_feed_with_real_events(client, project_factory, unique_actor):
    _login(client)
    name, bd = project_factory("activityfeedproj")
    item_id = bd.create("activity feed probe", tags=[A.LANE_WORK])
    bd.claim_item(item_id, actor=unique_actor)
    r = bd._run(["comment", item_id, "a very specific comment body"])  # noqa: SLF001
    assert r.returncode == 0, r.stderr
    bd.resolve(item_id, "a very specific resolution reason", actor=unique_actor)

    resp = client.get(f"/projects/{name}/items/{item_id}")
    assert resp.status_code == 200
    assert "Activity" in resp.text
    assert "Created" in resp.text
    assert "Claimed" in resp.text
    assert "Comment" in resp.text
    assert "a very specific comment body" in resp.text
    assert "Resolved" in resp.text


def test_item_detail_fresh_item_activity_feed_shows_only_created(client, project_factory):
    _login(client)
    name, bd = project_factory("activityfreshproj")
    item_id = bd.create("fresh activity probe", tags=[A.LANE_WORK])
    resp = client.get(f"/projects/{name}/items/{item_id}")
    assert resp.status_code == 200
    assert "Activity" in resp.text
    assert "Created" in resp.text
    assert "Comment" not in resp.text
    assert "Resolved" not in resp.text


def test_no_claim_affordance_anywhere_in_the_web_ui(client, project_factory, unique_actor):
    """Agent-focus regression guard: no page this UI renders offers a way
    to claim an item from a browser -- not the project listing, not an
    open item's own detail page, not a held one's. Claiming happens
    exclusively through the `work_claim` tool."""
    _login(client)
    name, bd = project_factory("noclaimuiproj")
    open_id = bd.create("open item, no claim button", tags=[A.LANE_WORK])
    held_item = bd.claim_next(lane=A.LANE_WORK, actor=unique_actor) or bd.get(open_id)

    # Checked as specific real UI signals, not a blanket "claim" substring
    # across the whole page -- the page's own embedded base64 font data
    # legitimately contains that substring by coincidence (gibberish
    # bytes), which a blanket check would misreport as a claim affordance.
    forbidden = ("Claim this item", "Claim next", ">Claim<", '/claim"')
    for text in (
        client.get(f"/projects/{name}").text,
        client.get(f"/projects/{name}/items/{open_id}").text,
        client.get(f"/projects/{name}/items/{held_item.id}").text,
    ):
        for phrase in forbidden:
            assert phrase not in text


# --------------------------------------------------- honest dashboard signals


def test_dashboard_held_item_raises_the_custody_reading(client, project_factory, unique_actor):
    """The A-Ledger overview has no per-row holder chip (see webapp.py's
    dashboard-rendering module comment) -- a held item's signal is the
    workspace-wide CUSTODY secondary reading and the queue's own
    composition-bar HELD segment, not a named identity on the overview."""
    _login(client)
    name, bd = project_factory("dashboardheldproj")
    bd.create("held for dashboard signal", tags=[A.LANE_WORK])
    bd.claim_next(lane=A.LANE_WORK, actor=unique_actor)

    r = client.get("/")
    assert r.status_code == 200
    assert '<span class="k">Custody</span>' in r.text
    # the held count (>=1) must appear as the custody reading's own figure
    assert re.search(r'Custody</span>\s*<span class="n">[1-9]\d*</span>', r.text)


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


# ----------------------------------------------- cycle 2: pagination/reachability


def test_project_view_pagination_reachability_and_no_cli_flag_leak(
    client, project_factory, unique_lane
):
    """Cycle 2 fix #1: a project with more than one page's worth of items
    must be FULLY reachable by clicking -- and the copy that used to say
    "raise --limit" (a CLI flag a browser user has no way to pass) must be
    gone. One project, exercised in two phases, to keep the (real, slow)
    project bootstrap cost down to a single call.

    goal wtv3/project-page: reachability is now a deliberate TWO-hop model,
    matching the already-shipped `/browse` split-pane view (see
    `test_webbrowse_route.py`'s own selection test, which established this
    exact pattern): a row's own href SELECTS it inline (`?...&item=<id>`,
    preserving `page`/`status`/`q`), and the populated (read-only) detail
    pane carries an "Open full item" link to the real, editable
    `/items/<id>` page. Every item is still reachable by clicking -- never
    by guessing/typing a URL, never a CLI flag -- just one hop further than
    the retired single-column table's direct link. This test verifies both
    hops.
    """
    _login(client)
    name, bd = project_factory("paginateproj")

    # Phase 1 -- well under one page. The pagination control must be
    # entirely ABSENT: "nothing to paginate" is the correct empty case,
    # not a degraded/disabled version of the control.
    few_ids = [bd.create(f"small batch {n}", tags=[unique_lane]) for n in range(3)]
    r0 = client.get(f"/projects/{name}")
    assert r0.status_code == 200
    assert 'class="pagination"' not in r0.text
    for i in few_ids:
        assert f"item={i}" in r0.text  # every item's own selection href present

    # Phase 2 -- push past one page's worth of items.
    page_size = A.LIST_DEFAULT_LIMIT
    more_ids = [bd.create(f"page probe {n:03d}", tags=[unique_lane]) for n in range(page_size)]
    all_ids = few_ids + more_ids  # page_size + 3 -- guaranteed more than one page

    r1 = client.get(f"/projects/{name}")
    assert r1.status_code == 200
    page1_text = r1.text
    next_href = f"/projects/{name}?page=2"
    assert f'href="{next_href}"' in page1_text
    assert "--limit" not in page1_text  # no CLI flag anywhere in the web copy

    # Every row is a real split-pane selection link, not text-width-only.
    assert 'class="wtb-rows"' in page1_text

    missing_from_page1 = [i for i in all_ids if f"item={i}" not in page1_text]
    assert missing_from_page1, "expected at least one item to be unreachable on page 1 alone"

    # Reachable by clicking Next -- not by guessing/typing a per-item URL.
    r2 = client.get(next_href)
    assert r2.status_code == 200
    assert "--limit" not in r2.text
    for i in missing_from_page1:
        assert f"item={i}" in r2.text
    assert f'href="/projects/{name}?page=1"' in r2.text  # Previous goes back

    # A stale/hand-typed page far beyond the real last page lands on the
    # real last page instead of a confusingly empty one.
    r3 = client.get(f"/projects/{name}", params={"page": "999"})
    assert r3.status_code == 200
    assert "No items yet" not in r3.text
    for i in missing_from_page1:
        assert f"item={i}" in r3.text

    # The status filter survives across a page link.
    r4 = client.get(f"/projects/{name}", params={"status": "open"})
    assert r4.status_code == 200
    assert f'href="/projects/{name}?page=2&status=open"' in r4.text

    # Second hop: selecting any one item surfaces the real, editable item
    # page -- genuine end-to-end reachability, not just a selection href
    # that goes nowhere further.
    one_id = few_ids[0]
    r5 = client.get(f"/projects/{name}", params={"item": one_id})
    assert r5.status_code == 200
    assert f'href="/projects/{name}/items/{one_id}"' in r5.text


# ------------------------------------------------- cycle 2: numeric alignment


def test_dashboard_queue_table_numeric_columns_are_right_aligned(client, shared_project_name):
    """The A-Ledger queue table's numeric columns (Total/Ready/Resolved/
    Done) -- see webapp.py's `_dashboard_row`/dashboard route."""
    _login(client)
    r = client.get("/")
    assert r.status_code == 200
    assert '<th class="r">Total</th>' in r.text
    assert '<th class="r">Ready</th>' in r.text
    assert '<th class="r">Resolved</th>' in r.text
    assert '<th class="r">Done&nbsp;%</th>' in r.text


def test_dashboard_project_name_cell_is_a_stretched_link(client, shared_project_name):
    """Cycle 2 fix #6: the whole cell is clickable, not just the text."""
    _login(client)
    r = client.get("/")
    assert r.status_code == 200
    assert '<td class="link-cell">' in r.text


# ------------------------------------------------- cycle 2: identity display


def test_item_detail_humanizes_the_reported_by_identity_end_to_end(client, shared_bd):
    """`owner` is bd's own concept (the git identity of whoever's `bd create`
    call made the item -- NOT the `--actor`/`BEADS_ACTOR` audit-trail value;
    that one lands in the raw `created_by` field instead, which this UI
    doesn't render). On this real, shared installation `owner` is always
    the Amplifier co-author trailer address -- exactly the verbatim string
    the cycle-2 bug report named. This is an end-to-end check against that
    real, naturally-occurring value; see `test_humanize_identity_*` in
    `tests/unit` for the pure-function passthrough/no-op guarantees that
    don't depend on what bd happens to set `owner` to in this environment.
    """
    _login(client)
    item_id = shared_bd.create("reported-by probe (real owner identity)", tags=[A.LANE_WORK])
    name = shared_bd._dir.parent.name  # noqa: SLF001 -- test-only introspection
    r = client.get(f"/projects/{name}/items/{item_id}")
    assert r.status_code == 200
    item = shared_bd.get(item_id)
    owner = item.raw.get("owner")
    if not owner:
        import pytest  # noqa: PLC0415

        pytest.skip(
            "bd set no `owner` on this item -- happens where the environment has no "
            "git identity (e.g. a bare CI container with no `git config user.email`). "
            "`owner` is an environment-provided value, not a code invariant; the "
            "environment-independent humanization guarantees are covered by "
            "test_humanize_identity_* in tests/unit."
        )
    from amplifier_work_tracker.webapp import _humanize_identity  # noqa: PLC0415

    humanized = _humanize_identity(owner)
    assert f"REPORTED BY {owner}" not in r.text.upper().replace("\n", " ")
    assert humanized in r.text
    assert owner in r.text  # the exact raw value is still present (a tooltip)
    assert f">{owner}<" not in r.text  # but never as the visible label text


# -------------------------------------------- cycle 2: destructive-path guard


def test_remove_confirmation_page_is_real_and_get_is_side_effect_free(client, project_factory):
    """The Danger Zone link must land on a real confirmation page requiring
    the typed project name -- never delete on a bare GET."""
    _login(client)
    name, bd = project_factory("removeguardproj")
    bd.create("still here after GET", tags=[A.LANE_WORK])

    r = client.get(f"/projects/{name}/remove")
    assert r.status_code == 200
    assert "type the project name" in r.text.lower()
    assert f'value="{name}"' not in r.text  # not pre-filled -- must be typed to confirm

    r2 = client.get(f"/projects/{name}")
    assert r2.status_code == 200
    assert "still here after GET" in r2.text  # GET never removed anything


def test_remove_held_refusal_is_rendered_as_visible_text_on_the_confirm_page(
    client, project_factory, unique_actor
):
    """The HELD-items refusal from `Workspace.remove` must actually reach
    the browser as readable text on the page the redirect lands on -- not
    just an opaque `error=` flag on the redirect URL."""
    _login(client)
    name, bd = project_factory("heldguardproj")
    bd.create("guard probe", tags=[A.LANE_WORK])
    bd.claim_next(lane=A.LANE_WORK, actor=unique_actor)

    r = client.post(f"/projects/{name}/remove", data={"confirm_name": name})
    assert r.status_code == 303
    assert "remove" in r.headers["location"]
    assert "error=" in r.headers["location"]

    r2 = client.get(r.headers["location"])
    assert r2.status_code == 200
    assert "held" in r2.text.lower()
    assert unique_actor in r2.text  # names the actual holder, per Workspace.remove


# ------------------------------------------------------- item edit (save)


def test_item_detail_edit_form_saves_and_persists_on_reload(client, project_factory):
    """The real save round-trip: title/description/acceptance/design all
    change via one POST, and the NEW values are what a fresh GET shows --
    not just what the redirect claims."""
    _login(client)
    name, bd = project_factory("itemeditproj")
    item_id = bd.create(
        "original title",
        tags=[A.LANE_WORK],
        description="original description",
        acceptance="original acceptance",
        design="original design",
    )

    r = client.post(
        f"/projects/{name}/items/{item_id}/update",
        data={
            "title": "edited title",
            "description": "edited description",
            "acceptance": "edited acceptance",
            "design": "edited design",
        },
    )
    assert r.status_code == 303, r.text
    assert r.headers["location"] == f"/projects/{name}/items/{item_id}?msg=saved%20{item_id}"

    r2 = client.get(f"/projects/{name}/items/{item_id}")
    assert r2.status_code == 200
    assert "edited title" in r2.text
    assert "original title" not in r2.text
    assert "edited description" in r2.text
    assert "edited acceptance" in r2.text
    assert "edited design" in r2.text

    # And directly against the adapter -- the real persisted record, not
    # just what the page happens to render.
    item = bd.get(item_id)
    assert item.title == "edited title"
    assert item.description == "edited description"
    assert item.acceptance == "edited acceptance"
    assert item.design == "edited design"


def test_item_detail_edit_form_is_present_and_prefilled(client, project_factory):
    name, bd = project_factory("itemeditformproj")
    item_id = bd.create(
        "prefill probe",
        tags=[A.LANE_WORK],
        description="prefill description",
        acceptance="prefill acceptance",
    )
    _login(client)
    r = client.get(f"/projects/{name}/items/{item_id}")
    assert r.status_code == 200
    assert f'action="/projects/{name}/items/{item_id}/update"' in r.text
    assert 'name="title"' in r.text
    assert 'value="prefill probe"' in r.text
    assert "<textarea" in r.text
    assert "prefill description" in r.text
    assert "prefill acceptance" in r.text


def test_item_detail_edit_does_not_touch_status_or_holder(client, project_factory, unique_actor):
    """Status/holder are lifecycle facts, not part of this form -- editing
    the free-text fields of a HELD item must never change who holds it or
    what status it is in."""
    _login(client)
    name, bd = project_factory("itemeditlifeproj")
    bd.create("about to be edited while held", tags=[A.LANE_WORK])
    item = bd.claim_next(lane=A.LANE_WORK, actor=unique_actor)

    r = client.post(
        f"/projects/{name}/items/{item.id}/update",
        data={"title": "edited while held", "description": "", "acceptance": "", "design": ""},
    )
    assert r.status_code == 303

    fresh = bd.get(item.id)
    assert fresh.title == "edited while held"
    assert fresh.status == "held"
    assert fresh.holder == unique_actor


def test_item_detail_edit_blank_fields_leave_existing_values_unchanged(client, project_factory):
    """Submitting an empty description/acceptance/design does not clear an
    existing value -- see `Beads.update`'s docstring for why blank means
    'leave unchanged' here, the same convention `add_item` already uses."""
    _login(client)
    name, bd = project_factory("itemeditblankproj")
    item_id = bd.create(
        "keep my body text",
        tags=[A.LANE_WORK],
        description="keep this description",
        acceptance="keep this acceptance",
    )

    r = client.post(
        f"/projects/{name}/items/{item_id}/update",
        data={"title": "keep my body text", "description": "", "acceptance": "", "design": ""},
    )
    assert r.status_code == 303

    item = bd.get(item_id)
    assert item.description == "keep this description"
    assert item.acceptance == "keep this acceptance"


def test_item_detail_edit_nonexistent_item_reports_error(client, shared_project_name):
    """A failed save (nonexistent item) must redirect back to the item page
    with a safe error, not leak a raw exception or a filesystem path."""
    _login(client)
    r = client.post(
        f"/projects/{shared_project_name}/items/does-not-exist-999/update",
        data={"title": "x", "description": "", "acceptance": "", "design": ""},
    )
    assert r.status_code == 303
    assert "error=" in r.headers["location"]
    assert ".beads" not in r.headers["location"]


# ---------------------------------------------------------------- rename


def test_rename_project_success_redirects_to_new_name(client, project_factory, workspace):
    _login(client)
    name, bd = project_factory("renamesrc")
    bd.create("survives the rename", tags=[A.LANE_WORK])
    new_name = f"{name}renamed"

    try:
        r = client.post(f"/projects/{name}/rename", data={"new_name": new_name})
        assert r.status_code == 303, r.text
        assert r.headers["location"].startswith(f"/projects/{new_name}")

        r2 = client.get(f"/projects/{new_name}")
        assert r2.status_code == 200
        assert "survives the rename" in r2.text

        r3 = client.get(f"/projects/{name}")
        assert r3.status_code == 200
        assert "doesn't exist" in r3.text.lower()  # old name no longer resolves
    finally:
        # `project_factory`'s own teardown tracks `name`, which no longer
        # exists on the server once the rename lands (dropping it is then a
        # safe no-op -- see `drop_project`'s docstring). The LIVE database is
        # now `new_name`; drop it directly here so the isolated-server
        # assertion never sees it as an unaccounted-for leak.
        from tests.conftest import drop_project  # noqa: PLC0415

        drop_project(workspace, new_name)


def test_rename_project_rejects_invalid_new_name(client, project_factory):
    _login(client)
    name, _bd = project_factory("renameinvalidproj")
    r = client.post(f"/projects/{name}/rename", data={"new_name": "Not-A-Valid-Name"})
    assert r.status_code == 303
    assert f"/projects/{name}" in r.headers["location"]
    assert "error=" in r.headers["location"]

    # Original project is untouched and still reachable under its old name.
    r2 = client.get(f"/projects/{name}")
    assert r2.status_code == 200


def test_rename_project_refuses_when_target_name_already_exists(client, project_factory):
    _login(client)
    name_a, _bd_a = project_factory("renametargeta")
    name_b, _bd_b = project_factory("renametargetb")

    r = client.post(f"/projects/{name_a}/rename", data={"new_name": name_b})
    assert r.status_code == 303
    assert "error=" in r.headers["location"]

    # Both projects still exist, untouched.
    assert client.get(f"/projects/{name_a}").status_code == 200
    assert client.get(f"/projects/{name_b}").status_code == 200


def test_rename_project_refuses_while_item_is_held(client, project_factory, unique_actor):
    _login(client)
    name, bd = project_factory("renameheldproj")
    bd.create("holding up the rename", tags=[A.LANE_WORK])
    bd.claim_next(lane=A.LANE_WORK, actor=unique_actor)
    new_name = f"{name}renamed"

    r = client.post(f"/projects/{name}/rename", data={"new_name": new_name})
    assert r.status_code == 303
    assert f"/projects/{name}" in r.headers["location"]
    assert "error=" in r.headers["location"]

    # Never renamed -- old name still resolves, new name does not exist.
    r2 = client.get(f"/projects/{name}")
    assert r2.status_code == 200
    assert "holding up the rename" in r2.text


def test_danger_zone_has_rename_form_and_no_claim_control(client, project_factory):
    _login(client)
    name, _bd = project_factory("dangerzoneproj")
    r = client.get(f"/projects/{name}")
    assert r.status_code == 200
    assert f'action="/projects/{name}/rename"' in r.text
    assert 'name="new_name"' in r.text
    assert f'href="/projects/{name}/remove"' in r.text
    assert "Claim next ready item" not in r.text


def test_danger_zone_rename_affordance_is_unambiguous_reveal_save_cancel(client, project_factory):
    """Regression guard for the reported footgun: clicking "Rename" used to
    reveal an inline input right above the SAME "Rename" button, with no
    visible distinction between "open the editor" and "submit it" -- a
    visitor had to click the identical button twice to find out the second
    click was the save. The fix is a dedicated `#rename-trigger` (never a
    submit control -- `type="button"`) that starts the form's `hidden`
    attribute set, plus an explicit Save (`type="submit"`) and Cancel
    (`type="button"`, never submits) inside it -- so there is exactly one
    button that opens the editor and exactly one that saves, never the
    same element doing both.
    """
    _login(client)
    name, _bd = project_factory("renamereveal")
    r = client.get(f"/projects/{name}")
    assert r.status_code == 200
    text = r.text

    # The trigger that reveals the editor: a plain button, never a submit.
    assert 'id="rename-trigger"' in text
    assert 'type="button" id="rename-trigger"' in text

    # The form starts hidden -- the editor is not shown until the trigger
    # is clicked (see `webtheme.rename_disclosure_js`).
    assert 'id="rename-form"' in text
    form_start = text.index('id="rename-form"')
    form_tag = text[max(0, form_start - 200) : form_start + 120]
    assert "hidden" in form_tag

    # Exactly one Save (submits) and one Cancel (never submits) inside it.
    assert '<button type="submit" class="btn danger">Save</button>' in text
    assert 'id="rename-cancel"' in text
    assert 'type="button" id="rename-cancel"' in text

    # The reveal/cancel behaviour is real client-side script, not just markup.
    assert "rename-trigger" in text and "openForm" in text


# --------------------------------------- holder-chip contradiction (regression)


def test_resolved_item_row_shows_no_holder_chip_though_it_has_a_stale_assignee(
    client, project_factory, unique_actor
):
    """Regression guard for the reported contradiction: a resolved item
    keeps its last assignee (`holder`) as a real historical fact, but that
    is NOT a current custody holder -- the project's `held` stat is (and
    must stay) 0.

    goal wtv3/project-page: the split-pane row (`webbrowse._row_html`, via
    `project_view`'s `row_extra_builder` -- see that route's own
    `_item_held_html`) renders NO held/custody line at all for a non-held
    item -- absent entirely, the same "absent when calm, never a dimmed
    placeholder" convention the attention banner already uses -- never a
    holder-looking chip with a dash standing in for "not held."
    """
    _login(client)
    name, bd = project_factory("resolvedholderproj")
    bd.create("will be claimed then resolved", tags=[A.LANE_WORK])
    item = bd.claim_next(lane=A.LANE_WORK, actor=unique_actor)
    bd.resolve(item.id, "done", actor=unique_actor)

    r = client.get(f"/projects/{name}")
    assert r.status_code == 200
    # No held/custody line rendered for this (resolved, not held) row at
    # all. The row's own `data-t` search-index attribute legitimately still
    # carries the actor's name for search-by-holder purposes (see
    # `webbrowse._row_html`'s `key`), which is a separate, deliberate
    # concern from what's visibly rendered.
    assert 'class="wtb-holder"' not in r.text
    # The project's own "Held" tally agrees: 0 currently held, even though
    # this project has exactly one resolved item with a real leftover holder.
    assert '<div class="v">0</div><span class="k">Held</span>' in r.text

    # And the status filter agrees too: nothing is actually held.
    held_only = client.get(f"/projects/{name}", params={"status": "held"})
    assert held_only.status_code == 200
    assert "No items match" in held_only.text


def test_resolved_item_detail_shows_no_held_by_chip(client, project_factory, unique_actor):
    _login(client)
    name, bd = project_factory("rhdetailproj")
    bd.create("will be claimed then resolved (detail)", tags=[A.LANE_WORK])
    item = bd.claim_next(lane=A.LANE_WORK, actor=unique_actor)
    bd.resolve(item.id, "done", actor=unique_actor)

    r = client.get(f"/projects/{name}/items/{item.id}")
    assert r.status_code == 200
    assert "held by" not in r.text.lower()


# ------------------------------------------------------------- auto-refresh
#
# `webtheme.auto_refresh_js` is JS -- these tests cannot execute it (no JS
# engine in `TestClient`'s ASGI transport). What they DO pin, with real
# server responses, is the mechanism's most safety-critical property: which
# pages ship the poller and which never do. A real, browser-driven
# demonstration of the poller actually firing (and the alarm treatment it
# reveals) lives outside this suite -- see the goal's own verification notes.

_AUTO_REFRESH_MARKER = "__wtAutoRefreshStarted"


def test_dashboard_includes_auto_refresh_script(client, shared_project_name):
    _login(client)
    r = client.get("/")
    assert r.status_code == 200
    assert _AUTO_REFRESH_MARKER in r.text
    assert str(webapp._AUTO_REFRESH_MS) in r.text  # noqa: SLF001 -- pinning the real interval


def test_project_view_includes_auto_refresh_script(client, shared_project_name):
    _login(client)
    r = client.get(f"/projects/{shared_project_name}")
    assert r.status_code == 200
    assert _AUTO_REFRESH_MARKER in r.text


def test_item_detail_never_includes_auto_refresh_script(client, project_factory):
    """The hard requirement: the edit page (live, unsaved title/description/
    acceptance/design inputs) must NEVER ship the poller at all -- not
    guarded, not conditionally, absent. The safest guard against clobbering
    an in-progress edit is not shipping the mechanism to this page."""
    _login(client)
    name, bd = project_factory("noautorefreshproj")
    new_id = bd.create("edit page must never auto-refresh", tags=[A.LANE_WORK])
    r = client.get(f"/projects/{name}/items/{new_id}")
    assert r.status_code == 200
    assert _AUTO_REFRESH_MARKER not in r.text
    assert "setInterval" not in r.text


def test_login_page_never_includes_auto_refresh_script(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert _AUTO_REFRESH_MARKER not in r.text


def test_remove_confirm_page_never_includes_auto_refresh_script(client, project_factory):
    _login(client)
    name, _bd = project_factory("norefreshrmproj")
    r = client.get(f"/projects/{name}/remove")
    assert r.status_code == 200
    assert _AUTO_REFRESH_MARKER not in r.text


# ------------------------------------------------ list polish: status tabs


def test_project_view_status_tabs_show_real_counts(client, project_factory, unique_lane):
    """The tab row's counts are the real per-project state -- not a
    fabricated/placeholder reading."""
    _login(client)
    name, bd = project_factory("tabcountsproj")
    bd.create("ready one", tags=[unique_lane, A.LANE_WORK])
    bd.create("ready two", tags=[unique_lane, A.LANE_WORK])

    r = client.get(f"/projects/{name}")
    assert r.status_code == 200
    assert 'class="tabs"' in r.text
    assert ">Ready<" in r.text
    assert ">Held<" in r.text
    assert ">Blocked<" in r.text
    assert ">Deferred<" in r.text
    assert ">Resolved<" in r.text
    # Two real ready items, everything else genuinely zero and dimmed.
    assert '<span class="tcount">2</span>' in r.text
    assert '<span class="tcount z">0</span>' in r.text


def test_project_view_clicking_a_status_tab_filters_the_list(client, project_factory, unique_lane):
    """Note: the ready-queue HERO (`_project_hero_html`, "oldest unclaimed
    in this queue") legitimately names this item's title regardless of the
    list's own status filter -- it is a project-wide reading, not part of
    the filtered list. So the filtering assertion is scoped to the item
    LIST itself (absent entirely -- an honest empty-state -- once
    filtered to a status this item doesn't have), not a blanket "title
    appears nowhere on the page" check.

    goal wtv3/project-page: the item list is now the split-pane's
    `.wtb-rows` (squircle row cards), not the retired `<table class="tbl">`
    -- see webapp.py's `project_view`, which reuses webbrowse.py's shared
    split-pane machinery."""
    _login(client)
    name, bd = project_factory("tabfilterproj")
    bd.create("only an open item", tags=[unique_lane, A.LANE_WORK])

    all_view = client.get(f"/projects/{name}")
    assert "only an open item" in all_view.text
    assert 'class="wtb-rows"' in all_view.text

    filtered = client.get(f"/projects/{name}", params={"status": "blocked"})
    assert filtered.status_code == 200
    assert 'class="wtb-rows"' not in filtered.text  # no rows -- filtered to nothing
    assert "No items match status" in filtered.text
    assert f'href="/projects/{name}?status=blocked"' in filtered.text
    assert 'class="tab active"' in filtered.text


def test_project_view_no_longer_ships_a_status_select_dropdown(client, shared_project_name):
    """The tab row replaces the old `<select name="status">` control
    entirely -- one status-filter widget, not two."""
    _login(client)
    r = client.get(f"/projects/{shared_project_name}")
    assert r.status_code == 200
    assert '<select name="status"' not in r.text


# ------------------------------------------ list polish: per-project health banner


def test_project_view_health_banner_absent_when_calm(client, project_factory, unique_lane):
    """A project with nothing held/blocked/deferred shows NO banner at
    all -- never a dimmed '0 blocked' (see `_attention_signal_html`)."""
    _login(client)
    name, bd = project_factory("calmprojbanner")
    bd.create("a perfectly calm ready item", tags=[unique_lane, A.LANE_WORK])

    r = client.get(f"/projects/{name}")
    assert r.status_code == 200
    assert "need attention" not in r.text


def test_project_view_health_banner_present_when_blocked(client, project_factory, unique_actor):
    _login(client)
    name, bd = project_factory("blockedprojbanner")
    item_id = bd.create("an item that will be blocked", tags=[A.LANE_WORK])
    # No public adapter method sets bd's raw status directly (by design --
    # see adapter.py's `update` docstring: lifecycle changes go through
    # dedicated, fenced methods, none of which cover a bare status flip).
    # `_run` is the same private escape hatch test_directed_claim.py
    # already uses for setup the public seam doesn't expose.
    r_status = bd._run(["update", item_id, "--status", "blocked"], actor=unique_actor)  # noqa: SLF001
    assert r_status.returncode == 0, r_status.stderr

    r = client.get(f"/projects/{name}")
    assert r.status_code == 200
    assert "need attention" in r.text
    assert "flash-error" in r.text
    assert "1 item blocked" in r.text


def test_project_view_health_banner_present_when_held(client, project_factory, unique_actor):
    _login(client)
    name, bd = project_factory("heldprojbanner")
    item_id = bd.create("an item to hold", tags=[A.LANE_WORK])
    bd.claim_item(item_id, actor=unique_actor)

    r = client.get(f"/projects/{name}")
    assert r.status_code == 200
    assert "need attention" in r.text
    assert "flash-msg" in r.text
    assert "1 item held" in r.text


# --------------------------------------------------- list polish: row gutter


def test_project_view_item_rows_include_priority_bar_and_status_icon(
    client, project_factory, unique_lane
):
    _login(client)
    name, bd = project_factory("gutterproj")
    bd.create("gutter probe item", tags=[unique_lane, A.LANE_WORK])

    r = client.get(f"/projects/{name}")
    assert r.status_code == 200
    # goal wtv3/project-page: the row's gutter is now the split-pane's
    # `.wtb-gutter` (squircle row card), not the retired table cell's
    # `class="c gutter"` -- see webbrowse.py's `_row_html`, reused verbatim.
    assert 'class="wtb-gutter"' in r.text
    # v3 fidelity pass (goal wtv3/components, B3/B4): a priority CHIP, not
    # the prior coloured bar.
    assert "priority-chip" in r.text
    assert "stico" in r.text


# ------------------------------------------------- list polish: item-detail age


def test_item_detail_created_and_updated_use_the_compact_age_format(client, project_factory):
    """Created/Updated on the item-detail page use the SAME compact
    relative-age vocabulary the item table's Age column uses (`age`/`age
    a0..a3` bands) -- not the coarser '12m ago' phrasing. Scoped to the
    exact fact rows rather than a blanket "'ago' not in the whole page"
    check -- the page also embeds base64 font data, where an incidental
    'ago' substring is not meaningful."""
    _login(client)
    name, bd = project_factory("itemagedetailproj")
    new_id = bd.create("fresh item for age check", tags=[A.LANE_WORK])

    r = client.get(f"/projects/{name}/items/{new_id}")
    assert r.status_code == 200
    assert '<span class="k">Created</span><span class="v serif">' in r.text
    assert '<span class="k">Updated</span><span class="v serif">' in r.text
    assert ">now<" in r.text
    assert "m ago" not in r.text
    assert "h ago" not in r.text
    assert "d ago" not in r.text


# ------------------------------------------------ nav/density: sidebar chrome


def test_dashboard_includes_the_sidebar_with_a_rollup_and_no_current_project(
    client, project_factory
):
    _login(client)
    name, _bd = project_factory("navsidebardash")

    r = client.get("/")
    assert r.status_code == 200
    assert 'id="sidebar"' in r.text
    assert "All projects" in r.text
    assert f'href="/projects/{name}"' in r.text
    # the roll-up is "current" on the dashboard, no project row is
    assert 'href="/" aria-current="page"' in r.text


def test_project_view_includes_the_sidebar_with_this_project_marked_current(
    client, project_factory
):
    _login(client)
    name, _bd = project_factory("navsidebarproj")

    r = client.get(f"/projects/{name}")
    assert r.status_code == 200
    assert 'id="sidebar"' in r.text
    assert f'href="/projects/{name}" aria-current="page"' in r.text
    assert 'href="/" aria-current="page"' not in r.text


def test_sidebar_shows_real_open_over_total_counts_for_a_real_project(
    client, project_factory, unique_lane
):
    _login(client)
    name, bd = project_factory("navsidebarcounts")
    bd.create("one", tags=[unique_lane, A.LANE_WORK])
    bd.create("two", tags=[unique_lane, A.LANE_WORK])

    r = client.get("/")
    assert r.status_code == 200
    assert '<span class="sb-badge" title="2 open of 2 items">2/2</span>' in r.text


def test_sidebar_marks_a_held_project_with_the_amber_alarm_class(
    client, project_factory, unique_actor
):
    _login(client)
    name, bd = project_factory("navsidebarheld")
    item_id = bd.create("an item to hold", tags=[A.LANE_WORK])
    bd.claim_item(item_id, actor=unique_actor)

    r = client.get("/")
    assert r.status_code == 200
    assert "alarm-am" in r.text


def test_sidebar_present_on_the_empty_workspace_state_too(client, workspace, unique_project_name):
    """The 'no projects yet' branch gets a sidebar too (an honest, empty
    one) -- chrome should not suddenly appear the moment the first project
    is created. `unique_project_name` (never created here) only keeps the
    fixture's teardown registered; the empty-state branch itself is
    exercised directly at the unit level (`_sidebar_html([], [], None)`),
    since it requires a genuinely-empty workspace this shared `client`
    fixture (session-scoped `workspace`, populated by every other test in
    this module) cannot guarantee.
    """
    assert unique_project_name
    _login(client)
    r = client.get("/")
    assert r.status_code == 200
    assert 'id="sidebar"' in r.text


# --------------------------------------------- nav/density: search shortcut hint


def test_project_view_search_placeholder_carries_the_slash_shortcut_hint(
    client, shared_project_name
):
    _login(client)
    r = client.get(f"/projects/{shared_project_name}")
    assert r.status_code == 200
    assert 'placeholder="Search titles, ids, holders and state  /"' in r.text
    # the accessible name stays clean -- no "slash" noise for a screen reader
    assert 'aria-label="Search titles, ids, holders and state"' in r.text


def test_dashboard_search_hint_carries_the_slash_shortcut(client, shared_project_name):
    """v3 fidelity pass (goal wtv3/components, B10): a real `<kbd>` element,
    ported from the approved gallery's own `.search-input kbd`."""
    _login(client)
    r = client.get("/")
    assert r.status_code == 200
    assert "<kbd>/</kbd>" in r.text


# --------------------------------------------- nav/density: density + keynav js


def test_dashboard_includes_the_density_toggle_and_keynav_script(client, shared_project_name):
    _login(client)
    r = client.get("/")
    assert r.status_code == 200
    assert 'id="density-toggle"' in r.text
    assert "window.__wtKeyNavBound" in r.text
    assert "wt-density" in r.text


def test_project_view_includes_the_density_toggle_and_keynav_script(client, project_factory):
    _login(client)
    name, _bd = project_factory("navdensityproj")
    r = client.get(f"/projects/{name}")
    assert r.status_code == 200
    assert 'id="density-toggle"' in r.text
    assert "window.__wtKeyNavBound" in r.text
    assert "wt-density" in r.text


def test_item_detail_never_includes_the_keynav_script(client, project_factory):
    """Same protected-page convention as `auto_refresh_js`: the item-detail
    edit form never receives a document-level keydown listener either."""
    _login(client)
    name, bd = project_factory("navdensitynoitem")
    item_id = bd.create("an item", tags=[A.LANE_WORK])
    r = client.get(f"/projects/{name}/items/{item_id}")
    assert r.status_code == 200
    assert "window.__wtKeyNavBound" not in r.text
    assert 'id="density-toggle"' not in r.text
