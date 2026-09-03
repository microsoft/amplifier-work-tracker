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
    function_names,
    read,
    row,
    sha256,
)

# The CLI's module docstring is argparse's `description` -- i.e. prose an
# operator reads at `--help`, and the CLI-side twin of `context/awareness.md`'s
# contention contract. Kept local to this module (only CCV1-016 pins it).
CLI = REPO_ROOT / "src" / "amplifier_work_tracker" / "cli.py"


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
    """Core 7 CONFORMS: the close fence is keyed on custody IDENTITY, not on
    the item's status, so it also refuses the released-but-not-yet-re-claimed
    state a reap leaves behind -- while still letting an integrator close an
    item nobody holds.

    Three parts, because each is defeatable alone:

      1. a refusal exists OUTSIDE the `status == "held"` gate -- the gate
         was the whole gap (a reaped item is `open` with its assignee
         cleared, so a status-gated fence skipped exactly the state it
         existed for);
      2. that refusal is reached ONLY when the custody record names THIS
         caller and the item is not theirs -- the identity key is what
         keeps PR #51's integrator resolve unfenced, and what keeps a
         holder's own already-landed close re-attemptable;
      3. the discriminating BEHAVIOURAL fixture exists and still carries
         both halves. This module is in-process only: it proves shape,
         never behaviour (see the module docstring) -- so it verifies the
         fixture's continued existence rather than pretending to be it.

    Body sliced from `resolve_outcome` (the fence moved there, 2026-09-02,
    merging origin/main's PR #67 -- item model_performance-f5c; `resolve`
    itself is now a one-line projection). The pre-write region is
    delimited by the `close` write itself rather than by "the first
    `try:`", because the merged method's OWN pre-write read (the
    already-resolved rule PR #67 added) also opens with a `try:`.
    """
    src = read(ADAPTER)
    body = src[src.index("    def resolve_outcome(") : src.index("    def _read_back_or_none")]
    pre_write = body[: body.index('p = self._run(["close"')]
    gate = 'current.status == "held":'
    assert gate in pre_write, "Core 7: the held-item fence disappeared entirely"

    identity_fence = "            elif cust_holder == who and current.holder != who:"
    assert identity_fence in pre_write, (
        "Core 7: the status-independent, custody-identity-keyed fence changed shape. "
        "A close by the session the custody record still names must be refused even "
        "when the item is no longer `held` (the post-reclaim state)."
    )
    fences = [m.start() for m in re.finditer(r"raise FencedError", pre_write)]
    assert any(pos > pre_write.index(identity_fence) for pos in fences), (
        "Core 7: the post-reclaim branch no longer raises FencedError -- a refusal that "
        "is not a FencedError does not clear the caller's local custody state"
    )
    assert "not held by this session" in pre_write, (
        "Core 7: the refusal must still name 'not held by this session' -- the wording "
        "the contract's own `fence.close_post_reclaim` machine check specifies"
    )

    fixture = REPO_ROOT / "tests" / "integration" / "test_post_reclaim_fence.py"
    assert fixture.exists(), f"Core 7: the discriminating fixture {fixture.name} is gone"
    names = function_names(fixture)
    for half in (
        "test_stale_holder_close_is_refused_after_a_real_reap",
        "test_stale_holder_close_is_refused_after_release_without_reclaim",
        "test_integrator_close_of_a_reclaimed_item_still_succeeds",
    ):
        assert half in names, (
            f"Core 7: {fixture.name} no longer carries {half} -- both halves must stay "
            f"measured together, or a fix to one silently trades away the other"
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
    "reopen",  # added 2026-09-02 merging origin/main's PR #67
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

    `reopen` (item model_performance-f5c, merged 2026-09-02 from
    origin/main's PR #67) joined this list on arrival rather than shipping
    with its own bespoke inline shape: it carries TWO verified writes (the
    `bd reopen` itself, and the conditional stale-assignee clear), both
    routed through this same helper -- see that method's own docstring for
    why the assignee clear needed it too (a bare unverified `_run` call
    there previously could not recover from a conflict once the reopen
    itself had already landed).
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
    assert count(ADAPTER, "_read_back_or_none") == 5, (
        "CCV1-015: `_read_back_or_none`'s call sites moved (expected 1 definition + "
        "resolve's conflict branch + release's verify + reopen's two verifies -- the "
        "main write and the stale-assignee clear). Re-check that every verb still "
        "verifies before adjusting this count."
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
    """Freeze 3 CONFORMS: all four Conformance fixtures exist as
    discriminating good/bad pairs, in files the already-wired test paths
    collect, with nothing quietly disabled -- AND the contract's own four
    Test-location lines actually name those real paths.

    Source-level on purpose (this ledger is in-process only -- no bd, no
    dolt, no subprocess), so this probe asserts the things a static check
    honestly CAN: the fixture files exist, each fixture contributes real
    test functions, no half is marked `xfail`/`skip`, and the contract text
    names the real paths rather than the four that never existed. That the
    fixtures actually PASS is measured by running them (`make test-module`
    / CI Tier 5) and recorded in the row's notes -- see CCV1-020 on why a
    probe is never the behavioural proof.

    That those paths are RUN at all is CCV1-022's clause, asserted by
    `test_row_ccv1_022` (venv install + `test-module` target + `make test`
    aggregation + the CI step). Not restated here: two rows asserting the
    same wiring is how one of them silently stops meaning anything.

    Part 5 below USED TO pin the contract's four stale Test-location lines
    on purpose (a recorded-but-not-fixed drift). The 2026-09-03 owner-
    ratified DRAFT amendment fixed that drift for real, so part 5 no longer
    pins anything -- it is a genuine conformance check now, same as parts
    1-4, and its expected flip direction is REGRESSION (a stale line
    returning), not VIOLATION-MOVEMENT.
    """
    module_suite = REPO_ROOT / "modules" / "tool-work-tracker" / "tests"
    fixtures_2_3_4 = module_suite / "test_conformance_fixtures.py"
    fixture_1 = REPO_ROOT / "tests" / "integration" / "test_phantom_conflict_recovery.py"

    # 1. Fixture 1 (conflicted-but-landed close) -- already existed when this
    #    row was opened; only the contract's pointer at it was ever wrong.
    assert fixture_1.exists(), (
        "CCV1-023 (Freeze Bar, CONFORMS): tests/integration/test_phantom_conflict_recovery.py "
        "is gone -- Fixture 1 has no home again."
    )

    # 2. Fixtures 2-4 live at the agent seam the contract writes them against
    #    (work_resolve / work_status / work_claim), i.e. the tool module's
    #    own suite -- the only suite that can exercise `WorkTrackerSession`.
    assert fixtures_2_3_4.exists(), (
        "CCV1-023 (Freeze Bar, CONFORMS): "
        "modules/tool-work-tracker/tests/test_conformance_fixtures.py is gone -- "
        "Conformance Fixtures 2, 3 and 4 are back to being unimplemented "
        "(the GAP work_item_pipeline-qmj closed)."
    )

    # 3. Each fixture contributes real, separately-named tests. Two apiece is
    #    the floor a good/bad PAIR requires: a fixture reduced to one test has
    #    stopped discriminating, which is the failure mode this row exists for.
    names = function_names(fixtures_2_3_4)
    for fixture, subject in (
        ("2", "post-reclaim close fence"),
        ("3", "in-process recovery after reclaim"),
        ("4", "single-hold constraint"),
    ):
        halves = sorted(n for n in names if n.startswith(f"test_fixture{fixture}_"))
        assert len(halves) >= 2, (
            f"CCV1-023: Conformance Fixture {fixture} ({subject}) has {len(halves)} test(s) "
            f"in {fixtures_2_3_4.name} -- a fixture is a good/bad PAIR, and one half alone "
            f"passes against the broken implementation too. Found: {halves}"
        )

    # 4. Nothing quietly disabled. An xfail'd or skipped half is a fixture
    #    that is not "passing" in the Freeze Bar's sense, and the row would
    #    have to say so; failing here forces that conversation.
    tree = ast.parse(read(fixtures_2_3_4))
    disabled = [
        f"{node.name} ({ast.unparse(dec)})"
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        for dec in node.decorator_list
        if re.search(r"\b(xfail|skip|skipif)\b", ast.unparse(dec))
    ]
    assert not disabled, (
        f"CCV1-023: a Conformance fixture half is disabled: {disabled}. The Freeze Bar "
        f"clause is 'implemented, PASSING, and executable via make test' -- flip this row "
        f"off CONFORMS and name the disabled half before landing that."
    )

    # 5. DISCHARGED 2026-09-03: the contract's four "Test location" lines
    #    used to name files that had never existed; the owner-ratified DRAFT
    #    amendment corrected all four to the real paths above and dropped
    #    their "(to be added)" / "(currently unrun in CI)" qualifiers. This
    #    now asserts the CORRECTED lines are present and the stale ones
    #    (and their status qualifiers) are gone -- a regression back to any
    #    of them is exactly the drift this row once had to just record.
    assert contains(
        CONTRACT_PATH, "**Test location:** `tests/integration/test_phantom_conflict_recovery.py`."
    ), "CCV1-023: Fixture 1's corrected Test-location line is gone"
    assert contains(
        CONTRACT_PATH,
        "**Test location:** `modules/tool-work-tracker/tests/test_conformance_fixtures.py` "
        "(tool seam) and `tests/integration/test_post_reclaim_fence.py` (adapter layer).",
    ), "CCV1-023: Fixture 2's corrected Test-location line is gone"
    assert (
        count(
            CONTRACT_PATH,
            "**Test location:** `modules/tool-work-tracker/tests/test_conformance_fixtures.py`.",
        )
        == 2
    ), "CCV1-023: Fixtures 3 and 4 must each still point at test_conformance_fixtures.py"
    for stale in (
        "tests/test_incident_b.py",
        "tests/test_reap_recovery.py:67-72",
        "tests/test_recovery.py",
        "tests/test_single_hold.py",
        "(to be added)",
        "(currently unrun in CI)",
    ):
        assert not contains(CONTRACT_PATH, stale), (
            f"CCV1-023 regression: the contract names a stale, never-existed path or status "
            f"qualifier again ({stale!r})."
        )
