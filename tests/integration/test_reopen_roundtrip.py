"""Tier 2 -- the correction cycle against a REAL bd binary: a published
resolution that is wrong can be reopened, re-claimed, and rewritten, and the
old text survives the transition.

Everything the wrapper promises about `reopen`/`resolve`-on-closed is
asserted here against bd itself, not a stub:

  - reopen -> claim -> resolve reads back the CORRECTED text;
  - bd's `events` table carries a `reopened` row naming actor and reason;
  - the item's comment history carries the VERBATIM previous resolution and
    the previous `closed_at` -- the guarantee that does not depend on what
    bd does to `close_reason`;
  - resolving a closed item with DIFFERENT text refuses and writes nothing;
  - resolving it with IDENTICAL text succeeds as an idempotent no-op.

The defect (work_tracker item model_performance-uma): before this, that
divergent resolve exited 0 and echoed the OLD text back as though the
correction had landed.
"""

from __future__ import annotations

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.integration


def _event_rows(bd: A.Beads, item_id: str, event_type: str) -> list[str]:
    """Raw CSV rows bd itself wrote to `events` for this item.

    Read straight out of dolt rather than through any wrapper counter: the
    claim under test is that BD writes the audit row, so reading it through
    our own code would prove less.
    """
    p = A._dolt_sql(
        f"SELECT `event_type`, `actor`, `comment` FROM `{bd.project_name}`.`events` "
        f"WHERE `issue_id` = '{A._sql_literal(item_id)}' "
        f"AND `event_type` = '{A._sql_literal(event_type)}'"
    )
    assert p.returncode == 0, p.stderr or p.stdout
    lines = [ln for ln in (p.stdout or "").splitlines() if ln.strip()]
    return lines[1:]  # drop the CSV header


def _comment_texts(bd: A.Beads, item_id: str) -> list[str]:
    return [e.detail or e.summary for e in bd.activity(item_id) if e.kind == "comment"]


def test_full_correction_cycle_reopen_claim_resolve_reads_back_corrected_text(
    shared_bd: A.Beads, unique_lane
):
    wrong = "VERDICT: retention non-inferiority PASSES (0.792 vs 0.688)"
    right = "CORRECTED: uncomputable -- arm B has zero valid runs"

    item_id = shared_bd.create("reopen probe: full cycle", tags=[unique_lane], priority=1)
    shared_bd.resolve(item_id, wrong, actor="first-pass")
    closed = shared_bd.get(item_id)
    assert closed.status == "resolved"
    assert closed.closed_at is not None

    outcome = shared_bd.reopen(item_id, "the stored verdict is wrong", actor="corrector")

    # 1. It is genuinely back in the queue, and claimable by a DIFFERENT
    #    actor than the one who closed it -- see
    #    test_reopen_clears_the_stale_assignee_bd_leaves_behind for why that
    #    is the assertion that has teeth.
    assert outcome.item.status != "resolved"
    assert outcome.item.holder is None
    assert outcome.previous_resolution == wrong
    assert outcome.previous_closed_at == closed.closed_at
    reclaimed = shared_bd.claim_item(item_id, actor="corrector")
    assert reclaimed.id == item_id

    # 2. bd's own events table records the reopen, attributed -- and the
    #    reason with it. MEASURED (bd 1.1.2, 2026-09-02): bd splits these
    #    across TWO rows in the same transaction rather than one -- the
    #    `reopened` row carries event_type + actor (its `comment` column is
    #    empty; the reason is NOT there), and `--reason` lands as an
    #    adjacent attributed `commented` row. Both are asserted, because a
    #    test that only looked for the reason on the `reopened` row would
    #    pass on a bd that stopped recording the transition at all.
    reopened = _event_rows(shared_bd, item_id, "reopened")
    assert len(reopened) == 1, f"expected exactly one 'reopened' event, got {reopened}"
    assert "corrector" in reopened[0]
    commented = _event_rows(shared_bd, item_id, "commented")
    assert any("the stored verdict is wrong" in row and "corrector" in row for row in commented), (
        f"bd no longer records the reopen --reason as an attributed event: {commented}"
    )

    # 3. The verbatim previous record survives in the comment history --
    #    independent of whatever bd did to close_reason.
    archived = "\n".join(_comment_texts(shared_bd, item_id))
    assert wrong in archived
    assert closed.closed_at.isoformat() in archived

    # 4. The correction lands and READS BACK as the corrected text.
    back = shared_bd.resolve(item_id, right, actor="corrector")
    assert back.status == "resolved"
    assert (back.resolution or "").strip() == right
    assert wrong not in (back.resolution or "")


def test_reopen_clears_closed_at_and_the_cost_is_visible(shared_bd: A.Beads, unique_lane):
    """The known, documented accounting cost: a corrected item stops
    counting toward the day it was genuinely resolved."""
    item_id = shared_bd.create("reopen probe: closed_at", tags=[unique_lane], priority=1)
    shared_bd.resolve(item_id, "first pass", actor="a")
    was = shared_bd.get(item_id).closed_at
    assert was is not None

    outcome = shared_bd.reopen(item_id, "correcting", actor="a")
    assert outcome.item.closed_at is None
    assert outcome.previous_closed_at == was


def test_reopen_clears_the_stale_assignee_bd_leaves_behind(shared_bd: A.Beads, unique_lane):
    """MEASURED (bd 1.1.2, 2026-09-02): `bd reopen` flips status to open and
    clears closed_at but LEAVES THE OLD ASSIGNEE IN PLACE -- after which a
    directed claim by anyone else is refused outright ("issue already claimed
    by <old holder>"). An item nobody can take is not a correctable item, so
    the wrapper clears the assignee (the same thing `release` already does).

    Found by this lane's own tool test failing on the claim leg; without the
    clear, `work_reopen(claim=True)` cannot claim what it just reopened
    unless the correcting agent happens to be the one who closed it.
    """
    item_id = shared_bd.create("reopen probe: assignee", tags=[unique_lane], priority=1)
    shared_bd.claim_item(item_id, actor="original-holder")
    shared_bd.resolve(item_id, "closed by the original holder", actor="original-holder")
    assert shared_bd.get(item_id).holder == "original-holder"

    outcome = shared_bd.reopen(item_id, "correcting", actor="corrector")
    assert outcome.item.holder is None

    taken = shared_bd.claim_item(item_id, actor="someone-else-entirely")
    assert taken.id == item_id


def test_resolve_on_a_closed_item_with_divergent_text_refuses_and_writes_nothing(
    shared_bd: A.Beads, unique_lane
):
    stored = "the original resolution text"
    item_id = shared_bd.create("reopen probe: divergent", tags=[unique_lane], priority=1)
    shared_bd.resolve(item_id, stored, actor="a")

    with pytest.raises(A.BeadsError) as e:
        shared_bd.resolve(item_id, "a completely different resolution", actor="b")
    msg = str(e.value)
    assert "NOTHING WAS WRITTEN" in msg
    assert stored in msg
    assert "a completely different resolution" in msg
    assert f"reopen --project {shared_bd.project_name} --id {item_id}" in msg

    # And it is literally true: the record is untouched.
    assert (shared_bd.get(item_id).resolution or "").strip() == stored


def test_resolve_on_a_closed_item_with_identical_text_is_idempotent(
    shared_bd: A.Beads, unique_lane
):
    """The retry the contention contract promises is safe."""
    text = "closed: the one true resolution"
    item_id = shared_bd.create("reopen probe: idempotent", tags=[unique_lane], priority=1)
    shared_bd.resolve(item_id, text, actor="a")

    outcome = shared_bd.resolve_outcome(item_id, text, actor="a")
    assert outcome.idempotent is True
    assert (outcome.item.resolution or "").strip() == text

    # Whitespace-only differences are transport noise, not an edit.
    again = shared_bd.resolve_outcome(item_id, f"  {text}\r\n", actor="a")
    assert again.idempotent is True


def test_reopen_refuses_an_item_that_is_not_resolved(shared_bd: A.Beads, unique_lane):
    item_id = shared_bd.create("reopen probe: not closed", tags=[unique_lane], priority=1)
    with pytest.raises(A.BeadsError) as e:
        shared_bd.reopen(item_id, "there is nothing to reopen")
    assert "nothing to reopen" in str(e.value)
    assert shared_bd.get(item_id).status == "open"


def test_reopen_twice_refuses_the_second_time(shared_bd: A.Beads, unique_lane):
    """Deliberately not idempotent -- the loser of a concurrent double
    reopen learns it loudly instead of being told it did something."""
    item_id = shared_bd.create("reopen probe: twice", tags=[unique_lane], priority=1)
    shared_bd.resolve(item_id, "first pass", actor="a")
    shared_bd.reopen(item_id, "correcting", actor="a")
    with pytest.raises(A.BeadsError) as e:
        shared_bd.reopen(item_id, "correcting again", actor="b")
    assert "nothing to reopen" in str(e.value)


def test_measured_close_reason_disposition_across_a_reopen(shared_bd: A.Beads, unique_lane):
    """MEASUREMENT, pinned as a test: what bd 1.1.2 actually does to
    `close_reason` when an item is reopened -- and the proof that the
    wrapper's guarantee does not depend on the answer.

    MEASURED 2026-09-02 against bd 1.1.2 (20e493e56): a reopen CLEARS
    `close_reason` -- the resolution text is GONE from the issue row, not
    preserved. bd's own docs say nothing about this either way, which is
    exactly why `reopen` archives the previous resolution into the comment
    history FIRST. Had the wrapper trusted bd to keep it, every correction
    would have destroyed the record it was correcting.

    Pinned here (and in `doctor`'s `reopen.close_reason_disposition`) so a
    future bd change is loud rather than silent. The assertion prefers no
    answer -- it asserts what was measured.
    """
    text = "resolution text that may or may not survive a reopen"
    item_id = shared_bd.create("reopen probe: disposition", tags=[unique_lane], priority=1)
    shared_bd.resolve(item_id, text, actor="a")
    outcome = shared_bd.reopen(item_id, "measuring close_reason disposition", actor="a")

    assert not (outcome.item.resolution or "").strip(), (
        "bd's close_reason disposition across a reopen has CHANGED -- it now "
        f"preserves text ({outcome.item.resolution!r}) where it used to clear "
        "it. Update this measured assumption and contract.py's "
        "reopen.close_reason_disposition deliberately, never silently."
    )
    # The wrapper's own guarantee holds regardless: the text bd threw away
    # is still in the item's attributed comment history.
    assert text in "\n".join(_comment_texts(shared_bd, item_id))
