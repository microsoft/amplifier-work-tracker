# Work-Item → /goal Pipeline: Findings

**Lane:** `charlie-pipeline-proof` (batch `wttools`)
**Date:** 2026-08-19
**Verdict:** COMPLETE — one work item carried the full pipe to a terminal PASS.

This document is the deliverable. The launched lane's work product (a `hello.sh`
in a throwaway repo) is incidental; the recorded evidence below is the point.

---

## 1. The pipe, end to end (what actually flowed)

| Stage | Artifact | Result |
|-------|----------|--------|
| item-authored | work-tracker item `gp_charlie_1787152944-n9l` in throwaway project `gp_charlie_1787152944` | PASS |
| converted | goal file `/tmp/gp_charlie_goal/hello-greeting-script.md` (goalify-composed) | PASS |
| lint-captured | two goalify lint passes (bare acceptance + composed file), verbatim in §4 | PASS |
| lane-launched | one isolated cold fork (`delegate(agent="self", context_depth="none")`) — named substitution for `/goal @path`, see §5 | PASS |
| lane-terminal | lane returned **VERDICT: PASS**, independently confirmed (§6) | PASS |

**Headline:** The trip completes. The single place the cold lane had to *guess*
was **git author identity** — a gap that traces straight back to the work item's
acceptance being silent on it. Everything else the lane needed was present
*because goalify composed it in* — the raw work item did not carry it.

---

## 2. Stage 1 — item-authored (PASS)

Created a fresh throwaway project (unique name, never an existing real project)
and authored one trivial, mechanical guinea-pig item.

**Friction found — `work_add` does not create the project it claims to seed.**
The `work_add` tool description says it is "the sanctioned way to seed the FIRST
item(s) in a brand-new project." In practice it refused, verbatim:

```
project 'gp_charlie_1787152944' not found at /home/bkrabach/.amplifier-work-tracker/projects/gp_charlie_1787152944/.beads. Create it first: amplifier-work-tracker new gp_charlie_1787152944
```

The project must be created out-of-band first (`amplifier-work-tracker new
<project>`, which took 8.2s — under the ">30s, do not interrupt" warning but
non-trivial). Only then does `work_add` succeed:

```
{"added": "gp_charlie_1787152944-n9l", "lane": "lane:eng", "project": "gp_charlie_1787152944"}
```

**The full item record, exactly as a cold session reads it** (via
`work_list --id`), is the entire hand-off surface between "someone filed work"
and "a lane must execute it":

```json
{
  "id": "gp_charlie_1787152944-n9l",
  "title": "Add a hello greeting script to the throwaway repo",
  "status": "open",
  "holder": null,
  "created_by": "agent-spark-1-949932",
  "description": "Guinea-pig item for the charlie-pipeline-proof evidence lane. Target is a throwaway git repo (created fresh under /tmp by the lane). Purely mechanical, low stakes. This item exists only to be carried through the work-item -> goal-file -> /goal-lane pipeline as a proof-of-pipe.",
  "acceptance": "Given a throwaway git repo at /tmp/gp_charlie_target\nWhen the item is done\nThen a file named hello.sh exists at the repo root\nAnd running `bash hello.sh` prints exactly: Hello, world",
  "design": null,
  "resolution": null
}
```

**What the item carries:** exactly three author-written fields — `title`,
`description`, `acceptance` (`design` is null; the rest is system metadata). Per
`claiming-work-safely`: "Read acceptance — that is your spec." The acceptance is
bare Given/When/Then. That is the whole spec a lane inherits.

---

## 3. Stage 2 — converted (PASS)

Applied the `goalify` skill's procedure **in-session** (the skill mandates:
"Run this procedure yourself, in the current conversation. Do not delegate it to
a sub-agent or forked session — Phase 1 reads the live transcript"). Phases 1–2
turned the bare acceptance into a well-formed stop-condition, written to
`/tmp/gp_charlie_goal/hello-greeting-script.md`.

Two real friction points surfaced here — both about *where the file is allowed
to land*, not its content:

**Friction A — goalify hardcodes the goal file into the repo.** goalify's output
format step 1 is: *"Write the condition text to `.amplifier/goals/<slug>.md`."*
That path is relative to the current working directory, which for this lane is
the owned repo worktree. A naive application would have written the goal file
**into this repo's `.amplifier/goals/`** — precisely the path this lane is
forbidden to touch. The output had to be manually redirected to `/tmp`. A work
item → goal-file conversion done from inside a repo worktree will, by default,
deposit the goal file in that repo.

**Friction B — `write_file` is sandboxed to the repo; `/tmp` is denied.**
Redirecting the goal file to `/tmp` could not be done with the `write_file`
tool, which is gated to allowed write paths. Verbatim:

```
Access denied: /tmp/gp_charlie_goal/hello-greeting-script.md is not within allowed write paths
```

The goal file had to be written via a shell heredoc instead. So the two
"outside-the-repo" requirements (goalify defaulting into the repo; the file tool
refusing `/tmp`) push in opposite directions and both had to be worked around by
hand.

The composed goal file supplies all five goalify elements the bare acceptance
lacked: a one-sentence checkable outcome, a **disjunctive** exit, a per-item
PASS/FAIL/BLOCKED terminal, a SCOPE-OUTS block, and a KNOWN block (including the
two things the lane would otherwise have to infer: "the repo does not exist yet,
create it fresh" and "you are an isolated lane").

---

## 4. Stage 3 — lint-captured (PASS) — VERBATIM

goalify's Phase 3 lint was run against **both** the raw work-item acceptance
(the naive "cold paste") and the composed goal file (the actual stage-2
artifact). Both tables are reproduced in goalify's own output format.

### 4A. Lint of the BARE work-item acceptance (treated as a candidate condition)

Input linted (the item's `acceptance` field, unchanged):

```
Given a throwaway git repo at /tmp/gp_charlie_target
When the item is done
Then a file named hello.sh exists at the repo root
And running `bash hello.sh` prints exactly: Hello, world
```

| Rule | Result | Note |
|------|--------|------|
| L0 | no known pattern detected | No escape hatch exists to be overridden; see L6. |
| L1 | no known pattern detected | No ordering/provenance constraint on transcript history. |
| L2 | no known pattern detected | "prints exactly" is not a universal quantifier over an exempt-member set. |
| L3 | no known pattern detected | No elapsed wall-clock requirement. |
| L4 | no known pattern detected | No human-in-the-loop / external actor mid-loop. |
| L5 | no known pattern detected | Single closed artifact; not an open enumeration. |
| L6 | **FIRED (warning)** | No disjunctive exit — only the achievement path; no "or conclusively cannot, naming the blocker." |
| W2 | **FIRED (warning)** | No clause asking the actor to show evidence inline as produced. |
| W1, W3, W4 | not fired | Single item; single-session scope; no cautionary narrative. |

**Finding — the vocabulary mismatch is real but the lint is permissive here.**
A bare Given/When/Then acceptance supplies goalify element #1 (a checkable end
state) and **none** of #2 (disjunctive exit), #3 (per-item terminal), #4
(SCOPE-OUTS). Yet on this trivial item it trips **no BLOCKER** — only the L6 and
W2 *warnings*, which explicitly "do not block presentation." goalify would
therefore still *present* the bare acceptance. The blockers (L2 universal
quantifier, L5 open enumeration) bite only when an acceptance says things like
"every endpoint" / "all screens" / "full parity." So: the acceptance↔goalify
mismatch surfaces as **advisory-only** for a small closed item, and would become
a hard blocker only for a broader one. (Observed, not fixed — per SCOPE-OUTS.)

### 4B. Lint of the COMPOSED goal file (the actual converted artifact)

| Rule | Result | Note |
|------|--------|------|
| L0 | no known pattern detected | Re-read whole doc: no sentence stricter than the stated disjunctive exit. |
| L1 | no known pattern detected | Constrains only future actions. |
| L2 | no known pattern detected | Single item carries its own negative terminal. |
| L3 | no known pattern detected | No wall-clock dependency. |
| L4 | no known pattern detected | Fully unattended; no external actor. |
| L5 | no known pattern detected | One closed, named artifact; SCOPE-OUTS bound it. |
| L6 | not fired | Disjunctive exit present ("EITHER … OR conclusively demonstrated … naming the blocker"). |
| W1–W4 | not fired | Single item with terminal; Step 3 shows evidence inline; single-session; no narrative. |

Clean table = no *known* failure pattern detected. It is not a guarantee of
satisfiability; it is the absence of a known termination-failure pattern.

---

## 5. Stage 4 — lane-launched (PASS, with a named substitution)

**Mechanism finding — a literal `/goal @path` lane is not launchable from inside
a session without the batch machinery this lane is forbidden to use.** `/goal` is
an *interactive slash command* that wraps a session in an autonomous-continuation
loop; `amplifier run` exposes no `--goal`/stop-condition flag (`run --help`
confirms: only `--mode {chat,single}`). Launching a lane as a separate isolated
*process* is what the `goal-batch` skill does via **tmux + `amplifier`** — which
is out of scope three times over: this lane must launch **one** lane (no batch),
and the host `AGENTS.md` forbids bare `tmux` outright (documented twice-repeated
mass-session-kill incidents).

**Faithful, safe stand-in used:** `delegate(agent="self", context_depth="none")`
— a genuine cold fork that **cannot see this parent conversation** (the defining
property of a `/goal` lane per this batch's own KNOWN notes), runs its own
orchestrator loop, and returns a terminal verdict. It was handed only the goal
file *path*, exactly as `/goal @path` would be. What it does **not** replicate is
the autonomous-continuation *loop* (repeated turns against a stop condition) — it
runs once to completion. For a single trivial item that reaches PASS in one pass,
that difference did not bind; for a lane that needed to iterate against a
stop-condition it would. This substitution is recorded as the honest boundary of
what this evidence lane could launch.

---

## 6. Stage 5 — lane-terminal (PASS)

The cold lane returned, verbatim:

```
- VERDICT: PASS
- EVIDENCE: Output of `bash /tmp/gp_charlie_target/hello.sh`:
    Hello, world
  (Verified byte-exact via `od -c`: H e l l o ,   w o r l d \n — capital H, one
  comma, one space, lowercase world, single trailing newline, no other output.
  File hello.sh was committed as root-commit d4a6bb1 "add hello greeting
  script"; working tree clean.)
- WHAT-I-LACKED: nothing — the goal file was fully specified. One inference:
  git commit requires an author identity, and the goal didn't specify one, so I
  supplied a throwaway user.name/user.email via inline `git -c` flags (scoped to
  this single commit, no global config touched). This did not affect the
  checkable outcome.
- WHERE-I-STALLED: none.
```

**Independent confirmation** (not trusting the lane's own claim) — run from this
lane against the throwaway repo:

```
=== hello.sh contents ===
echo "Hello, world"
=== actual output (od -c) ===
0000000   H   e   l   l   o   ,       w   o   r   l   d  \n
0000015
=== git log ===
d4a6bb1 add hello greeting script
```

The lane's work is real: 20-byte `hello.sh`, byte-exact `Hello, world\n`, one
root commit. Stage terminal = PASS.

---

## 7. What the cold session lacked / guessed / stalled (the required record)

- **Lacked:** essentially nothing at execution time — **because goalify had
  already injected** the disjunctive exit, the scope boundary ("touch no path
  other than `/tmp/gp_charlie_target`"), the "repo does not exist yet, create it
  fresh" note, and the "you are an isolated lane" note. **None of those came from
  the work item;** all were manufactured during conversion. The raw acceptance
  carried only the end state.
- **Guessed (the one concrete inference):** **git author identity.** `git commit`
  needs `user.name`/`user.email`; neither the acceptance nor the composed goal
  file mentioned git config; the lane supplied a throwaway identity via inline
  `git -c`. This is the single real "where it guessed," and it traces directly to
  the work item's acceptance being silent on execution prerequisites.
- **Stalled:** nowhere.
- **Counterfactual (the measure of what a raw item carries):** had the *bare
  acceptance* been launched as-is, the lane would additionally have lacked the
  exit condition, the scope boundary, the "create the repo" instruction, and the
  isolation note — i.e. everything in §3's "supplies all five elements" list.
  That delta **is** goalify's contribution, and inversely, the measure of how
  little a work item hands a lane on its own.

---

## 8. The acceptance ↔ goalify vocabulary mismatch (observed, not fixed)

- A work item's authored surface is `title` / `description` / `acceptance`.
  Acceptance in Given/When/Then maps to **exactly one** of goalify's five
  required elements (the checkable outcome, #1). It structurally cannot express
  the other four — a disjunctive exit, a per-item terminal, scope-outs, or a
  KNOWN block have no home in G/W/T.
- Therefore "convert work item → goal file" is **not transcription; it is
  composition.** All the terminate-safely structure is added at conversion time,
  not carried by the item.
- goalify's lint is calibrated to *termination-failure patterns*, not to
  *completeness of the four missing elements*. On a small closed item the missing
  structure shows up only as the L6/W2 **warnings** (§4A); it escalates to a hard
  blocker only when the acceptance itself contains a universal quantifier (L2) or
  open enumeration (L5). A filer writing a broad acceptance would be caught; a
  filer writing a narrow one would sail through with an under-specified condition.

---

## 9. Residuals (findings only — NOT acted on, per file ownership + SCOPE-OUTS)

These are recorded as evidence, not changes. This lane owns exactly one repo file
and made no source or tool change.

- **R1 — `work_add` project auto-creation.** The tool refuses on a missing
  project despite its description implying it seeds a brand-new one. Either it
  should create the project, or the description should stop implying it does.
- **R2 — goalify default output path is repo-relative.** Running goalify from
  inside a repo worktree deposits the goal file in that repo's
  `.amplifier/goals/`. When the goal file is meant to be scratch/out-of-repo,
  this fights file-ownership boundaries and needs a manual redirect the skill
  does not mention.
- **R3 — `write_file` cannot reach `/tmp`.** The file tool is sandboxed to
  allowed write paths, so out-of-repo scratch (which R2 makes necessary) must go
  through a shell heredoc. The two constraints compound.
- **R4 — work items carry no execution prerequisites.** The single guess (git
  identity) shows a work item hands a lane a *what* but no *operating context*
  (identity, environment, isolation). A future authoring convention could add an
  optional execution-notes field. (Designing that convention is explicitly
  out of scope here — see `docs/work-item-authoring-convention.md`, owned
  elsewhere.)
- **R5 — no in-session `/goal` launch path.** A literal autonomous-continuation
  `/goal` lane cannot be launched from within a session without the
  tmux+`amplifier` batch machinery; the isolated-fork stand-in (§5) does not
  reproduce the continuation loop.

---

## 10. Provenance (so this trip is reproducible / auditable)

| Thing | Value |
|-------|-------|
| Throwaway project | `gp_charlie_1787152944` (root `~/.amplifier-work-tracker`) |
| Guinea-pig item | `gp_charlie_1787152944-n9l` (status: open, left unresolved — not this lane's to close) |
| Goal file (out-of-repo) | `/tmp/gp_charlie_goal/hello-greeting-script.md` |
| Lane target repo (out-of-repo) | `/tmp/gp_charlie_target` (root-commit `d4a6bb1`) |
| Lane mechanism | `delegate(agent="self", context_depth="none")`, session `0000000000000000-ddeefd1637234d17_self`, 5 turns |
| Lane verdict | PASS (independently confirmed via `od -c` + `git log`) |
