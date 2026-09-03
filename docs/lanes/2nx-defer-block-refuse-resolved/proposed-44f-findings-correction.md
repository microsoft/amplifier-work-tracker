# Proposed correction to `model_performance-44f`'s ai-notes

**Status: PREPARED, NOT APPLIED.** The files live in a different repo
(`/home/bkrabach/dev/openai-evals-team-ci/ai-notes/`, its own `.git`) and in another lane's
directory. This lane's Procedure says *"Never touch other repos"*; the program's lane rule 2 says
*"Write only in your own directory… propose corrections as a diff."* So it is a diff.

## What is wrong

`ai-notes/w3-44f-immutable-resolution/FINDINGS.md` §1.7 — *"Summary table — every sanctioned path
against a closed item"* — line 169:

```
| `work_move` / `work_defer` / `work_block` / `work_dep` | no | status/location only |
```

That row is wrong on **both** counts for `work_defer` and `work_block`. Measured on bd 1.1.2,
2026-09-03, on a throwaway project, first by `model_performance-2nx` and then independently
re-measured by this lane (`evidence/measurement-BEFORE.txt`): against a **resolved** item both
verbs exited 0, moved it out of `resolved`, **and blanked `resolution`**. The full
`block → --clear → claim → resolve` loop then rewrote the official record end to end using only
sanctioned verbs and no `bd` invocation at all.

The consequence for the surrounding argument is not cosmetic. §1.7's own header claim — and the
item's title — is *"a closed item's `resolution` is immutable through every sanctioned path"*.
It was never immutable. It was writable all along: destructively, unaudited, and by accident.
`74w`'s out-of-band `bd reopen` repair was never necessary.

This is also why the defect survived two lanes that were looking straight at it: both tested
`claim`, `resolve`, `edit`, `merge_into` and `release`; neither tested `defer`/`block` against a
CLOSED item.

## Patch 1 — `FINDINGS.md` §1.7

```diff
--- a/ai-notes/w3-44f-immutable-resolution/FINDINGS.md
+++ b/ai-notes/w3-44f-immutable-resolution/FINDINGS.md
@@
 | `work_edit`'s audit comment | no | the only append-only channel; invisible to `resolution` readers |
 | `work_release` | no | refuses by design (`adapter.py:3193-3197`) |
-| `work_move` / `work_defer` / `work_block` / `work_dep` | no | status/location only |
+| `work_move` / `work_dep` | no | status/location only |
+| `work_defer` / `work_block` | **DESTROYS it** | **CORRECTED 2026-09-03 (`model_performance-2nx`).** On a RESOLVED item both exited 0, moved it out of `resolved` AND blanked `resolution` — the already-published text gone, no archive, no trace. `--clear` → `claim` → `resolve` then completes a full, sanctioned rewrite with no `bd` call. Not tested by this lane or by `uma`; both tested claim/resolve/edit/merge_into/release only. **Closed** by the guard in `_set_status_with_reason` (PR on `microsoft/amplifier-work-tracker`, branch `lane/2nx-defer-block-refuse-resolved`); both verbs now fail non-zero with the record untouched, and `doctor` pins it as `defer.refuses_resolved` / `block.refuses_resolved`. |
 | `bd reopen` + claim + resolve | **yes** | works — **but is not exposed by any sanctioned path** |
+
+> **§1.7 HEADER CORRECTION, 2026-09-03.** The claim this table was written to support — *"a
+> closed item's `resolution` is immutable through every sanctioned path"* — is FALSE, and the
+> row above is why. It was never immutable, only unwritable *safely*. The gap `44f` correctly
+> identified is real; its framing was "there is no way to correct a record" when the accurate
+> framing is "the only way that existed was destructive, silent and unaudited." `f5c`'s
+> `reopen` (shipped, `2468a69`) is the safe version of what `defer`/`block` already did by
+> accident; `2nx` closes the unsafe one.
```

## Patch 2 — `RESOLUTION-CORRECTION.md`

Its "Why the lane did not fix it" table carries the same omission and should gain the same row:

```diff
--- a/ai-notes/w3-44f-immutable-resolution/RESOLUTION-CORRECTION.md
+++ b/ai-notes/w3-44f-immutable-resolution/RESOLUTION-CORRECTION.md
@@
 | `work_edit(merge_into=…)` | would **blank** the resolution entirely (`adapter.py:2614-2662`) |
+| `work_defer` / `work_block` | **would have worked — destructively.** Blanked `resolution` at exit 0 on a resolved item, then `--clear` → `claim` → `resolve` rewrote it. Untested by this lane. Corrected and CLOSED by `model_performance-2nx` (2026-09-03); both verbs now refuse. |
 | `bd reopen` + claim + resolve | **works** — and the GOAL forbids it: *"NEVER touch bd directly — work_* tools only."* |
```

The three-command repair recipe in that file is now superseded twice over: `f5c` shipped
`reopen` + `work_reopen` (`2468a69`), so steps 1–2 are `work_reopen` → `work_claim` →
`work_resolve`, runnable by any lane, with the readback comparison making step 3 automatic —
exactly as its own closing section predicted.

## Applied instead, within this lane's authority

`model_performance-44f`'s tracker record: a `design` addendum + title flag via `work_edit`
(attributed, audit-commented). See this lane's `DONE-NOTE.md` for why its `resolution` text
itself was not rewritten.
