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

import ast
import re

from ._support import (
    CHARTSVG,
    LITERAL,
    OPERATOR_CONTRACT_PATH,
    PINNING_DISPOSITIONS,
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


def _exists(rel: str) -> bool:
    return (REPO_ROOT / rel).exists()


# ---------------------------------------------------------------------------
# Reading the Tier-A conformance kit.
#
# Several rows below are about the KIT rather than about `src/` -- whether the
# check the contract names is implemented, whether it ships a bad half, and
# whether its good half is still DEFERRED against an open row. All three go
# through `read()` so the mutation harness's reader injection reaches them.
# ---------------------------------------------------------------------------


def _kit_source() -> str:
    return read(REPO_ROOT / TIER_A_KIT)


def _kit_defs(kit: str) -> frozenset[str]:
    return frozenset(
        n.name
        for n in ast.walk(ast.parse(kit))
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    )


def _kit_bad_halves(kit: str, good: str) -> list[str]:
    """The bad-half tests paired with a check's good half, by name."""
    return sorted(n for n in _kit_defs(kit) if n.startswith(f"{good}_bad_half_"))


def _kit_deferred_rows(kit: str, test_name: str) -> frozenset[str]:
    """Row ids named in `test_name`'s `xfail` reason -- empty if not deferred.

    A kit test marked `xfail(strict=True)` is a check that RUNS and currently
    FAILS, with the ledger row that owns the failure named in its reason. That
    marker is what a red Conformance row pins: when the product fix lands the
    test XPASSes, the run fails, and the marker and the row move together.
    """
    for node in ast.walk(ast.parse(kit)):
        if not isinstance(node, ast.FunctionDef) or node.name != test_name:
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            if not ast.unparse(dec.func).endswith("xfail"):
                continue
            for kw in dec.keywords:
                if kw.arg == "reason" and isinstance(kw.value, ast.Constant):
                    return frozenset(re.findall(r"OSV1-\d{3}", str(kw.value.value)))
            return frozenset()
    return frozenset()


def _widgets_function(name: str) -> str:
    """One function's source out of `widgets.py`, via the patched reader."""
    src = read(WIDGETS)
    lines = src.splitlines()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "\n".join(lines[node.lineno - 1 : (node.end_lineno or node.lineno)])
    raise AssertionError(f"widgets.py no longer defines {name!r}")


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
    """Core 2 GAP pin (calm pixels): no pixel sweep exists, and the retired
    palette that a sweep would catch is still in the tree.
    """
    assert not _exists(TIER_B_KIT), (
        f"OSV1-003 (Core 2): {TIER_B_KIT} now exists. Re-derive this row from the "
        f"sweep's EMITTED ARTIFACT (Freeze 3 / ruling 6) -- never from the fact that "
        f"a file appeared (work_item_pipeline-qgo)."
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


# --------------------------------------------------------------- OSV1-004


def test_row_osv1_004() -> None:
    """Core 3 CONFORMS: the rendered check exists, is not deferred, and the
    chip vocabulary it walks still gives every status a WORD.

    This row rests on the kit's real result over rendered L0/L1/L2 (recorded
    in the row itself), which no in-process probe can re-run. So this probe
    asserts the two things that CAN still be seen going wrong from here: the
    check disappearing or being deferred, and a status losing its word in the
    map the check walks.
    """
    assert _exists(TIER_A_KIT), (
        f"OSV1-004 (Core 3) REGRESSION: {TIER_A_KIT} is gone. Core 3's check is Tier "
        f"A and scoped to RENDERED fixtures -- without the kit nothing asserts it, and "
        f"this row has no basis to be green."
    )
    kit = _kit_source()
    assert {"check_state_not_colour_only", "test_state_not_colour_only"} <= _kit_defs(kit), (
        "OSV1-004 (Core 3) REGRESSION: the kit no longer implements "
        "`state.not_colour_only` over rendered pages."
    )
    assert not _kit_deferred_rows(kit, "test_state_not_colour_only"), (
        "OSV1-004 (Core 3) REGRESSION: the rendered Core 3 check is now marked xfail. "
        "This row is CONFORMS because the check PASSES; a deferred check is a red row."
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


#: THE exemption register Core 4 names -- "The register lives in `ledger/`, not
#: in this contract, so that shrinking it is a convergent change requiring no
#: amendment." Module-level rather than local to `test_row_osv1_006` below so
#: that the Tier-A conformance kit
#: (`tests/conformance/operator_surface/test_tier_a.py`, Conformance 6) reads
#: THIS register rather than growing a second copy: OSV1-025's own notes name
#: that as the failure to avoid, because two censuses disagree silently.
EXEMPTION_REGISTER: frozenset[str] = frozenset(
    {
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
)


def test_row_osv1_006() -> None:
    """Core 4 CONFORMS: computed-geometry sites are EXACTLY the register.

    This is the exemption register itself (Phase-1 ruling Need 2 put it in
    `ledger/` so shrinking it needs no amendment). Shrinking passes only after
    `EXEMPTION_REGISTER` above is shrunk to match; GROWING fails immediately,
    which is the direction that matters.
    """
    register = EXEMPTION_REGISTER
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
    """Core 6 GAP pin: no browser kit, and the swap restores exactly two
    things -- neither of them the pause control or a live region.
    """
    assert not _exists(TIER_B_KIT), (
        f"OSV1-008 (Core 6): {TIER_B_KIT} now exists -- re-derive this row from the "
        f"post-swap DOM SNAPSHOT it emits (work_item_pipeline-qgo)."
    )
    theme = read(WEBTHEME)
    assert "function captureState()" in theme and "function restoreState(state)" in theme, (
        "OSV1-008 (Core 6): the swap's capture/restore pair is gone -- the mechanism "
        "this row measures moved. Re-derive."
    )
    restore = theme[theme.index("function restoreState(state)") :][:400]
    assert "openIds" in restore and "scrollTo" in restore, (
        "OSV1-008 (Core 6): `restoreState` no longer restores open disclosures and scroll position."
    )
    assert "__wtRefreshPaused" not in restore, (
        "OSV1-008 (Core 6) PIN BROKE THE RIGHT WAY: `restoreState` now touches the "
        "pause flag. The pause CONTROL's state surviving the swap is one of the four "
        "things Core 6 names -- flip the row only after the browser kit MEASURES it, "
        "and retarget this probe in the same change (work_item_pipeline-qgo)."
    )
    assert count(WEBAPP, "aria-live") == 0 and count(WEBTHEME, "aria-live") == 0, (
        "OSV1-008 (Core 6) PIN BROKE THE RIGHT WAY: an `aria-live` region appeared. "
        "Core 6's announcement half had NO implementation at seed -- if one landed, "
        "re-derive this row from the Tier-B snapshot rather than from its presence."
    )


# --------------------------------------------------------------- OSV1-009


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
    """Core 7 GAP pin (rendered half): nothing in this repo drives a browser."""
    assert not _exists(TIER_B_KIT), (
        f"OSV1-010 (Core 7): {TIER_B_KIT} now exists -- re-derive this row from the "
        f"computed contrast ratios, bounding boxes and motion trace it EMITS, which "
        f"the ledger must re-check itself (Freeze 3 / ruling 6)."
    )
    for driver in BROWSER_DRIVERS:
        assert not _repo_mentions(driver), (
            f"OSV1-010 (Core 7) PIN BROKE THE RIGHT WAY: {driver!r} now appears in the "
            f"repo. A browser is being driven somewhere -- re-derive this row, and "
            f"OSV1-003, -008, -020..-023, from what it actually measures."
        )
    assert contains(WEBTHEME, "--u:44px"), (
        "OSV1-010 (Core 7): the 44px target token is gone -- the thing the Tier-B "
        "bounding-box check exists to verify."
    )


# --------------------------------------------------------------- OSV1-011


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
    """Core 8 VIOLATION pin: two widget renderers still have no empty branch,
    and the kit's two `calm.keeps_slot` halves are still deferred against this
    row.

    Pinned on the RENDERERS rather than on a rendered page, because that is
    what an in-process probe can see: `render_attention_queue` and
    `render_agents_panel` return their container unconditionally, so an empty
    one is a slot with nothing in it. Giving either an empty branch flips this
    pin -- which is the fix landing.
    """
    for func in ("render_attention_queue", "render_agents_panel"):
        body = _widgets_function(func)
        assert "if not data[" not in body, (
            f"OSV1-012 (Core 8) PIN BROKE THE RIGHT WAY: `{func}` now has an empty "
            f"branch. If it emits the empty SENTENCE Core 8 requires, re-run the "
            f"Tier-A kit's `calm.keeps_slot` halves, flip OSV1-012 to CONFORMS, delete "
            f"their xfail markers and retarget this probe -- all in the same change "
            f"(work_item_pipeline-c1a)."
        )
    kit = _kit_source()
    for test_name in ("test_calm_keeps_slot", "test_calm_keeps_slot_l1"):
        assert "OSV1-012" in _kit_deferred_rows(kit, test_name), (
            f"OSV1-012 (Core 8) PIN BROKE THE RIGHT WAY: the kit's `{test_name}` is no "
            f"longer deferred against this row. A passing good half is the fix -- flip "
            f"the row in the same change."
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
    """Conformance 1 pin: no browser kit, so no calm pixel sweep exists."""
    assert not _exists(TIER_B_KIT), (
        f"OSV1-020 (Conformance 1): {TIER_B_KIT} now exists. Freeze 4 requires the BAD "
        f"half to fail against the defect it names, DEMONSTRATED BY RUNNING IT -- "
        f"re-derive this row from that demonstration, never from the file's existence "
        f"(work_item_pipeline-qgo)."
    )
    assert contains(
        OPERATOR_CONTRACT_PATH, "the sweep reports zero pixels matching `--alarm` or `--blocked`"
    ), "OSV1-020: Conformance 1's good half moved in the contract -- re-review the row."


def test_row_osv1_021() -> None:
    """Conformance 2 pin: the Tier-A half landed; the Tier-B hue half has not,
    and that absence is what keeps this row red."""
    assert not _exists(TIER_B_KIT), (
        f"OSV1-021 (Conformance 2): {TIER_B_KIT} now exists. This is the one fixture "
        f"that spans BOTH tiers -- the Tier-A accessible-name half already landed "
        f"(work_item_pipeline-c1a, measured in OSV1-004); re-derive this row from the "
        f"Tier-B hue half's own demonstrated pair (work_item_pipeline-qgo)."
    )
    kit = _kit_source()
    assert "check_state_not_colour_only" in _kit_defs(kit), (
        "OSV1-021 (Conformance 2): the Tier-A half is gone from the kit. This row is "
        "red on the Tier-B half ONLY -- losing the Tier-A half is a second, new defect."
    )
    assert _kit_bad_halves(kit, "test_state_not_colour_only"), (
        "OSV1-021 (Conformance 2): the Tier-A half no longer ships a bad half. A "
        "fixture whose bad half nobody runs is a claim, not a fixture (Freeze 4)."
    )
    assert contains(
        OPERATOR_CONTRACT_PATH, "fixture whose status chips carry only a status class"
    ), "OSV1-021: Conformance 2's bad half moved in the contract -- re-review the row."


def test_row_osv1_022() -> None:
    """Conformance 3 pin: no browser kit, so body-swap survival is untested."""
    assert not _exists(TIER_B_KIT), (
        f"OSV1-022 (Conformance 3): {TIER_B_KIT} now exists -- re-derive from the "
        f"post-swap DOM snapshot and the demonstrated bad half (work_item_pipeline-qgo)."
    )
    assert contains(WEBTHEME, "document.body.innerHTML = doc.body.innerHTML"), (
        "OSV1-022 (Conformance 3): the whole-body innerHTML swap is gone. That IS the "
        "mechanism Conformance 3's bad half describes -- if the swap changed shape, "
        "the fixture's premise changed with it. Re-derive this row and OSV1-008."
    )


def test_row_osv1_023() -> None:
    """Conformance 4 pin: no viewport sweep, and the breakpoints it must sweep."""
    assert not _exists(TIER_B_KIT), (
        f"OSV1-023 (Conformance 4): {TIER_B_KIT} now exists -- re-derive from the "
        f"emitted scrollWidth/clientWidth, bounding-box and contrast numbers "
        f"(work_item_pipeline-qgo)."
    )
    theme = read(WEBTHEME)
    for width in ("1280px", "900px", "430px"):
        assert f"max-width:{width}" in theme or f"min-width:{width}" in theme, (
            f"OSV1-023 (Conformance 4): the {width} breakpoint is gone from "
            f"webtheme.py. Conformance 4 sweeps 430, 900 and 1280 -- a viewport the "
            f"stylesheet no longer knows about is a different test."
        )


def test_row_osv1_024() -> None:
    """Conformance 5 pin: the fixture exists and discriminates, and its GOOD
    half is still deferred against OSV1-001."""
    kit = _kit_source()
    assert "check_hero_velocity_and_counts" in _kit_defs(kit), (
        f"OSV1-024 (Conformance 5): {TIER_A_KIT} no longer implements "
        f"`hero.velocity_and_counts` at the location the contract names."
    )
    assert _kit_bad_halves(kit, "test_hero_velocity_and_counts"), (
        "OSV1-024 (Conformance 5): the fixture no longer ships a bad half -- a fixture "
        "that cannot be watched failing is a claim (Freeze 4)."
    )
    assert "OSV1-001" in _kit_deferred_rows(kit, "test_hero_velocity_and_counts"), (
        "OSV1-024 (Conformance 5) PIN BROKE THE RIGHT WAY: the good half is no longer "
        "deferred against OSV1-001. If the hero now carries velocity with its window "
        "and all four counts, flip OSV1-001 AND this row and retarget both probes in "
        "the same change (work_item_pipeline-ujy)."
    )
    assert row("OSV1-001")["disposition"] in PINNING_DISPOSITIONS, (
        "OSV1-024 (Conformance 5) PIN BROKE THE RIGHT WAY: OSV1-001 is no longer red, "
        "so Conformance 5's good half should now pass against a conforming hero. "
        "Re-derive this row from the PASSING pair, never from the fixture's presence."
    )
    assert contains(
        OPERATOR_CONTRACT_PATH,
        "a hero carrying only a verdict line, or a figure without the four counts",
    ), "OSV1-024: Conformance 5's bad half moved in the contract -- re-review the row."


def test_row_osv1_025() -> None:
    """Conformance 6 pin: the fixture exists, reads THIS ledger's register, and
    its GOOD half is still deferred against OSV1-005."""
    kit = _kit_source()
    assert "check_visual_single_source" in _kit_defs(kit), (
        f"OSV1-025 (Conformance 6): {TIER_A_KIT} no longer implements "
        f"`visual.single_source` at the location the contract names."
    )
    assert _kit_bad_halves(kit, "test_visual_single_source"), (
        "OSV1-025 (Conformance 6): the fixture no longer ships a bad half (Freeze 4)."
    )
    assert "EXEMPTION_REGISTER" in kit, (
        "OSV1-025 (Conformance 6): the kit stopped importing this ledger's exemption "
        "register. ONE census, ONE register (Phase-1 ruling Need 2) -- a second copy "
        "disagrees with this one, silently."
    )
    assert "OSV1-005" in _kit_deferred_rows(kit, "test_visual_single_source"), (
        "OSV1-025 (Conformance 6) PIN BROKE THE RIGHT WAY: the good half is no longer "
        "deferred against OSV1-005. Flip OSV1-005 AND this row and retarget both "
        "probes in the same change (work_item_pipeline-np3)."
    )
    assert row("OSV1-005")["disposition"] in PINNING_DISPOSITIONS, (
        "OSV1-025 (Conformance 6) PIN BROKE THE RIGHT WAY: OSV1-005 is no longer red, "
        "so Conformance 6's good half should now pass. Re-derive from the PASSING pair."
    )
    assert contains(OPERATOR_CONTRACT_PATH, 'style="color:#D9A253"'), (
        "OSV1-025: Conformance 6's named bad specimen moved in the contract -- re-review the row."
    )


def test_row_osv1_026() -> None:
    """Conformance 7 pin: the two-render fixture exists and discriminates, and
    its GOOD halves are still deferred against OSV1-012."""
    kit = _kit_source()
    assert "check_calm_keeps_slot" in _kit_defs(kit), (
        f"OSV1-026 (Conformance 7): {TIER_A_KIT} no longer implements "
        f"`calm.keeps_slot` at the location the contract names."
    )
    assert _kit_bad_halves(kit, "test_calm_keeps_slot"), (
        "OSV1-026 (Conformance 7): the fixture no longer ships a bad half (Freeze 4)."
    )
    assert "OSV1-012" in _kit_deferred_rows(kit, "test_calm_keeps_slot"), (
        "OSV1-026 (Conformance 7) PIN BROKE THE RIGHT WAY: the good half is no longer "
        "deferred against OSV1-012. Flip OSV1-012 AND this row and retarget both "
        "probes in the same change (work_item_pipeline-c1a)."
    )
    assert row("OSV1-012")["disposition"] in PINNING_DISPOSITIONS, (
        "OSV1-026 (Conformance 7) PIN BROKE THE RIGHT WAY: OSV1-012 is no longer red, "
        "so Conformance 7's good halves should now pass. Re-derive from the PASSING pair."
    )
    assert contains(
        OPERATOR_CONTRACT_PATH, "a render that drops empty widgets, or renders a hero-scale `0`"
    ), "OSV1-026: Conformance 7's bad half moved in the contract -- re-review the row."


# --------------------------------------------------------------- OSV1-027..-034
# The Freeze Bar conditions that carry an in-repo byte check.


def test_row_osv1_027() -> None:
    """Freeze 1 CONFORMS: the Tier-A kit exists AND runs in a real gate.

    Both halves are asserted, because a kit that exists but runs in nothing is
    the exact failure this repo already measured once (CCV1-022: a whole suite
    of green claims nobody had ever executed). Matched on the KIT PATH, never
    on the word "conformance": the Makefile and ci.yml already say "conformance
    ledger" about Tier 4, and a check a pre-existing comment satisfies asserts
    nothing.
    """
    assert _exists(TIER_A_KIT), f"OSV1-027 (Freeze 1) REGRESSION: {TIER_A_KIT} is gone."
    make = read(MAKEFILE)
    assert "tests/conformance" in make and "test-conformance-a:" in make, (
        "OSV1-027 (Freeze 1) REGRESSION: the Makefile no longer carries a target "
        "covering tests/conformance. Existing is not the same as running."
    )
    ci = read(CI_WORKFLOW)
    assert "tests/conformance/operator_surface" in ci, (
        "OSV1-027 (Freeze 1) REGRESSION: ci.yml no longer runs the Tier-A kit -- "
        "Freeze 1's second half is 'runs on every pull request'."
    )
    assert "pull_request" in ci, (
        "OSV1-027 (Freeze 1) REGRESSION: the workflow that runs the kit no longer "
        "triggers on pull_request."
    )
    kit = _kit_source()
    assert "TIER_A_CHECKS" in kit and _kit_defs(kit) >= {
        "test_every_tier_a_machine_check_the_contract_names_is_implemented_here",
        "test_every_check_ships_a_bad_half",
    }, (
        "OSV1-027 (Freeze 1) REGRESSION: the kit dropped its own coverage tripwires. "
        "Without them it can quietly cover less of the contract than it claims, which "
        "is the failure Freeze 1 and Freeze 4 exist to prevent."
    )


def test_row_osv1_028() -> None:
    """Freeze 2 pin: no browser kit path, and no browser driver anywhere."""
    assert not _exists(TIER_B_KIT), (
        f"OSV1-028 (Freeze 2): {TIER_B_KIT} now exists. Freeze 2 has THREE further "
        f"conditions -- a PINNED chromium, ISOLATED fixture data, and its OWN CI tier. "
        f"A partial build satisfies none of them (work_item_pipeline-qgo)."
    )
    for driver in BROWSER_DRIVERS:
        assert not _repo_mentions(driver), (
            f"OSV1-028 (Freeze 2): {driver!r} now appears in the repo -- a browser is "
            f"being driven. Re-derive this row and every row that depends on it."
        )


def test_row_osv1_029() -> None:
    """Freeze 3 pin: there is no Tier-B artifact for the orchestrator to re-check.

    Pinned even though it is vacuously unmet today, because this is the
    condition most likely to be quietly skipped once a browser tier exists and
    its own assertions look green (PROTOCOL.md pillar 2).
    """
    assert not _exists(TIER_B_KIT), (
        f"OSV1-029 (Freeze 3): {TIER_B_KIT} now exists. This row is NOT satisfied by "
        f"the kit passing -- it is satisfied when the kit EMITS artifacts (contrast "
        f"numbers, pixel counts, bounding boxes, DOM snapshots) that ledger probes "
        f"here re-read for themselves. Until the ledger re-checks them, a green "
        f"Tier-B tier is a self-report (work_item_pipeline-qgo)."
    )
    assert not _exists("tests/conformance/operator_surface/browser/artifacts"), (
        "OSV1-029 (Freeze 3): an artifact directory appeared -- wire the ledger probes "
        "to re-read it, then flip this row."
    )


def test_row_osv1_030() -> None:
    """Freeze 4 pin: the Tier-A fixtures are demonstrated; no browser kit
    exists, so the three Tier-B fixtures are not."""
    assert not _exists(TIER_B_KIT), (
        "OSV1-030 (Freeze 4): the Tier-B kit path appeared. 'Demonstrated by running "
        "it' is the whole clause -- record WHICH revert produced WHICH failure, the "
        "way CCV1-023 did for the custody family, before flipping this row."
    )
    assert _exists(TIER_A_KIT) and _kit_bad_halves(_kit_source(), "test_calm_keeps_slot"), (
        "OSV1-030 (Freeze 4): the Tier-A fixtures' demonstrated bad halves are gone. "
        "This row is red on the TIER-B half only -- losing the Tier-A half is a "
        "second, new defect."
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
    assert len(red) == 9, (
        f"OSV1-031 (Freeze 5): pinned 9 red Core-carrying rows, observed {len(red)}: "
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
