"""Tier 2 (integration) tests for wt-v4 Observatory's L1 (project) and L2
(item detail) routes, mounted standalone via ``webbrowse.register`` -- no
auth middleware, so no login step, proving the module mounts independently
of ``webapp.create_app``'s full app.

Retired: the v3 split-pane browse view (``/projects/{name}/browse``,
``?item=`` selection) -- see ``webbrowse.py``'s module docstring. Its
former coverage here is superseded by the redirect test below plus
``test_web.py``'s own L1/L2 route coverage (run through the full,
authenticated app).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

pytestmark = pytest.mark.integration

pytest.importorskip("fastapi", reason="the 'web' extra is not installed")

from fastapi import FastAPI  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from amplifier_work_tracker import adapter as A  # noqa: E402
from amplifier_work_tracker import webbrowse as B  # noqa: E402


@pytest.fixture
def browse_env(workspace, project_factory) -> Iterator[tuple[str, A.Beads, TestClient]]:
    """A fresh isolated project + a TestClient over a tiny app that mounts
    ONLY webbrowse's routes (via ``register``), proving the module mounts
    standalone."""
    name, bd = project_factory("browse")
    app = FastAPI()
    B.register(app, workspace)
    with TestClient(app, follow_redirects=False) as client:
        yield name, bd, client


def test_retired_browse_route_redirects_to_l1_without_item_param(browse_env):
    name, _bd, client = browse_env
    resp = client.get(f"/projects/{name}/browse")
    assert resp.status_code == 302
    assert resp.headers["location"] == f"/projects/{name}"


def test_retired_browse_route_redirects_to_l2_with_item_param(browse_env):
    name, bd, client = browse_env
    item_id = bd.create("redirect target item")
    resp = client.get(f"/projects/{name}/browse", params={"item": item_id})
    assert resp.status_code == 302
    assert resp.headers["location"] == f"/projects/{name}/items/{item_id}"


def test_l1_lists_items_as_direct_links_to_l2(browse_env):
    name, bd, client = browse_env
    bd.create("First browse item", tags=[A.LANE_WORK])
    bd.create("Second browse item", tags=[A.LANE_WORK])

    resp = client.get(f"/projects/{name}")
    assert resp.status_code == 200
    html = resp.text
    assert "First browse item" in html
    assert "Second browse item" in html
    assert 'class="item-row"' in html


def test_l2_shows_the_real_item_content(browse_env):
    name, bd = browse_env[0], browse_env[1]
    client = browse_env[2]
    item_id = bd.create("Selectable item", description="the body text here")

    resp = client.get(f"/projects/{name}/items/{item_id}")
    assert resp.status_code == 200
    html = resp.text
    assert "Selectable item" in html
    assert "the body text here" in html
    assert item_id in html


def test_l2_unknown_item_is_graceful_not_500(browse_env):
    name, bd, client = browse_env
    bd.create("Present item")

    resp = client.get(f"/projects/{name}/items/{name}-ghost999")
    assert resp.status_code == 200
    assert "doesn't exist" in resp.text.lower()


def test_l1_unknown_project_is_graceful(browse_env):
    _name, _bd, client = browse_env
    resp = client.get("/projects/definitely_not_a_project")
    assert resp.status_code == 200
    # the shared not-found body, not a traceback
    assert "doesn't exist" in resp.text.lower()


def test_l1_and_l2_ship_the_auto_refresh_poller(browse_env):
    """L1 gets the poller (observability surface, meant to update live); L2
    (an editable form page) never does -- same protected-page convention
    `webapp.py`'s own item-detail-predecessor established."""
    name, bd = browse_env[0], browse_env[1]
    client = browse_env[2]
    item_id = bd.create("Poller probe item")

    l1_html = client.get(f"/projects/{name}").text
    assert "__wtAutoRefreshStarted" in l1_html

    l2_html = client.get(f"/projects/{name}/items/{item_id}").text
    assert "__wtAutoRefreshStarted" not in l2_html


def test_l1_and_l2_reflect_status_transitions_live(browse_env, unique_actor):
    """Every request reads fresh: an item claimed then resolved shows its
    resolved state and resolution text on the next GET -- never a stale
    model."""
    name, bd, client = browse_env
    item_id = bd.create("Lifecycle item", tags=[A.LANE_WORK])

    # open -> held
    bd.claim_item(item_id, actor=unique_actor)
    held_html = client.get(f"/projects/{name}/items/{item_id}").text
    assert "held" in held_html.lower()

    # held -> resolved
    bd.resolve(item_id, "done and dusted", actor=unique_actor)
    resolved_html = client.get(f"/projects/{name}/items/{item_id}").text
    assert "done and dusted" in resolved_html
    assert "Resolution" in resolved_html


def test_l1_and_l2_show_the_corrected_badge_and_errata_block_after_an_erratum(
    browse_env, unique_actor
):
    """The resolution TEXT renders unchanged; an erratum is an ADDITIONAL,
    clearly-marked block -- never a rewrite of what was actually published.
    Both L1 (list row) and L2 (detail) surfaces must show the correction."""
    name, bd, client = browse_env
    item_id = bd.create("Erratum probe item", tags=[A.LANE_WORK])
    bd.claim_item(item_id, actor=unique_actor)
    bd.resolve(item_id, "the original published verdict", actor=unique_actor)

    # Before the erratum: neither surface claims the item is corrected.
    l1_before = client.get(f"/projects/{name}").text
    assert "corrected" not in l1_before

    bd.erratum(item_id, actor="corrector", text="the underlying data was mislabeled")

    l1_after = client.get(f"/projects/{name}").text
    assert "corrected" in l1_after

    l2_html = client.get(f"/projects/{name}/items/{item_id}").text
    assert "the original published verdict" in l2_html  # resolution unchanged
    assert "Errata" in l2_html
    assert "corrector" in l2_html
    assert "the underlying data was mislabeled" in l2_html
    assert "corrected" in l2_html


def test_l1_bounds_its_item_query_and_says_so_when_the_bound_binds(browse_env, monkeypatch):
    """Core 10 end to end: the L1 read is bounded, and a bounded read is
    confessed rather than passed off as a total.

    The ceiling is lowered to 2 for this test rather than creating 501 items
    -- the mechanism under test is the bound and the sentence it produces,
    not the specific number. Three items against a ceiling of 2 also
    exercises the one-past-the-window probe: the view asks for 3, gets 3,
    and therefore KNOWS more exist rather than guessing from a full window.
    """
    name, bd, client = browse_env
    for n in range(3):
        bd.create(f"Bounded query item {n}", tags=[A.LANE_WORK])
    monkeypatch.setattr(B, "_L1_ITEM_QUERY_LIMIT", 2)

    html = client.get(f"/projects/{name}").text
    assert "read capped at 2" in html, "a bounded read must say it was bounded"
    assert "of 2+ items" in html, (
        "a capped read reports a FLOOR (`2+`), never a bare count that reads as a measured total"
    )


def test_l1_says_nothing_about_truncation_when_it_is_showing_everything(browse_env):
    """The other direction: a small project must not wear a truncation note
    it did not earn.
    """
    name, bd, client = browse_env
    bd.create("The only item", tags=[A.LANE_WORK])

    html = client.get(f"/projects/{name}").text
    assert "The only item" in html
    # The CLASS name is always in the stylesheet; it is the rendered ELEMENT
    # that must be absent.
    assert '<div class="truncation-note">' not in html
    assert "read capped at" not in html
