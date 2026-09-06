> **ARCHIVED 2026-09-06 (applied).** This proposal was ratified by the owner and applied to `contracts/operator-surface.v1.md` in the custody-lock lane (base main `4c37b16`); the contract's Changelog records it. It is kept here as the record of what was ratified. It was moved out of the `*-candidate.md` name shape because a ratified candidate left beside its target keeps the candidate-guard's escape hatch open indefinitely (measured 2026-09-06; upstream item converge-wu3y).

# Proposal — operator-surface v1, one under-qualified citation re-anchored

```
target: contracts/operator-surface.v1.md
```

**Date:** 2026-09-06
**Author:** agent:lane/custody-freeze-prep (measured on this tree, not transcribed)
**Status:** RATIFIED by owner 2026-09-06 ("your recommendations are good, go for all") — applied to operator-surface.v1.md in the custody-lock lane (base main `4c37b16`)
**Against:** `contracts/operator-surface.v1.md`, Status FROZEN, `main` @ `86cd375`
**Evidence source:** `contracts/operator-surface.v2-candidate.md`, §"Not in this proposal — seen,
and deliberately left out", item 3 — a returned need, plus a false finding that need carries.

---

## What this proposal is

**One change.** Backlogged 4's trigger cites `` `__init__.py:711` `` — a bare filename with no
path, in a repository that contains **eleven** files named `__init__.py`. The citation is not
wrong; it is *unresolvable*, and it has already been resolved wrongly once, on the record, by an
independent drafter.

No promise moves. No clause body moves. No check moves. This repairs a pointer so the next reader
lands on the line the citation was always about.

---

## Change 1 — Backlogged 4: re-anchor the citation to its full path

**Target line (`contracts/operator-surface.v1.md`, Backlogged 4, line 211), quoted verbatim from
the locked file as it reads today:**

> **Trigger:** the owner reports a reclaim they did not see on the web surface. *(Brief A §3, `__init__.py:711`)*

Verified before drafting: this exact string occurs **once** in the locked file
(`grep -c '__init__.py:711' contracts/operator-surface.v1.md` → `1`), so the edit is
unambiguous.

**Before:**

```
**Trigger:** the owner reports a reclaim they did not see on the web surface. *(Brief A §3, `__init__.py:711`)*
```

**After:**

```
**Trigger:** the owner reports a reclaim they did not see on the web surface. *(Brief A §3, `modules/tool-work-tracker/amplifier_module_tool_work_tracker/__init__.py:711`)*
```

The line number is unchanged, because it was measured and is still correct. Only the file is
qualified.

---

### Evidence — a cost already paid, not a preference

**1. The bare citation was resolved to the wrong file, by a careful reader, and the wrong answer
was written down.** `contracts/operator-surface.v2-candidate.md` §"Not in this proposal", item 3,
verbatim:

> **Backlogged 4's own citation `` `__init__.py:711` `` is a dead pointer.** Measured on
> `279a6ef`: `src/amplifier_work_tracker/__init__.py` is **9 lines long**. The reviewer did not
> name this; I found it while verifying Change 6. It is left out because repairing it needs a
> ruling on what it was meant to point at — the reclaim path has moved since Brief A — and
> guessing a pointer is how the Change 5 defect was created in the first place.
> → **Returned as a need:** someone who knows the Brief A §3 reference should say what
> `__init__.py:711` was citing before it can be re-anchored.

That measurement is correct and the conclusion drawn from it is wrong. `src/amplifier_work_tracker/__init__.py`
**is** 9 lines long — re-measured on `86cd375`, still 9. It is simply not the file the citation
means.

**2. The citation is live, and it was live when it was written.** Measured on `86cd375`:

```
$ grep -n "custody_lost" modules/tool-work-tracker/amplifier_module_tool_work_tracker/__init__.py
711:                    "custody_lost": held.lost_reason,

$ sed -n '705,715p' modules/tool-work-tracker/amplifier_module_tool_work_tracker/__init__.py
        with self._lock:
            held = self._held
            holding = (
                {
                    "project": held.project,
                    "id": held.item_id,
                    "custody_lost": held.lost_reason,
                }
                if held
                else None
            )
```

That is `work_status`'s `holding.custody_lost` — precisely the "custody loss reaches the agent
through the tool result" fact Backlogged 4 contrasts against the web surface, and precisely the
signal `contracts/custody-coordination.v1.md` Core 4 and Core 8 name. The clause body one line
above cites `contracts/custody-coordination.v1.md Core 8` in the same breath.

And it was already that line at the commit that authored the citation:

```
$ git show 4aaee50:modules/tool-work-tracker/amplifier_module_tool_work_tracker/__init__.py | sed -n '711p'
                    "custody_lost": held.lost_reason,
```

`4aaee50` is `converge(ENCODE): operator-surface.v1 DRAFT contract + repo vision extended to two
seams (owner-ratified 2026-09-04) (#79)` — the commit that introduced this contract. So the
pointer has never drifted. Only its addressing was ambiguous.

**3. The ambiguity is measurable, not a matter of taste.** Eleven files in this repository are
named `__init__.py`:

```
$ find . -name "__init__.py" -not -path "./.venv/*" | wc -l
11
```

Two of them are plausible homes for a custody signal — `src/amplifier_work_tracker/__init__.py`
(9 lines, a re-export shim) and `modules/tool-work-tracker/amplifier_module_tool_work_tracker/__init__.py`
(2151 lines, the tool seam). A reader who picks the first one gets "dead pointer", which is what
happened.

**The cost, stated plainly:** one drafting cycle spent measuring the wrong file, one false
"dead pointer" finding on the permanent record of a ratified proposal, and one open need returned
to the owner that did not need to exist. Freeze 7's spirit — "every quote a contiguous
substring of the actual code" — is not served by a pointer whose *file* cannot be determined.

**And it is the only one.** The contract cites thirteen distinct in-repo files by
`<file>.py:<line>`: `adapter.py`, `chartsvg.py`, `cli.py`, `__init__.py`, `supervisor.py`,
`_support.py`, `webapp.py`, `webbrowse.py`, `webpush.py`, `webpwa.py`, `webtheme.py`,
`webtrust.py`, `widgets.py`. Counted on `86cd375`, twelve of the thirteen resolve to **exactly
one** file in this repository. `__init__.py` resolves to eleven. That is why this is a one-line
proposal and not a citation-style overhaul: there is one defect, not a policy gap.

---

## What does NOT change

- **Backlogged 4's clause body and its trigger prose.** "the owner reports a reclaim they did not
  see on the web surface" is untouched, word for word. The `*(Brief A §3, …)*` attribution stays;
  only the file inside it is qualified.
- **The line number.** `711` is not a guess — it was measured today and at `4aaee50` and is the
  same line in both.
- **Every other clause.** No Core, Conformance, Reserved, Freeze Bar, Scope, Boundary or Excluded
  text is opened. No other Backlogged clause is opened.
- **Status stays FROZEN.** This is a v1 amendment, not a v2 authoring, exactly as
  `operator-surface.v2-candidate.md` was.
- **No `src/`, no `tests/`, no kit, no `Makefile`, no CI.** Nothing executable moves. Tier A and
  Tier B are unaffected and need no re-run: this changes text a browser cannot see.
- **The custody boundary.** `contracts/custody-coordination.v1.md` is not opened; the citation
  between the two contracts stays one-way.
- **Brief A itself.** Out-of-repo, unquoted here, untouched.

---

## Ledger consequence — one re-hash, zero re-anchors (measured, not predicted)

On ratification, `OSV1-000` must be re-hashed for `contracts/operator-surface.v1.md` and the
mandatory full re-review of all 36 OSV1 rows performed — **never a silent hash bump**
(`LEDGER-FORMAT.md` §4). `OSV1-000` pins two files; only the operator one moves:

| pinned file | today | after |
|---|---|---|
| `contracts/operator-surface.v1.md` | `a1f304b11b17e686…` | re-hash required |
| `contracts/custody-coordination.v1.md` | `ec4b736f8d6dca4e…` | **unchanged** — re-verify byte-for-byte, do not assume |

`CCV1-000` pins `contracts/custody-coordination.v1.md` and `docs/VISION.md`; neither moves, so the
custody family is not disturbed at all.

**No quote needs re-anchoring — verified by walking all 36 OSV1 rows, not inferred from the
proposal's own prediction.** Two independent checks, both run on `86cd375`:

1. **No OSV1 row cites a Backlogged clause.** The 36 rows' `contract.clause` values distribute as
   Core ×19, Freeze ×8, Conformance ×7, Reserved ×1, SYNC ×1. Backlogged: **zero**.
2. **No row's quote overlaps line 211 in either direction.** Every quote-carrying row was
   whitespace-collapsed and tested for containment against the collapsed target line, and the
   target line against each quote. Result: **NONE**.

So the expected outcome of the re-review is *0 rows re-anchored, 0 dispositions changed* — but
**a surviving quote is not a re-review**, so the rows must still be walked, exactly as the v2
amendment walked them and found the same.

**The `OSV1-033` trap, named so it is not tripped.** `test_row_osv1_033` asserts the contract's
`## Changelog` section cites exactly one in-repo file:

```python
cited = {m.group(1) for m in _SOURCE_CITE.finditer(changelog)}
assert cited == {"webapp.py"}
```

`_SOURCE_CITE` is `` r"`([A-Za-z_][A-Za-z_0-9]*\.py):(\d+(?:-\d+)?)`" `` — a backticked bare
`<file>.py:<line>`. Two consequences:

- **The replacement text is safe.** It lives in Backlogged 4, outside the Changelog; and being a
  *path*, the character before `__init__.py` is `/`, not a backtick, so the pattern would not
  match it even if it were inside the Changelog.
- **The ratifying Changelog entry must not write a backticked bare `` `__init__.py:711` ``** (or
  any other non-`webapp.py` `file.py:LINE`) — describe the change in prose, or extend the probe in
  the same change. This is the same trap the v2 amendment named and avoided.

**One more bookkeeping consequence.** Once this lands, `operator-surface.v2-candidate.md`'s
item 3 — "Backlogged 4's own citation is a dead pointer" — becomes a superseded finding. The v2
candidate is a ratified historical record and is **not** edited by this proposal; the reconcile
report's entry for this amendment should say plainly that the need it returned is answered here,
and that its "dead pointer" reading was a mis-resolution rather than a real dead pointer.

---

## Not in this proposal — seen, and deliberately left out

1. **A citation-style rule for the whole contract.** Every other in-repo citation already names a
   unique filename, so a general "always use full paths" rule would be a preference, not a defect,
   and the evidence bar refuses it.
2. **Anything about Backlogged 4's substance.** Whether lost custody *should* be visible on the
   HTML surface, and whether its trigger has fired, are untouched. This is a pointer repair.
3. **Nothing was left out as a preference.** The single change here traces to a named,
   written-down failure in an independent drafting pass, re-measured on `86cd375` before drafting.

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

Ratified by owner — 2026-09-06, literal: "your recommendations are good, go for all".

<!-- end stamp line -->

**Landing a ratified change is a separate, owner-gated step.** This proposal edits nothing. The
locked file is untouched by it.
