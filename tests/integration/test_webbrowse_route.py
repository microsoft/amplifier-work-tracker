"""Tier 2 (integration) tests for the split-pane browse route.

Real ``bd`` + the session's isolated dolt server (see ``tests/conftest.py``).
The route is mounted onto a throwaway ``FastAPI`` app via
``webbrowse.register`` -- no auth middleware, so no login step -- exactly the
"build a tiny app that registers your route directly" path the goal calls for.
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
    """A fresh isolated project + a TestClient over a tiny app that mounts ONLY
    the browse route (via ``register``), proving the module mounts standalone."""
    name, bd = project_factory("browse")
    app = FastAPI()
    B.register(app, workspace)
    with TestClient(app, follow_redirects=False) as client:
        yield name, bd, client


def test_browse_lists_items_and_prompts_selection(browse_env):
    name, bd, client = browse_env
    bd.create("First browse item")
    bd.create("Second browse item")

    resp = client.get(f"/projects/{name}/browse")
    assert resp.status_code == 200
    html = resp.text
    # both panes present with their stable scroll-container ids
    assert 'id="browse-list"' in html
    assert 'id="browse-detail"' in html
    # both items listed
    assert "First browse item" in html
    assert "Second browse item" in html
    # nothing selected -> the detail pane prompts a selection
    assert "Select a work item" in html


def test_browse_selecting_an_item_renders_its_detail(browse_env):
    name, bd, client = browse_env
    item_id = bd.create("Selectable item", description="the body text here")

    resp = client.get(f"/projects/{name}/browse", params={"item": item_id})
    assert resp.status_code == 200
    html = resp.text
    # the detail pane shows the selected item's real content (read fresh from bd)
    assert "Selectable item" in html
    assert "the body text here" in html
    assert item_id in html
    # the selected row carries the selection affordance
    assert "wtb-row selected" in html
    assert 'aria-current="true"' in html
    # canonical editable item page reachable from the read-only pane
    assert f'href="/projects/{name}/items/{item_id}"' in html


def test_browse_missing_selection_is_graceful_not_500(browse_env):
    name, bd, client = browse_env
    bd.create("Present item")

    resp = client.get(f"/projects/{name}/browse", params={"item": f"{name}-ghost999"})
    assert resp.status_code == 200
    assert "could not be found" in resp.text
    # the list still renders alongside the graceful detail message
    assert "Present item" in resp.text


def test_browse_unknown_project_is_graceful(browse_env):
    _name, _bd, client = browse_env
    resp = client.get("/projects/definitely_not_a_project/browse")
    assert resp.status_code == 200
    # the shared not-found body, not a traceback
    assert "doesn't exist" in resp.text


def test_browse_survives_redirect_flash_and_ships_the_pollers(browse_env):
    """A post-mutation redirect can land on this view with ?item=&msg=; the
    view must render the flash AND a FRESH model for the item, and it must ship
    both the auto-refresh poller and the scroll-preservation script that let it
    survive its own 20s body swap."""
    name, bd, client = browse_env
    item_id = bd.create("Redirected-to item")

    resp = client.get(
        f"/projects/{name}/browse",
        params={"item": item_id, "msg": "added something"},
    )
    assert resp.status_code == 200
    html = resp.text
    # flash from the redirect is shown
    assert "added something" in html
    # fresh model for the selected item is rendered (no stale/again-error)
    assert "Redirected-to item" in html
    # the self-polling auto-refresh is shipped (webtheme.auto_refresh_js marker)
    assert "__wtAutoRefreshStarted" in html
    # the scroll-preservation + client-side selection script is shipped
    assert "__wtBrowseListScroll" in html
    assert "browse-detail" in html


def test_browse_reflects_status_transitions_live(browse_env, unique_actor):
    """Every request reads fresh: an item claimed then resolved shows its
    resolved state and resolution text on the next GET -- never a stale model."""
    name, bd, client = browse_env
    item_id = bd.create("Lifecycle item")

    # open -> held
    bd.claim_item(item_id, actor=unique_actor)
    held_html = client.get(f"/projects/{name}/browse", params={"item": item_id}).text
    assert "held" in held_html.lower()

    # held -> resolved
    bd.resolve(item_id, "done and dusted", actor=unique_actor)
    resolved_html = client.get(f"/projects/{name}/browse", params={"item": item_id}).text
    assert "done and dusted" in resolved_html
    assert "Resolution" in resolved_html
