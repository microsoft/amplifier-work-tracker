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
    contains,
    count,
    read,
    row,
    sha256,
)

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
    """Core 3 CONFORMS: a `take_custody` failure after a successful claim
    COMPENSATES -- it releases the just-claimed item, confirms that release
    by its own contention-free read-back, and reports both facts.

    Three separable things must all hold, so each is asserted separately:
    the failing arm calls the compensation (rather than returning), the
    compensation actually releases AND independently verifies, and the
    residual case -- a compensating release that itself fails -- stays
    loud. A fix that quietly dropped the verification read, or softened the
    still-held message into a rollback claim, would pass a single blunt
    check and fail these.

    Behavioral proof lives in the tool module's own suite (real bd/dolt);
    this kit is in-process only, so what it can prove is the SHAPE. See the
    row's `notes` for the fixture names and the honest limit.
    """
    assert contains(
        TOOL_MODULE,
        """
                return ToolResult(
                    success=False,
                    output=self._release_after_failed_custody(bd, item.id, e),
                )
        """,
    ), (
        "CCV1-003 (Core 3): the failing `take_custody` arm of `claim` no longer "
        "routes to the compensating release. If it returns a bare failure again, "
        "the two-write hole is BACK: the item stays held with no custody record "
        "until a reap sweep frees it (work_item_pipeline-aih)."
    )
    assert contains(
        TOOL_MODULE,
        """
            outcome = bd.release(item_id)
        """,
    ) and contains(
        TOOL_MODULE,
        """
            back = bd.get_readonly(item_id)
        """,
    ), (
        "CCV1-003 (Core 3): the compensation must both RELEASE the claim and "
        "verify by its OWN read-back -- a write's self-report of success is "
        "exactly what this repo has repeatedly measured to be unreliable."
    )
    # Matched as fragments, not whole sentences: these messages are built
    # from adjacent f-string literals, so the source text a reader sees as
    # one sentence carries a `" f"` seam that whitespace-collapsing cannot
    # remove. Each fragment is still specific enough that a reworded
    # message fails here.
    assert contains(
        TOOL_MODULE, "claim landed; custody could not be established; item released back to "
    ), "CCV1-003 (Core 3): the success-path message must name BOTH facts"
    assert contains(TOOL_MODULE, "release ALSO FAILED --") and contains(
        TOOL_MODULE, "may STILL BE HELD by"
    ), (
        "CCV1-003 (Core 3): a compensating release that itself fails must stay "
        "loud -- it is the one path that can still leave an item held, and it "
        "must never be reported as a rollback that happened."
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
    """Core 10 VIOLATION pin: `release()` returns success straight off the
    subprocess exit code -- no read-back that the status actually became
    `open`. Every sibling write verifies itself; this one, which both
    `work_release` and every reap reclaim call, does not.
    """
    assert contains(
        ADAPTER,
        """
        if p.returncode != 0:
            detail = _clean_bd_error(p.stderr or p.stdout, limit=200)
            raise BeadsError(f"release {item_id}: {detail}")
        return ReleaseOutcome(item_id=item_id, already_closed=False)
        """,
    ), (
        "CCV1-012 (Core 10, VIOLATION) pin no longer matches. If release() gained its "
        "read-back, this is the expected failure: flip the row to CONFORMS and resolve "
        "work_item_pipeline-1f2."
    )


# --------------------------------------------------------------- CCV1-013


def test_row_ccv1_013() -> None:
    """Core 10 GAP pin: neither claim path verifies itself by read-back. Both
    return an item parsed from the WRITING process's own stdout -- the
    "exit code is not proof" shape, on the highest-stakes custody write.
    """
    assert contains(
        ADAPTER,
        """
        if not items:
            raise BeadsError(f"claim {item_id}: bd reported success but returned no item")
        return Item.from_beads(items[0])
        """,
    ), "CCV1-013 pin (claim_item) no longer matches"
    assert contains(
        ADAPTER,
        """
        data = self._json(["ready", "--label", lane, "--claim"], actor=actor)
        items = data if isinstance(data, list) else ([data] if data else [])
        items = [i for i in items if isinstance(i, dict) and i.get("id")]
        return Item.from_beads(items[0]) if items else None
        """,
    ), (
        "CCV1-013 (Core 10, GAP) pin (claim_next) no longer matches. If the claim path "
        "gained verify-by-read-back, flip the row to CONFORMS and resolve "
        "work_item_pipeline-1gz."
    )


# --------------------------------------------------------------- CCV1-015


def test_row_ccv1_015() -> None:
    """Core 11 GAP pin: the conflicted-write read-back helper has exactly
    three occurrences -- its definition and two call sites (`resolve`,
    `release`). Every other write verb still propagates an exhausted-retry
    exception directly, so a landed write can still surface as a reported
    failure there.
    """
    occurrences = count(ADAPTER, "_read_back_or_none")
    assert occurrences == 3, (
        f"CCV1-015 (Core 11, GAP) pin: expected 3 occurrences of `_read_back_or_none` "
        f"(1 definition + 2 call sites: resolve, release), found {occurrences}. If a "
        f"third write verb adopted verify-on-conflict, update the row's coverage list "
        f"(and resolve work_item_pipeline-2x3 when the custody-relevant writes -- "
        f"take_custody, renew_custody -- are covered)."
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
