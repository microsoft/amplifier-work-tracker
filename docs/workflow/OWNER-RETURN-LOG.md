# Owner return log

One entry per return of the intent steward (clock-stamped) or per unprompted brief (date only). Newest last.

## 2026-09-06 08:39 - they came back to a locked contract and switched the session to converge-manager

**Time away.** About eleven hours since you said "looked, ratify." last night; one lock landed in that time (PR #88, the operator-surface contract went FROZEN), and no lanes ran — this cycle was housekeeping, not a wave.

**Finished.** The contract is locked and the ledger agrees with it (I re-ran `pytest ledger/checks` — 60 passed — and `make ledger-mutate` — 69 of 69 mutations still turn their probe red); the stale "pinning" prose on two ledger rows is trued up in this PR (the same two checks re-run green after the edit, and a scan for pin-prose above a green row now finds none); a proposal file for six small wording fixes the external reviewer found is written beside the locked contract and waits for your word; the one remaining code residue (a dead function that keeps one Tier-A check deferred) is filed as a claimable item.

**Stuck.** Nothing stopped — but one question could not be answered on this machine: the contract's Backlogged 4 cites `__init__.py:711`, a file that is nine lines long today, and nobody here knows what the original brief was pointing at, so that pointer is left as-is in the proposal rather than guessed.

**Needs you.** Two words: **ratify** (or "ratified as edited" / "declined") for `contracts/operator-surface.v2-candidate.md`, and **priority** — yes or later — for the Core 10 dead-function item `zhv`, which is a code change on a locked surface and I will not launch a lane for it without your word.

**Anything quietly broken.** The lock's in-session guard did not fire: I edited the frozen contract from this session twice (once in each mode) and both edits went through — I reverted them at once and nothing reached git — because the guard's file patterns are relative to the session's working directory, which here is the multi-repo folder above the repo; the check that runs in CI (the ledger's hash row) does catch such an edit, so the repository was never actually exposed, and I have added the fix to this workspace's settings (active next session) and filed the defect against the converge bundle as `converge-qfi9`.

<details><summary>Technical detail</summary>

- Lock: `contracts/operator-surface.v1.md` `**Status:** FROZEN` @ 279a6ef; OSV1 33 CONFORMS / 3 NOT-ASSERTABLE / 0 GAP / 0 VIOLATION; Freeze 1–10 met (1–7 measurement, 8+10 owner's recorded acts, 9 external review ×2).
- Guard: `hooks-candidate-guard` `normalize_repo_relative(path, cwd)` → `amplifier-work-tracker/contracts/…` ≠ `contracts/*.md`; pure-evaluator proof: cwd=repo → deny, cwd=workspace → continue, `**/`-prefixed globs → deny. Override in `.amplifier/settings.yaml` (workspace).
- This PR: v2 candidate (6 changes, evidence = Freeze 9 review), `lvn` prose repair (OSV1-024/025 + `test_row_osv1_025` docstring), `docs/workflow/{PLAN,OWNER-RETURN-LOG}.md`.
- Queue: `zhv` (Core 10 residual, ready), `1y2` (external), `lvn` (held → resolving on merge).
</details>

## 2026-09-06 13:30 - they came back with the word: "yes" (priority for zhv)

## 2026-09-06 15:14 - they came back with feedback (dashes in project names) and "tackle all of those what's-left items"

**Time away.** About an hour and a half since your feedback; three lanes ran in it and all three landed.

**Finished.** Project names now say their rule where an agent first reads it — every tool's `project` description, the awareness file and the CLI help carry one sentence, and a dash name is refused with the underscore spelling suggested (I re-ran the unit suite on the union: 976 passed; ruff, pyright, ledger 60, mutations 69/69, Tier-A 42/0 all green, recorded in CHECK-RECORD.md); the custody contract's Freeze Bar is measured (Freeze 1–7 met by measurement, 8 is the external review — done, 9 is yours) and its one drift (a row title saying the opposite of its disposition) is fixed; the Backlogged 4 citation turned out to be under-qualified rather than dead — it pointed at the tool module's `__init__.py:711`, which still reads `"custody_lost": held.lost_reason,` today — and a one-change v3 proposal re-anchors it; the guard defect is fixed upstream (amplifier-bundle-converge PR #59, tests 118 → 132) and awaits a maintainer's review.

**Stuck.** Nothing stopped; PR #59 upstream needs a review I cannot give it, and the workspace guard stays toothless until that lands or the bundle cache refreshes.

**Needs you.** Four words, each answerable in one: **ratify** the custody pre-lock true-up (the external review's nine text fixes — listed in the reply); **ratify** operator-surface v3 (one citation); **hold loosely** or **lock** for docs/VISION.md (the reviewer recommends hold loosely until the custody contract is locked, so its governing-contracts line changes once); and for custody Freeze 2, **discharge** (work_release's already-closed branch is the D-6 recovery verb, tested) or **defer**.

**Anything quietly broken.** I found and closed a second hole in the lock: the ratified v2 proposal I left beside the frozen contract after applying it kept the guard's escape hatch open, so an in-place edit of the locked contract was permitted in-session for the past day (CI's hash row still caught any that would have landed; none did) — it is archived now under contracts/applied/, the hatch reads closed, and the upstream defect is filed as converge-wu3y.

## 2026-09-06 18:19 - they came back with the words: "your recommendations are good, go for all" (ratify true-up · discharge · ratify v3 · hold loosely)

**Time away.** About two hours since "go for all"; one lane ran in it and landed, and I redid its last step once.

**Finished.** All four words are applied and on one branch now heading to main: the custody contract carries the reviewer's nine fixes and six nits, names its recovery verb with your word "discharge", and is locked — I re-ran the ledger (60 passed), the mutation harness (69/69), the Tier-A kit (42/0) and the custody fixtures (10 passed) myself and the file's hash matches the ledger's pin; the operator-surface v3 citation fix is applied through the sanctioned path with its proposal archived so the guard's hatch is shut behind it; VISION.md records "hold loosely" with your word and a revisit trigger; the independent reviewer read the final diff and approved (pass 3).

**Stuck.** Nothing stopped; the upstream guard fix (amplifier-bundle-converge PR #59) still waits on a maintainer's review.

**Needs you.** Nothing — no call is open for this repository.

**Anything quietly broken.** The lane's own lock had a defect the reviewer caught before merge: the rewording of §Checks it did for you introduced a false sentence ("there is no check_* function namespace" — there are 44, as doctor checks), and because the file was already stamped FROZEN on the lane's branch I rebuilt the branch from the pre-lock commit, fixed the sentence while the text still read DRAFT, and locked again in one write — nothing false reached main, and the reconcile report records the re-issue; two post-lock proposal candidates the reviewer noted (Freeze 4's wording; "listed below" naming 5 of 32 checks) are queued for a v2 proposal, not silently absorbed.
