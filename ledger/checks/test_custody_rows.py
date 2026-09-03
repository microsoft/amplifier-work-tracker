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

# The CLI's module docstring is argparse's `description` -- i.e. prose an
# operator reads at `--help`, and the CLI-side twin of `context/awareness.md`'s
# contention contract. Kept local to this module (only CCV1-016 pins it).
CLI = REPO_ROOT / "src" / "amplifier_work_tracker" / "cli.py"

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
    """Core 4 CONFORMS: both agent-facing documents now state renewal as
    one-strike AND name the passive discovery signal. Pinned in both
    directions -- the corrected claim must be present, and the reassurance
    it replaced ("you do not need to do anything to keep it fresh") must
    stay gone.
    """
    for path, label, present in (
        (
            CLAIM_SKILL,
            "SKILL.md",
            "**Any single renewal failure ends renewal permanently** — there is no "
            "retry on the next tick.",
        ),
        (
            AWARENESS,
            "awareness.md",
            "a single failed renewal ends renewal permanently — there is no retry on the next tick",
        ),
    ):
        assert contains(path, present), (
            f"CCV1-005 (Core 4) pin: {label} no longer states renewal as one-strike"
        )
        assert contains(path, "holding.custody_lost"), (
            f"CCV1-005 (Core 4) pin: {label} no longer names the passive signal an "
            f"agent discovers a stopped renewal by"
        )
        assert not contains(path, "you do not need to do anything to keep it fresh"), (
            f"CCV1-005 (Core 4) pin: the corrected prose in {label} regressed to the "
            f"custody-keeps-itself-fresh reassurance Core 4 contradicts"
        )


# --------------------------------------------------------------- CCV1-008


def test_row_ccv1_008() -> None:
    """Core 6 CONFORMS: both agent-facing documents now state the TTL as
    reclaim-ELIGIBILITY enforced by the out-of-band sweep, name the sweep,
    and name the consequence of no sweep running. Pinned in both
    directions -- the stale "is released by the clock" phrasing must stay
    gone from each.
    """
    assert contains(
        AWARENESS,
        "**The TTL does not enforce itself.** After 15 minutes with no renewal a hold "
        "is merely *reclaim-eligible*; the out-of-band `reap` sweep is what actually "
        "reclaims it, and only where an operator has one installed and running.",
    ), "CCV1-008 (Core 6) pin: awareness.md no longer states the TTL as sweep-enforced"
    assert contains(
        AWARENESS, "expect a dead agent's hold to persist indefinitely where no sweep runs"
    ), "CCV1-008 (Core 6) pin: awareness.md no longer names the no-sweep consequence"
    assert contains(
        CLAIM_SKILL,
        "**The TTL is not self-enforcing.** Nothing in your process, and no timer in "
        "the database, hands a stale hold back. The out-of-band `reap` sweep does, and "
        "only where an operator has one installed and running.",
    ), "CCV1-008 (Core 6) pin: SKILL.md no longer states the TTL as sweep-enforced"
    assert contains(
        CLAIM_SKILL, "Where no sweep runs, a dead agent's hold **persists indefinitely**."
    ), "CCV1-008 (Core 6) pin: SKILL.md no longer names the no-sweep consequence"
    for path, label in ((AWARENESS, "awareness.md"), (CLAIM_SKILL, "SKILL.md")):
        assert not contains(path, "releases the item back to the queue"), (
            f"CCV1-008 (Core 6) pin: {label} regressed to stating the release as "
            f"automatic -- Core 6 denies exactly that"
        )
        assert not contains(path, "15-minute hold is released back to the queue"), (
            f"CCV1-008 (Core 6) pin: {label} regressed to stating the release as "
            f"automatic -- Core 6 denies exactly that"
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
    """Core 11 CONFORMS: both prose surfaces -- the agent-facing awareness
    file and the CLI's own CONTENTION / RETRY CONTRACT -- now state a
    reported conflict as UNKNOWN rather than as proof the write did not
    land, name the two verbs that verify by read-back, and keep the
    re-read-before-retry guidance that was always correct.

    Pinned in both directions: the "did not happen" claim (defensible
    before PR #63, wrong the moment resolve/release started reading a
    conflicted write back) must stay gone from both files.
    """
    assert contains(
        AWARENESS,
        "**A reported write failure does NOT prove the write failed — treat it as "
        "UNKNOWN and re-read before you retry.**",
    ), "CCV1-016 (Core 11) pin: awareness.md no longer states a reported failure as unknown"
    assert contains(
        AWARENESS,
        "`work_resolve` and `work_release` already handle it for you: on a conflict "
        "they re-read the item and report success when the write did in fact land",
    ), "CCV1-016 (Core 11) pin: awareness.md no longer names the verify-by-read-back verbs"
    assert contains(
        AWARENESS, "There, a reported failure means *unknown*, never *didn't happen*."
    ), "CCV1-016 (Core 11) pin: awareness.md no longer scopes the guarantee to those verbs"
    assert contains(
        CLI, 'Treat a reported failure as "this MIGHT have happened," never as "this did not '
    ), "CCV1-016 (Core 11) pin: the CLI contention contract no longer states failure as unknown"
    assert contains(CLI, "Every other write verb"), (
        "CCV1-016 (Core 11) pin: the CLI contention contract no longer scopes the guarantee"
    )
    for path, label in ((AWARENESS, "context/awareness.md"), (CLI, "src/.../cli.py")):
        assert not contains(path, "the write genuinely did not happen"), (
            f"CCV1-016 (Core 11) pin: {label} regressed to claiming a reported conflict "
            f"proves the write did not land"
        )
    assert not contains(
        CLI, "those specific error signatures are, by dolt/MySQL's own transaction semantics"
    ), (
        "CCV1-016 (Core 11) pin: the CLI contention contract regressed to the "
        "transaction-was-aborted guarantee Incident B disproved"
    )
    # The correct half of the original guidance must survive the correction.
    for path, label in ((AWARENESS, "context/awareness.md"), (CLI, "src/.../cli.py")):
        assert contains(path, "read-only") and contains(path, "cannot itself conflict"), (
            f"CCV1-016 (Core 11) pin: {label} lost the re-read-before-retry instruction "
            f"(the half of the original guidance that was always correct)"
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
    """Freeze Bar CONFORMS: the tool module's own suite is importable and is
    run -- by `make test` and by CI. Asserts all three halves of the wiring,
    because any one of them going missing silently returns the suite to
    "green claims nobody has ever run", which is the state this row closed.

    Source-level on purpose (this ledger is in-process only, no bd/dolt/
    subprocess). The suite's actual green-ness is measured by running it --
    Makefile `test-module` / CI "Tier 5" -- and recorded in the row's notes.
    """
    module_pkg = "modules/tool-work-tracker"

    # 1. Installed into the same, single venv -- without the editable install
    #    `import amplifier_module_tool_work_tracker` is a ModuleNotFoundError
    #    and the suite cannot even be collected.
    for path, label in ((MAKEFILE, "Makefile"), (CI_WORKFLOW, ".github/workflows/ci.yml")):
        assert contains(path, f'-e "{module_pkg}[dev]"'), (
            f"CCV1-022 (Freeze Bar, CONFORMS): {label} no longer installs the tool module "
            f"editable into the venv. Without it `import amplifier_module_tool_work_tracker` "
            f"raises ModuleNotFoundError and the suite runs in nothing again -- the exact "
            f"VIOLATION this row closed (work_item_pipeline-a7n)."
        )

    # 2. `make test` runs it, via its own target AND as part of the full run.
    makefile = read(MAKEFILE)
    assert "test-module:" in makefile, (
        "CCV1-022: the `test-module` target is gone from the Makefile"
    )
    assert makefile.count(f"$(PYTEST) {module_pkg}/tests") >= 2, (
        f"CCV1-022: `{module_pkg}/tests` must be run BOTH by the `test-module` target and "
        f"by the all-tiers `test` target -- a target nothing aggregates is a target CI and "
        f"contributors forget."
    )

    # 3. CI runs it as its own step.
    assert contains(CI_WORKFLOW, f"pytest {module_pkg}/tests"), (
        "CCV1-022: CI no longer runs the tool module tests (the `Tier 5 -- tool module "
        "tests` step). The Freeze Bar clause is specifically about CI."
    )

    # 4. The suite it points at still exists and still holds the post-reclaim
    #    custody assertions that made this row the Freeze blocker.
    suite = REPO_ROOT / module_pkg / "tests"
    assert (suite / "test_reap_recovery.py").exists(), (
        "CCV1-022: modules/tool-work-tracker/tests/test_reap_recovery.py is gone -- the "
        "wiring is worth nothing without the tests it wires in."
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
