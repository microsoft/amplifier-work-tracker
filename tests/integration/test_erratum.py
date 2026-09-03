"""Tier 2 -- `Beads.erratum` against a REAL bd binary + isolated dolt server.

work_tracker item pipeline-03c (measured 2026-09-03): an agent resolved an
item with a factually false reason, noticed in the same run, and had no
sanctioned way to correct the RECORD without either destroying the
resolution's finality (`reopen`, which also clears `closed_at`) or silently
discarding the correction (`resolve` against an already-closed item is a
same-text-only no-op). `erratum` is the append-only, no-claim-required
third path: the record is wrong, but the work stands.

Everything this file proves is end-to-end against real storage, not a stub:

  - two errata from two different actors append in order, and the
    resolution field itself is byte-identical before and after;
  - `status`/`closed_at`/`holder` are untouched by an erratum, before AND
    after -- and the item is genuinely NOT claimable (`claim_next` skips it,
    same as any other resolved item);
  - a same-text re-append (any actor) is an idempotent no-op that writes
    nothing;
  - `erratum` refuses (writing nothing) an item that is not resolved, and
    the error names `edit`/`work_edit` as the remedy;
  - the conflict-after-landed / phantom-success shapes every other
    item-level write verb here proves (see `test_write_readback.py`, which
    is where this verb's own pair of those tests live, alongside every
    other verb's).
"""

from __future__ import annotations

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.integration


def _resolved_item(bd: A.Beads, lane: str, actor: str, title: str, resolution: str) -> str:
    item_id = bd.create(title, tags=[lane])
    bd.claim_item(item_id, actor=actor)
    bd.resolve(item_id, resolution, actor=actor)
    return item_id


def test_two_errata_from_two_actors_append_in_order_and_resolution_is_unchanged(
    shared_bd: A.Beads, unique_lane
):
    resolution = "VERDICT: the retention gate PASSES"
    item_id = _resolved_item(
        shared_bd, unique_lane, "first-pass", "erratum probe: two actors", resolution
    )

    first = shared_bd.erratum(item_id, actor="alice", text="the verdict text is backwards")
    assert first.already_recorded is False
    second = shared_bd.erratum(item_id, actor="bob", text="the underlying data was mislabeled")
    assert second.already_recorded is False

    back = shared_bd.get_readonly(item_id)
    # The resolution FIELD is byte-identical -- an erratum is never a
    # rewrite of it.
    assert (back.resolution or "").strip() == resolution
    assert back.corrected is True
    assert len(back.errata) == 2
    assert back.errata[0].by == "alice"
    assert back.errata[0].text == "the verdict text is backwards"
    assert back.errata[1].by == "bob"
    assert back.errata[1].text == "the underlying data was mislabeled"
    # Oldest -> newest: alice's timestamp sorts at or before bob's.
    assert back.errata[0].at <= back.errata[1].at


def test_erratum_never_touches_status_closed_at_or_holder(shared_bd: A.Beads, unique_lane):
    item_id = _resolved_item(
        shared_bd, unique_lane, "closer", "erratum probe: lifecycle untouched", "closed text"
    )
    before = shared_bd.get_readonly(item_id)
    assert before.status == "resolved"
    assert before.holder == "closer"
    closed_at_before = before.closed_at

    shared_bd.erratum(item_id, actor="corrector", text="the reason given was misleading")

    after = shared_bd.get_readonly(item_id)
    assert after.status == "resolved"
    assert after.holder == "closer"  # bd's own leftover-assignee fact, unchanged
    assert after.closed_at == closed_at_before
    assert (after.resolution or "").strip() == "closed text"


def test_corrected_item_is_not_returned_by_claim_next(shared_bd: A.Beads, unique_lane):
    item_id = _resolved_item(
        shared_bd, unique_lane, "closer", "erratum probe: not ready", "closed text"
    )
    shared_bd.erratum(item_id, actor="corrector", text="wrong reason")

    claimed = shared_bd.claim_next(lane=unique_lane, actor="whoever-is-next")
    assert claimed is None, "a corrected-but-resolved item must never surface as ready work"


def test_erratum_requires_no_claim_at_all(shared_bd: A.Beads, unique_lane):
    """Any actor, at any time -- the corrector never claims the item, and
    the item is never held during or after the call."""
    item_id = _resolved_item(
        shared_bd, unique_lane, "closer", "erratum probe: no claim needed", "closed text"
    )
    outcome = shared_bd.erratum(item_id, actor="a-completely-unrelated-actor", text="wrong")
    assert outcome.item.holder != "a-completely-unrelated-actor"
    assert outcome.item.status == "resolved"


def test_same_text_re_append_by_any_actor_is_idempotent_and_writes_nothing(
    shared_bd: A.Beads, unique_lane
):
    item_id = _resolved_item(
        shared_bd, unique_lane, "closer", "erratum probe: idempotent", "closed text"
    )
    text = "the same correction, byte for byte"
    first = shared_bd.erratum(item_id, actor="alice", text=text)
    assert first.already_recorded is False
    assert len(first.item.errata) == 1

    # Same text, DIFFERENT actor -- still idempotent per the design's own
    # "by any actor" rule.
    again = shared_bd.erratum(item_id, actor="a-different-actor", text=f"  {text}\r\n")
    assert again.already_recorded is True
    assert len(again.item.errata) == 1, "a same-text re-append must add no second erratum"


def test_erratum_refuses_an_item_that_is_not_resolved_and_names_edit(
    shared_bd: A.Beads, unique_lane
):
    item_id = shared_bd.create("erratum probe: still open", tags=[unique_lane])
    with pytest.raises(A.BeadsError) as e:
        shared_bd.erratum(item_id, actor="alice", text="doesn't matter, refused first")
    msg = str(e.value)
    assert "'resolved'" in msg
    assert "edit" in msg.lower()
    back = shared_bd.get_readonly(item_id)
    assert not back.errata
    assert back.corrected is False


def test_erratum_refuses_empty_text_and_writes_nothing(shared_bd: A.Beads, unique_lane):
    item_id = _resolved_item(
        shared_bd, unique_lane, "closer", "erratum probe: empty text", "closed text"
    )
    with pytest.raises(A.BeadsError, match="text is required"):
        shared_bd.erratum(item_id, actor="alice", text="   ")
    back = shared_bd.get_readonly(item_id)
    assert not back.errata


def test_erratum_refuses_a_missing_item(shared_bd: A.Beads):
    fake_id = f"{shared_bd.project_name}-zzzzzzz"
    with pytest.raises(A.BeadsError, match="no issues found"):
        shared_bd.erratum(fake_id, actor="alice", text="doesn't matter")


# ------------------------------------------------------------- list surfaces


def test_list_bounded_surfaces_corrected_flag_without_the_full_errata_text(
    shared_bd: A.Beads, unique_lane
):
    """The cheap-list-view contract: `corrected` is accurate on a many-row
    listing, but the full erratum TEXT is not fetched there -- see
    `Item.errata`'s own docstring note on why `errata` stays `[]` on a
    lean row."""
    item_id = _resolved_item(
        shared_bd, unique_lane, "closer", "erratum probe: list view", "closed text"
    )
    shared_bd.erratum(item_id, actor="alice", text="wrong reason recorded")

    result = shared_bd.list_bounded(status="resolved")
    row = next(i for i in result.items if i.id == item_id)
    assert row.corrected is True
    assert row.errata == []

    # A directed single-item read, by contrast, carries the full list.
    full = shared_bd.get_readonly(item_id)
    assert full.corrected is True
    assert len(full.errata) == 1
    assert full.errata[0].text == "wrong reason recorded"


def test_summary_lean_row_carries_corrected_but_not_errata(shared_bd: A.Beads, unique_lane):
    item_id = _resolved_item(
        shared_bd, unique_lane, "closer", "erratum probe: summary lean", "closed text"
    )
    shared_bd.erratum(item_id, actor="alice", text="wrong reason recorded")

    lean = shared_bd.get_readonly(item_id).summary()
    assert lean["corrected"] is True
    assert "errata" not in lean

    full = shared_bd.get_readonly(item_id).summary(full=True)
    assert full["corrected"] is True
    assert len(full["errata"]) == 1
    assert full["errata"][0]["by"] == "alice"
    assert full["errata"][0]["text"] == "wrong reason recorded"
