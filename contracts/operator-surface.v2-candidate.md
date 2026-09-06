# Proposal — operator-surface v1, six post-lock text corrections

```
target: contracts/operator-surface.v1.md
```

**Date:** 2026-09-06
**Author:** agent:converge-manager via proposal-drafter
**Status:** PROPOSED — awaiting the owner's word
**Against:** `contracts/operator-surface.v1.md`, Status FROZEN, `main` @ `279a6ef`
**Evidence source:** `.amplifier/converge/operator-surface-freeze9-review.md` — the Freeze 9
external review (independent reviewer, not the author): pass-1 findings 4, 6, 7, 8 and 9, and
pass-2 note 1.

---

## What this proposal is

Six sentence-level corrections to the locked text. Every one of them is a defect an
**independent review of the locked text** found and named — not a preference. None narrows a
promise, none widens a check, and none moves a single line of `src/` or of any kit. Five of the
six make the contract say what the machinery already does; the sixth repairs two triggers that
cannot fire.

Each change below carries: the target line quoted verbatim from the locked file as it reads
today, the exact before/after pair, the evidence, and what does not change.

**Line numbers below were re-measured against `279a6ef` on 2026-09-06.** They drifted after
true-up #2, so the review's own `:NN` pointers no longer land; the quoted bytes are what bind.

---

## Change 1 — Core 1: route the "leads" judgment to a cadence instead of leaving it unchecked

**Target line (`contracts/operator-surface.v1.md`, Core 1 clause body, line 19):**

> The L0 hero region carries throughput over a stated window, presented together with the counts an operator acts on: in flight (held), blocked, needs attention, and open/ready. Observability leads the page; no other figure displaces the hero.

The clause's second sentence is a "leads" judgment. Core 12 declares exactly that class of
judgment undecidable by any check. The Core 1 machine check reaches presence only. So the clause
promises more than anything asserts it, and says nothing about that gap.

**Recommended: route it, do not drop it.** The sentence is the owner's ratified intent
("Focus is on observability", Changelog 2026-09-04). Deleting it would lose the intent to close
a bookkeeping hole. Naming how it is carried keeps the intent and makes the contract honest.

Current text (lines 21–23):

```
**Machine check:** `hero.velocity_and_counts` — the rendered L0 hero region contains a velocity figure with its window stated, and each of the four named counts.

**Tier:** A
```

Replacement:

```
**Machine check:** `hero.velocity_and_counts` — the rendered L0 hero region contains a velocity figure with its window stated, and each of the four named counts. The check reaches presence only; "leads" is not decided by it.

**Tier:** A

**Reviewed at cadence:** the "leads" sentence is the judgment Core 12 names NOT-ASSERTABLE; it is carried by the same owner review of L0/L1/L2, at each `ledger/reconcile-report.md` re-check.
```

**Evidence — a failure caught by review.** Freeze 9, pass 1, finding 4:

> **Core 1 (`:19`)** — "Observability leads the page; no other figure displaces the hero" is
> precisely the "leads" judgment Core 12 (`:153`) declares undecidable by any check. The check
> (`:21`) covers only *presence* of a figure with its window plus four counts. Either drop the
> sentence or route it to Core 12's cadence.

Verified against the locked text: Core 12's machine check reads "none — \"leads\" is a judgment
about what a human reads first, which no static or rendered assertion can decide"
(`contracts/operator-surface.v1.md:153`), and Core 1's check names only a velocity figure and
four counts (`:21`). The two clauses contradict each other as locked.

**What does NOT change.** The clause body (line 19) is untouched, including the "leads" sentence
itself. `hero.velocity_and_counts` is not modified — the added half-sentence describes the check
that already exists. Tier stays A. OSV1-001 quotes line 19 only, so its quote still verifies.

---

## Change 2 — Core 4: put the "growth is not convergent" rule in the clause

**Target line (`contracts/operator-surface.v1.md`, Core 4 clause body, line 55 — final sentence):**

> The register lives in `ledger/`, not in this contract, so that shrinking it is a convergent change requiring no amendment.

The clause states the rule for shrinking and is silent on growth. The rule for growth exists and
is enforced — but only in `ledger/rows.yaml`, OSV1-006's notes. This is the same defect class the
reviewer used to block RC-1 before the lock: *"A ledger note does not travel with a locked
clause."*

Current text (final sentence of line 55):

```
The register lives in `ledger/`, not in this contract, so that shrinking it is a convergent change requiring no amendment.
```

Replacement:

```
The register lives in `ledger/`, not in this contract, so that shrinking it is a convergent change requiring no amendment. Growth is not convergent: a new inline computed-geometry site absent from the register fails the check loudly, and adding it to the register is a deliberate, recorded act, never a silent one.
```

**Evidence — a failure caught by review.** Freeze 9, pass 1, finding 7:

> **Core 4 (`:55`)** says shrinking the exemption register needs no amendment and is silent on
> *growth*. The "an INCREASE fails the probe loudly" rule lives only in OSV1-006's notes. One
> clause sentence closes it.

The rule the reviewer points to, verbatim from `ledger/rows.yaml`, OSV1-006 notes:

> A DECREASE is convergent (shrink the register, let the ledger confirm). An INCREASE — a new
> inline computed site not listed here — fails the probe loudly.

Measured on `279a6ef` by the ledger's own census (`_support.inline_style_sites()`): 55 inline
`style=` sites — 47 token-referencing, 8 computed-geometry, **0 literal**;
`_support.style_block_literal_sites()` returns 0. The register is exactly the 8.

**What does NOT change.** `visual.single_source` is not modified — the added sentence states the
behaviour the probe already has. The register stays in `ledger/`, out of the contract, and no
ceiling constant enters Core (Phase-1 ruling Need 2 is untouched). Shrinking stays convergent.
Backlogged 2's trigger — the register reaching zero — is unaffected. OSV1-005 and OSV1-006 quote
earlier sentences of line 55, so both quotes still verify against the appended paragraph.

---

## Change 3 — Core 5: name the predicate inline, and name the audit's bound (RC-1 residual)

**Target line (`contracts/operator-surface.v1.md`, Core 5 machine check, line 69):**

> **Machine check:** `reads.never_write` — a route audit over every registered handler, asserting the clause's first sentence against each read-only one.

Two problems in one line. First, "the clause's first sentence" has two halves —
*no `GET` handler reaches a mutating adapter call*, and *writes happen only through `POST`* — and
the audit asserts only the first. Second, now that the word "reaches" sits in the clause, the
audit's bound is load-bearing and is stated nowhere in the contract.

Current text:

```
**Machine check:** `reads.never_write` — a route audit over every registered handler, asserting the clause's first sentence against each read-only one.
```

Replacement:

```
**Machine check:** `reads.never_write` — a route audit over every registered handler, asserting of each read-only (`GET`/`HEAD`) one that it reaches no mutating adapter call. The audit is static, module-local, name-matched against the adapter's write verbs, and bounded at depth 4 (`ledger/checks/_support.py:746-800`); it does not reach the clause's second promise, that writes happen only through `POST`.
```

**Evidence — a failure caught by review.** Freeze 9, pass 2, note 1 (the RC-1 residual, recorded
at the moment RC-1 landed):

> **Residual (proposal):** `:69` now says "asserting the clause's first sentence", whose second
> half (writes only via `POST`) the audit never asserts — true on this tree (8 POST-only writers,
> verified) and partly guarded by the 30/22 pin, but under-tested, and less legible than naming
> the predicate inline. That line should also carry the audit's bound (pass-1 finding 6: static,
> module-local, depth-4), now that "reaches" sits in the *clause*.

And pass 1, finding 6:

> **Core 5's audit is narrower than "reaches"** — static, module-local, depth-4, name-matched
> (`ledger/checks/_support.py:746-799`). OSV1-007 names the limit; the contract does not.

Verified in source. `route_audit()` spans `ledger/checks/_support.py:746-800` (the reviewer's
`:799` is one line short of the closing `return audited` at `:800`). It parses each route module
with `ast.parse` (**static**), resolves helpers only from that module's own `funcs` table
(**module-local**), walks `for _ in range(4)` (**depth 4**), and tests `name in MUTATING_VERBS`
(**name-matched**). Its own docstring says so:

> Static and module-local, bounded at depth 4 -- the honest limit is recorded in ledger row
> OSV1-007's notes rather than hidden here.

Re-run on `279a6ef`: 30 routes, 22 read-only, **0** reaching a mutating adapter call.

**What does NOT change.** `route_audit()` and `test_row_osv1_007` are not touched — this line is
brought into agreement with the check that already exists, exactly as RC-1 brought the clause
into agreement with it. The clause body (line 67) is untouched, including the `GET /auth/logout`
exception, so OSV1-007's quote still verifies. The 30/22/0 numbers do not move. Tier stays A.

---

## Change 4 — Core 12 and Core 13: define "ENCODE gate" once, at first use

**Target lines (`contracts/operator-surface.v1.md`, lines 157 and 171):**

> **Reviewed at cadence:** owner review of L0/L1/L2 at each ENCODE gate and before any Freeze stamp, and at each `ledger/reconcile-report.md` re-check.

> **Reviewed at cadence:** owner review at each ENCODE gate and at each `ledger/reconcile-report.md` re-check; promoted by Backlogged 6.

"ENCODE gate" appears four times in the contract (`:157`, `:171`, `:385`, `:386`) and is defined
at none of them. A non-engineer reading the two clauses no machine check carries cannot locate
the event those clauses depend on.

**Recommended: define it, do not replace it.** RC-3 already added the in-repo standing trigger
(`ledger/reconcile-report.md` re-check), so neither cadence is stranded. What is left is a term a
reader cannot resolve. The definition below is phrased from the Changelog's own two uses of it —
`:385` "**ENCODE gate:** owner reviewed the DRAFT text and ratified it", and `:386` "First draft,
authored at the ENCODE gate from Phase-0 evidence".

**Change 4a — Core 12, line 157.** Current text:

```
**Reviewed at cadence:** owner review of L0/L1/L2 at each ENCODE gate and before any Freeze stamp, and at each `ledger/reconcile-report.md` re-check.
```

Replacement:

```
**Reviewed at cadence:** owner review of L0/L1/L2 at each ENCODE gate — the authoring checkpoint at which the owner reads and ratifies drafted contract text, the event this contract's 2026-09-04 Changelog entries record — and before any Freeze stamp, and at each `ledger/reconcile-report.md` re-check.
```

**Change 4b — Core 13, line 171.** Current text:

```
**Reviewed at cadence:** owner review at each ENCODE gate and at each `ledger/reconcile-report.md` re-check; promoted by Backlogged 6.
```

Replacement:

```
**Reviewed at cadence:** owner review at each ENCODE gate (defined in Core 12) and at each `ledger/reconcile-report.md` re-check; promoted by Backlogged 6.
```

**Evidence — a failure caught by review.** Freeze 9, pass 1, RC-3:

> "ENCODE gate" is also never defined anywhere in the contract, which fails "a non-engineer could
> understand it."

Re-affirmed in pass 2, note 3, after RC-3 landed:

> **"ENCODE gate" is still undefined** (`:157`, `:171`, `:385-386`). Acceptable post-lock: each
> cadence now has one trigger a reader can locate in-repo, so neither clause is carried by an
> expired event. Proposal, not blocker.

Verified: `grep -n 'ENCODE' contracts/operator-surface.v1.md` returns exactly those four lines,
and none is a definition.

**What does NOT change.** Both machine-check lines (`:153`, `:167`) are untouched, so OSV1-018's
and OSV1-019's quotes still verify. Both clauses stay NOT-ASSERTABLE; no check is invented for
either. RC-3's standing trigger survives verbatim in both cadences. Backlogged 6's promotion
route from Core 13 is unchanged. The Changelog's own uses of the term (`:385`, `:386`) are not
edited — they are the source the definition is drawn from.

---

## Change 5 — Core 2: re-anchor two drifted evidence pointers

**Target line (`contracts/operator-surface.v1.md`, Core 2 evidence line, line 37):**

> *(Brief A §2, webtheme.py:169-188, webtheme.py:1338; Brief B §5, DESIGN-SYSTEM.md:63-64, DESIGN-SYSTEM.md:66-68)*

Current text:

```
*(Brief A §2, webtheme.py:169-188, webtheme.py:1338; Brief B §5, DESIGN-SYSTEM.md:63-64, DESIGN-SYSTEM.md:66-68)*
```

Replacement:

```
*(Brief A §2, webtheme.py:211-230, webtheme.py:1430; Brief B §5, DESIGN-SYSTEM.md:63-64, DESIGN-SYSTEM.md:66-68)*
```

**Evidence — a failure caught by review.** Freeze 9, pass 1, finding 9:

> **Line citations have drifted.** Core 2 cites `webtheme.py:169-188` for the three status hues;
> those lines are now an `--ink-tertiary`/`--ink-quiet` comment. Freeze 7 verifies *quotes*, not
> `file:line` pointers, so this passes the bar honestly — but it misleads a reader who follows
> the evidence.

**This is a readability defect, not a Freeze 7 break.** Freeze 7 binds quotations, not pointers,
so the contract does not currently lie by its own bar. It does mislead every reader who follows
the citation.

Re-measured on `279a6ef`, and the drift is exactly +42 lines, verified at both ends against the
contract's seed commit `4aaee50`:

| pointer | at `4aaee50` (when written) | at `279a6ef` (today) |
|---|---|---|
| `webtheme.py:169` | `  --alarm:#f59e0b;` | line 211, same bytes |
| `webtheme.py:188` | `  --watch-ink-on-surface:#d6def2;` | line 230, same bytes |
| `webtheme.py:1338` | `   marker + bold weight, never a bespoke third hue. */` | line 1430, same bytes |

Today `webtheme.py:169-188` lands mid-way through the `--ink-tertiary` and `--ink-quiet`
comments, exactly as the reviewer reported. The three status hues now sit at `--alarm:211`,
`--blocked:214`, `--watch:228`, inside the `RESERVED STATUS` block at `:210-231`.

**Measured by this drafter, not named by the reviewer:** the second pointer on the same line,
`webtheme.py:1338`, has drifted the same +42 to `:1430`. It is included because leaving one
correct and one wrong pointer on a single evidence line is worse than either state.

**What does NOT change.** No clause text, no machine check, no tier. The `DESIGN-SYSTEM.md`
pointers are untouched (that file is out-of-repo; nothing in this repo can verify or re-measure
them, and this proposal does not pretend otherwise). `webtheme.py` is not edited — a drifted
pointer is fixed at the pointer, never by moving the code under it. OSV1-002 and OSV1-003 quote
Core 2's clause body, not this line, so both quotes still verify.

---

## Change 6 — Backlogged 2, 4 and 6: figures that drifted, and two triggers that cannot fire

**Target lines (`contracts/operator-surface.v1.md`, lines 193, 209, 225):**

> **Trigger:** the exemption register named in Core 4 reaches zero. *(Brief A §2, "137 `style=` occurrences, 134 of them outside `webtheme.py`")*

> **Trigger:** the first reclaim the owner missed on screen. *(Brief A §3, `__init__.py:711`)*

> **Trigger:** the first alarm-to-acknowledgement measurement exists. *(Brief B §6, wt-v2-poa.md:242-244)*

A Backlogged clause is held behind a trigger; a trigger that cannot be observed holds its clause
forever. Two of these cannot fire, and one cites a figure that is three orders of magnitude off.

**Change 6a — Backlogged 2, line 193.** Current text:

```
**Trigger:** the exemption register named in Core 4 reaches zero. *(Brief A §2, "137 `style=` occurrences, 134 of them outside `webtheme.py`")*
```

Replacement:

```
**Trigger:** the exemption register named in Core 4 reaches zero. *(Brief A §2, at Phase 0: "137 `style=` occurrences, 134 of them outside `webtheme.py`"; measured 2026-09-06 on this tree: 0 literal, 8 computed-geometry sites on the register)*
```

**Change 6b — Backlogged 4, line 209.** Current text:

```
**Trigger:** the first reclaim the owner missed on screen. *(Brief A §3, `__init__.py:711`)*
```

Replacement:

```
**Trigger:** the owner reports a reclaim they did not see on the web surface. *(Brief A §3, `__init__.py:711`)*
```

**Change 6c — Backlogged 6, line 225.** Current text:

```
**Trigger:** the first alarm-to-acknowledgement measurement exists. *(Brief B §6, wt-v2-poa.md:242-244)*
```

Replacement:

```
**Trigger:** an alarm-to-acknowledgement interval is recorded by any means — instrumentation, a log, or the owner timing one by hand. *(Brief B §6, wt-v2-poa.md:242-244)*
```

**Evidence — a failure caught by review.** Freeze 9, pass 1, finding 8:

> **Backlogged triggers 4 and 6 are not observable.** B4 fires on "the first reclaim the owner
> missed on screen" — by construction, a missed thing. B6 fires on "the first
> alarm-to-acknowledgement measurement," which nothing in the repo produces and Core 13 says has
> never been measured. B2 quotes "137 `style=` occurrences, 134 outside `webtheme.py`" — now 0
> literal / 8 computed.

Verified. B4's trigger is self-defeating as the reviewer states: nobody can observe the first
thing the owner *missed*; what is observable is the owner saying afterwards that they missed it.
B6's trigger names a measurement that Core 13 itself says does not exist ("no number is asserted,
because none has been measured") and that no code in this repo emits; as written it can be
satisfied only by the very instrumentation its own clause would govern. B2's figures re-measured
on `279a6ef`: **0 literal, 8 computed** (`_support.inline_style_sites()` → 47 TOKEN / 8 COMPUTED
/ 0 literal; `_support.style_block_literal_sites()` → 0).

**Deviation from the brief this proposal was drafted under, stated plainly.** The instruction was
to "true up B2's numbers". I did not overwrite them. The string "137 `style=` occurrences, 134 of
them outside `webtheme.py`" is a **verbatim quotation of Brief A**, a Phase-0 evidence document
outside this repo. Rewriting the numbers inside the quotation marks would turn a true citation
into a fabricated one — Brief A does not say "0 and 8". OSV1-033 records this exact string as an
out-of-repo honest limit, and its own probe re-measured it as accurate for its time:

> (For the record, the SEED reconcile re-measured Brief A's claim against the tree: 137 total,
> 134 outside `webtheme.py` -- exactly right.)

So the quotation is preserved byte-for-byte and dated, and the current measurement is added
beside it. That closes the misleading-figure defect without breaking a quote. If the owner
prefers the quotation simply deleted, that is a ratify-with-edits away.

**What does NOT change.** Nothing here binds — the Backlogged section's own preamble says
"nothing here binds until then", and these three clauses remain unbound. No trigger is made
*easier* to fire in substance: B4 still needs a real missed reclaim, B6 still needs a real
interval; both are simply now stated as something a person can observe happening. B2's trigger
sentence — "the exemption register named in Core 4 reaches zero" — is untouched, and Brief A's
quotation is byte-identical. No Backlogged clause is promoted into Core by this proposal; that
remains an owner amendment. No ledger row quotes any of these three lines.

---

## What does NOT change — the whole blast radius

- **No `src/` change. No kit change. No probe change.** Nothing in
  `src/amplifier_work_tracker/`, `tests/conformance/`, or `ledger/checks/` is edited by this
  proposal. Every check keeps asserting exactly what it asserts today.
- **No check is widened or narrowed.** Changes 1 and 3 describe existing checks more precisely;
  they do not change what runs. `pytest ledger/checks -q` (60 passed), `make ledger-mutate`
  (69/69), and `make test-conformance-a` (41 passed, 1 xfailed) all keep the results they have
  on `279a6ef`.
- **No promise is removed and no work that keeps a promise is broken.** These are additive
  clarifications and pointer repairs. Nothing here is a new version of the contract.
- **No clause changes tier.** Core 1 stays A, Core 4 stays A, Core 5 stays A, Core 12 and Core 13
  stay NOT-ASSERTABLE.
- **No Core clause body is edited except Core 4's**, which gains one appended sentence. Core 1,
  Core 5, Core 12 and Core 13 keep their clause bodies verbatim; only their machine-check,
  cadence or evidence lines move.
- **No quotation is altered.** Brief A's B2 quotation is preserved byte-for-byte. The Changelog's
  two `webapp.py:37-44` quotations are untouched.
- **The custody boundary is untouched.** `contracts/custody-coordination.v1.md` is not opened;
  the citation stays one-way, as Phase-1 ruling Need 3 settled.
- **Status stays FROZEN.** This proposal does not unfreeze the contract; it is a v1 amendment,
  not a v2 authoring.
- **Conformance 1–7, Reserved 1–6, and the Freeze Bar are untouched.**

---

## Ledger consequence — one line, plus one trap worth naming

On ratification, `OSV1-000` must be re-hashed for `contracts/operator-surface.v1.md` and the
mandatory full-ledger re-review of all 36 OSV1 rows performed — never a silent hash bump — with
the notes of `OSV1-001`, `OSV1-005`, `OSV1-006`, `OSV1-007`, `OSV1-018`, `OSV1-019` and
`OSV1-033` re-reviewed against the moved text.

**Measured, and it differs from what this proposal was briefed to expect: no row's quote needs
re-anchoring.** Checked, not assumed — every one of these six changes was tested against the
quote each affected row actually carries in `ledger/rows.yaml`:

| row | clause | what it quotes | disturbed? |
|---|---|---|---|
| OSV1-001 | Core 1 | clause body, line 19 | no — Change 1 edits `:21` and inserts after `:23` |
| OSV1-002 / -003 | Core 2 | clause body, line 31 | no — Change 5 edits the evidence line `:37` |
| OSV1-005 / -006 | Core 4 | sentences 1 and 2 of line 55 | no — Change 2 appends after sentence 3 |
| OSV1-007 | Core 5 | clause body, line 67 | no — Change 3 edits the machine check `:69` |
| OSV1-018 / -019 | Core 12 / 13 | machine-check lines `:153`, `:167` | no — Change 4 edits the cadence lines |
| — | Backlogged 2 / 4 / 6 | *no row quotes these* | n/a |

A surviving quote is not a re-review, so the notes still need walking — several of them
(OSV1-006's INCREASE rule, OSV1-007's honest limit 2, OSV1-033's out-of-repo B2 paragraph)
describe precisely the text these changes move into the contract.

**The trap.** `test_row_osv1_033` asserts that the **Changelog** cites exactly one in-repo file:

```python
cited = {m.group(1) for m in _SOURCE_CITE.finditer(changelog)}
assert cited == {"webapp.py"}
```

`_SOURCE_CITE` is `` r"`([A-Za-z_][A-Za-z_0-9]*\.py):(\d+(?:-\d+)?)`" `` — any backticked
`<file>.py:<line>` inside the `## Changelog` section. So the ratifying Changelog entry **must not
write `` `webtheme.py:211-230` `` (or any other non-`webapp.py` file:line) in backticks**, or
OSV1-033 goes red on a bookkeeping detail. Describe Change 5 in prose, or extend the probe in the
same change. Core 2's evidence line itself is safe: it lives outside the Changelog and carries no
backticks.

---

## Not in this proposal — seen, and deliberately left out

1. **Core 10's `xfail(strict=True)` — a source change, not a contract change.**
   `test_antigoals_enforced` (`tests/conformance/operator_surface/test_tier_a.py:1108`) is
   `xfail(strict=True)` because `_oldest_ready_item` (`src/amplifier_work_tracker/webapp.py:902`)
   calls `bd.list` with no `limit`. Verified on `279a6ef`: `grep -rn '_oldest_ready_item' src/`
   returns **one** line — its own definition. The function is dead. OSV1-015 reads CONFORMS
   honestly, because Core 10 scores calls "reached from a view" and dead code is not reached from
   a view. The clause is correct as written; **the fix is deleting the dead function**, which
   retires the marker and restores Core 10's unbounded-query conjunct to catching things.
   → **File as a work item: delete `_oldest_ready_item` from `webapp.py` and remove the
   `xfail(strict=True)` marker in the same change.** No contract text is involved.

2. **Kit docstrings still quote pre-RC-2 wording** (Freeze 9, pass 2, note 2: *"Nit: kit
   docstrings still quote pre-RC-2 wording"*). Also a source-side change, in
   `tests/conformance/operator_surface/browser/test_tier_b.py`, not contract text. Named here so
   it is not lost; not drafted here because a contract proposal is the wrong instrument for it.

3. **Backlogged 4's own citation `` `__init__.py:711` `` is a dead pointer.** Measured on
   `279a6ef`: `src/amplifier_work_tracker/__init__.py` is **9 lines long**. The reviewer did not
   name this; I found it while verifying Change 6. It is left out because repairing it needs a
   ruling on what it was meant to point at — the reclaim path has moved since Brief A — and
   guessing a pointer is how the Change 5 defect was created in the first place.
   → **Returned as a need:** someone who knows the Brief A §3 reference should say what
   `__init__.py:711` was citing before it can be re-anchored.

4. **Nothing was left out as a preference.** Each of the six changes above traces to a named
   finding in an independent review of the locked text, and each was re-verified against
   `279a6ef` before being drafted. The one place I departed from the drafting brief — preserving
   Brief A's quotation in Change 6a rather than overwriting its numbers — is argued in that
   section rather than done silently.

---

## The owner's word

One of four: **ratified** · **ratified as edited** · **declined** · **later**.

Write the stamp on the blank line below, **on its own line**, starting at the very beginning of
that line with the word `ratified` and containing `by owner`. The two forms the guard accepts:

- `ratified by owner`
- `ratified as edited by owner`

A stamp written anywhere else, or with anything in front of it on the line, will not unlock
`contracts/operator-surface.v1.md`. If the answer is **declined** or **later**, write that word
instead — the guard will simply not open the file, which is the correct outcome.

Owner's word:

<!-- stamp line — the owner writes on the blank line below this comment; leave it blank otherwise -->

Ratified by owner — 2026-09-06, literal word "Ratified".

<!-- end stamp line -->

**Landing a ratified change is a separate, owner-gated step.** This proposal edits nothing. The
locked file is untouched by it.
