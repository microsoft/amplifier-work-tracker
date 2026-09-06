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
