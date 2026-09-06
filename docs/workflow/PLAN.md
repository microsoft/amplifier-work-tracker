# Operating picture — amplifier-work-tracker under Converge

Regenerated each manager cycle from the repository's history and the shared queue (project `work_tracker`). Newest cycle last.

## Governing documents
- `contracts/custody-coordination.v1.md` — DRAFT (Freeze 9 = owner ratification still open).
- `contracts/operator-surface.v1.md` — **FROZEN** 2026-09-05 (PR #88 → 279a6ef). Changes only by `contracts/operator-surface.vN-candidate.md`.
- `docs/VISION.md` — DRAFT.

## Landed (from git log, main)
- 2026-09-05 279a6ef converge(FREEZE): operator-surface.v1 FROZEN — owner-ratified true-up #2 (RC-1/2/3), Freeze 8 record, FROZEN stamp; OSV1 SYNC rehash + full re-review (#88)
- 2026-09-05 d039b32 ledger(reconcile): re-check 2026-09-05 after hw-operator-surface — Freeze 5 met by measurement, 0 red Core rows; Freeze Bar reading (#86)
- 2026-09-05 7e43e73 highway(operator-surface) wave 4: calm pixels, swap survival, rendered floors, empty states, CLI isolation — Freeze 5 met (0 red Core rows) (#85)
- 2026-09-05 065da04 highway(operator-surface) wave 3: one source of visual truth — zero literal colour/font/size outside the token module (Core 4) (#84)
- 2026-09-05 6c2e9fa highway(operator-surface) wave 2: Tier-B browser conformance kit + Core 10 fixes (bounded L1 query, theme persists) + integration (#83)
- 2026-09-05 aec9991 highway(operator-surface) wave 1: Tier-A conformance kit + L0 hero = velocity+counts + contrast floor (3 lanes) (#82)
- 2026-09-04 65f0e91 converge(SEED): operator-surface.v1 conformance ledger -- 36 OSV1 rows, 33 probes, 10 items filed (#80)
- 2026-09-04 4aaee50 converge(ENCODE): operator-surface.v1 DRAFT contract + repo vision extended to two seams (owner-ratified 2026-09-04) (#79)

## Cycle 2026-09-06 (manager: this session; owner returned 08:39 UTC)
- Guard probe: an in-place `edit_file` on the FROZEN contract went through in BOTH evaluation and converge-manager modes. Root cause measured with the module's pure evaluator: `hooks-candidate-guard` globs are cwd-relative and this workspace's cwd is the multi-repo root, so `contracts/*.md` never matched `amplifier-work-tracker/contracts/*.md`. Repo-side lock (OSV1-000 SYNC probe) does bite in CI. Workspace override added to `.amplifier/settings.yaml` (`**/contracts/*.md` …), effective next session start; upstream defect filed as `converge-qfi9`.
- Proposal drafted: `contracts/operator-surface.v2-candidate.md` — six post-lock text fixes from the Freeze 9 review (Core 1 route-to-cadence, Core 4 register growth, Core 5 check bound, Core 12/13 "ENCODE gate" defined, Core 2 citations re-anchored, Backlogged 2/4/6 triggers made observable). One need returned: Backlogged 4's `__init__.py:711` pointer is dead and nobody on the machine knows what Brief A §3 cited.
- Repaired in place (clause 8, five-edit class): `work_item_pipeline-lvn` — OSV1-024/025 stale PINNING lead-ins + OSV1-025 probe docstring; dispositions unchanged; ledger 60 passed, harness 69/69.
- Filed: Core 10 residual (dead `_oldest_ready_item`, Tier-A `test_antigoals_enforced` xfail) as a lane-ready item — see queue.
- 2026-09-06T08:52:47Z CALL ratify - contracts/operator-surface.v2-candidate.md needs your word ("ratified" / "ratified as edited" / "declined"). Parked: the v2 amendment + its ledger re-hash. Continued: lvn repair (this PR), Core 10 residual item filed and claimable, converge-qfi9 filed upstream.

## Queue (work_tracker) at this cycle
- ready: `1y2` (external, not this operation) + the Core 10 residual item filed this cycle. Held: `lvn` (this session, resolving on merge).
- Width: 0 lanes running; nothing under width — the only lane-shaped item is the Core 10 residual, held for the owner's priority word since it is a src change on a frozen surface (kit + ledger re-derivation).
- 2026-09-06T13:30:54Z CALL priority ANSWERED "yes" — lane zhv launched (batch hw-post-lock).

## Cycle 2026-09-06 (third wake; owner returned with feedback + "tackle all of those what's-left items")
- Where-you-run: no WORKSPACE-MANIFEST.json here; this multi-repo dir is the operating root (it already holds .converge/feedback). BATCH_DIRs: `.converge/work_tracker` (lanes dash-names, custody-freeze-prep) and `.converge/converge` (lane guard-cwd, repo amplifier-bundle-converge cloned into the workspace). Earlier batches under .amplifier/highway/ predate the rule; left in place (moving is the steward's call).
- Feedback drop `.converge/feedback/2026-09-06-project-names-dashes.md` → became lane **dash-names** (decision: document + actionable refusal with suggested underscore form; NAME_RE unchanged, no silent normalization — the owner said documenting is fine and normalization would create two spellings of one project). Cause measured: adapter.py:211 NAME_RE, tool schemas carry no naming rule, error prints a regex.
- Guard after restart: STILL not biting — the `hooks:` key in workspace settings is not read by the CLI (mounted config unchanged). Key removed; note kept. Fix is upstream → lane **guard-cwd** in amplifier-bundle-converge (converge-qfi9). Until it lands, CI (OSV1-000) is the lock's only teeth in this workspace.
- Backlogged 4 pointer RESOLVED by git archaeology: at 4aaee50, modules/tool-work-tracker/…/__init__.py:711 = `"custody_lost": held.lost_reason,` — the citation was under-qualified, not dead; same key at :711 today. → operator-surface.v3-candidate (one change) drafted by lane custody-freeze-prep.
- Custody lock: lane **custody-freeze-prep** measures Freeze 1–9 + drift check; external review (Freeze 8) delegated read-only; owner's word (Freeze 9) then ONE-write lock.
- VISION.md: reviewer gives LOCK vs HOLD-LOOSELY reading → owner's call.
- Width 3 / 3 lanes live, provably disjoint files (tool module+adapter+awareness+cli | ledger report+v3 candidate | other repo). Deficit 0.
- 2026-09-06T15:18:42Z — no CALL open yet; three will follow when lanes land: ratify (v3 candidate), ratify/priority (custody lock word), priority (VISION lock or hold loosely).
- 2026-09-06T16:42:50Z three lanes landed: guard-cwd (converge PR #59 open, REVIEW_REQUIRED), custody-freeze-prep, dash-names (item filed at integration, resolving on merge). Manager repair: applied v2 candidate archived → hatch closed (measured deny). Second guard defect filed converge-wu3y.
- 2026-09-06T16:42:50Z CALL ratify - custody pre-lock true-up (external review RC-1..9 + lane C4-1..6, one list). Parked: custody lock. Continued: dash-names + custody prep landing in PR.
- 2026-09-06T16:42:50Z CALL ratify - operator-surface.v3-candidate (Backlogged 4 citation). Parked: v3 apply. Continued: same.
- 2026-09-06T16:42:50Z CALL priority - VISION.md: hold loosely (recommended) or lock. Parked: none. Continued: same.
- 2026-09-06T16:42:50Z CALL ratify - custody Freeze 2: discharge D-6 via work_release's already_closed branch, or defer. Parked: custody lock. Continued: same.
