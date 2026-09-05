# Operator Surface Contract — v1

**Status:** DRAFT

**Scope:** This contract governs the operator surface of amplifier-work-tracker: the human web surface one operator watches — L0 Mission Control (`GET /`), L1 Project Observatory (`GET /projects/{name}`), L2 Item Detail (`GET /projects/{name}/items/{id}`), the login, `/setup` and `/trust` onboarding pages, and the PWA shell. Its consumer is a human outside this repo's own commits; a silent change breaks trained perception, and that dependence is what makes it a seam. *(Brief A §1, webapp.py:4551, webbrowse.py:287, webbrowse.py:611; Brief B §8)*

**Boundary.** Custody semantics through the tool seam belong to `contracts/custody-coordination.v1.md`; presentation of those facts to a human belongs here. Where this surface renders custody it depends on `contracts/custody-coordination.v1.md Core 8` and `contracts/custody-coordination.v1.md Core 14`, cites them by identifier, and restates neither.

**Excluded.** The adapter firewall — all bd/dolt knowledge confined to `amplifier_work_tracker.adapter` — is machine-enforced elsewhere, not restated here: see `docs/widget-contract.md`. The agent tool-result surface, the CLI, dolt-ops internals, project semantics, work-item filtering, and scheduling heuristics are out of scope.

---

## Core Clauses

These are the frozen invariants of the operator surface. Each carries a machine check and the tier that runs it: **Tier A** is an in-process static, HTML, or token assertion; **Tier B** is a real-browser assertion whose emitted artifacts are re-checked by the orchestrator, never a rendered verdict; **NOT-ASSERTABLE** is named as such and reviewed at cadence.

### Core 1: The L0 hero is fleet velocity, with the counts that matter

The L0 hero region carries throughput over a stated window, presented together with the counts an operator acts on: in flight (held), blocked, needs attention, and open/ready. Observability leads the page; no other figure displaces the hero.

**Machine check:** `hero.velocity_and_counts` — the rendered L0 hero region contains a velocity figure with its window stated, and each of the four named counts.

**Tier:** A

*(Brief A §1, webapp.py:4602, webapp.py:4611-4641, webapp.py:4647)*

---

### Core 2: Status colour is a closed set, and a calm screen shows none of it

The token set defines exactly three status hues — `--alarm`, `--blocked`, `--watch`. Only `--alarm` and `--blocked` carry status meaning; no bespoke hue is introduced outside the set. On a calm screen — nothing held past TTL, nothing blocked — zero `--alarm` and zero `--blocked` pixels are painted; that absence is what makes the alarm pop.

**Machine check:** `palette.status_hue_set` — the token block declares exactly the three hues and no other status hue is defined; `calm.zero_alarm_pixels` — a rendered calm fixture, swept pixel-wise in both themes, contains no `--alarm` or `--blocked` colour.

**Tier:** A and B

*(Brief A §2, webtheme.py:169-188, webtheme.py:1338; Brief B §5, DESIGN-SYSTEM.md:63-64, DESIGN-SYSTEM.md:66-68)*

---

### Core 3: State is never colour-only

Every element carrying a state carries it in text as well as hue — a status chip has a word, not only a class. Colour is redundant encoding, never the only encoding.

**Machine check:** `state.not_colour_only` — every status-bearing element in the rendered L0/L1/L2 fixtures has non-empty text or an accessible name, not merely a status class.

**Tier:** A

*(Brief B §5, DESIGN-SYSTEM.md:69; Brief A §3, webbrowse.py:139-152)*

---

### Core 4: One source of visual truth

Literal colour, font, or size in an inline `style=` attribute, or in a `<style>` block outside the token module (`webtheme.py`'s token block), is a violation; zero are tolerated. Computed geometry in an inline `style=` — a bar width, a chart offset — is permitted only for sites enumerated on the exemption register. The register lives in `ledger/`, not in this contract, so that shrinking it is a convergent change requiring no amendment.

**Machine check:** `visual.single_source` — zero inline `style=` attributes carrying a literal colour, font, or size anywhere in `src/`; every inline `style=` site carrying computed geometry appears on the ledger's exemption register; and zero literal colour/font/size declarations in any `<style>` block outside the token module.

**Tier:** A

*(Brief A §2, webtheme.py:87, webtrust.py:258-259, webpwa.py:121-122; Brief A "Measured facts" 3-4)*

---

### Core 5: Reads never write

No `GET` route mutates state. The surface may poll itself aggressively; it writes only through explicit operator actions, which are `POST`.

**Machine check:** `reads.never_write` — a route audit over every registered handler: no `GET` handler reaches a mutating adapter call.

**Tier:** A

*(Brief B §5, wt-v4-observatory/BRIEF.md:65-66; Brief A §1, webapp.py:4780-4875)*

---

### Core 6: Every view survives its own body-swap — including what was announced

The self-poll replaces the body of a live page. Scroll position, every open `<details>`, and the pause control's state survive that swap, and an assistive-technology announcement pending at the moment of the swap is not silently destroyed by it.

**Machine check:** `swap.survives` — force a body-swap on L0 and L1 with the page scrolled, a `<details>` open, and the poll paused; the post-swap DOM snapshot shows scroll offset, disclosure state, and pause flag preserved, and the live region present and announcing.

**Tier:** B

*(Brief A §4, webapp.py:129, webapp.py:648-656; Brief B §7, GAUNTLET-SYNTHESIS.md:215-222; Phase 1 minutes evidence correction, webapp.py:1211, webapp.py:1507, webapp.py:4213)*

---

### Core 7: Perception floors are measured, not asserted

Text contrast is at least 4.5:1 and non-text contrast at least 3:1, in both themes; interactive targets are at least 44px; and `prefers-reduced-motion` is honoured by one kernel-level rule rather than per-widget opt-in, so no animation runs under the preference.

**Machine check:** `perception.floors` — token-pair relative-luminance math over the declared token set, plus a browser run emitting computed contrast ratios, target bounding boxes, and a motion-preference trace at 430, 900, and 1280px in both themes; the orchestrator re-checks those numbers against the floors.

**Tier:** A and B

*(Brief B §5, DESIGN-SYSTEM.md:73-74, DESIGN-SYSTEM.md:77-79, frame.md:59; Brief A §6, webtheme.py:278, webtheme.py:2162; Brief B §3, critique/findings.md:17-18)*

---

### Core 8: Calm is reported, never celebrated; empty states keep their slot

The calm state is stated plainly and never rendered as a triumphant zero. A widget with nothing to show keeps its slot and says so in a sentence, so the page does not reflow between calm and alarm.

**Machine check:** `calm.keeps_slot` — against an all-empty fixture, every widget region present on the populated fixture is present, each carries its empty sentence, and no numeral renders at hero scale outside the Core 1 hero.

**Tier:** A

*(Brief B §5, dash-v2/NOTES.md:119-127; Brief A §3, widgets.py:423, widgets.py:433, webapp.py:2275, chartsvg.py:295)*

---

### Core 9: No JS framework, template engine, build step, or plugin loader

The surface is server-rendered HTML composed in Python, with small inline scripts and no client-side layout engine, asset pipeline, dashboard builder, plugin loader, CMS, or public widget API.

**Machine check:** `deps.no_framework` — the dependency manifest declares no front-end framework, bundler, or template engine, and the repo contains no build step producing served assets.

**Tier:** A

*(Brief B §5, webapp.py:22-24, wt-v2-poa.md:257-259)*

---

### Core 10: The anti-goals hold

No kanban drag-board — its central gesture fights machine-owned custody. No client-side state that dies on refresh. No new chart library or JS dependency. No unbounded query behind a view.

**Machine check:** `antigoals.enforced` — the dependency manifest declares no charting or drag-and-drop library; every adapter call reached from a view passes an explicit limit; no view holds state that does not survive a refresh (state persisted in `localStorage` or on the server survives; state held only in page memory does not).

**Tier:** A

*(Brief B §5, wt-v4-observatory/BRIEF.md:82-88; Brief B §7, wt-v2-poa.md:147-151)*

---

### Core 11: Push fires on a custody-TTL breach only; calm is silent

The push channel carries exactly one event class: a sweep reclaiming custody after a TTL breach. No other condition sends a notification, and calm sends nothing at all.

**Machine check:** `push.alarm_only` — exactly one call site fires the push channel, and it is the reclaim path; no other code path reaches the sender.

**Tier:** A

*(Brief A §4, supervisor.py:156, webpush.py:372-373; Brief B §2, docs/ntfy-alarm-channel.md:54-59)*

---

### Core 12: Forms never lead a page

A page's leading content is what the operator came to see, not a form to fill in. Actions live in disclosures and drawers below the information they act on.

**Machine check:** none — "leads" is a judgment about what a human reads first, which no static or rendered assertion can decide. Named NOT-ASSERTABLE rather than approximated by a proxy.

**Tier:** NOT-ASSERTABLE

**Reviewed at cadence:** owner review of L0/L1/L2 at each ENCODE gate and before any Freeze stamp.

*(Brief B §5, wt-v4-observatory/BRIEF.md:82-88)*

---

### Core 13: Alarm-to-acknowledgement is the outcome this surface is judged by

The surface exists so the time between an alarm appearing and the operator acknowledging it stays short. That interval is the outcome measure; no number is asserted, because none has been measured.

**Machine check:** none — no baseline or target for time-to-notice or time-to-act has been measured, and a number invented in place of one cannot ratchet. Named NOT-ASSERTABLE rather than proxied by a gameable substitute.

**Tier:** NOT-ASSERTABLE

**Reviewed at cadence:** owner review at each ENCODE gate; promoted by Backlogged 6.

*(Brief B §6, wt-v2-poa.md:242-244, wt-v4-observatory/BRIEF.md:109-118)*

---

## Backlogged Clauses

Candidate clauses, each held behind a named trigger. A trigger firing promotes the clause into Core by amendment; nothing here binds until then.

### Backlogged 1: Glass sits behind data, never on data

Gloss, gradient, and glass belong to the chrome vocabulary — a panel may be glass, the text and marks on it may not.

**Trigger:** the owner arbitrates the chrome-scope split — six design lenses call it P0 systemic integrity, the human-advocate lens argues flat panels can carry better contrast for low vision. *(Brief B §3, wt-v3-council-synthesis.md:122-124; Brief B §5, DESIGN-SYSTEM.md:59-62)*

---

### Backlogged 2: No inline `style=` at all

Every inline `style=` attribute is a violation, computed geometry included.

**Trigger:** the exemption register named in Core 4 reaches zero. *(Brief A §2, "137 `style=` occurrences, 134 of them outside `webtheme.py`")*

---

### Backlogged 3: `supersedes` has a dedicated rendering

A `supersedes` edge is rendered as its own relation rather than falling into the generic other-links bucket.

**Trigger:** the first `supersedes` edge appears in real data. *(Brief A §3, adapter.py:152, cli.py:1207)*

---

### Backlogged 4: Lost custody is visible on the HTML surface

A custody loss is legible to the operator on the web surface, not only through the agent tool result described by `contracts/custody-coordination.v1.md Core 8`.

**Trigger:** the first reclaim the owner missed on screen. *(Brief A §3, `__init__.py:711`)*

---

### Backlogged 5: Push carries a second event class

The push channel broadens past the custody-TTL breach frozen in Core 11.

**Trigger:** the owner ratifies a specific second event class. *(Brief B §7, docs/ntfy-alarm-channel.md:104-109)*

---

### Backlogged 6: A target number for alarm-to-acknowledgement

Core 13's outcome acquires an asserted threshold and a probe.

**Trigger:** the first alarm-to-acknowledgement measurement exists. *(Brief B §6, wt-v2-poa.md:242-244)*

---

### Backlogged 7: Attention-ranking weights are governed

The order of the ranked attention queue becomes a governed promise rather than an unadjustable server-side hypothesis.

**Trigger:** ranking-engagement instrumentation exists. *(Brief B §7, GAUNTLET-SYNTHESIS.md:207-211, GAUNTLET-SYNTHESIS.md:229-233)*

---

### Backlogged 8: Widget arrangement is governed

Layout and density become operator-arrangeable under a governed rule.

**Trigger:** the owner's own "I keep wanting to hide X" moment. *(Brief B §7, wt-v2-poa.md:203-204)*

---

## Conformance

Each fixture is a discriminating pair: a good input the check passes, a bad input the same check fails. Tier-A fixtures are static or rendered-HTML inputs; Tier-B fixtures run in a pinned chromium and emit artifacts — pixel sweeps, contrast numbers, bounding boxes, post-swap DOM snapshots — the orchestrator re-checks itself. An impression of a page is never a pass.

Tier-A-checkable Core clauses: 1, 3, 4, 5, 8, 9, 10, 11, and the token half of 2 and 7. Tier-B-only: 6, and the rendered halves of 2 and 7. Core 12 and 13 are NOT-ASSERTABLE and carry no fixture.

### Conformance 1: Calm render carries no alarm colour

**Scenario:** L0 and L1 rendered against a fixture with nothing held past TTL and nothing blocked, swept pixel-wise in both themes.

**Good:** the sweep reports zero pixels matching `--alarm` or `--blocked`.

**Bad:** the same page with the retired-palette region reinstated — a hardcoded amber outside the token set — is reported as alarm-coloured pixels on a calm page.

**Test location:** `tests/conformance/operator_surface/browser/test_tier_b.py` (Core 2).

---

### Conformance 2: Alarm render is unmissable and never colour-only

**Scenario:** the same fixture with one item held past TTL and one blocked.

**Good:** the alarm region is present, its hue is `--alarm` or `--blocked`, and every status-bearing element also carries a word.

**Bad:** a fixture whose status chips carry only a status class fails the accessible-name assertion.

**Test location:** `tests/conformance/operator_surface/test_tier_a.py` (Core 3), `tests/conformance/operator_surface/browser/test_tier_b.py` (Core 2).

---

### Conformance 3: Body-swap survival

**Scenario:** L0 loaded in a real browser, scrolled, one `<details>` opened, the poll paused; a body-swap is forced.

**Good:** the post-swap DOM snapshot preserves scroll offset, the open disclosure, and the pause flag, and the live region survives to announce.

**Bad:** a whole-body innerHTML replacement that recreates the region loses all four; the snapshot shows offset zero, the disclosure closed, the pause flag cleared, and a fresh live region with nothing announced.

**Test location:** `tests/conformance/operator_surface/browser/test_tier_b.py` (Core 6).

---

### Conformance 4: Viewport sweep at 430, 900, and 1280px

**Scenario:** L0, L1, and L2 loaded at each viewport in both themes.

**Good:** `scrollWidth == clientWidth` at every viewport, every interactive target measures at least 44px, and computed text contrast is at least 4.5:1.

**Bad:** a fixture with a fixed-width element wider than 430px emits `scrollWidth > clientWidth`; a fixture using the recorded 4.27:1 ink pair emits a contrast number below the floor.

**Test location:** `tests/conformance/operator_surface/browser/test_tier_b.py` (Core 7).

---

### Conformance 5: Hero composition

**Scenario:** L0 rendered against a populated fixture.

**Good:** the hero region contains a velocity figure with its window stated and each of in flight, blocked, needs attention, and open/ready.

**Bad:** a hero carrying only a verdict line, or a figure without the four counts, fails the assertion naming what is missing.

**Test location:** `tests/conformance/operator_surface/test_tier_a.py` (Core 1).

---

### Conformance 6: Inline-style register

**Scenario:** a static pass over `src/` plus the ledger's exemption register.

**Good:** zero inline `style=` attributes carry a literal colour, font, or size; every computed-geometry site is on the register.

**Bad:** a file carrying `style="color:#D9A253"` is reported as a literal-colour violation, and a computed-geometry site absent from the register is reported as unregistered.

**Test location:** `tests/conformance/operator_surface/test_tier_a.py` (Core 4).

---

### Conformance 7: Empty states keep their slot

**Scenario:** L0 and L1 rendered against an all-empty fixture and against a populated one.

**Good:** every widget region present on the populated render is present on the empty render, each carrying its empty sentence.

**Bad:** a render that drops empty widgets, or renders a hero-scale `0`, fails on the missing region or on the numeral.

**Test location:** `tests/conformance/operator_surface/test_tier_a.py` (Core 8).

---

## Reserved

Namespaces explicitly held. Nothing here is promised; acquiring one is a visible amendment, not drift.

**Reserved 1:** `list`/`status`/`instances` `--json` output shapes — namespace held, ungoverned. **Trigger:** the first parse of `--json` output by a caller outside this repo's own commits. On trigger, `cli-json.v1` is authored as its own contract and taken through the Freeze Bar; it does not enter this contract.

**Reserved 2:** the agent tool-result surface — governed where it is governed at all by `contracts/custody-coordination.v1.md Core 8` and `contracts/custody-coordination.v1.md Core 14`; it does not enter this contract.

**Reserved 3:** a machine-readable data API for this surface — namespace held. This contract's seam reading rests on there being no machine consumer of the rendered pages, so shipping one is an amendment, never drift.

**Reserved 4:** multi-user scoping, identity, and "my queue" — this contract governs a personal tool. **Trigger:** the owner ratifies a shared or hosted team instance.

**Reserved 5:** configurability — held at "layout and density freedom, never palette or motion"; nothing configurable is promised.

**Reserved 6:** an agent-detail page as a fourth IA level — namespace held; L0 and L1 agent rows are not promised a destination.

---

## Freeze Bar

Before this contract moves from DRAFT to FROZEN, all of the following conditions must be satisfied.

**Freeze 1:** the Tier-A kit exists at `tests/conformance/operator_surface/test_tier_a.py` and runs on every pull request.

**Freeze 2:** the Tier-B kit exists at `tests/conformance/operator_surface/browser/test_tier_b.py`, drives a pinned chromium against a live app with isolated fixture data, and runs as its own CI tier.

**Freeze 3:** every Tier-B check emits artifacts the orchestrator re-checks itself; no check reports a rendered impression as a pass.

**Freeze 4:** every Conformance fixture discriminates: its bad half fails against the defect it names, demonstrated by running it.

**Freeze 5:** every Core clause reads CONFORMS in `ledger/`, or is NOT-ASSERTABLE with its review cadence named here.

**Freeze 6:** the exemption register named in Core 4 is complete in `ledger/` — every computed-geometry inline-style site enumerated, and no literal colour, font, or size site remaining.

**Freeze 7:** every quote in this contract is verified as a contiguous, whitespace-collapsed substring of the file it cites.

**Freeze 8:** the owner has looked at the rendered L0, L1, and L2 at 430, 900, and 1280px in both themes, and that look is recorded in the Changelog as a ratification input, never a machine check.

**Freeze 9:** pull-request review of this contract by an external reviewer, not its author.

**Freeze 10:** owner ratification and signature ("FROZEN" stamp in a dated Changelog entry).

---

## Changelog

- **2026-09-04 — DRAFT true-up #1,** owner-ratified ("yep, do it all."): Core 4 widened to reach per-page `<style>` blocks outside the token module (evidence: `webtrust.py`'s hardcoded retired palette); Core 10's machine-check wording aligned to the clause ("does not survive a refresh"); the Changelog's `webapp.py:38-39` quotation made byte-exact (Freeze 7). Status remains DRAFT.
- **2026-09-04 — ENCODE gate:** owner reviewed the DRAFT text and ratified it (literal: "lgtm."). Status remains DRAFT.
- **2026-09-04 — DRAFT.** First draft, authored at the ENCODE gate from Phase-0 evidence (Brief A, shipped surface; Brief B, prior decisions), nine owner-ratified decisions, and four conformance rulings. Owner ratification, literal: *"Let's make hero the velocity, along w/ other numbers that matter, such as the active/in-flight, blocked, need attention, open, etc. Focus is on observability, etc. The rest looks good to me."* That overrode a recorded invariant — *"the dashboard's hero is the AGE of the oldest unclaimed item, never a count"*, rationale *"a giant `0` trains a viewer to stop looking. An age reads as neglect"* (`webapp.py:37-44`). The owner weighed that alternative and chose observability, so Core 1 asserts velocity with the counts that matter; the concern behind the alternative survives in the form the owner accepted, as Core 8. Settled by ruling: a human-perception seam is admissible, so every clause admitting a machine check carries one and the two that cannot are named NOT-ASSERTABLE; no ceiling constant enters Core, the exemption register living in `ledger/` (Core 4, Backlogged 2); the custody boundary is a one-way citation, leaving `contracts/custody-coordination.v1.md` untouched; CLI `--json` is Reserved 1, a different seam being a different contract.
