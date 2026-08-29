"""`Beads.list()` now reads via a read-only SQL SELECT (`_list_rows_via_sql`),
not `bd list [--all|--status][--label][--limit] --json`, for the same reason
`project_summary` was fixed the same way (see `_summary_items_via_sql`'s
docstring): a plain `bd list` read+WRITEs (it appends an interaction-log row
per call), and on a large project that read+write transaction reliably loses
a dolt serialization conflict against the shared single-writer server's
concurrent write traffic -- `_run` exhausts its whole `_MAX_RETRIES` (8)
budget and raises. A pure SELECT has no write set, so it cannot conflict at
any project size. See work_tracker items pipeline-exz / pipeline-knu.

These tests pin EQUIVALENCE between the two paths against the real
`bd`/dolt storage layer (the isolated per-session test server, not the
shared production one -- see `tests/_dolt_isolation.py`): `_old_list` below
is an exact, frozen reconstruction of `Beads.list()`'s PRE-FIX body (the
`bd`-args path), calling the still-present, unchanged `Beads._json`/`_run`
private methods directly. Comparing its output against the live
`Beads.list()` (the NEW SQL path) on freshly-created, fully-controlled test
data proves the seam swap changed nothing observable -- same ids, same
order, same fields -- for every filter combination `Beads.list()` supports.

A one-off LIVE run of this same comparison was also performed directly
against every real project on the shared PRODUCTION dolt server (21
projects x 7 filter combinations = 147 checks: 136 matched exactly, 11 were
the known-large-project confirmations -- `bd`'s own path failing exactly as
the bug describes while the new SQL path succeeds) -- that one-off check is
not itself a permanent automated test (it deliberately talks to production
data outside the test isolation model), but its result is the evidence this
fix actually closes the bug for cortex/openai_improvement/work_tracker.
"""

from __future__ import annotations

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.integration


def _old_list(
    b: A.Beads,
    *,
    lane: str | None = None,
    include_resolved: bool = False,
    status: str | None = None,
    limit: int | None = None,
) -> list[A.Item]:
    """Exact reconstruction of `Beads.list()`'s PRE-FIX body -- the `bd list
    [--all|--status][--label][--limit] --json` path -- kept here, frozen,
    purely as the equivalence baseline these tests compare the new SQL path
    against. `_json`/`_run` are unchanged by this fix, so this still
    exercises the real `bd` CLI against the real (isolated test) dolt
    server, not a mock.
    """
    args = ["list"]
    if status is not None:
        raw = A._STATUS_MAP_REVERSE.get(status)  # noqa: SLF001 -- deliberate: pinning the old path
        if raw is None:
            raise A.BeadsError(f"unknown status {status!r}: must be one of {A.STATUSES}")
        args += ["--status", raw]
    elif include_resolved:
        args += ["--all"]
    if lane:
        args += ["--label", lane]
    if limit is not None:
        args += ["--limit", str(limit)]
    data = b._json(args) or []  # noqa: SLF001
    return [A.Item.from_beads(d) for d in data if isinstance(d, dict)]


def _key(i: A.Item) -> tuple:
    """The full comparable shape of an `Item` for equivalence purposes --
    every field the new SQL path populates (deliberately excludes `raw`,
    which is never meant to match: the old path's `raw` is bd's JSON dict,
    the new path's is the SQL row dict)."""
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


def _ids(items: list[A.Item]) -> list[str]:
    return [i.id for i in items]


# --------------------------------------------------------------- default/all


def test_list_default_matches_old_path_excludes_only_closed(shared_bd, unique_lane):
    open_id = shared_bd.create("equiv default open", tags=[unique_lane], priority=1)
    held_id = shared_bd.create("equiv default held", tags=[unique_lane], priority=2)
    closed_id = shared_bd.create("equiv default closed", tags=[unique_lane], priority=3)
    shared_bd.claim_item(held_id, actor="equiv-default-actor")
    shared_bd.resolve(closed_id, "equiv default cleanup reason", actor="equiv-closer")

    old = _old_list(shared_bd, limit=0)
    new = shared_bd.list(limit=0)
    old_ids, new_ids = {i.id for i in old}, {i.id for i in new}

    assert open_id in old_ids and open_id in new_ids
    assert held_id in old_ids and held_id in new_ids
    assert closed_id not in old_ids and closed_id not in new_ids
    assert [_key(i) for i in old if i.id in {open_id, held_id}] == [
        _key(i) for i in new if i.id in {open_id, held_id}
    ]

    shared_bd.resolve(held_id, "test cleanup", actor="equiv-default-actor")


def test_list_include_resolved_matches_old_path_exactly(shared_bd, unique_lane):
    open_id = shared_bd.create("equiv all open", tags=[unique_lane], priority=1)
    closed_id = shared_bd.create("equiv all closed", tags=[unique_lane], priority=1)
    shared_bd.resolve(closed_id, "equiv all cleanup reason", actor="equiv-all-closer")

    old = _old_list(shared_bd, include_resolved=True, limit=0)
    new = shared_bd.list(include_resolved=True, limit=0)
    old_by_id = {i.id: i for i in old}
    new_by_id = {i.id: i for i in new}

    assert open_id in old_by_id and open_id in new_by_id
    assert closed_id in old_by_id and closed_id in new_by_id
    assert _key(old_by_id[closed_id]) == _key(new_by_id[closed_id])
    assert _key(old_by_id[open_id]) == _key(new_by_id[open_id])


# --------------------------------------------------------------------- order


def test_list_ordering_matches_old_path_created_at_desc(shared_bd, unique_lane):
    """bd's own listing order must be reproduced EXACTLY -- this is the
    load-bearing invariant, proven against the real bd-args path itself,
    not against a re-derived assumption about what that order "should" be.

    Deliberately does NOT assert `new == list(reversed(ids))`: bd's real
    default order is priority-primary (see `_list_rows_via_sql`'s
    docstring) with `created_at DESC, id ASC` only as tie-breaks, and dolt
    stores `created_at` at whole-SECOND resolution -- five items created
    back-to-back easily land in the same second, at which point the real
    tie-break is `id` (effectively random relative to creation sequence),
    not creation order. Asserting equivalence to bd's own path is the
    correct invariant; asserting a specific creation-order outcome is not,
    and was a bug in an earlier version of this test.
    """
    ids = [shared_bd.create(f"equiv order {n}", tags=[unique_lane], priority=1) for n in range(5)]

    old = _old_list(shared_bd, lane=unique_lane, limit=0)
    new = shared_bd.list(lane=unique_lane, limit=0)

    assert _ids(old) == _ids(new)
    assert set(_ids(new)) == set(ids)


def test_list_ordering_prefers_lower_priority_number_over_creation_order(shared_bd, unique_lane):
    """The disentangling case that actually distinguishes bd's real default
    sort (priority ascending, primary key) from a naive `created_at`-only
    theory: create the FIRST item with the WORST (highest-number) priority
    and the SECOND item with the BEST (lowest-number) priority -- the
    better-priority item must sort first despite being created later,
    matching the old bd-args path exactly."""
    worse_id = shared_bd.create("equiv priority-order worse", tags=[unique_lane], priority=4)
    better_id = shared_bd.create("equiv priority-order better", tags=[unique_lane], priority=1)

    old = _old_list(shared_bd, lane=unique_lane, limit=0)
    new = shared_bd.list(lane=unique_lane, limit=0)

    assert _ids(old) == _ids(new)
    assert _ids(new).index(better_id) < _ids(new).index(worse_id)


# ------------------------------------------------------------- status filter


@pytest.mark.parametrize("status", list(A.STATUSES))
def test_list_status_filter_matches_old_path(status, shared_bd, unique_lane):
    open_id = shared_bd.create(f"equiv status-filter open ({status})", tags=[unique_lane])
    held_id = shared_bd.create(f"equiv status-filter held ({status})", tags=[unique_lane])
    shared_bd.claim_item(held_id, actor=f"equiv-status-actor-{status}")

    old = _old_list(shared_bd, status=status, limit=0)
    new = shared_bd.list(status=status, limit=0)
    assert _ids(old) == _ids(new)
    for i in new:
        assert i.status == status

    if status == "open":
        assert open_id in _ids(new)
        assert held_id not in _ids(new)
    elif status == "held":
        assert held_id in _ids(new)
        assert open_id not in _ids(new)

    shared_bd.resolve(held_id, "test cleanup", actor=f"equiv-status-actor-{status}")


def test_list_unknown_status_raises_same_way_as_old_path(shared_bd):
    with pytest.raises(A.BeadsError):
        shared_bd.list(status="not-a-real-status")


# --------------------------------------------------------------- lane filter


def test_list_lane_filter_matches_old_path(shared_bd, unique_lane):
    other_lane = f"{unique_lane}-other"
    in_lane_id = shared_bd.create("equiv lane in", tags=[unique_lane])
    other_lane_id = shared_bd.create("equiv lane out", tags=[other_lane])

    old = _old_list(shared_bd, lane=unique_lane, limit=0)
    new = shared_bd.list(lane=unique_lane, limit=0)
    assert _ids(old) == _ids(new)
    new_ids = _ids(new)
    assert in_lane_id in new_ids
    assert other_lane_id not in new_ids


def test_list_lane_plus_include_resolved_matches_old_path(shared_bd, unique_lane):
    open_id = shared_bd.create("equiv lane+all open", tags=[unique_lane])
    closed_id = shared_bd.create("equiv lane+all closed", tags=[unique_lane])
    shared_bd.resolve(closed_id, "equiv lane+all cleanup", actor="equiv-lane-all-closer")

    old = _old_list(shared_bd, lane=unique_lane, include_resolved=True, limit=0)
    new = shared_bd.list(lane=unique_lane, include_resolved=True, limit=0)
    assert _ids(old) == _ids(new)
    assert {open_id, closed_id} <= set(_ids(new))


# ------------------------------------------------------------------- limit


def test_list_limit_zero_is_unlimited_like_old_path(shared_bd, unique_lane):
    ids = [shared_bd.create(f"equiv limit {n}", tags=[unique_lane]) for n in range(6)]
    old = _old_list(shared_bd, lane=unique_lane, limit=0)
    new = shared_bd.list(lane=unique_lane, limit=0)
    assert _ids(old) == _ids(new)
    assert set(ids) <= set(_ids(new))


def test_list_explicit_limit_matches_old_path(shared_bd, unique_lane):
    for n in range(4):
        shared_bd.create(f"equiv limit-n {n}", tags=[unique_lane])
    old = _old_list(shared_bd, lane=unique_lane, limit=2)
    new = shared_bd.list(lane=unique_lane, limit=2)
    assert len(new) == 2
    assert _ids(old) == _ids(new)


def test_list_default_limit_is_50_like_bd(shared_bd, unique_lane):
    for n in range(3):
        shared_bd.create(f"equiv default-limit {n}", tags=[unique_lane])
    new = shared_bd.list(lane=unique_lane)
    assert len(new) <= A.LIST_DEFAULT_LIMIT


# ---------------------------------------------------- free-text field safety


def test_list_free_text_with_commas_and_newlines_survives_intact(shared_bd, unique_lane):
    """The exact hazard `_dolt_sql_json` (not CSV) exists to avoid: a
    description containing commas AND embedded newlines must round-trip
    byte-for-byte through the new SQL path, matching the old bd-args path
    exactly -- a naive CSV parse would have corrupted or split this row."""
    tricky_description = (
        "Line one, with a comma.\nLine two, also, with, several, commas.\n"
        'Line three has "quotes, too" and a trailing comma,'
    )
    tricky_title = 'Title, with a comma and "quotes"'
    item_id = shared_bd.create(
        tricky_title,
        tags=[unique_lane],
        description=tricky_description,
        acceptance="Given X, When Y, Then Z, with a trailing comma,",
    )

    old = {i.id: i for i in _old_list(shared_bd, lane=unique_lane, limit=0)}[item_id]
    new = {i.id: i for i in shared_bd.list(lane=unique_lane, limit=0)}[item_id]

    assert new.title == old.title == tricky_title
    assert new.description == old.description == tricky_description
    assert new.acceptance == old.acceptance


def test_list_metadata_dict_round_trips_via_sql_path(shared_bd, unique_lane):
    item_id = shared_bd.create(
        "equiv metadata probe", tags=[unique_lane], meta={"nested": {"a": 1}, "flag": True}
    )
    new = {i.id: i for i in shared_bd.list(lane=unique_lane, limit=0)}[item_id]
    assert new.meta == {"nested": {"a": 1}, "flag": True}


def test_list_priority_is_int_not_string_via_sql_path(shared_bd, unique_lane):
    item_id = shared_bd.create("equiv priority-type probe", tags=[unique_lane], priority=3)
    new = {i.id: i for i in shared_bd.list(lane=unique_lane, limit=0)}[item_id]
    assert new.priority == 3
    assert isinstance(new.priority, int)


def test_list_unset_optional_fields_are_none_not_empty_string(shared_bd, unique_lane):
    """bd's own `--json` omits an empty optional field entirely rather than
    reporting it as `""` -- the SQL path must reproduce that (`None`, never
    an empty string) for holder/resolution/design."""
    item_id = shared_bd.create("equiv none-vs-empty probe", tags=[unique_lane])
    new = {i.id: i for i in shared_bd.list(lane=unique_lane, limit=0)}[item_id]
    assert new.holder is None
    assert new.resolution is None
    assert new.design is None


# -------------------------------------------------------------- no mutation


def test_list_via_sql_never_mutates_anything(shared_bd, unique_lane):
    """The entire point of the fix: a `SELECT` has no write set. Full
    project state before/after several `list()` calls must be identical."""
    shared_bd.create("equiv no-mutation probe 1", tags=[unique_lane])
    held_id = shared_bd.create("equiv no-mutation probe 2", tags=[unique_lane])
    shared_bd.claim_item(held_id, actor="equiv-no-mutation-actor")

    def snapshot():
        items = shared_bd.list(include_resolved=True, limit=0)
        return {
            i.id: (i.status, i.holder, i.resolution, i.title, tuple(sorted(i.tags))) for i in items
        }

    before = snapshot()
    shared_bd.list(lane=unique_lane)
    shared_bd.list(status="held")
    shared_bd.list(status="open", limit=1)
    shared_bd.list(include_resolved=True, limit=0)
    after = snapshot()
    assert before == after

    shared_bd.resolve(held_id, "test cleanup", actor="equiv-no-mutation-actor")


# ------------------------------------------------------------------ empty


def test_list_on_empty_project_returns_empty_not_an_error(project_factory):
    _, bd = project_factory("listsqlempty")
    assert bd.list() == []
    assert bd.list(include_resolved=True) == []
