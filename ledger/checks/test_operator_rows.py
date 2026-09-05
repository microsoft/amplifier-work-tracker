"""Per-row probes for `contracts/operator-surface.v1.md` (OSV1-###).

The sibling of `test_custody_rows.py`, and it follows the SAME convention --
read that module's docstring first; the one restated here is the one a reader
of a red operator row must not miss:

    A probe on a **CONFORMS** row asserts the invariant holds.

    A probe on a **VIOLATION** or **GAP** row asserts the *currently observed,
    known-wrong* shape, ON PURPOSE. Those rows carry a filed work item; until
    it lands, the ledger's job is to make the drift immovable in BOTH
    directions -- a regression fails, and so does a silent fix. When the fix
    lands the probe here fails, and that failure is the instruction: flip the
    row to CONFORMS and replace the pin with the real check, in the same
    change. Doing neither means main carries a ledger that lies.

## What this family can and cannot prove

Twenty of this family's thirty-five rows are red, and most of them are red for
one reason: `contracts/operator-surface.v1.md` names two conformance kits
(`tests/conformance/operator_surface/test_tier_a.py` and
`.../browser/test_tier_b.py`) and NEITHER EXISTS. This ledger kit is
in-process only -- no browser, no bd, no dolt, no subprocess -- so it cannot
stand in for them, and it does not pretend to. What it does instead:

  * where a clause IS measurable in-process (the inline-style census, the
    token-pair luminance math, the route audit, call-site counts, the
    dependency manifest), it MEASURES it, every run, via the engines in
    `_support.py` -- so those rows rest on a number this kit computed, not on
    a number someone wrote down;
  * where a clause needs a rendered page or a real browser, the probe pins the
    kit's ABSENCE plus whatever source-level evidence the row's notes record,
    and the row stays GAP with the reason "kit not built" -- never
    NOT-ASSERTABLE, because those clauses ARE assertable and simply are not
    asserted yet.

`NOT-ASSERTABLE` is used exactly three times (OSV1-018, -019, -035) and every
one of them is a clause the CONTRACT ITSELF declares unassertable, or a ruling
required to sit on a cadence. It is never a place to put work.
"""

from __future__ import annotations

import json
import re

from ._support import (
    CHARTSVG,
    LITERAL,
    OPERATOR_CONTRACT_PATH,
    PYPROJECT,
    REPO_ROOT,
    SUPERVISOR,
    WEBAPP,
    WEBBROWSE,
    WEBPUSH,
    WEBPWA,
    WEBTHEME,
    WEBTRUST,
    WIDGETS,
    collapse,
    contains,
    count,
    inline_style_sites,
    non_text_pairs,
    read,
    resolve_token,
    route_audit,
    row,
    rows,
    sha256,
    src_modules,
    style_block_literal_sites,
    style_blocks_outside_token_module,
    style_sites_in,
    text_pairs,
    token_blocks,
)

# The two kit paths the contract names. Held as REPO_ROOT-relative so the
# mutation harness's throwaway root can make them exist.
TIER_A_KIT = "tests/conformance/operator_surface/test_tier_a.py"
TIER_B_KIT = "tests/conformance/operator_surface/browser/test_tier_b.py"

#: Anything that would mean a browser is being driven somewhere in this repo.
BROWSER_DRIVERS = ("playwright", "selenium", "axe-core", "axe_core")

MAKEFILE = REPO_ROOT / "Makefile"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

#: The Tier-B kit's COMMITTED run summary -- the bridge that lets this
#: in-process, browserless ledger re-read numbers a real chromium produced
#: (Freeze 3, OSV1-029). Written by
#: `tests/conformance/operator_surface/browser/_artifacts.py`; the per-run
#: artifact directory beside it is gitignored and unreadable from here.
TIER_B_SUMMARY = "tests/conformance/operator_surface/browser/LAST_RUN.json"
TIER_B_SUMMARY_SCHEMA = "operator-surface-tier-b/1"


def tier_b_summary() -> dict:
    """The Tier-B run summary, parsed, with its envelope checked.

    Fails loud rather than returning `{}`: a probe that quietly read an empty
    summary would report "no violation measured" for every Tier-B row at once,
    which is precisely the hollow green Freeze 3 exists to prevent. Read
    through `read()` so the mutation harness's injected world is what a
    mutated run sees.
    """
    path = REPO_ROOT / TIER_B_SUMMARY
    assert path.exists(), (
        f"{TIER_B_SUMMARY} is missing. Every Tier-B row re-reads its verdict "
        f"from it -- run `make test-conformance-b` to regenerate it."
    )
    data = json.loads(read(path))
    assert data.get("schema") == TIER_B_SUMMARY_SCHEMA, (
        f"{TIER_B_SUMMARY} declares schema {data.get('schema')!r}, expected "
        f"{TIER_B_SUMMARY_SCHEMA!r} -- the artifact shape moved under the ledger."
    )
    assert data.get("checks"), f"{TIER_B_SUMMARY} carries no checks"
    return data


def tier_b(check: str, scenario: str) -> dict:
    """One headline out of the run summary, or a loud failure naming what is there."""
    checks = tier_b_summary()["checks"]
    assert check in checks, (
        f"the Tier-B run summary has no `{check}` check (it has "
        f"{sorted(checks)}). Either the kit stopped emitting it or the run was "
        f"partial -- re-run `make test-conformance-b`."
    )
    scenarios = checks[check]
    assert scenario in scenarios, (
        f"the Tier-B run summary has no `{check}` / `{scenario}` scenario (it has "
        f"{sorted(scenarios)})."
    )
    return scenarios[scenario]


def _exists(rel: str) -> bool:
    return (REPO_ROOT / rel).exists()


def _repo_mentions(needle: str) -> bool:
    """Does any tracked source/config file name this string?

    Deliberately narrow (the package, the Makefile, CI, the manifest) rather
    than a whole-tree walk: the ledger kit must stay sub-second, and a stray
    match inside `.venv` would be noise, not evidence.
    """
    for path in (*src_modules(), MAKEFILE, CI_WORKFLOW, PYPROJECT):
        if path.exists() and needle in read(path).lower():
            return True
    return False


# --------------------------------------------------------------- OSV1-000


def test_row_osv1_000() -> None:
    """SYNC. Pins BOTH governed contracts by content hash.

    The second pin is the point: Phase-1 ruling Need 3 made the boundary to
    `custody-coordination.v1` a one-way citation, and the price of that
    cheapness is that a custody amendment must re-review THIS family too.
    A mismatch on either file is never a silent hash bump -- it triggers a
    MANDATORY full-ledger re-review, because quote verification only proves
    the text still exists, not that each row still reads it correctly.
    """
    sync = row("OSV1-000")["contract"]
    pinned = {e["file"] for e in sync["files"]}
    assert pinned == {
        "contracts/operator-surface.v1.md",
        "contracts/custody-coordination.v1.md",
    }, (
        "LEDGER-INTEGRITY: OSV1-000 must pin BOTH contracts. Dropping the custody pin "
        "would let a custody amendment move under this family without re-review "
        "(Phase-1 ruling Need 3)."
    )
    for entry in sync["files"]:
        path = REPO_ROOT / entry["file"]
        actual = sha256(path)
        assert actual == entry["sha256"], (
            f"LEDGER-INTEGRITY: {entry['file']} content hash changed\n"
            f"  pinned:   {entry['sha256']}\n"
            f"  observed: {actual}\n"
            f"A governed contract moved under the ledger. Do NOT bump this hash on its "
            f"own: re-review EVERY OSV1 row against the new text, then update the SYNC "
            f"row in the same change (LEDGER-FORMAT.md sec.4)."
        )


# --------------------------------------------------------------- OSV1-001


def test_row_osv1_001() -> None:
    """Core 1 VIOLATION pin: the L0 hero is a verdict, and velocity is a chart.

    Three separable facts, asserted separately so a partial fix cannot pass a
    single blunt check: the hero renderer emits no figure and no count; L0
    builds its hero from the verdict path; and the KPI strip carries the five
    shipped keys with NO needs-attention key among them.
    """
    hero = read(WIDGETS)
    start = hero.index("def render_verdict_hero")
    body = hero[start : start + 1400]
    assert 'class="verdict"' in body and 'class="eyebrow2"' in body, (
        "OSV1-001 (Core 1): `render_verdict_hero` no longer emits the verdict/eyebrow "
        "shape this pin was written against -- the hero moved. Re-measure the row."
    )
    assert "velocity" not in body.lower(), (
        "OSV1-001 (Core 1) PIN BROKE THE RIGHT WAY: the hero renderer now mentions "
        "velocity. If the hero really carries throughput over a stated window plus the "
        "four counts, flip OSV1-001 to CONFORMS and retarget this probe at the fixed "
        "shape IN THE SAME CHANGE (work_item_pipeline-ujy). A passing pin is not "
        "conformance; only the retargeted probe is."
    )

    app = read(WEBAPP)
    assert "hero_html = WD.render_verdict_hero(" in app, (
        "OSV1-001 (Core 1): L0 no longer builds its hero from `render_verdict_hero`. "
        "That is the fix landing -- re-derive the row."
    )

    # The shipped KPI strip: five keys, and `needs attention` is not one of them.
    kpi = app[app.index("kpi_html = WD.render_kpi_strip(") :][:2200]
    shipped = set(re.findall(r'key="([a-z_0-9]+)"', kpi))
    assert shipped == {"agents", "held", "ready", "blocked", "resolved24h"}, (
        f"OSV1-001 (Core 1): the L0 KPI strip's keys moved -- pinned "
        f"{{agents, held, ready, blocked, resolved24h}}, observed {sorted(shipped)}. "
        f"If a needs-attention count was added, that is the fix landing "
        f"(work_item_pipeline-ujy): flip the row and retarget this probe."
    )
    # Matched on the card LABELS, not on the word "attention": the Blocked card
    # already links to `#attention-queue`, so a substring check would be
    # satisfied by an href and assert nothing about a count.
    labels = set(re.findall(r'label="([^"]+)"', kpi))
    assert labels == {"Agents active now", "Held", "Ready", "Blocked", "Resolved 24h"}, (
        f"OSV1-001 (Core 1): the KPI strip's card labels moved -- pinned the five "
        f"shipped ones, observed {sorted(labels)}. Core 1 names FOUR counts an operator "
        f"acts on; `needs attention` was the one absent at seed. If it was added, that "
        f"is the fix landing (work_item_pipeline-ujy) -- re-derive the row."
    )


# --------------------------------------------------------------- OSV1-002


def test_row_osv1_002() -> None:
    """Core 2 CONFORMS: exactly three status hues, and the two alias names
    resolve INTO the set rather than adding to it.

    The alias half is what makes this a real check rather than a grep: every
    `var(--amber)` call site in webapp.py would look like a bespoke fourth hue
    to a naive scan, and is not one only because `--amber:var(--alarm)` is
    declared inside the same block.
    """
    dark = token_blocks()["dark"]
    hues = {t for t in dark if re.fullmatch(r"--(alarm|blocked|watch)", t)}
    assert hues == {"--alarm", "--blocked", "--watch"}, (
        f"OSV1-002 (Core 2): the status hue SET moved -- pinned exactly "
        f"{{--alarm, --blocked, --watch}}, observed {sorted(hues)}. Core 2 freezes "
        f"the set at three; a fourth is an amendment, not a commit."
    )
    for hue in ("--alarm", "--blocked", "--watch"):
        val = resolve_token(hue, dark)
        assert val is not None and val.startswith("#"), (
            f"OSV1-002 (Core 2): {hue} no longer resolves to a literal colour (observed {val!r})."
        )
    for alias, target in (("--amber", "--alarm"), ("--crimson", "--blocked")):
        assert dark.get(alias) == f"var({target})", (
            f"OSV1-002 (Core 2): the compatibility alias {alias} no longer resolves to "
            f"var({target}) (observed {dark.get(alias)!r}). If it acquired its own "
            f"literal value it has become a bespoke FOURTH status hue, which the "
            f"clause forbids."
        )
    assert resolve_token("--calm-ink", dark) == resolve_token("--ink-secondary", dark), (
        "OSV1-002 (Core 2): --calm-ink is no longer neutral. Calm must not acquire a "
        "hue -- that is the absence Core 2 says makes the alarm pop."
    )


# --------------------------------------------------------------- OSV1-003


def test_row_osv1_003() -> None:
    """Core 2 VIOLATION pin, RE-READ from the browser run's own numbers.

    Not "a file appeared" and not the browser tier's pass/fail: the calm sweep
    wrote pixel counts, and this reads them back. L0 is clean in both themes;
    L1 paints `--blocked` on a page with nothing blocked, and THAT is the
    pinned violation.
    """
    for theme in ("dark", "light"):
        clean = tier_b("calm.zero_alarm_pixels", f"calm/L0/{theme}")
        assert clean["alarm"] == 0 and clean["blocked"] == 0, (
            f"OSV1-003 (Core 2): a calm L0 in {theme} now paints "
            f"{clean['alarm']} --alarm and {clean['blocked']} --blocked pixels. "
            f"L0 was the CLEAN half of this row -- a regression, not progress."
        )
        dirty = tier_b("calm.zero_alarm_pixels", f"calm/L1/{theme}")
        assert dirty["blocked"] == 97, (
            f"OSV1-003 (Core 2) PIN MOVED: a calm L1 in {theme} painted "
            f"{dirty['blocked']} --blocked pixels, pinned at 97. If the legend "
            f"swatch, the live dot and the danger button stopped painting "
            f"`--blocked` on a calm page, re-derive this row from the new sweep "
            f"(work_item_pipeline-qgo)."
        )
    assert contains(WEBPWA, "background:#0D0D0C;color:#F2EEE6"), (
        "OSV1-003 (Core 2): the retired palette at webpwa.py:121-122 is gone. That is "
        "the Conformance 1 bad fixture's specimen and a Core 4 violation closing "
        "(OSV1-005) -- re-derive both rows."
    )
    assert contains(WEBTRUST, "--amber:#D9A253"), (
        "OSV1-003 (Core 2): webtrust.py's retired `--amber:#D9A253` is gone -- the "
        "hardcoded amber outside the token set that Conformance 1's bad half "
        "reinstates. Re-derive this row and OSV1-005's note."
    )


def test_row_osv1_004() -> None:
    """Core 3 GAP pin: no rendered-fixture kit, and the chip vocabulary that
    the kit will check is still the five-word map measured at seed.
    """
    assert not _exists(TIER_A_KIT), (
        f"OSV1-004 (Core 3): {TIER_A_KIT} now exists -- re-derive this row from the "
        f"kit's real result over rendered L0/L1/L2 fixtures (work_item_pipeline-c1a)."
    )
    browse = read(WEBBROWSE)
    labels = set(re.findall(r'"(?:open|held|blocked|deferred|resolved)":\s*"([A-Z]+)"', browse))
    assert labels == {"READY", "HELD", "BLOCKED", "DEFERRED", "RESOLVED"}, (
        f"OSV1-004 (Core 3): `_ITEM_STATUS_CHIP_LABEL`'s words moved -- pinned five "
        f"words, observed {sorted(labels)}. Every status must keep carrying a WORD, "
        f"not only a class."
    )
    assert contains(WEBBROWSE, "_ITEM_STATUS_CHIP_CLASS") and contains(
        WEBBROWSE, "_ITEM_STATUS_CHIP_LABEL"
    ), "OSV1-004 (Core 3): the chip class/label pair this row measures is gone."


# --------------------------------------------------------------- OSV1-005


def test_row_osv1_005() -> None:
    """Core 4 VIOLATION pin: the literal-style census, RE-RUN here.

    The count is computed, never transcribed, so this pin cannot drift away
    from the tree. Two named specimens are asserted individually as well, so
    that migrating the 44 easy `margin-top` sites while leaving the retired
    palette in place does not look like progress the row did not make.

    TWO HALVES since the 2026-09-04 DRAFT true-up widened Core 4: the inline
    `style=` attribute census, and the `<style>`-BLOCK census the widening
    made reachable. They are pinned separately so that fixing one while
    leaving the other is progress the row records rather than a flip it did
    not earn.
    """
    literal = style_sites_in(LITERAL)
    assert len(literal) == 66, (
        f"OSV1-005 (Core 4) CENSUS MOVED: pinned 66 inline `style=` sites carrying a "
        f"literal colour, font, or size; observed {len(literal)}.\n"
        f"  If FEWER: the migration is under way -- update the pinned count (or flip "
        f"the row to CONFORMS at zero) and retarget this probe IN THE SAME CHANGE "
        f"(work_item_pipeline-np3). A passing pin is not conformance.\n"
        f"  If MORE: a new literal site landed. That is a regression against a clause "
        f"that tolerates zero.\n"
        f"  observed: {literal}"
    )
    assert "webpwa.py:121" in literal, (
        "OSV1-005 (Core 4): webpwa.py:121's retired-palette inline body is no longer "
        "counted as a literal site -- the worst specimen in the census. Re-derive."
    )
    assert "webbrowse.py:741" in literal, (
        "OSV1-005 (Core 4): webbrowse.py:741's textarea (literal font-size, max-width "
        "and padding) is no longer counted. Re-derive."
    )
    total = len(inline_style_sites())
    assert total == 137, (
        f"OSV1-005 (Core 4): the total inline `style=` population moved from 137 to "
        f"{total}. Neither direction is neutral -- re-run the census and re-derive "
        f"both OSV1-005 and OSV1-006."
    )

    # --- the `<style>`-block half, reachable since the 2026-09-04 true-up ---
    blocks = [(f, ln) for f, ln, _css in style_blocks_outside_token_module()]
    assert blocks == [("webtrust.py", 256)], (
        f"OSV1-005 (Core 4): the population of `<style>` blocks OUTSIDE the token "
        f"module moved -- pinned exactly one, `webtrust.py:256` (the `_CSS` constant "
        f"embedded at webtrust.py:374), observed {blocks}.\n"
        f"  If GONE: webtrust.py now imports the token CSS -- that is the fix landing "
        f"(work_item_pipeline-np3). Flip the block half of this row and retarget IN "
        f"THE SAME CHANGE.\n"
        f"  If MORE: a second module started shipping its own stylesheet, which is "
        f"the defect Core 4 was widened to reach."
    )
    block_literals = style_block_literal_sites()
    assert len(block_literals) == 40, (
        f"OSV1-005 (Core 4) `<style>`-BLOCK CENSUS MOVED: pinned 40 literal "
        f"colour/font/size declarations inside a `<style>` block outside the token "
        f"module; observed {len(block_literals)}.\n"
        f"  If FEWER: the migration is under way -- update the pinned count (or flip "
        f"the row to CONFORMS at zero on BOTH halves) and retarget this probe IN THE "
        f"SAME CHANGE (work_item_pipeline-np3). A passing pin is not conformance.\n"
        f"  If MORE: a new literal declaration landed in a page-local stylesheet.\n"
        f"  observed: {[f'{f}:{n} {d}' for f, n, d, _r in block_literals]}"
    )
    palette = sorted(d for f, n, d, _r in block_literals if n in (258, 259))
    assert palette == [
        "--amber:#D9A253",
        "--ground:#0D0D0C",
        "--ink:#F2EEE6",
        "--mid:#A6A199",
        "--quiet:#9C978F",
        "--raise:#151513",
        "--rule-hi:#333330",
        "--rule:#1F1F1D",
    ], (
        f"OSV1-005 (Core 4): the retired palette webtrust.py:258-259 hardcodes is no "
        f"longer counted as literal -- observed {palette}. That block is the specimen "
        f"the true-up widened Core 4 to reach, and the one Conformance 1's bad half "
        f"reinstates. If it was tokenised, that is the fix landing: re-derive this row "
        f"and OSV1-003 (work_item_pipeline-np3)."
    )


# --------------------------------------------------------------- OSV1-006


def test_row_osv1_006() -> None:
    """Core 4 CONFORMS: computed-geometry sites are EXACTLY the register.

    This is the exemption register itself (Phase-1 ruling Need 2 put it in
    `ledger/` so shrinking it needs no amendment). Shrinking passes only after
    the register below is shrunk to match; GROWING fails immediately, which is
    the direction that matters.
    """
    register = {
        "chartsvg.py:268",
        "chartsvg.py:464",
        "chartsvg.py:488",
        "webapp.py:1122",
        "webapp.py:1144",
        "webapp.py:1709",
        "webapp.py:1711",
        "webapp.py:1829",
        "webapp.py:1832",
        "webapp.py:2101",
        "webapp.py:2142",
        "webapp.py:2266",
        "webapp.py:2572",
        "webapp.py:3376",
        "webapp.py:4393",
        "webapp.py:4908",
        "webtheme.py:4120",
        "webtheme.py:4139",
        "webtheme.py:4146",
        "widgets.py:704",
        "widgets.py:831",
        "widgets.py:834",
        "widgets.py:1110",
    }
    observed = set(style_sites_in("COMPUTED"))
    unregistered = observed - register
    assert not unregistered, (
        f"OSV1-006 (Core 4): computed-geometry inline sites NOT on the exemption "
        f"register: {sorted(unregistered)}.\n"
        f"Core 4 permits computed geometry inline ONLY for enumerated sites. Either "
        f"move the style into the token system, or add the site to this register AND "
        f"to row OSV1-006's notes in the same change -- growing the register silently "
        f"is how 'one source of visual truth' stops being true."
    )
    retired = register - observed
    assert not retired, (
        f"OSV1-006 (Core 4): registered sites that no longer exist: {sorted(retired)}.\n"
        f"That is a CONVERGENT change and it is welcome -- but the register must shrink "
        f"with it, here and in the row's notes, or the ledger keeps claiming an "
        f"exemption nobody uses. At zero, Backlogged 2's promotion trigger fires."
    )


# --------------------------------------------------------------- OSV1-007


def test_row_osv1_007() -> None:
    """Core 5 CONFORMS: the route audit, RE-RUN here -- no GET handler reaches
    a mutating adapter call.
    """
    audited = route_audit()
    assert len(audited) == 30, (
        f"OSV1-007 (Core 5): the route population moved from 30 to {len(audited)}. A "
        f"new route is not a defect, but it must be audited -- re-derive this row."
    )
    read_only = [r for r in audited if r["read_only"]]
    assert len(read_only) == 22, (
        f"OSV1-007 (Core 5): read-only handlers moved from 22 to {len(read_only)}."
    )
    dirty = [r for r in read_only if r["mutating_reached"]]
    assert not dirty, (
        "OSV1-007 (Core 5) REGRESSION -- a GET handler now reaches a mutating adapter "
        "call:\n  "
        + "\n  ".join(
            f"{r['module']}:{r['line']} {r['methods']} {r['route']} {r['handler']} "
            f"-> {r['mutating_reached']}"
            for r in dirty
        )
        + "\nThe surface polls itself aggressively; a mutation on a GET is a write "
        "every 20 seconds. Move it to POST."
    )


# --------------------------------------------------------------- OSV1-008


def test_row_osv1_008() -> None:
    """Core 6 VIOLATION pin: one of four survivals holds, RE-READ from the run.

    Pinned in BOTH directions per survival, because they are separable and a
    fix to any one of them is progress this row must record rather than
    absorb.
    """
    for level in ("L0", "L1"):
        m = tier_b("swap.survives", f"calm/{level}/dark")
        assert m["scroll_preserved"], (
            f"OSV1-008 (Core 6): scroll offset stopped surviving the body-swap on "
            f"{level}. That was the ONE of Core 6's four named survivals that held "
            f"-- a regression."
        )
        assert not m["open_details_preserved"], (
            f"OSV1-008 (Core 6) PIN BROKE THE RIGHT WAY on {level}: an open "
            f"`<details>` now survives the swap. Confirm it survives because the "
            f"markup gained ids and `restoreState` reaches them, then re-derive "
            f"this row (work_item_pipeline-qgo)."
        )
        assert m["details_with_id"] == 0, (
            f"OSV1-008 (Core 6) PIN BROKE THE RIGHT WAY on {level}: "
            f"{m['details_with_id']} `<details>` now carry an id. `restoreState` "
            f"only ever re-opens `details[id]`, so this is the mechanism acquiring "
            f"its first targets -- re-derive from the new swap measurement."
        )
        assert not m["pause_control_preserved"], (
            f"OSV1-008 (Core 6) PIN BROKE THE RIGHT WAY on {level}: the pause "
            f"CONTROL's state now survives the swap. Re-derive this row."
        )
        assert m["pause_flag_preserved"], (
            f"OSV1-008 (Core 6): `window.__wtRefreshPaused` stopped surviving the "
            f"swap on {level}. The flag living on `window` is why polling stays "
            f"paused at all -- a regression."
        )
        assert m["live_regions_before"] == 0, (
            f"OSV1-008 (Core 6) PIN BROKE THE RIGHT WAY on {level}: the page now "
            f"renders {m['live_regions_before']} live region(s). Core 6's "
            f"announcement half had NOTHING to preserve at this measurement -- "
            f"re-derive this row from whether the region SURVIVES the swap."
        )
    assert count(WEBAPP, "aria-live") == 0 and count(WEBTHEME, "aria-live") == 0, (
        "OSV1-008 (Core 6) PIN BROKE THE RIGHT WAY: an `aria-live` region appeared "
        "in the source. Re-derive this row from the Tier-B snapshot rather than "
        "from its presence."
    )


def test_row_osv1_009() -> None:
    """Core 7 VIOLATION pin: the token-pair luminance math, RE-RUN here.

    Two halves, both pinned: the six below-floor pairs are all --ink-quiet in
    light mode, AND that token is used for real reading copy. Fixing either
    half alone is progress the row must record, so neither is folded into the
    other.
    """
    below = sorted(
        (round(r, 2), ink, ground, block) for block, ink, ground, r in text_pairs() if r < 4.5
    )
    assert len(below) == 6, (
        f"OSV1-009 (Core 7) LUMINANCE MOVED: pinned six declared text pairs below the "
        f"4.5:1 floor, observed {len(below)}.\n"
        f"  If FEWER: the tokens are being fixed -- update the pin (or flip the row to "
        f"CONFORMS at zero) and retarget this probe IN THE SAME CHANGE "
        f"(work_item_pipeline-sxh). A passing pin is not conformance.\n"
        f"  If MORE: a token regressed below a frozen floor.\n"
        f"  observed: {below}"
    )
    assert {b[1] for b in below} == {"--ink-quiet"}, (
        f"OSV1-009 (Core 7): a token OTHER than --ink-quiet is now below the text "
        f"floor: {sorted({b[1] for b in below})}. --ink-quiet is at least documented "
        f"as decorative; anything else below 4.5:1 is a plain regression."
    )
    assert min(b[0] for b in below) == 2.72, (
        f"OSV1-009 (Core 7): the worst declared text pair moved from 2.72:1 to "
        f"{min(b[0] for b in below)}:1."
    )
    assert contains(CHARTSVG, 'style="fill:var(--ink-quiet)">'), (
        "OSV1-009 (Core 7) PIN BROKE THE RIGHT WAY: chartsvg.py no longer paints its "
        "empty-state caption with --ink-quiet. That call site is what makes the "
        "below-floor token READING COPY rather than a documented decorative "
        "exemption -- re-derive the row (work_item_pipeline-sxh)."
    )
    worst_non_text = min(r for *_rest, r in non_text_pairs())
    assert worst_non_text >= 3.0, (
        f"OSV1-009 (Core 7) REGRESSION: a status hue fell below the 3:1 NON-TEXT "
        f"floor ({worst_non_text:.2f}:1). That half CONFORMED at seed and this row "
        f"does not cover it -- it is a separate, new violation."
    )


# --------------------------------------------------------------- OSV1-010


def test_row_osv1_010() -> None:
    """Core 7 VIOLATION pin (rendered half), RE-READ from the browser run.

    Four floors, measured across 18 renders. Three fail and one passes, and
    all four are pinned: a fix to any one is progress this row must record.
    """
    l0 = tier_b("perception.floors", "calm/L0/1280/dark")
    l1 = tier_b("perception.floors", "calm/L1/1280/dark")
    l1_light = tier_b("perception.floors", "calm/L1/1280/light")

    assert l0["text_below_floor"] == 0, (
        f"OSV1-010 (Core 7): L0 now has {l0['text_below_floor']} text elements below "
        f"4.5:1. L0 was the CLEAN level for text contrast -- a regression."
    )
    assert l1["text_below_floor"] == 3 and l1_light["text_below_floor"] == 5, (
        f"OSV1-010 (Core 7) PIN MOVED: L1 text below 4.5:1 measured "
        f"{l1['text_below_floor']} dark / {l1_light['text_below_floor']} light, "
        f"pinned at 3 / 5. Movement in either direction means the render changed "
        f"-- re-derive (work_item_pipeline-qgo)."
    )
    assert l0["controls_below_44px"] == 26 and l0["controls"] == 35, (
        f"OSV1-010 (Core 7) PIN MOVED: L0 measured {l0['controls_below_44px']} of "
        f"{l0['controls']} interactive controls under 44px, pinned at 26 of 35."
    )
    assert l0["non_text_below_floor"] > 0, (
        "OSV1-010 (Core 7) PIN BROKE THE RIGHT WAY: every measured control border "
        "and icon stroke on L0 now meets 3:1. Re-derive this row."
    )
    assert l0["running_animations_under_reduced_motion"] == 0, (
        f"OSV1-010 (Core 7): {l0['running_animations_under_reduced_motion']} "
        f"animation(s) now run under `prefers-reduced-motion: reduce`. That floor "
        f"PASSED at this measurement -- a regression, and Core 7's kernel-rule half "
        f"(OSV1-011) with it."
    )
    assert contains(WEBTHEME, "--u:44px"), (
        "OSV1-010 (Core 7): the 44px target token is gone -- the thing the Tier-B "
        "bounding-box check exists to verify."
    )


def test_row_osv1_011() -> None:
    """Core 7 CONFORMS: reduced motion is ONE kernel-level rule.

    Both halves matter: exactly one block, and its selector is universal. A
    per-widget opt-in would satisfy a naive "is it handled?" check and is
    precisely what the clause forbids.
    """
    theme = read(WEBTHEME)
    blocks = re.findall(r"@media \(prefers-reduced-motion:\s*reduce\)\s*\{", theme)
    assert len(blocks) == 1, (
        f"OSV1-011 (Core 7): there are now {len(blocks)} `prefers-reduced-motion` "
        f"blocks. Core 7 requires ONE kernel-level rule rather than per-widget "
        f"opt-in -- a second block is the drift starting."
    )
    body = theme[theme.index("@media (prefers-reduced-motion:reduce){") :][:420]
    assert "*,*::before,*::after" in body, (
        "OSV1-011 (Core 7): the reduced-motion rule is no longer universal "
        "(`*,*::before,*::after`). Scoping it to specific widgets is exactly the "
        "per-widget opt-in the clause names."
    )
    for prop in ("animation-duration", "transition-duration", "scroll-behavior"):
        assert prop in body, f"OSV1-011 (Core 7): the kernel rule no longer resets {prop}."
    others = re.findall(r"prefers-reduced-motion", read(WEBAPP)) + re.findall(
        r"prefers-reduced-motion", read(WEBBROWSE)
    )
    assert not others, (
        "OSV1-011 (Core 7): a `prefers-reduced-motion` query appeared outside "
        "webtheme.py. The rule is kernel-level and belongs in one place."
    )


# --------------------------------------------------------------- OSV1-012


def test_row_osv1_012() -> None:
    """Core 8 GAP pin: no two-render kit, and the empty sentences measured at
    seed are still the ones the kit will look for.
    """
    assert not _exists(TIER_A_KIT), (
        f"OSV1-012 (Core 8): {TIER_A_KIT} now exists -- re-derive this row from a real "
        f"empty-vs-populated render comparison (work_item_pipeline-c1a)."
    )
    assert contains(WIDGETS, '"All clear"'), (
        "OSV1-012 (Core 8): the calm headline 'All clear' is gone. Calm must stay "
        "STATED -- and must not become a triumphant zero."
    )
    assert contains(WEBAPP, "Nothing is waiting to be claimed in this queue right now."), (
        "OSV1-012 (Core 8): the ready-queue empty sentence is gone. A widget with "
        "nothing to show keeps its slot AND says so in a sentence."
    )
    assert contains(CHARTSVG, "No activity in this window"), (
        "OSV1-012 (Core 8): the chart's empty sentence is gone."
    )
    assert contains(WEBBROWSE, "No items match this filter."), (
        "OSV1-012 (Core 8): the filtered-list empty sentence is gone."
    )
    assert contains(WEBAPP, '<span class="fig none sm">'), (
        "OSV1-012 (Core 8): the empty hero figure no longer renders as the `fig none` "
        "em-dash. If it became a numeral, that is the 'triumphant zero' the clause "
        "forbids; if it became something else, re-derive the row."
    )


# --------------------------------------------------------------- OSV1-013


def test_row_osv1_013() -> None:
    """Core 9 CONFORMS: no front-end framework, bundler, template engine, or
    build step producing served assets.
    """
    manifest = read(PYPROJECT).lower()
    for banned in (
        "jinja2",
        "mako",
        "chameleon",
        "react",
        "vue",
        "svelte",
        "htmx",
        "alpine",
        "webpack",
        "vite",
        "rollup",
        "esbuild",
        "parcel",
    ):
        assert banned not in manifest, (
            f"OSV1-013 (Core 9) REGRESSION: the dependency manifest now declares "
            f"{banned!r}. Core 9 freezes this surface as server-rendered HTML composed "
            f"in Python with no client-side layout engine, asset pipeline or template "
            f"engine."
        )
    assert "dependencies = []" in read(PYPROJECT), (
        "OSV1-013 (Core 9): the package acquired runtime dependencies. Re-derive the "
        "row -- a runtime dep is not automatically a violation, but it must be looked at."
    )
    for build_file in (
        "package.json",
        "webpack.config.js",
        "vite.config.js",
        "vite.config.ts",
        "rollup.config.js",
        "tsconfig.json",
    ):
        assert not _exists(build_file), (
            f"OSV1-013 (Core 9) REGRESSION: {build_file} appeared. Core 9 forbids a "
            f"build step producing served assets."
        )


# --------------------------------------------------------------- OSV1-014


def test_row_osv1_014() -> None:
    """Core 10 CONFORMS: no charting or drag-and-drop library in the manifest."""
    manifest = read(PYPROJECT).lower()
    for banned in (
        "chart.js",
        "chartjs",
        "d3",
        "plotly",
        "echarts",
        "highcharts",
        "recharts",
        "apexcharts",
        "sortable",
        "dragula",
        "interact.js",
        "react-dnd",
        "dnd-kit",
    ):
        assert banned not in manifest, (
            f"OSV1-014 (Core 10) REGRESSION: the dependency manifest now declares "
            f"{banned!r}. Core 10's anti-goals name a new chart library and a kanban "
            f"drag-board specifically -- the drag gesture fights machine-owned custody."
        )
    assert CHARTSVG.exists() and contains(CHARTSVG, "<svg"), (
        "OSV1-014 (Core 10): the hand-rolled SVG chart module is gone. If charts moved "
        "to a library, this row is a violation, not a refactor."
    )


# --------------------------------------------------------------- OSV1-015


def test_row_osv1_015() -> None:
    """Core 10 VIOLATION pin: the L1 view's unbounded query, and the dead
    uncapped helper beside it.
    """
    assert contains(WEBBROWSE, "bd.list(status=status_filter, include_resolved=True, limit=0)"), (
        "OSV1-015 (Core 10) PIN BROKE THE RIGHT WAY: webbrowse.py's `limit=0` call is "
        "gone. If the L1 view now passes a bound that actually bounds (e.g. via "
        "`adapter.list_bounded`), flip OSV1-015 to CONFORMS and retarget this probe IN "
        "THE SAME CHANGE (work_item_pipeline-8vv). A passing pin is not conformance."
    )
    app = read(WEBAPP)
    assert app.count("_oldest_ready_item") == 1, (
        f"OSV1-015 (Core 10): `_oldest_ready_item` now has "
        f"{app.count('_oldest_ready_item') - 1} caller(s). It calls `bd.list(...)` with "
        f"NO limit at all -- dead code was the only reason it did not violate this "
        f"clause. Give it a bound or delete it."
    )
    assert contains(WEBAPP, 'items = bd.list(lane=A.LANE_WORK, status="open")'), (
        "OSV1-015 (Core 10): the uncapped `bd.list` in `_oldest_ready_item` is gone -- "
        "welcome, and the row's second pinned fact just changed. Re-derive."
    )


# --------------------------------------------------------------- OSV1-016


def test_row_osv1_016() -> None:
    """Core 10 VIOLATION pin: the theme choice persists nowhere.

    Pinned narrowly, on theme only. At seed the density preference raised a
    genuine reading question (localStorage survives a refresh but IS 'only in
    the browser') that the reconcile returned to the root rather than deciding,
    so this probe deliberately said nothing about it.

    SETTLED 2026-09-04 by the owner-ratified DRAFT true-up #1: the machine
    check now reads "no view holds state that does not survive a refresh
    (state persisted in `localStorage` or on the server survives; ...)". Under
    that wording density is CONFORMANT and theme is still a violation, so the
    probe now asserts BOTH -- the pin on theme, and the persistence that makes
    density conformant, since a row whose notes rule on density must notice if
    density stops persisting.
    """
    app = read(WEBAPP)
    setter = app[app.index("function wtSetTheme(t){") :][:340]
    assert "setAttribute('data-theme', t)" in setter, (
        "OSV1-016 (Core 10): `wtSetTheme` no longer sets the theme attribute -- the "
        "mechanism this row measures moved."
    )
    for persistence in ("localStorage", "sessionStorage", "document.cookie", "fetch("):
        assert persistence not in setter, (
            f"OSV1-016 (Core 10) PIN BROKE THE RIGHT WAY: `wtSetTheme` now uses "
            f"{persistence!r}. If the theme choice survives a refresh, flip OSV1-016 to "
            f"CONFORMS and retarget this probe IN THE SAME CHANGE "
            f"(work_item_pipeline-dg3). A passing pin is not conformance."
        )
    assert contains(WEBTHEME, '<html lang="en" data-theme="dark">'), (
        'OSV1-016 (Core 10): the server no longer hardcodes `data-theme="dark"` on '
        "every page. That hardcoding is the other half of why a chosen theme dies on "
        "refresh -- re-derive the row."
    )
    # The OTHER preference on this surface, and the one the true-up's aligned
    # wording rules CONFORMANT: density persists, so it survives a refresh. Not
    # a pin -- a live check on the fact this row's notes rule on.
    theme_src = read(WEBTHEME)
    assert theme_src.count("wt-density") == 2 and contains(
        WEBTHEME, "localStorage.setItem(KEY, next ? 'compact' : 'comfortable')"
    ), (
        "OSV1-016 (Core 10): the density preference no longer persists in "
        "`localStorage`. Under the 2026-09-04 aligned wording that persistence is "
        "exactly why density is CONFORMANT while theme is not -- if it stopped, "
        "density became a second violation of this clause and this row's ruling note "
        "is stale. Re-derive."
    )


# --------------------------------------------------------------- OSV1-017


def test_row_osv1_017() -> None:
    """Core 11 CONFORMS: exactly ONE call site fires the push channel, and it
    is inside the reclaim path.

    The count and the location are both asserted: a second call site is the
    violation the clause names, and a first call site that moved OUT of the
    reclaim branch would keep the count at one while breaking the promise.
    """
    call_sites = [
        (p.name, ln)
        for p in src_modules()
        if p != WEBPUSH
        for ln, line in enumerate(read(p).splitlines(), start=1)
        if "fire_reclaim_alarm" in line or "send_alarm(" in line
    ]
    assert call_sites == [("supervisor.py", 156)], (
        f"OSV1-017 (Core 11): the push channel's call sites moved -- pinned exactly "
        f"one, `supervisor.py:156`, observed {call_sites}. Core 11 freezes the channel "
        f"at ONE event class: a sweep reclaiming custody after a TTL breach. A second "
        f"sender is Backlogged 5 and needs the owner to ratify a specific second event "
        f"class first."
    )
    sup = read(SUPERVISOR)
    reclaim = sup[sup.index("if eligible:") :][:1200]
    assert "bd.release(item.id)" in reclaim and "WP.fire_reclaim_alarm(" in reclaim, (
        "OSV1-017 (Core 11): the push no longer fires from inside the reclaim branch, "
        "after the release. Firing on eligibility rather than on a completed reclaim "
        "would make calm noisy, which the clause forbids."
    )
    assert reclaim.index("bd.release(item.id)") < reclaim.index("WP.fire_reclaim_alarm("), (
        "OSV1-017 (Core 11): the alarm now fires BEFORE the release it announces."
    )


# --------------------------------------------------------------- OSV1-020..-026
# The seven Conformance fixtures. Each pins the ABSENCE of the file the
# contract names, plus one fact about the defect its bad half must catch, so a
# kit that appears without the discriminating pair still reads red.


def test_row_osv1_020() -> None:
    """Conformance 1 CONFORMS: the fixture exists AND its bad halves caught the
    defects they name -- re-read, not taken on the kit's word.

    Deliberately not `_exists(TIER_B_KIT)` alone. Freeze 4 is about a bad half
    that FAILS against its defect, demonstrated by running it, so this reads
    the three demonstrations' own numbers back out of the run summary.
    """
    assert _exists(TIER_B_KIT), (
        f"OSV1-020 (Conformance 1): {TIER_B_KIT} is gone -- the fixture this row "
        f"records no longer exists."
    )
    chip = tier_b("calm.zero_alarm_pixels", "bad-alarm-chip/L0/dark")
    assert chip["alarm"] > 0, (
        f"OSV1-020 (Conformance 1): the injected `var(--alarm)` chip bad half "
        f"reported {chip['alarm']} --alarm pixels. A bad half that no longer "
        f"discriminates makes the good half vacuous."
    )
    retired = tier_b("calm.zero_alarm_pixels", "bad-retired-palette/L0/dark")
    assert retired["retired_amber"] > 0, (
        "OSV1-020 (Conformance 1): the contract's own named bad half -- the retired "
        "#D9A253 palette region reinstated -- reported zero pixels of it."
    )
    real = tier_b("calm.zero_alarm_pixels", "bad-alarm-fixture/L0/dark")
    assert real["alarm"] > 0 or real["blocked"] > 0, (
        "OSV1-020 (Conformance 1): the genuinely-alarming fixture (one real blocked "
        "item, nothing injected) painted no reserved status hue at all."
    )
    assert contains(
        OPERATOR_CONTRACT_PATH, "the sweep reports zero pixels matching `--alarm` or `--blocked`"
    ), "OSV1-020: Conformance 1's good half moved in the contract -- re-review the row."


def test_row_osv1_021() -> None:
    """Conformance 2 GAP pin: the Tier-B half landed, the Tier-A half has not.

    This fixture spans both tiers, so the row stays red for the half that is
    still missing -- and the probe proves the landed half is real rather than
    just present, so "half of it works" cannot decay unnoticed while the other
    half is waited on.
    """
    assert not _exists(TIER_A_KIT), (
        f"OSV1-021 (Conformance 2) PIN BROKE THE RIGHT WAY: {TIER_A_KIT} now exists. "
        f"This is the one fixture spanning BOTH tiers -- flip it to CONFORMS once "
        f"the Tier-A accessible-name half discriminates too "
        f"(work_item_pipeline-c1a); the Tier-B half already does."
    )
    hue = tier_b("alarm.reserved_hue", "alarm/L1/dark")
    assert hue["alarm"] > 0 or hue["blocked"] > 0, (
        "OSV1-021 (Conformance 2): the Tier-B hue half stopped measuring -- the "
        "alarm render painted neither --alarm nor --blocked."
    )
    for level in ("L0", "L1", "L2"):
        words = tier_b("state.not_colour_only", f"alarm/{level}/dark")
        assert words["status_elements"] > 0, (
            f"OSV1-021 (Conformance 2): no status-bearing element was found on "
            f"{level} in the render -- the check cannot pass vacuously."
        )
        assert words["wordless"] == 0, (
            f"OSV1-021 (Conformance 2): {words['wordless']} status-bearing element(s) "
            f"on {level} now carry a class and no word. Core 3's rendered half was "
            f"CLEAN at this measurement -- a regression (OSV1-004)."
        )
    assert contains(
        OPERATOR_CONTRACT_PATH, "fixture whose status chips carry only a status class"
    ), "OSV1-021: Conformance 2's bad half moved in the contract -- re-review the row."


def test_row_osv1_022() -> None:
    """Conformance 3 CONFORMS: both bad halves ran and both caught their defect.

    Two of them, because the contract's literal bad half does not discriminate
    on scroll here (a synchronous whole-body replacement preserves the offset
    by itself on chromium 148); the reflow variant does. Both are re-read.
    """
    assert _exists(TIER_B_KIT), (
        f"OSV1-022 (Conformance 3): {TIER_B_KIT} is gone -- the fixture this row "
        f"records no longer exists."
    )
    naive = tier_b("swap.survives", "bad-naive-replacement/L0/dark")
    assert not naive["open_details_preserved"], (
        "OSV1-022 (Conformance 3): the contract's literal bad half -- a naive "
        "whole-body innerHTML replacement -- no longer loses the open `<details>`, "
        "so it discriminates against nothing."
    )
    reflow = tier_b("swap.survives", "bad-naive-replacement-reflow/L0/dark")
    assert not reflow["scroll_preserved"], (
        "OSV1-022 (Conformance 3): the reflow bad half no longer loses the scroll "
        "offset. It exists precisely because the literal bad half cannot "
        "discriminate on scroll -- without it, the good half's scroll assertion is "
        "unproven."
    )
    good = tier_b("swap.survives", "calm/L0/dark")
    assert good["scroll_preserved"] and not good["open_details_preserved"], (
        "OSV1-022 (Conformance 3): the good half's own outcome moved (scroll "
        f"{good['scroll_preserved']}, disclosures {good['open_details_preserved']}) "
        f"-- re-derive this row and OSV1-008 together."
    )
    assert contains(WEBTHEME, "document.body.innerHTML = doc.body.innerHTML"), (
        "OSV1-022 (Conformance 3): the whole-body innerHTML swap is gone. That IS the "
        "mechanism Conformance 3's bad half describes -- if the swap changed shape, "
        "the fixture's premise changed with it. Re-derive this row and OSV1-008."
    )


def test_row_osv1_023() -> None:
    """Conformance 4 CONFORMS: the sweep covers what the clause names, and its
    bad halves ran.

    The contrast bad half carries its own control (the same token pair must
    come back below the floor in light and above it in dark), which is what
    separates "the probe measures" from "the probe always says no".
    """
    assert _exists(TIER_B_KIT), (
        f"OSV1-023 (Conformance 4): {TIER_B_KIT} is gone -- the fixture this row "
        f"records no longer exists."
    )
    summary = tier_b_summary()["checks"]["perception.floors"]
    swept = {s for s in summary if s.startswith("calm/")}
    expected = {
        f"calm/{level}/{width}/{theme}"
        for level in ("L0", "L1", "L2")
        for width in (430, 900, 1280)
        for theme in ("dark", "light")
    }
    assert swept == expected, (
        f"OSV1-023 (Conformance 4): the sweep no longer covers L0/L1/L2 at 430, 900 "
        f"and 1280px in both themes. Missing: {sorted(expected - swept)}; "
        f"unexpected: {sorted(swept - expected)}."
    )
    wide = summary.get("bad-wide-element/L0/430/dark")
    assert wide and wide["elements_beyond_viewport_moved"], (
        "OSV1-023 (Conformance 4): the overflow bad half -- a 900px fixed-width "
        "element at a 430px viewport -- no longer moves the element-level reading."
    )
    assert wide["scroll_width_moved"] is False, (
        "OSV1-023 (Conformance 4) PIN BROKE THE RIGHT WAY: the injected wide element "
        "now DOES move `scrollWidth`. That means `overflow-x: clip` is gone from the "
        "surface, the clause's literal metric has become discriminating, and this "
        "row's note about it should be re-derived."
    )
    low = summary.get("bad-low-contrast/L0/light")
    high = summary.get("bad-low-contrast/L0/dark")
    assert low and high, "OSV1-023 (Conformance 4): the contrast bad half did not run."
    assert low["min_ratio"] < 4.5 <= high["min_ratio"], (
        f"OSV1-023 (Conformance 4): the recorded --ink-quiet/--ground pair measured "
        f"{low['min_ratio']} light / {high['min_ratio']} dark. The bad half needs "
        f"BOTH -- below the floor in light AND above it in dark -- or it is not "
        f"demonstrating a measurement."
    )
    theme = read(WEBTHEME)
    for width in ("1280px", "900px", "430px"):
        assert f"max-width:{width}" in theme or f"min-width:{width}" in theme, (
            f"OSV1-023 (Conformance 4): the {width} breakpoint is gone from "
            f"webtheme.py. Conformance 4 sweeps 430, 900 and 1280 -- a viewport the "
            f"stylesheet no longer knows about is a different test."
        )


def test_row_osv1_024() -> None:
    """Conformance 5 pin: no Tier-A kit, so hero composition is unasserted."""
    assert not _exists(TIER_A_KIT), (
        f"OSV1-024 (Conformance 5): {TIER_A_KIT} now exists -- re-derive from the "
        f"demonstrated good/bad pair (work_item_pipeline-c1a)."
    )
    assert contains(
        OPERATOR_CONTRACT_PATH,
        "a hero carrying only a verdict line, or a figure without the four counts",
    ), "OSV1-024: Conformance 5's bad half moved in the contract -- re-review the row."


def test_row_osv1_025() -> None:
    """Conformance 6 pin: no Tier-A kit, so the register is checked only here."""
    assert not _exists(TIER_A_KIT), (
        f"OSV1-025 (Conformance 6): {TIER_A_KIT} now exists. Make sure it reads THIS "
        f"ledger's register (OSV1-006) rather than growing its own copy -- two censuses "
        f"will disagree, silently (work_item_pipeline-c1a)."
    )
    assert contains(OPERATOR_CONTRACT_PATH, 'style="color:#D9A253"'), (
        "OSV1-025: Conformance 6's named bad specimen moved in the contract -- re-review the row."
    )


def test_row_osv1_026() -> None:
    """Conformance 7 pin: no Tier-A kit, so empty-vs-populated is uncompared."""
    assert not _exists(TIER_A_KIT), (
        f"OSV1-026 (Conformance 7): {TIER_A_KIT} now exists -- re-derive from a real "
        f"two-render comparison (work_item_pipeline-c1a)."
    )
    assert contains(
        OPERATOR_CONTRACT_PATH, "a render that drops empty widgets, or renders a hero-scale `0`"
    ), "OSV1-026: Conformance 7's bad half moved in the contract -- re-review the row."


# --------------------------------------------------------------- OSV1-027..-034
# The Freeze Bar conditions that carry an in-repo byte check.


def test_row_osv1_027() -> None:
    """Freeze 1 pin: the Tier-A kit neither exists nor runs in any gate.

    Both halves are pinned, because a kit that exists but runs in nothing is
    the exact failure this repo already measured once (CCV1-022: a whole suite
    of green claims nobody had ever executed).
    """
    assert not _exists(TIER_A_KIT), (
        f"OSV1-027 (Freeze 1): {TIER_A_KIT} now exists. Freeze 1 ALSO requires it to "
        f"run on every pull request -- do not flip this row on the file alone "
        f"(work_item_pipeline-c1a)."
    )
    # Matched on the KIT PATH, never on the word "conformance": the Makefile
    # and ci.yml already say "conformance ledger" about Tier 4, and a probe
    # that a pre-existing comment satisfies is a probe asserting nothing.
    #
    # NARROWED 2026-09-05 by work_item_pipeline-qgo (an out-of-scope edit to
    # THIS row's probe, named in that lane's summary): when this pin was
    # written no `tests/conformance` path was wired anywhere, so bare
    # containment WAS the Tier-A signal. The Tier-B browser kit is now wired
    # (Makefile `test-conformance-b`, CI "Tier 7"), which would fire this pin
    # for a reason that has nothing to do with Freeze 1. The Tier-B path is
    # therefore removed before the check, leaving the original question
    # intact: is any conformance wiring OTHER than Tier-B's present, i.e. is
    # the Tier-A half landing? Neither the disposition nor the row moved.
    tier_b_dir = TIER_B_KIT.rsplit("/", 1)[0]
    for path, where in ((MAKEFILE, "the Makefile"), (CI_WORKFLOW, "ci.yml")):
        remainder = read(path).replace(tier_b_dir, "").replace(TIER_B_KIT, "")
        assert "tests/conformance" not in remainder, (
            f"OSV1-027 (Freeze 1): {where} now wires a conformance path that is not "
            f"the Tier-B browser kit -- the Tier-A wiring half is landing. Re-derive "
            f"(work_item_pipeline-c1a)."
        )


def test_row_osv1_028() -> None:
    """Freeze 2 CONFORMS: all four sub-conditions, checked independently.

    The seed said a partial build satisfies none of them, so none of them is
    inferred from another: the path, the PIN, the isolation and the OWN TIER
    are four separate assertions.
    """
    assert _exists(TIER_B_KIT), f"OSV1-028 (Freeze 2): {TIER_B_KIT} is gone."

    pinned = "playwright=="
    manifest = read(PYPROJECT)
    assert pinned in manifest, (
        "OSV1-028 (Freeze 2): `pyproject.toml` no longer pins playwright to an EXACT "
        "version. A playwright release pins exactly one chromium build, and that pin "
        "is the whole of 'a pinned chromium' -- an unpinned browser makes every "
        "recorded contrast ratio and pixel count unreproducible."
    )
    version = manifest.split(pinned, 1)[1].split('"', 1)[0].strip()
    recorded = tier_b_summary()["browser"]
    assert recorded.get("playwright") == version, (
        f"OSV1-028 (Freeze 2): the manifest pins playwright {version!r} but the "
        f"Tier-B run summary was produced by {recorded.get('playwright')!r}. The "
        f"recorded numbers came from a different browser build than the one the repo "
        f"now pins -- re-run `make test-conformance-b`."
    )
    assert recorded.get("name") == "chromium" and recorded.get("version"), (
        f"OSV1-028 (Freeze 2): the run summary names no chromium build ({recorded})."
    )

    makefile = read(MAKEFILE)
    assert "test-conformance-b:" in makefile and "playwright-install" in makefile, (
        "OSV1-028 (Freeze 2): the Makefile no longer carries `test-conformance-b` "
        "(and its `playwright-install` dependency). Existing is not the same as "
        "running."
    )
    ci = read(CI_WORKFLOW)
    assert "Tier 7 -- operator-surface conformance (Tier B, browser)" in ci, (
        "OSV1-028 (Freeze 2): CI no longer runs the browser tier as its OWN step. A "
        "browser tier folded into another tier is not the tier Freeze 2 asks for."
    )
    assert "-m tier_b" in ci and "playwright install" in ci, (
        "OSV1-028 (Freeze 2): the CI step no longer selects the `tier_b` marker or no "
        "longer installs chromium -- either way the tier runs nothing."
    )
    kit = read(REPO_ROOT / "tests/conformance/operator_surface/browser/conftest.py")
    assert "isolated_dolt_server" in kit and "port=0" in kit, (
        "OSV1-028 (Freeze 2): the kit no longer states its isolation -- the inherited "
        "isolated dolt server, or the ephemeral `port=0` bind. The live service must "
        "be unreachable from this tier by construction, not by luck."
    )


def test_row_osv1_029() -> None:
    """Freeze 3 CONFORMS: artifacts are emitted, AND this ledger re-reads them.

    The row's own closing condition, written at seed: "a stable on-disk
    artifact path with a documented JSON shape, and ledger probes here that
    RE-READ those numbers rather than trusting the browser test's own
    pass/fail." This probe checks both halves -- the summary parses and names
    its schema and browser, and the kit is structurally incapable of asserting
    on a screenshot.
    """
    data = tier_b_summary()
    assert data.get("recorded_at") and data.get("browser"), (
        "OSV1-029 (Freeze 3): the Tier-B run summary carries no provenance "
        "(recorded_at / browser). A number with no named engine behind it is not "
        "reproducible, which is the whole reason Freeze 2 pins the browser."
    )
    for check in ("calm.zero_alarm_pixels", "swap.survives", "perception.floors"):
        assert data["checks"].get(check), (
            f"OSV1-029 (Freeze 3): the run summary carries no `{check}` numbers. "
            f"Every Tier-B check must emit artifacts the orchestrator re-checks."
        )

    kit = read(REPO_ROOT / TIER_B_KIT)
    writes, reads = kit.count("artifacts.write("), kit.count("_artifacts.read(")
    assert writes > 0 and reads >= writes, (
        f"OSV1-029 (Freeze 3): the Tier-B kit performs {writes} artifact write(s) but "
        f"only {reads} read-back(s). Measure -> write -> read back -> assert is the "
        f"discipline this row records: a check that writes an artifact and then "
        f"asserts on the value still in its own local variable is a self-report, and "
        f"the artifact it left behind is decoration."
    )
    assert "save_screenshot" in kit and "assert" not in kit.split("save_screenshot")[0][-200:], (
        "OSV1-029 (Freeze 3): a screenshot appears to be feeding an assertion. "
        "Screenshots are evidence for a human's Freeze 8 look, never an input to a "
        "pass -- 'no check reports a rendered impression as a pass'."
    )
    artifacts_module = read(REPO_ROOT / "tests/conformance/operator_surface/browser/_artifacts.py")
    assert "carries an empty measurement" in artifacts_module, (
        "OSV1-029 (Freeze 3): the artifact reader no longer refuses an empty "
        "measurement. A check that wrote `{}` and asserted `.get(..., 0) == 0` would "
        "pass forever while measuring nothing."
    )


def test_row_osv1_030() -> None:
    """Freeze 4 GAP pin: Conformance 1-4 demonstrated, 5-7 not.

    Red for the half that has not been run, and the probe re-reads the half
    that HAS -- so the demonstrated bad halves cannot quietly stop
    discriminating while this row waits on the other kit.
    """
    assert not _exists(TIER_A_KIT), (
        f"OSV1-030 (Freeze 4) PIN BROKE THE RIGHT WAY: {TIER_A_KIT} now exists. "
        f"'Demonstrated by running it' is the whole clause -- record WHICH revert "
        f"produced WHICH failure for Conformance 5-7, the way CCV1-023 did for the "
        f"custody family, before flipping this row (work_item_pipeline-c1a)."
    )
    demonstrated = {
        ("calm.zero_alarm_pixels", "bad-alarm-chip/L0/dark"),
        ("calm.zero_alarm_pixels", "bad-retired-palette/L0/dark"),
        ("calm.zero_alarm_pixels", "bad-alarm-fixture/L0/dark"),
        ("state.not_colour_only", "bad-wordless-chips/L1/dark"),
        ("swap.survives", "bad-naive-replacement/L0/dark"),
        ("swap.survives", "bad-naive-replacement-reflow/L0/dark"),
        ("perception.floors", "bad-wide-element/L0/430/dark"),
        ("perception.floors", "bad-low-contrast/L0/light"),
    }
    checks = tier_b_summary()["checks"]
    missing = sorted(f"{c}/{s}" for c, s in demonstrated if s not in checks.get(c, {}))
    assert not missing, (
        f"OSV1-030 (Freeze 4): {len(missing)} Conformance 1-4 bad half/halves were "
        f"not run in the recorded Tier-B run: {missing}. A bad half that has never "
        f"been executed is a claim."
    )
    stripped = checks["state.not_colour_only"]["bad-wordless-chips/L1/dark"]
    assert stripped["stripped"] > 0 and stripped["wordless"] > 0, (
        "OSV1-030 (Freeze 4): the Conformance 2 bad half stopped discriminating -- "
        f"it stripped {stripped['stripped']} chips and still reported "
        f"{stripped['wordless']} wordless."
    )


def test_row_osv1_031() -> None:
    """Freeze 5 pin: at least one Core-carrying row is still red.

    The only probe in this family that reads the LEDGER rather than the repo.
    It goes red when the last Core row turns green -- which is the signal to
    flip this row, not a failure.
    """
    core_rows = [
        r
        for r in rows()
        if r["id"].startswith("OSV1-") and r["contract"].get("clause", "").startswith("Core ")
    ]
    assert len(core_rows) == 19, (
        f"OSV1-031 (Freeze 5): the Core-carrying row population moved from 19 to "
        f"{len(core_rows)}. Splitting or merging a row changes what this gate counts -- "
        f"re-derive."
    )
    red = sorted(r["id"] for r in core_rows if r["disposition"] in {"GAP", "VIOLATION"})
    assert red, (
        "OSV1-031 (Freeze 5) PIN BROKE THE RIGHT WAY: every Core-carrying row now reads "
        "CONFORMS or NOT-ASSERTABLE. Confirm each formerly-red row was RE-DERIVED from "
        "real measurement (not flipped because a kit file appeared), then flip OSV1-031 "
        "to CONFORMS and retarget this probe to assert no Core row is red "
        "(work_item_pipeline-umm)."
    )
    assert len(red) == 10, (
        f"OSV1-031 (Freeze 5): pinned 10 red Core-carrying rows, observed {len(red)}: "
        f"{red}. Movement in either direction means this gate's tally changed -- update "
        f"the pin and the row's notes in the same change."
    )
    assert {r["id"] for r in core_rows if r["disposition"] == "NOT-ASSERTABLE"} == {
        "OSV1-018",
        "OSV1-019",
    }, (
        "OSV1-031 (Freeze 5): the NOT-ASSERTABLE Core rows changed. Freeze 5's second "
        "limb admits exactly the clauses the CONTRACT declares unassertable, each with "
        "its cadence named -- a new one is a downgrade, not a pass."
    )


def test_row_osv1_032() -> None:
    """Freeze 6 pin: the register is enumerated, but literal sites remain.

    Freeze 6's "no literal colour, font, or size site remaining" reads through
    Core 4, so the 2026-09-04 true-up widened what "site" means here too: an
    inline `style=` attribute OR a declaration in a `<style>` block outside the
    token module. Both halves are pinned separately -- migrating all 66 inline
    sites while leaving webtrust.py's page-local stylesheet in place must NOT
    read as this gate closing.
    """
    literal = style_sites_in(LITERAL)
    assert literal, (
        "OSV1-032 (Freeze 6) PIN BROKE THE RIGHT WAY (inline half): zero literal "
        "colour/font/size INLINE sites remain. If the `<style>`-block half below is "
        "also at zero, both of Freeze 6's conjuncts now hold -- flip OSV1-032 (and "
        "OSV1-005) to CONFORMS and retarget both probes IN THE SAME CHANGE "
        "(work_item_pipeline-np3). Note that a register at zero also fires Backlogged "
        "2's promotion trigger."
    )
    assert style_block_literal_sites(), (
        "OSV1-032 (Freeze 6) PIN BROKE THE RIGHT WAY (`<style>`-block half): zero "
        "literal colour/font/size declarations remain in any `<style>` block outside "
        "the token module. That is webtrust.py's retired palette closing -- the half "
        "Core 4's frozen text could not reach until the 2026-09-04 true-up. Re-derive "
        "this row and OSV1-005 in the same change (work_item_pipeline-np3)."
    )
    assert len(style_sites_in("COMPUTED")) == 23, (
        "OSV1-032 (Freeze 6): the enumerated half moved -- see OSV1-006, which owns "
        "the register itself."
    )


#: A quotation the contract ATTRIBUTES -- its own `*"..."*` convention, used
#: for exactly the three attributed quotations in the Changelog and nowhere
#: else. A new one appearing that this probe cannot classify goes red.
_ATTRIBUTED_QUOTE = re.compile(r'\*"(.+?)"\*', re.DOTALL)
#: An in-repo source citation: `file.py:LINE` or `file.py:LINE-LINE`.
_SOURCE_CITE = re.compile(r"`([A-Za-z_][A-Za-z_0-9]*\.py):(\d+(?:-\d+)?)`")
#: The attribution that marks a quotation as a PERSON's words rather than a
#: file's. Such a quote cites no file, so Freeze 7's substring rule cannot
#: reach it -- it is REPORTED as unverifiable, never silently passed.
_SPEAKER_MARKER = "literal:"

#: The two spans the Changelog attributes to `webapp.py:37-44`, enumerated so
#: that deleting one is caught rather than trivially satisfying the loop below.
_CHANGELOG_SOURCE_QUOTES = (
    "the dashboard's hero is the AGE of the oldest unclaimed item, never a count",
    "a giant `0` trains a viewer to stop looking. An age reads as neglect",
)


def test_row_osv1_033() -> None:
    """Freeze 7 CONFORMS: every quotation the contract attributes to an in-repo
    file verifies verbatim against that file.

    RETARGETED 2026-09-04 by the owner-ratified DRAFT true-up #1. At seed this
    row was a GAP and this probe PINNED the failure: the Changelog's
    `**never a count**` carried markdown emphasis the cited source does not,
    and markup is part of the exact match. The true-up struck the emphasis, the
    pin went red the way a pin is meant to, and this is the real check that
    replaced it IN THE SAME CHANGE.

    WHAT IT PROVES, AND WHAT IT DOES NOT. It proves that every attributed
    quotation is either verbatim in the file it cites, or is a speaker's words
    citing no file at all. It CANNOT verify the contract's quotations of Brief
    A and Brief B (Backlogged 2 quotes one): those documents live outside this
    repository, so an in-repo check must report them as out-of-repo rather than
    silently pass them -- see the row's notes.
    """
    contract = read(OPERATOR_CONTRACT_PATH)
    source = collapse(read(WEBAPP))
    changelog = contract[contract.index("## Changelog") :]

    cited = {m.group(1) for m in _SOURCE_CITE.finditer(changelog)}
    assert cited == {"webapp.py"}, (
        f"OSV1-033 (Freeze 7): the Changelog's in-repo source citations moved -- this "
        f"probe verifies against `webapp.py` because that was the only file cited; "
        f"observed {sorted(cited)}. Extend this probe to the new file rather than "
        f"leaving it silently narrow."
    )

    for m in _ATTRIBUTED_QUOTE.finditer(contract):
        quote = collapse(m.group(1))
        if collapse(quote) in source:
            continue
        window = contract[max(0, m.start() - 40) : m.start()]
        assert _SPEAKER_MARKER in window, (
            f"OSV1-033 (Freeze 7) REGRESSION: an attributed quotation neither verifies "
            f"against `webapp.py` nor is marked as a speaker's words "
            f"({_SPEAKER_MARKER!r} in the 40 characters before it):\n"
            f"  {quote[:160]}\n"
            f"Freeze 7 requires every quote to be a contiguous, whitespace-collapsed "
            f"substring of the file it cites -- markdown markup included. Either make "
            f"it byte-exact, or attribute it to its speaker."
        )

    for quote in _CHANGELOG_SOURCE_QUOTES:
        assert collapse(quote) in collapse(changelog), (
            f"OSV1-033 (Freeze 7): the Changelog no longer carries the quotation "
            f"{quote[:60]!r}... This probe verifies the quotations that ARE there; "
            f"deleting one must not be how this row stays green. Re-review."
        )
        assert collapse(quote) in source, (
            f"OSV1-033 (Freeze 7) REGRESSION: the Changelog quotation {quote[:60]!r}... "
            f"no longer verifies against webapp.py. Either the contract's quote "
            f"drifted, or webapp.py:37-44's prose moved under it -- both are Freeze 7 "
            f"failures and both need the quote re-derived from the source."
        )

    assert "**never a count**" not in contract, (
        "OSV1-033 (Freeze 7) REGRESSION: the `**`-emphasised form of the "
        "`webapp.py:38-39` quotation is back in the contract. That is the exact defect "
        "the 2026-09-04 true-up corrected -- markup is part of the exact match, so an "
        "emphasised quote is not a substring of the plain source sentence."
    )
    assert "**never a count**" not in source, (
        "OSV1-033 (Freeze 7): webapp.py now carries the markdown-emphasised form. That "
        "would satisfy the quote from the wrong end -- source prose should not acquire "
        "markup to make a contract quotation verify. Re-derive."
    )


def test_row_osv1_034() -> None:
    """Freeze 8 pin: the Changelog records no look at the rendered pages.

    HONEST LIMIT, and it is irreducible: this can only ever assert that a
    RECORD exists, never that the owner looked. Freeze 8 says "never a machine
    check" for exactly that reason.
    """
    contract = read(OPERATOR_CONTRACT_PATH)
    changelog = contract[contract.index("## Changelog") :]
    for viewport in ("430", "900", "1280"):
        assert viewport not in changelog, (
            f"OSV1-034 (Freeze 8) PIN BROKE THE RIGHT WAY: the Changelog now mentions "
            f"{viewport}px. If the OWNER looked and an owner-ratified amendment "
            f"recorded it, flip this row. If an agent wrote that entry, revert it -- "
            f"it is a fabricated attestation (work_item_pipeline-eah)."
        )
    assert "looked at the rendered" not in changelog, (
        "OSV1-034 (Freeze 8): the Changelog now records a look at the rendered pages. "
        "Confirm it was the OWNER's, then flip the row."
    )
