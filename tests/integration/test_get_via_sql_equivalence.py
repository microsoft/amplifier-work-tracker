"""`Beads.get()` (the `with_links=False` base-item path) now reads via a
read-only SQL SELECT (`_get_item_via_sql`), not `bd show <id> --json`, for
the same reason `Beads.list()` / `project_summary` were fixed the same way
(see `_list_rows_via_sql`'s docstring): a plain `bd show` read+WRITEs (it
appends an interaction-log row per call), and that read+write transaction
CAN lose a dolt serialization conflict against the shared single-writer
server's concurrent write traffic -- `_run` burns retries on a call that
need never have had a write set at all. A pure SELECT has no write set, so
it cannot conflict at any contention level. See work_tracker item
pipeline-bug.

These tests pin EQUIVALENCE between the two paths against the real
`bd`/dolt storage layer (the isolated per-session test server -- see
`tests/_dolt_isolation.py`): `_old_get` below is a frozen reconstruction of
`Beads.get()`'s PRE-FIX `with_links=False` body (the `bd show` path),
calling the still-present, unchanged `Beads._json` private method directly.
Comparing its output against the live `Beads.get()` (the NEW SQL path) on
freshly-created, fully-controlled test data proves the seam swap changed
nothing observable for the base item -- same fields, same not-found
behavior -- for every case `get()`/`get_readonly()` need to handle.

`with_links=True` is NOT touched by this fix (still `bd show
--include-dependents`, unchanged) -- see `Beads.get`'s own docstring for
why that enrichment deliberately stays on bd. A small pin test below
confirms the links path still returns the right shape, so a future change
cannot accidentally break it while working on the base-item path.
"""

from __future__ import annotations

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.integration


def _old_get(b: A.Beads, item_id: str) -> A.Item:
    """Exact reconstruction of `Beads.get()`'s PRE-FIX `with_links=False`
    body -- the `bd show <id> --json` path -- kept here, frozen, purely as
    the equivalence baseline the new SQL path is compared against. `_json`
    is unchanged by this fix, so this still exercises the real `bd` CLI
    against the real (isolated test) dolt server, not a mock."""
    d = b._json(["show", item_id])  # noqa: SLF001 -- deliberate: pinning the old path
    d = d[0] if isinstance(d, list) else d
    if not isinstance(d, dict):
        raise A.BeadsError(f"show {item_id} returned no object")
    return A.Item.from_beads(d)


def _key(i: A.Item) -> tuple:
    """The full comparable shape of an `Item` for equivalence purposes --
    every field the new SQL path populates (deliberately excludes `raw`,
    `links`: the old path's `raw` is bd's JSON dict, the new path's is the
    SQL row dict, and links are out of scope for this fix -- see module
    docstring)."""
    return (
        i.id,
        i.title,
        i.status,
        i.holder,
        i.kind,
        i.resolution,
        i.acceptance,
        i.description,
        i.design,
        tuple(sorted(i.tags)),
        i.meta,
        i.priority,
        i.created_at,
        i.updated_at,
        i.closed_at,
        i.created_by,
    )


# ------------------------------------------------------------------- basics


def test_get_open_item_matches_old_path_exactly(shared_bd, unique_lane):
    item_id = shared_bd.create(
        "equiv get open",
        tags=[unique_lane],
        priority=2,
        description="a description",
        acceptance="Given/When/Then",
    )
    old = _old_get(shared_bd, item_id)
    new = shared_bd.get(item_id)
    assert _key(old) == _key(new)


def test_get_held_item_matches_old_path_exactly(shared_bd, unique_lane):
    item_id = shared_bd.create("equiv get held", tags=[unique_lane])
    shared_bd.claim_item(item_id, actor="equiv-get-actor")
    old = _old_get(shared_bd, item_id)
    new = shared_bd.get(item_id)
    assert _key(old) == _key(new)
    assert new.status == "held"
    assert new.holder == "equiv-get-actor"
    shared_bd.resolve(item_id, "test cleanup", actor="equiv-get-actor")


def test_get_resolved_item_matches_old_path_exactly(shared_bd, unique_lane):
    item_id = shared_bd.create("equiv get resolved", tags=[unique_lane])
    shared_bd.claim_item(item_id, actor="equiv-get-resolved-actor")
    shared_bd.resolve(item_id, "equiv get resolution text", actor="equiv-get-resolved-actor")
    old = _old_get(shared_bd, item_id)
    new = shared_bd.get(item_id)
    assert _key(old) == _key(new)
    assert new.status == "resolved"
    assert new.resolution == "equiv get resolution text"


def test_get_unknown_item_raises_same_way_as_old_path(shared_bd):
    fake_id = f"{shared_bd.project_name}-zzzzzzz"
    with pytest.raises(A.BeadsError):
        _old_get(shared_bd, fake_id)
    with pytest.raises(A.BeadsError):
        shared_bd.get(fake_id)


# ------------------------------------------------------ free-text/metadata


def test_get_free_text_with_commas_and_newlines_survives_intact(shared_bd, unique_lane):
    """The exact hazard the JSON (not CSV) projection in `_list_rows_via_sql`
    -- which `_get_item_via_sql` reuses -- exists to avoid: a description
    containing commas AND embedded newlines must round-trip byte-for-byte
    through the new SQL path, matching the old bd-args path exactly."""
    tricky_description = (
        "Line one, with a comma.\nLine two, also, with, several, commas.\n"
        'Line three has "quotes, too" and a trailing comma,'
    )
    tricky_title = 'Get title, with a comma and "quotes"'
    item_id = shared_bd.create(
        tricky_title,
        tags=[unique_lane],
        description=tricky_description,
        acceptance="Given X, When Y, Then Z, with a trailing comma,",
    )
    old = _old_get(shared_bd, item_id)
    new = shared_bd.get(item_id)
    assert new.title == old.title == tricky_title
    assert new.description == old.description == tricky_description
    assert new.acceptance == old.acceptance


def test_get_metadata_dict_round_trips_via_sql_path(shared_bd, unique_lane):
    item_id = shared_bd.create(
        "equiv get metadata probe", tags=[unique_lane], meta={"nested": {"a": 1}, "flag": True}
    )
    new = shared_bd.get(item_id)
    assert new.meta == {"nested": {"a": 1}, "flag": True}


def test_get_priority_is_int_not_string_via_sql_path(shared_bd, unique_lane):
    item_id = shared_bd.create("equiv get priority-type probe", tags=[unique_lane], priority=3)
    new = shared_bd.get(item_id)
    assert new.priority == 3
    assert isinstance(new.priority, int)


# ------------------------------------------------------------- no mutation


def test_get_via_sql_never_mutates_anything(shared_bd, unique_lane):
    """The entire point of the fix: a `SELECT` has no write set. Full item
    state before/after several `get()` calls must be identical."""
    item_id = shared_bd.create("equiv get no-mutation probe", tags=[unique_lane])

    def snapshot():
        i = shared_bd.get(item_id)
        return (i.status, i.holder, i.resolution, i.title, tuple(sorted(i.tags)))

    before = snapshot()
    shared_bd.get(item_id)
    shared_bd.get(item_id)
    shared_bd.get_readonly(item_id)
    after = snapshot()
    assert before == after


# --------------------------------------------------------------- get_readonly


def test_get_readonly_real_missing_item_reports_not_found(shared_bd):
    """End-to-end (no monkeypatching) confirmation that `get_readonly`'s
    not-found disambiguation still works against the real SQL-backed
    `get()`: a genuinely-missing id under THIS project's own prefix must
    report plain "not found", never "wrong project"."""
    fake_id = f"{shared_bd.project_name}-zzzzzzz"
    with pytest.raises(A.BeadsError) as exc_info:
        shared_bd.get_readonly(fake_id)
    assert "not found in project" in str(exc_info.value)
    assert "does not look like it belongs" not in str(exc_info.value)


def test_get_readonly_real_wrong_project_prefix_reports_mismatch(shared_bd):
    fake_id = "totally-different-project-99"
    with pytest.raises(A.BeadsError) as exc_info:
        shared_bd.get_readonly(fake_id)
    assert "does not look like it belongs to project" in str(exc_info.value)


# ------------------------------------------------------------------- links


def test_get_with_links_still_returns_dependency_graph(shared_bd, unique_lane):
    """`with_links=True` is out of scope for this fix (still `bd show
    --include-dependents`, see `Beads.get`'s docstring) -- pinned here so a
    future change to the base-item path cannot silently break it."""
    src_id = shared_bd.create("equiv get links source", tags=[unique_lane])
    work_id = shared_bd.create("equiv get links work", tags=[unique_lane], discovered_from=[src_id])
    full = shared_bd.get(work_id, with_links=True)
    assert full.id == work_id
    from_links = [ln for ln in full.links if ln["direction"] == "from"]
    assert any(ln["id"] == src_id for ln in from_links)
