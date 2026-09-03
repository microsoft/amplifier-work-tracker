"""Tier 2 -- every item-level write verb verifies itself by read-back.

Ledger rows CCV1-012 (`release`'s success path), CCV1-013 (both claim
paths) and CCV1-015 (every remaining item-level write verb); work items
work_item_pipeline-1f2 / -1gz / -2x3.

Two failure shapes are injected here, and both are silent in production --
which is exactly why they need a test rather than an argument:

  - **conflict-after-landed**: the write REALLY happens against the isolated
    dolt server, then `Beads._run` raises its own exhausted-retries
    `BeadsError` anyway. This is the measured 2026-09-01 incident
    (work_tracker item pipeline-yym) generalized past `resolve`/`release`.
    Every verb must notice the write landed and report SUCCESS.
  - **phantom success**: `bd` exits 0 having changed nothing at all. Every
    verb must notice the state is not there and RAISE -- "exit code is not
    proof" is a claim about the success path first, not only the conflict
    path.

Both are injected by patching `Beads._run` (never a mocked dolt, never
manufactured contention timing) -- the same technique
`test_phantom_conflict_recovery.py` established. Read-back always runs
through the contention-free SQL path, which never goes through `_run` at
all, so a patched `_run` never blinds the verification itself.
"""

from __future__ import annotations

import json
import socket
import subprocess

import pytest

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import custody as C

pytestmark = pytest.mark.integration


# --------------------------------------------------------------- injectors


def _conflict_after_real_write(monkeypatch, match):
    """Patch `Beads._run` so the FIRST call matching `match(args)` really
    executes, then raises `_run`'s own exhausted-retries `BeadsError`
    regardless of the real outcome.

    Returns the list of intercepted arg-vectors, so a test can assert the
    path fired exactly once rather than assuming it did.
    """
    real_run = A.Beads._run
    calls: list[list[str]] = []

    def fake_run(self, args, actor=None):  # noqa: ANN001 -- matches Beads._run's signature
        if not calls and match(args):
            calls.append(list(args))
            result = real_run(self, args, actor=actor)
            raise A.BeadsError(
                f"`bd {' '.join(args[:2])}` still conflicting after 8 retries. "
                f"Contention too high; refusing to keep hammering. "
                f"Last: {(result.stdout or result.stderr or '').strip()}"
            )
        return real_run(self, args, actor=actor)

    monkeypatch.setattr(A.Beads, "_run", fake_run)
    return calls


def _conflict_without_write(monkeypatch, match):
    """Patch `Beads._run` so a call matching `match(args)` raises the same
    exhausted-retries `BeadsError` WITHOUT ever performing the write -- the
    discriminating negative for every conflict-path test above.
    """
    real_run = A.Beads._run
    calls: list[list[str]] = []

    def fake_run(self, args, actor=None):  # noqa: ANN001
        if match(args):
            calls.append(list(args))
            raise A.BeadsError(
                f"`bd {' '.join(args[:2])}` still conflicting after 8 retries. "
                f"Contention too high; refusing to keep hammering. "
                f"Last: (no successful attempt)"
            )
        return real_run(self, args, actor=actor)

    monkeypatch.setattr(A.Beads, "_run", fake_run)
    return calls


def _phantom_success(monkeypatch, match, *, stdout: str = ""):
    """Patch `Beads._run` so a call matching `match(args)` returns exit 0
    (optionally with plausible stdout) having performed NO write at all --
    a `bd` that reports success and changes nothing.
    """
    real_run = A.Beads._run
    calls: list[list[str]] = []

    def fake_run(self, args, actor=None):  # noqa: ANN001
        if match(args):
            calls.append(list(args))
            return subprocess.CompletedProcess(["bd", *args], 0, stdout=stdout, stderr="")
        return real_run(self, args, actor=actor)

    monkeypatch.setattr(A.Beads, "_run", fake_run)
    return calls


# ------------------------------------------------------------- arg matchers


def _is_update(args, *flags: str) -> bool:
    return bool(args) and args[0] == "update" and all(f in args for f in flags)


def _is_custody_write(args) -> bool:
    """A `bd update --metadata '{"custody": ...}'` -- take_custody/renew_custody,
    told apart from defer/block's own `--metadata` reason write by content.
    """
    if not _is_update(args, "--metadata"):
        return False
    blob = args[args.index("--metadata") + 1]
    return f'"{C.CUSTODY_KEY}"' in blob


def _held_item(bd: A.Beads, lane: str, actor: str, title: str) -> str:
    item_id = bd.create(title, tags=[lane])
    bd.claim_item(item_id, actor=actor)
    return item_id


# ============================================================ CCV1-012 release


def test_release_raises_when_bd_reports_success_but_the_hold_did_not_clear(
    shared_bd, unique_lane, monkeypatch
):
    """CCV1-012, the discriminating negative for the SUCCESS path: `bd
    update --status open --assignee ''` exits 0 and changes nothing. Before
    this fix `release` returned `ReleaseOutcome(already_closed=False)` off
    that exit code alone -- so `work_release` and every reap reclaim
    reported an item handed back that is in fact still HELD.
    """
    actor = f"rel-phantom-{unique_lane}"
    item_id = _held_item(shared_bd, unique_lane, actor, f"release phantom {unique_lane}")

    calls = _phantom_success(monkeypatch, lambda a: _is_update(a, "--status", "--assignee"))

    with pytest.raises(A.BeadsError, match="did not land"):
        shared_bd.release(item_id)

    assert len(calls) == 1
    monkeypatch.undo()
    assert shared_bd.get_readonly(item_id).status == "held", "the hold really was never cleared"
    shared_bd.resolve(item_id, "cleanup", actor=actor)


def test_release_success_path_returns_only_after_the_readback_shows_no_hold(shared_bd, unique_lane):
    """The positive half of CCV1-012: a real release still succeeds, and the
    item is genuinely no longer held afterward.
    """
    actor = f"rel-real-{unique_lane}"
    item_id = _held_item(shared_bd, unique_lane, actor, f"release real {unique_lane}")

    outcome = shared_bd.release(item_id)

    assert outcome.item_id == item_id
    assert outcome.already_closed is False
    back = shared_bd.get_readonly(item_id)
    assert back.status == "open"
    assert not back.holder


# ============================================================== CCV1-013 claim


def test_claim_item_verifies_by_readback_when_the_wrapper_reports_conflict(
    shared_bd, unique_lane, monkeypatch
):
    """A directed claim that really landed, reported as a conflict. The claim
    must be recognised as landed -- otherwise the caller believes it holds
    nothing while bd has it assigned to them, and only a reap frees it.
    """
    actor = f"claim-conflict-{unique_lane}"
    item_id = shared_bd.create(f"claim conflict {unique_lane}", tags=[unique_lane])

    calls = _conflict_after_real_write(monkeypatch, lambda a: _is_update(a, "--claim"))

    item = shared_bd.claim_item(item_id, actor=actor)

    assert len(calls) == 1
    assert item.id == item_id
    assert item.holder == actor
    assert item.status == "held"
    monkeypatch.undo()
    assert shared_bd.get_readonly(item_id).holder == actor
    shared_bd.resolve(item_id, "cleanup", actor=actor)


def test_claim_item_still_raises_when_the_claim_genuinely_did_not_land(
    shared_bd, unique_lane, monkeypatch
):
    """The discriminating negative: a conflict whose write never happened
    still raises. Verify-by-read-back is a safety net for a landed write,
    never a way to swallow a real failure.
    """
    actor = f"claim-genuine-{unique_lane}"
    item_id = shared_bd.create(f"claim genuine fail {unique_lane}", tags=[unique_lane])

    _conflict_without_write(monkeypatch, lambda a: _is_update(a, "--claim"))

    with pytest.raises(A.BeadsError, match="still conflicting"):
        shared_bd.claim_item(item_id, actor=actor)

    monkeypatch.undo()
    assert shared_bd.get_readonly(item_id).status == "open"


def test_claim_item_raises_when_bd_reports_success_but_nobody_holds_the_item(
    shared_bd, unique_lane, monkeypatch
):
    """CCV1-013's core claim: the returned item used to be parsed from the
    WRITING process's own stdout. A `bd` that prints a plausible claimed
    item while writing nothing therefore produced a caller that believed it
    held work nobody had assigned it -- and then started custody on it.
    """
    actor = f"claim-phantom-{unique_lane}"
    item_id = shared_bd.create(f"claim phantom {unique_lane}", tags=[unique_lane])
    fake = json.dumps([{"id": item_id, "title": "phantom", "status": "in_progress"}])

    _phantom_success(monkeypatch, lambda a: _is_update(a, "--claim"), stdout=fake)

    with pytest.raises(A.BeadsError, match="did not land"):
        shared_bd.claim_item(item_id, actor=actor)

    monkeypatch.undo()
    assert shared_bd.get_readonly(item_id).status == "open"


def test_claim_next_verifies_by_readback_when_the_wrapper_reports_conflict(
    shared_bd, unique_lane, monkeypatch
):
    """`claim_next` cannot read the claim back by id on the conflict path --
    bd chose the item and its stdout is gone. It is decided instead by the
    id-set difference over items assigned to this actor, snapshotted before
    the write.
    """
    actor = f"next-conflict-{unique_lane}"
    item_id = shared_bd.create(f"claim next conflict {unique_lane}", tags=[unique_lane])

    calls = _conflict_after_real_write(monkeypatch, lambda a: bool(a) and a[0] == "ready")

    item = shared_bd.claim_next(lane=unique_lane, actor=actor)

    assert len(calls) == 1
    assert item is not None and item.id == item_id
    assert item.holder == actor
    monkeypatch.undo()
    assert shared_bd.get_readonly(item_id).holder == actor
    shared_bd.resolve(item_id, "cleanup", actor=actor)


def test_claim_next_still_raises_when_the_claim_genuinely_did_not_land(
    shared_bd, unique_lane, monkeypatch
):
    """No new hold appeared for this actor, so the set difference is empty:
    the original conflict propagates untouched.
    """
    actor = f"next-genuine-{unique_lane}"
    item_id = shared_bd.create(f"claim next genuine {unique_lane}", tags=[unique_lane])

    _conflict_without_write(monkeypatch, lambda a: bool(a) and a[0] == "ready")

    with pytest.raises(A.BeadsError, match="still conflicting"):
        shared_bd.claim_next(lane=unique_lane, actor=actor)

    monkeypatch.undo()
    assert shared_bd.get_readonly(item_id).status == "open"


def test_claim_next_raises_when_bd_names_an_item_it_never_actually_claimed(
    shared_bd, unique_lane, monkeypatch
):
    """The phantom-success half of CCV1-013 for the queue claim."""
    actor = f"next-phantom-{unique_lane}"
    item_id = shared_bd.create(f"claim next phantom {unique_lane}", tags=[unique_lane])
    fake = json.dumps([{"id": item_id, "title": "phantom", "status": "in_progress"}])

    _phantom_success(monkeypatch, lambda a: bool(a) and a[0] == "ready", stdout=fake)

    with pytest.raises(A.BeadsError, match="did not land"):
        shared_bd.claim_next(lane=unique_lane, actor=actor)

    monkeypatch.undo()
    assert shared_bd.get_readonly(item_id).status == "open"


def test_claim_next_on_an_empty_queue_is_still_a_normal_none(shared_bd, unique_lane):
    """An empty queue is a normal terminal outcome, never a failed write --
    the verification must not turn "nothing to claim" into an error.
    """
    assert shared_bd.claim_next(lane=f"{unique_lane}-empty", actor=f"empty-{unique_lane}") is None


# ============================================== CCV1-015 every other write verb


def test_create_verifies_by_readback_when_the_wrapper_reports_conflict(
    shared_bd, unique_lane, monkeypatch
):
    """`create` is the one verb whose conflict-path key is not an id -- bd
    prints the new id on stdout, which the conflict destroys. Decided by the
    id-set difference over this exact title, which also RECOVERS the id.
    """
    title = f"create conflict {unique_lane}"
    calls = _conflict_after_real_write(monkeypatch, lambda a: bool(a) and a[0] == "create")

    item_id = shared_bd.create(title, tags=[unique_lane])

    assert len(calls) == 1
    assert item_id
    monkeypatch.undo()
    assert shared_bd.get_readonly(item_id).title == title


def test_create_still_raises_when_the_create_genuinely_did_not_land(
    shared_bd, unique_lane, monkeypatch
):
    """No new row with this title appeared, so the conflict propagates."""
    _conflict_without_write(monkeypatch, lambda a: bool(a) and a[0] == "create")

    with pytest.raises(A.BeadsError, match="still conflicting"):
        shared_bd.create(f"create genuine fail {unique_lane}", tags=[unique_lane])


def test_create_raises_when_bd_prints_an_id_it_never_actually_wrote(
    shared_bd, unique_lane, monkeypatch
):
    """Phantom success: an id on stdout with no row behind it used to be
    returned verbatim, handing the caller a dangling id.
    """
    _phantom_success(
        monkeypatch, lambda a: bool(a) and a[0] == "create", stdout="work_tracker-nope\n"
    )

    with pytest.raises(A.BeadsError, match="did not land"):
        shared_bd.create(f"create phantom {unique_lane}", tags=[unique_lane])


def test_update_verifies_by_readback_when_the_wrapper_reports_conflict(
    shared_bd, unique_lane, monkeypatch
):
    item_id = shared_bd.create(f"update conflict {unique_lane}", tags=[unique_lane])
    calls = _conflict_after_real_write(monkeypatch, lambda a: _is_update(a, "--title"))

    back = shared_bd.update(item_id, title=f"updated {unique_lane}")

    assert len(calls) == 1
    assert back.title == f"updated {unique_lane}"
    monkeypatch.undo()
    assert shared_bd.get_readonly(item_id).title == f"updated {unique_lane}"


def test_edit_item_verifies_by_readback_when_the_wrapper_reports_conflict(
    shared_bd, unique_lane, monkeypatch
):
    """`edit` = a verified field write plus its audit comment. Both halves go
    through the shared helper, so a conflicted-but-landed comment is not a
    reported failure either.
    """
    item_id = shared_bd.create(f"edit conflict {unique_lane}", tags=[unique_lane])
    calls = _conflict_after_real_write(monkeypatch, lambda a: bool(a) and a[0] == "comment")

    back = shared_bd.edit_item(
        item_id, description=f"edited {unique_lane}", actor=f"editor-{unique_lane}"
    )

    assert len(calls) == 1
    assert back.description == f"edited {unique_lane}"
    monkeypatch.undo()
    texts = [e.detail for e in shared_bd.activity(item_id) if e.kind == "comment"]
    assert any("edited: description" in (t or "") for t in texts)


def test_comment_raises_when_bd_reports_success_but_no_comment_landed(
    shared_bd, unique_lane, monkeypatch
):
    item_id = shared_bd.create(f"comment phantom {unique_lane}", tags=[unique_lane])
    _phantom_success(monkeypatch, lambda a: bool(a) and a[0] == "comment")

    with pytest.raises(A.BeadsError, match="did not land"):
        shared_bd.comment(item_id, f"never written {unique_lane}")


def test_defer_verifies_by_readback_when_the_wrapper_reports_conflict(
    shared_bd, unique_lane, monkeypatch
):
    item_id = shared_bd.create(f"defer conflict {unique_lane}", tags=[unique_lane])
    calls = _conflict_after_real_write(monkeypatch, lambda a: _is_update(a, "--status", "deferred"))

    back = shared_bd.defer(item_id, "waiting on upstream")

    assert len(calls) == 1
    assert back.status == "deferred"
    monkeypatch.undo()
    assert shared_bd.get_readonly(item_id).status == "deferred"


def test_defer_raises_when_bd_reports_success_but_the_status_did_not_move(
    shared_bd, unique_lane, monkeypatch
):
    item_id = shared_bd.create(f"defer phantom {unique_lane}", tags=[unique_lane])
    _phantom_success(monkeypatch, lambda a: _is_update(a, "--status", "deferred"))

    with pytest.raises(A.BeadsError, match="did not land"):
        shared_bd.defer(item_id, "never lands")

    monkeypatch.undo()
    assert shared_bd.get_readonly(item_id).status == "open"


def test_block_verifies_by_readback_when_the_wrapper_reports_conflict(
    shared_bd, unique_lane, monkeypatch
):
    item_id = shared_bd.create(f"block conflict {unique_lane}", tags=[unique_lane])
    calls = _conflict_after_real_write(monkeypatch, lambda a: _is_update(a, "--status", "blocked"))

    back = shared_bd.block(item_id, "needs a decision")

    assert len(calls) == 1
    assert back.status == "blocked"
    monkeypatch.undo()
    assert shared_bd.get_readonly(item_id).status == "blocked"


def test_unblock_verifies_by_readback_when_the_wrapper_reports_conflict(
    shared_bd, unique_lane, monkeypatch
):
    """The clear side of the same pair -- `--unset-metadata` back to open."""
    item_id = shared_bd.create(f"unblock conflict {unique_lane}", tags=[unique_lane])
    shared_bd.block(item_id, "needs a decision")
    calls = _conflict_after_real_write(monkeypatch, lambda a: _is_update(a, "--unset-metadata"))

    back = shared_bd.unblock(item_id)

    assert len(calls) == 1
    assert back.status == "open"
    monkeypatch.undo()
    assert shared_bd.get_readonly(item_id).status == "open"


def test_add_dependency_verifies_by_readback_when_the_wrapper_reports_conflict(
    shared_bd, unique_lane, monkeypatch
):
    a_id = shared_bd.create(f"dep conflict a {unique_lane}", tags=[unique_lane])
    b_id = shared_bd.create(f"dep conflict b {unique_lane}", tags=[unique_lane])
    calls = _conflict_after_real_write(monkeypatch, lambda a: a[:2] == ["dep", "add"])

    shared_bd.add_dependency(a_id, b_id)

    assert len(calls) == 1
    monkeypatch.undo()
    links = shared_bd.get(a_id, with_links=True).links
    assert any(link["id"] == b_id and link["direction"] == "from" for link in links)


def test_add_dependency_raises_when_bd_reports_success_but_no_edge_landed(
    shared_bd, unique_lane, monkeypatch
):
    a_id = shared_bd.create(f"dep phantom a {unique_lane}", tags=[unique_lane])
    b_id = shared_bd.create(f"dep phantom b {unique_lane}", tags=[unique_lane])
    _phantom_success(monkeypatch, lambda a: a[:2] == ["dep", "add"])

    with pytest.raises(A.BeadsError, match="did not land"):
        shared_bd.add_dependency(a_id, b_id)


def test_take_custody_verifies_by_readback_when_the_wrapper_reports_conflict(
    shared_bd, unique_lane, monkeypatch
):
    """A false failure here produces exactly the CCV1-003 shape: the item is
    HELD with a custody record that the caller believes does not exist.
    """
    actor = f"custody-conflict-{unique_lane}"
    item_id = _held_item(shared_bd, unique_lane, actor, f"take custody conflict {unique_lane}")
    calls = _conflict_after_real_write(monkeypatch, _is_custody_write)

    rec = shared_bd.take_custody(item_id, holder=actor, pid=4242, host=socket.gethostname())

    assert len(calls) == 1
    assert rec["holder"] == actor
    monkeypatch.undo()
    assert shared_bd.get_custody(item_id) == rec
    shared_bd.resolve(item_id, "cleanup", actor=actor)


def test_renew_custody_verifies_by_readback_when_the_wrapper_reports_conflict(
    shared_bd, unique_lane, monkeypatch
):
    """Renewal is ONE-STRIKE (Core 4): a renewal failure stops the loop for
    good. A false failure here therefore dooms a live, healthy hold -- which
    is why the conflict path must be decided by read-back, not by the
    wrapper's verdict.
    """
    actor = f"renew-conflict-{unique_lane}"
    item_id = _held_item(shared_bd, unique_lane, actor, f"renew custody conflict {unique_lane}")
    rec = shared_bd.take_custody(item_id, holder=actor, pid=4242, host=socket.gethostname())

    calls = _conflict_after_real_write(monkeypatch, _is_custody_write)

    updated = shared_bd.renew_custody(
        item_id,
        holder=actor,
        generation=rec["generation"],
        pid=4243,
        declared_state=C.STATE_AWAITING_HUMAN,
    )

    assert len(calls) == 1
    assert updated["declared_state"] == C.STATE_AWAITING_HUMAN
    assert updated["pid"] == 4243
    monkeypatch.undo()
    assert shared_bd.get_custody(item_id) == updated
    shared_bd.resolve(item_id, "cleanup", actor=actor)


def test_renew_custody_raises_when_bd_reports_success_but_the_record_did_not_move(
    shared_bd, unique_lane, monkeypatch
):
    """`declare` (the tool's `work_declare`) is this write. A phantom success
    would report a declared state that no reader ever sees.
    """
    actor = f"renew-phantom-{unique_lane}"
    item_id = _held_item(shared_bd, unique_lane, actor, f"renew custody phantom {unique_lane}")
    rec = shared_bd.take_custody(item_id, holder=actor, pid=4242, host=socket.gethostname())

    _phantom_success(monkeypatch, _is_custody_write)

    with pytest.raises(A.BeadsError, match="did not land"):
        shared_bd.renew_custody(
            item_id,
            holder=actor,
            generation=rec["generation"],
            pid=4243,
            declared_state=C.STATE_AWAITING_HUMAN,
        )

    monkeypatch.undo()
    assert shared_bd.get_custody(item_id) == rec, "the record really never moved"
    shared_bd.resolve(item_id, "cleanup", actor=actor)


def test_supersede_verifies_by_readback_when_the_wrapper_reports_conflict(
    shared_bd, unique_lane, monkeypatch
):
    old_id = shared_bd.create(f"supersede old {unique_lane}", tags=[unique_lane])
    new_id = shared_bd.create(f"supersede new {unique_lane}", tags=[unique_lane])
    calls = _conflict_after_real_write(monkeypatch, lambda a: bool(a) and a[0] == "supersede")

    back = shared_bd.supersede(old_id, new_id)

    assert len(calls) == 1
    assert back.status == "resolved"
    monkeypatch.undo()
    assert shared_bd.get_readonly(old_id).status == "resolved"


# --------------------------------------------------------------- CCV1-015 reopen
#
# `reopen` (item model_performance-f5c) joined this list on merge (2026-09-02,
# origin/main's PR #67): it carries TWO verified writes -- the `bd reopen`
# itself, and the conditional stale-assignee clear -- both routed through
# `_verified_write` rather than either being a bare unverified `_run` call.


def test_reopen_verifies_by_readback_when_the_wrapper_reports_conflict(
    shared_bd, unique_lane, monkeypatch
):
    """The same conflict-after-landed shape every other verb here proves:
    `bd reopen` really lands against the isolated dolt server, then
    `Beads._run` raises its own exhausted-retries `BeadsError` anyway.
    `reopen` must notice the item is no longer `resolved` and report
    SUCCESS rather than propagate the wrapper's false failure.
    """
    actor = f"reopen-conflict-{unique_lane}"
    item_id = shared_bd.create(f"reopen conflict {unique_lane}", tags=[unique_lane])
    shared_bd.claim_item(item_id, actor=actor)
    shared_bd.resolve(item_id, "first pass", actor=actor)

    calls = _conflict_after_real_write(monkeypatch, lambda a: bool(a) and a[0] == "reopen")

    outcome = shared_bd.reopen(item_id, "correcting under contention", actor=actor)

    assert len(calls) == 1, "the reopen path must have been exercised exactly once"
    assert outcome.item.status != "resolved"
    assert outcome.previous_resolution == "first pass"
    monkeypatch.undo()
    assert shared_bd.get_readonly(item_id).status != "resolved"


def test_reopen_still_raises_when_readback_shows_the_reopen_genuinely_did_not_land(
    shared_bd, unique_lane, monkeypatch
):
    """Contrast case: if `_run` raises AND the item is genuinely still
    resolved (the reopen never landed at all), `reopen` must still raise --
    verify-by-read-back is a safety net for a landed write, never a way to
    silently swallow a real failure.
    """
    actor = f"reopen-genuine-{unique_lane}"
    item_id = shared_bd.create(f"reopen genuine fail {unique_lane}", tags=[unique_lane])
    shared_bd.claim_item(item_id, actor=actor)
    shared_bd.resolve(item_id, "first pass", actor=actor)

    _conflict_without_write(monkeypatch, lambda a: bool(a) and a[0] == "reopen")

    with pytest.raises(A.BeadsError, match="still conflicting"):
        shared_bd.reopen(item_id, "should not land", actor=actor)

    monkeypatch.undo()
    assert shared_bd.get_readonly(item_id).status == "resolved"
    shared_bd.reopen(item_id, "correcting for real", actor=actor)


# --------------------------------------------------------------- CCV1-015 erratum
#
# `erratum` (work_item_pipeline-03c) joins this list on arrival, same as
# `reopen` did: routed through `_verified_write` from day one, never a
# bespoke inline shape. Its verify predicate is COUNT-based, like
# `comment()`'s own -- see `Beads.erratum`'s docstring for why "an erratum
# matching this actor+text now exists" is the right predicate (two errata
# with identical text from the SAME actor is a real, legitimate case).


def test_erratum_verifies_by_readback_when_the_wrapper_reports_conflict(
    shared_bd, unique_lane, monkeypatch
):
    """The same conflict-after-landed shape every other verb here proves:
    `bd comment` really lands against the isolated dolt server, then
    `Beads._run` raises its own exhausted-retries `BeadsError` anyway.
    `erratum` must notice the comment landed and report SUCCESS.
    """
    actor = f"erratum-conflict-{unique_lane}"
    item_id = shared_bd.create(f"erratum conflict {unique_lane}", tags=[unique_lane])
    shared_bd.claim_item(item_id, actor=actor)
    shared_bd.resolve(item_id, "first pass", actor=actor)

    calls = _conflict_after_real_write(monkeypatch, lambda a: bool(a) and a[0] == "comment")

    outcome = shared_bd.erratum(item_id, actor=actor, text="the reason given was wrong")

    assert len(calls) == 1, "the erratum path must have been exercised exactly once"
    assert outcome.already_recorded is False
    assert any(e.text == "the reason given was wrong" for e in outcome.item.errata)
    monkeypatch.undo()
    back = shared_bd.get_readonly(item_id)
    assert any(e.text == "the reason given was wrong" for e in back.errata)
    assert back.status == "resolved"  # never touched by the erratum


def test_erratum_still_raises_when_readback_shows_the_write_genuinely_did_not_land(
    shared_bd, unique_lane, monkeypatch
):
    """Contrast case: a conflict whose write never happened still raises --
    verify-by-read-back is a safety net for a landed write, never a way to
    silently swallow a real failure."""
    actor = f"erratum-genuine-{unique_lane}"
    item_id = shared_bd.create(f"erratum genuine fail {unique_lane}", tags=[unique_lane])
    shared_bd.claim_item(item_id, actor=actor)
    shared_bd.resolve(item_id, "first pass", actor=actor)

    _conflict_without_write(monkeypatch, lambda a: bool(a) and a[0] == "comment")

    with pytest.raises(A.BeadsError, match="still conflicting"):
        shared_bd.erratum(item_id, actor=actor, text="should not land")

    monkeypatch.undo()
    assert not shared_bd.get_readonly(item_id).errata
    shared_bd.erratum(item_id, actor=actor, text="correcting for real")


def test_erratum_raises_when_bd_reports_success_but_no_erratum_comment_landed(
    shared_bd, unique_lane, monkeypatch
):
    """Phantom success: `bd comment` exits 0 having written nothing at all.
    `erratum` must notice no matching comment landed and RAISE -- "exit code
    is not proof" applies to this verb's success path too."""
    actor = f"erratum-phantom-{unique_lane}"
    item_id = shared_bd.create(f"erratum phantom {unique_lane}", tags=[unique_lane])
    shared_bd.claim_item(item_id, actor=actor)
    shared_bd.resolve(item_id, "first pass", actor=actor)

    _phantom_success(monkeypatch, lambda a: bool(a) and a[0] == "comment")

    with pytest.raises(A.BeadsError, match="did not land"):
        shared_bd.erratum(item_id, actor=actor, text="never actually written")

    monkeypatch.undo()
    assert not shared_bd.get_readonly(item_id).errata


# ------------------------------------------------------------------ move
#
# `move_item` is the one verb in this list that never touches `bd` or
# `Beads._run` at all -- it is direct dolt SQL, so the conflict-family
# retry hazard the helper exists for cannot reach it. It carries its own,
# older read-back: real row counts in `dst` compared against `src`'s counts
# taken before anything moved, plus a residue check in `src` after the
# delete. This test proves that verification is load-bearing rather than
# decorative, by making the copy LOOK successful while the rows are not
# there -- the move must refuse and leave `src` intact.


def test_move_refuses_when_the_copy_reports_success_but_the_rows_are_not_there(
    workspace, project_factory, monkeypatch
):
    src_name, src_bd = project_factory("mvsrc")
    dst_name, _ = project_factory("mvdst")
    item_id = src_bd.create("move verification", tags=[A.LANE_WORK])

    real_counts = A._item_row_counts  # noqa: SLF001 -- test injection

    def fake_counts(db: str, iid: str) -> dict[str, int]:
        if db == dst_name:  # dst looks empty no matter what the copy reported
            return dict.fromkeys(real_counts(db, iid), 0)
        return real_counts(db, iid)

    monkeypatch.setattr(A, "_item_row_counts", fake_counts)

    with pytest.raises(A.BeadsError, match="incomplete copy"):
        workspace.move_item(src_name, dst_name, item_id)

    monkeypatch.undo()
    assert src_bd.get_readonly(item_id).title == "move verification", "src must be untouched"
