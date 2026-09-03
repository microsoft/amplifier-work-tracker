"""Per-row probes for `contracts/custody-coordination.v1.md`.

One `test_row_ccv1_NNN` function per ledger row whose `assertion.kind` is
`probe` or `absence`. The pairing is enforced in both directions by
`test_ledger_integrity.py` -- a probe with no row, or a row citing a probe
that does not exist, fails the ledger.

## The one convention a reader must know before reading further

A probe on a **CONFORMS** row asserts the invariant holds.

A probe on a **VIOLATION** or **GAP** row asserts the *currently observed,
known-wrong* shape -- on purpose. Those rows carry a filed work item; the
ledger's job until that item lands is to make the drift **immovable in both
directions**: a regression fails, and so does a *silent fix*. When the fix
lands, the probe here fails, and that failure is the instruction: flip the
row to CONFORMS and replace the pin with the discriminating fixture. Doing
neither means main carries a ledger that lies.

These probes are in-process source assertions, not behavioral fixtures.
They prove the shape of the code, not the behavior of the system -- see
each row's `notes` and the reconcile report's "Honest limits". Rows whose
behavior IS measured cite real tests instead (`assertion.kind: indexed`).
"""

from __future__ import annotations

import ast
import re

from ._support import (
    ADAPTER,
    AWARENESS,
    CI_WORKFLOW,
    CLAIM_SKILL,
    CONTRACT_PATH,
    MAKEFILE,
    REPO_ROOT,
    TOOL_MODULE,
    collapse,
    contains,
    count,
    read,
    row,
    sha256,
)


def _beads_method(name: str) -> str:
    """The whitespace-collapsed source of exactly ONE `Beads` method.

    Sliced by AST line span rather than by string search, so a probe about
    (say) `release` can never accidentally match a sibling method that
    happens to contain a similar line -- the failure mode a whole-file
    `contains()` has whenever the same shape appears in more than one verb,
    which is precisely the situation once every write verb shares one
    helper. Collapsed for the same reason `contains` collapses: survives
    reformatting, never survives a real change of wording.
    """
    src = read(ADAPTER)
    lines = src.splitlines(keepends=True)
    for node in ast.parse(src).body:
        if not (isinstance(node, ast.ClassDef) and node.name == "Beads"):
            continue
        for member in node.body:
            if isinstance(member, ast.FunctionDef) and member.name == name:
                return collapse("".join(lines[member.lineno - 1 : member.end_lineno]))
    raise AssertionError(f"Beads.{name} not found in {ADAPTER} -- the probe is out of date")


# --------------------------------------------------------------- CCV1-000


def test_row_ccv1_000() -> None:
    """SYNC. Pins the contract (and the vision that points at it) by content
    hash. A mismatch is never a silent hash bump: it triggers a MANDATORY
    full-ledger re-review, because quote verification only proves the text
    still exists -- not that each row still reads it correctly.
    """
    sync = row("CCV1-000")["contract"]
    for entry in sync["files"]:
        path = REPO_ROOT / entry["file"]
        actual = sha256(path)
        assert actual == entry["sha256"], (
            f"LEDGER-INTEGRITY: {entry['file']} content hash changed\n"
            f"  pinned:   {entry['sha256']}\n"
            f"  observed: {actual}\n"
            f"The contract moved under the ledger. Do NOT bump this hash on its own: "
            f"re-review EVERY row against the new text, then update the SYNC row in the "
            f"same change (LEDGER-FORMAT.md sec.4)."
        )


# --------------------------------------------------------------- CCV1-003


def test_row_ccv1_003() -> None:
    """Core 3 VIOLATION pin: a failed `take_custody` after a successful claim
    returns a failure and leaves the item HELD with no custody record --
    no release, no rollback.
    """
    assert contains(
        TOOL_MODULE,
        """
            except A.BeadsError as e:
                return ToolResult(
                    success=False,
                    output=f"claimed {item.id} but could not establish custody: {e}",
                )
        """,
    ), (
        "CCV1-003 (Core 3, VIOLATION) pin no longer matches. If the claim/custody "
        "two-write hole was CLOSED, this is the expected failure: flip the row to "
        "CONFORMS, cite the discriminating fixture, and resolve work_item_pipeline-aih."
    )


# --------------------------------------------------------------- CCV1-004


def test_row_ccv1_004() -> None:
    """Core 4 CONFORMS: renewal is one-strike. Any renewal failure records the
    reason, stops the loop for good, and returns -- no internal retry. A
    FencedError additionally drops this session's own belief that it holds
    the item.
    """
    assert contains(
        TOOL_MODULE,
        """
                    held.lost_reason = str(e)
                    held.stop.set()
                    if isinstance(e, A.FencedError) and self._held is held:
                        self._held = None
                    return
        """,
    ), "Core 4: the one-strike renewal mechanism changed shape"


# --------------------------------------------------------------- CCV1-005


def test_row_ccv1_005() -> None:
    """Core 4 GAP pin (doc drift): the skill still reassures agents that
    custody keeps itself fresh while the process lives -- which is false for
    exactly the failure mode Core 4 names (a non-fenced renewal failure
    stops renewal and leaves `self._held` set).
    """
    assert contains(
        CLAIM_SKILL,
        "you do not need to do anything to keep it fresh under normal operation.",
    ), (
        "CCV1-005 (Core 4, GAP) pin no longer matches -- the prose changed. If it was "
        "CORRECTED, flip the row to CONFORMS, re-pin the new wording, and resolve "
        "work_item_pipeline-m7o."
    )


# --------------------------------------------------------------- CCV1-008


def test_row_ccv1_008() -> None:
    """Core 6 GAP pin (doc drift): both agent-facing documents state the TTL
    as self-enforcing -- an unrenewed hold "is released" -- with no mention
    of the out-of-band sweep the release actually depends on.
    """
    assert contains(
        AWARENESS, "15 minutes without a renewal releases\nthe item back to the queue."
    ), "CCV1-008 pin (awareness.md) no longer matches"
    assert contains(CLAIM_SKILL, "An unrenewed\n15-minute hold is released back to the queue."), (
        "CCV1-008 pin (SKILL.md) no longer matches"
    )


# --------------------------------------------------------------- CCV1-009


def test_row_ccv1_009() -> None:
    """Core 7 VIOLATION pin: the whole close fence runs only while the item is
    still `held`. A reaped item is `open` with its assignee cleared, so a
    stale holder's close skips the fence entirely.

    Pinned structurally rather than by one line, so that ADDING a fence for
    the released state (a legitimate fix shape that keeps the existing gate)
    also flips this probe: every `raise FencedError` in resolve's pre-write
    region must still sit inside the `status == "held"` block.
    """
    src = read(ADAPTER)
    body = src[
        src.index("    def resolve(self, item_id: str") : src.index("    def _read_back_or_none")
    ]
    pre_write = body[: body.index("        try:")]
    gate = '        if current.status == "held":'
    assert gate in pre_write, "CCV1-009 pin: the status gate is gone"
    fences = [m.start() for m in re.finditer(r"raise FencedError", pre_write)]
    assert fences and all(pos > pre_write.index(gate) for pos in fences), (
        "CCV1-009 (Core 7, VIOLATION) pin no longer matches. If the post-reclaim fence "
        "was FIXED, this is the expected failure: flip the row to CONFORMS, cite the "
        "discriminating fixture (both halves -- refuse the stale holder, still allow the "
        "integrator's plain resolve), and resolve work_item_pipeline-dn4."
    )


# --------------------------------------------------------------- CCV1-011


def test_row_ccv1_011() -> None:
    """Core 9 CONFORMS: renewal is fenced on holder AND generation (plus, in
    defence-in-depth, on bd's own assignee), and takeover always increments
    generation past whatever was there -- so a resurrected zombie's old
    generation can never match again.
    """
    assert contains(
        ADAPTER,
        'if current.get("holder") != holder or int(current.get("generation", -1)) != generation:',
    ), "Core 9: the renew holder+generation fence changed shape"
    assert contains(
        ADAPTER, 'gen = (int(prior.get("generation", 0)) + 1) if isinstance(prior, dict) else 1'
    ), "Core 9: the monotonic generation increment changed shape"
    assert contains(ADAPTER, 'f"cannot take custody of {item_id}: bd assignee is "'), (
        "Core 9: take_custody's assignee fence changed shape"
    )


# --------------------------------------------------------------- CCV1-012


def test_row_ccv1_012() -> None:
    """Core 10 CONFORMS: `release()` confirms the hold actually cleared
    before returning -- on the SUCCESS path, not only the conflict path.
    The outcome it reports is derived from that read-back, never asserted
    from a zero exit code.
    """
    body = _beads_method("release")
    assert "self._verified_write(" in body, "CCV1-012: release no longer routes through the helper"
    assert (
        collapse(
            """
        def _verify() -> bool:
            back = self._read_back_or_none(item_id)
            if back is None or back.status == "held":
                return False
        """
        )
        in body
    ), "CCV1-012: release's verify no longer demands the item is out of `held`"
    assert (
        collapse("return ReleaseOutcome(item_id=item_id, already_closed=(seen[-1].status ==")
        in body
    ), "CCV1-012: the reported outcome is no longer derived from the read-back"
    assert "already_closed=False)" not in body, (
        "CCV1-012 (Core 10) regression: release reports an outcome it did not read back. "
        "The exit-code-only success return is exactly the shape this row exists to forbid."
    )


# --------------------------------------------------------------- CCV1-013


def test_row_ccv1_013() -> None:
    """Core 10 CONFORMS: both claim paths verify by read-back, and both
    RETURN the read-back rather than an Item parsed from the writing
    process's own stdout. A claim is the highest-stakes custody write here
    -- its caller starts custody on the strength of it -- so "bd said so"
    is never the answer.
    """
    directed = _beads_method("claim_item")
    queued = _beads_method("claim_next")
    for verb, body in (("claim_item", directed), ("claim_next", queued)):
        assert "self._verified_write(" in body, (
            f"CCV1-013 (Core 10) regression: {verb} no longer routes through the "
            f"verified-write helper."
        )
        assert "Item.from_beads(" not in body, (
            f"CCV1-013 (Core 10) regression: {verb} builds its returned Item from the "
            f"writing process's own stdout again. The returned item must be the read-back."
        )
        assert 'back.status == "held" and back.holder == actor' in body, (
            f"CCV1-013: {verb}'s verify no longer demands THIS actor holds the item"
        )
    assert "return self.get(item_id)" in directed, "CCV1-013: claim_item returns a non-read-back"
    assert "return self.get(claimed[0]) if claimed else None" in queued, (
        "CCV1-013: claim_next returns a non-read-back, or lost its empty-queue None"
    )
    # The conflict path has no id to read back by -- it is decided by the
    # id-set difference, and an ambiguous result must never be guessed.
    assert (
        collapse(
            """
                new = _ids_via_sql(self.project_name, held_where) - held_before
                if len(new) != 1:
        """
        )
        in queued
    ), "CCV1-013: claim_next's conflict-path set difference changed shape"


# --------------------------------------------------------------- CCV1-015


#: Every item-level write verb on `Beads`. The closed list this row is
#: about: each one must route its `bd` write through `_verified_write`, so
#: a conflict-family failure is decided by read-back rather than by the
#: wrapper's verdict. `resolve` is deliberately absent -- it keeps PR #63's
#: own inline shape, pinned by CCV1-009 (see that row).
_VERIFIED_WRITE_VERBS = (
    "create",
    "update",
    "comment",
    "supersede",
    "claim_next",
    "claim_item",
    "release",
    "_set_status_with_reason",  # defer / block
    "_clear_status_with_reason",  # undefer / unblock
    "add_dependency",
    "take_custody",
    "renew_custody",
)


def test_row_ccv1_015() -> None:
    """Core 11 CONFORMS: one shared helper carries verify-on-conflict for
    EVERY item-level write verb, not just `resolve`/`release`. Exhaustion
    of the retry budget does not prove a write did not land, so a reported
    failure is decided by a contention-free read-back before it is
    believed -- and a reported success is verified too.
    """
    helper = _beads_method("_verified_write")
    assert "except BeadsError:" in helper and "if self._landed(verify):" in helper, (
        "CCV1-015: the helper no longer verifies on the wrapper's exhausted-retry raise"
    )
    assert "if (_retryable(blob) or _connection_retryable(blob)) and self._landed(verify):" in (
        helper
    ), "CCV1-015: the helper no longer verifies a conflict-family non-zero exit"
    assert "if not verify():" in helper, (
        "CCV1-015: the helper stopped verifying the SUCCESS path -- exit code is not proof"
    )
    assert "return False" in _beads_method("_landed"), (
        "CCV1-015: `_landed` must swallow a failed verification into False, never mask "
        "the original error with a second one"
    )

    missing = [v for v in _VERIFIED_WRITE_VERBS if "self._verified_write(" not in _beads_method(v)]
    assert not missing, (
        f"CCV1-015 (Core 11) regression: these write verbs no longer route through "
        f"`_verified_write`, so a landed write there can still surface as a reported "
        f"failure: {missing}"
    )

    edit = _beads_method("edit_item")
    assert "self.update(" in edit and "self.comment(" in edit, (
        "CCV1-015: `edit` must delegate BOTH halves (field write + audit comment) to "
        "verbs that verify themselves"
    )
    # `move_item` is a module-level function over direct dolt SQL -- it never
    # touches `Beads._run`, so the helper cannot apply. It carries its own,
    # equivalent proof: real row counts in dst, and a compensating cleanup so
    # a reported failure never leaves state as if the write succeeded.
    assert contains(ADAPTER, "left an incomplete copy in"), (
        "CCV1-015: move_item's own row-count verification is gone"
    )
    assert count(ADAPTER, "_read_back_or_none") == 3, (
        "CCV1-015: `_read_back_or_none`'s call sites moved (expected 1 definition + "
        "resolve's conflict branch + release's verify). Re-check that every verb still "
        "verifies before adjusting this count."
    )


# --------------------------------------------------------------- CCV1-016


def test_row_ccv1_016() -> None:
    """Core 11 GAP pin (doc drift): awareness.md still tells agents a reported
    serialization failure means the write did not happen -- contradicting
    both the measured incident and the verify-by-read-back code that exists
    because of it.
    """
    assert contains(AWARENESS, "so the write genuinely did not happen"), (
        "CCV1-016 (Core 11, GAP) pin no longer matches -- the prose changed. If it was "
        "CORRECTED, flip the row to CONFORMS, re-pin the new wording, and resolve "
        "work_item_pipeline-ryp."
    )


# --------------------------------------------------------------- CCV1-017


def test_row_ccv1_017() -> None:
    """Core 12 CONFORMS: a second claim while already holding is refused, by
    name, before any bd call.
    """
    assert contains(
        TOOL_MODULE,
        """
            if self._held is not None:
                return ToolResult(
                    success=False,
                    output=(
                        f"already holding {self._held.item_id!r} in project "
        """,
    ), "Core 12: the single-hold refusal changed shape"


# --------------------------------------------------------------- CCV1-021


def test_row_ccv1_021() -> None:
    """Conformance/Checks CONFORMS: this ledger actually runs. `make test` and
    CI both collect `ledger/checks`. A ledger that is not run is a
    remembered audit, which is what this row exists to prevent.
    """
    assert contains(MAKEFILE, "$(PYTEST) tests ledger/checks -v"), (
        "`make test` no longer runs the ledger checks"
    )
    assert contains(MAKEFILE, "test-ledger:"), "the `test-ledger` target is gone"
    assert contains(CI_WORKFLOW, "pytest ledger/checks -v"), "CI no longer runs the ledger checks"


# --------------------------------------------------------------- CCV1-022


def test_row_ccv1_022() -> None:
    """Freeze Bar VIOLATION pin (absence): nothing runs the tool module's own
    test suite -- neither `make test` nor CI names it. The only mechanical
    assertions of post-reclaim custody behavior live there.
    """
    for path, label in ((MAKEFILE, "Makefile"), (CI_WORKFLOW, ".github/workflows/ci.yml")):
        assert "tool-work-tracker" not in read(path), (
            f"CCV1-022 (Freeze Bar, VIOLATION) pin: {label} now references "
            f"the tool-work-tracker module. If the suite genuinely RUNS (importable and "
            f"green), this is the expected failure: flip the row to CONFORMS, upgrade the "
            f"rows that depend on it (CCV1-004, CCV1-009, CCV1-010, CCV1-017) from "
            f"source-pinned probes to behavioral cites, and resolve work_item_pipeline-a7n."
        )


# --------------------------------------------------------------- CCV1-023


def test_row_ccv1_023() -> None:
    """Freeze Bar GAP pin (absence): three of the four Conformance fixtures are
    not implemented-and-runnable, and the contract's own "Test location"
    lines point at files that do not exist.
    """
    for named in (
        "tests/test_incident_b.py",
        "tests/test_reap_recovery.py",
        "tests/test_recovery.py",
        "tests/test_single_hold.py",
    ):
        assert not (REPO_ROOT / named).exists(), (
            f"CCV1-023 (Freeze Bar, GAP) pin: {named} now exists. Re-check which fixtures "
            f"are implemented-and-runnable, update the row, and resolve "
            f"work_item_pipeline-qmj when all four are."
        )
    # Fixture 4 (single-hold) is asserted by no test anywhere in either suite.
    hits = [
        p
        for p in (REPO_ROOT / "tests").rglob("test_*.py")
        if "single_hold" in read(p) or "already holding" in read(p)
    ]
    hits += [
        p
        for p in (REPO_ROOT / "modules" / "tool-work-tracker" / "tests").rglob("test_*.py")
        if "single_hold" in read(p) or "already holding" in read(p)
    ]
    assert not hits, f"CCV1-023 pin: a single-hold fixture now exists ({hits}) -- update the row"
    # The contract still names those non-existent locations (drift the row records).
    assert contains(
        CONTRACT_PATH, "**Test location:** `tests/test_single_hold.py` (to be added)."
    ), "CCV1-023 pin: the contract's Fixture 4 location line changed"
