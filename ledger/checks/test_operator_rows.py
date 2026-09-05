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
import json
import re

from ._support import (
    ADAPTER,
    CHARTSVG,
    GROUND_TOKENS,
    LITERAL,
    OPERATOR_CONTRACT_PATH,
    PINNING_DISPOSITIONS,
    PYPROJECT,
    REPO_ROOT,
    ROUTE_MODULES,
    SUPERVISOR,
    WEBAPP,
    WEBBROWSE,
    WEBPUSH,
    WEBPWA,
    WEBTHEME,
    WEBTRUST,
    WIDGETS,
    _called_names,
    _route_methods,
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
TIER_B_PROBE_LIB = "tests/conformance/operator_surface/browser/_probe.py"
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
    """Core 1 CONFORMS: the L0 hero LEADS with fleet velocity over a stated
    window, and the four counts an operator acts on sit in that same region.

    RETARGETED 2026-09-04. This probe used to be the VIOLATION pin -- it
    asserted the hero was a verdict line, that velocity was a chart two
    regions below, and that the KPI strip carried five keys with no
    needs-attention count among them. That behaviour moved TOWARD the clause
    (VIOLATION-MOVEMENT), so the row flipped to CONFORMS and this probe was
    pointed at the fixed shape in the same change. Flip direction is now
    REGRESSION: this going red means the repo moved back AWAY from Core 1.

    Three separable facts, asserted separately so a partial regression cannot
    slip past a single blunt check:
      1. the renderer emits a velocity FIGURE and STATES its window -- a bare
         number with no window is the half-fix Core 1 does not accept;
      2. L0 builds its hero from that renderer, with exactly the four counts
         the clause names, each carrying a text LABEL (Core 3);
      3. the counts are composed INTO the hero region, not into a separate
         strip below it -- which is precisely where they used to live.
    """
    hero = read(WIDGETS)
    start = hero.index("def render_velocity_hero")
    body = hero[start : start + 1800]
    assert 'class="figv"' in body, (
        "OSV1-001 (Core 1) REGRESSION: `render_velocity_hero` no longer emits the "
        "velocity figure. Core 1's hero IS that throughput reading -- without it the "
        "region is a verdict line again, which is the defect this row closed."
    )
    assert 'class="figwin"' in body and "velocity_window" in body, (
        "OSV1-001 (Core 1) REGRESSION: the hero's throughput figure no longer states "
        'the window it covers. Core 1 says "throughput over a STATED window" -- an '
        "operator reading a bare number learns nothing from it."
    )
    assert "render_kpi_strip(" in body, (
        "OSV1-001 (Core 1) REGRESSION: the hero renderer no longer composes the counts "
        "strip itself. If the route places one below the hero again, the counts have "
        "left the hero REGION, which is what Core 1 requires them to be inside."
    )
    assert 'role="status"' in body, (
        "OSV1-001 (Core 1): the hero stopped being a live region. The 20s body-swap "
        'replaces this panel in place (Core 6) -- without `role="status"` that '
        "replacement announces nothing."
    )

    app = read(WEBAPP)
    assert "hero_html = WD.render_velocity_hero(" in app, (
        "OSV1-001 (Core 1) REGRESSION: L0 no longer builds its hero from "
        "`render_velocity_hero`. Re-derive the row before changing this."
    )

    # The four counts Core 1 names, read off the hero's own construction --
    # bounded to it, so a label somewhere else on the page cannot stand in for
    # one that is missing here.
    call = app[
        app.index("hero_counts = [") : app.index("velocity_data = _workspace_velocity_data(")
    ]
    labels = set(re.findall(r'label="([^"]+)"', call))
    assert labels == {"In flight (held)", "Blocked", "Needs attention", "Open / ready"}, (
        f"OSV1-001 (Core 1): the L0 hero's counts moved -- Core 1 names FOUR (in flight "
        f"(held), blocked, needs attention, open/ready); observed {sorted(labels)}. "
        f"`Needs attention` is the one that was absent anywhere at seed; losing it "
        f"again is the original defect returning."
    )
    assert "velocity_window=" in call and "velocity_value=" in call, (
        "OSV1-001 (Core 1): L0 stopped passing a velocity figure and/or its window to "
        "the hero. Both halves are the clause."
    )

    # No second strip survives below the hero: the route holds no separate
    # `kpi_html` fragment to interpolate under it any more.
    assert "kpi_html" not in app, (
        "OSV1-001 (Core 1) REGRESSION: a separate KPI-strip fragment is back in the L0 "
        "route. The counts belong INSIDE the hero region (`render_velocity_hero` "
        "composes them); a strip below it is the shape this row closed."
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
    # THE PALETTE SPECIMENS CLOSED 2026-09-05 (work_item_pipeline-np3, OSV1-005).
    # This row's own VIOLATION is unchanged -- a calm L1 still paints `--blocked`,
    # which is what the recorded sweep above measures. But the two specimens it
    # also named are gone from the tree, so they are asserted from the OTHER side
    # now: a pin that a defect is still present would be a false pin, and silently
    # deleting the assertions would lose the only in-process guard that the
    # retired palette does not come back.
    assert not contains(WEBPWA, "#0D0D0C"), (
        "OSV1-003 (Core 2) REGRESSION: the retired pre-blend-3 ground is back in "
        "webpwa.py's offline body. Core 4 (OSV1-005) closed it on 2026-09-05."
    )
    assert not contains(WEBTRUST, "#D9A253"), (
        "OSV1-003 (Core 2) REGRESSION: webtrust.py hardcodes the retired amber again. "
        "It consumes `webtheme.trust_style_tag()` now -- see OSV1-005."
    )


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
    """Core 4 CONFORMS: the literal-style census, RE-RUN here, reads ZERO.

    FLIPPED 2026-09-05 from VIOLATION (VIOLATION-MOVEMENT: the pin went red
    because the tree moved TOWARD the clause). Flip direction is now
    REGRESSION -- this probe asserts the invariant, and the mutations
    reinstate each half of the closed defect.

    BOTH HALVES, still measured separately, because they close for different
    reasons and can regress independently: the inline `style=` attribute
    census, and the `<style>`-BLOCK census the 2026-09-04 true-up made
    reachable. The counts are COMPUTED here, never transcribed, so this row
    cannot drift away from the tree.
    """
    literal = style_sites_in(LITERAL)
    assert literal == [], (
        f"OSV1-005 (Core 4) REGRESSION: {len(literal)} inline `style=` site(s) carry "
        f"a literal colour, font, or size. Core 4 tolerates zero.\n"
        f"  The fix is never a new inline value: add a class or a token to "
        f"`webtheme.py` (the token module Core 4 names) and reference it.\n"
        f"  observed: {literal}"
    )
    block_literals = style_block_literal_sites()
    assert block_literals == [], (
        f"OSV1-005 (Core 4) REGRESSION: {len(block_literals)} literal colour/font/size "
        f"declaration(s) in a `<style>` block OUTSIDE the token module. A page-local "
        f"stylesheet is a second source of visual truth -- the exact defect the "
        f"2026-09-04 true-up widened this clause to reach.\n"
        f"  observed: {[f'{f}:{n} {d}' for f, n, d, _r in block_literals]}"
    )
    blocks = [f"{f}:{ln}" for f, ln, _css in style_blocks_outside_token_module()]
    assert blocks == [], (
        f"OSV1-005 (Core 4): a module outside the token module started shipping a "
        f"`<style>` block again: {blocks}.\n"
        f"  This is not YET a Core 4 violation on its own -- the clause forbids "
        f"literal colour/font/size INSIDE such a block, and the assertion above is "
        f"what measures that. It is asserted here because zero is the shape this row "
        f"was flipped on (`webtrust.py` now consumes `webtheme.trust_style_tag()`), "
        f"and a page-local sheet reappearing is how the literal count comes back."
    )
    total = len(inline_style_sites())
    assert total == 55, (
        f"OSV1-005 (Core 4): the total inline `style=` population moved from 55 to "
        f"{total}. Neither direction is neutral -- a DECREASE is convergent (Backlogged "
        f"2 wants zero inline `style=` at all) and welcome, but it must be recorded "
        f"here and in OSV1-006's register in the same change; an INCREASE is a new "
        f"inline site whose bucket nobody has looked at. Re-run the census and "
        f"re-derive both rows."
    )
    # The two specimens this row pinned by name while it was red -- asserted
    # from the OTHER side now, so the fix cannot be silently undone.
    assert not contains(WEBPWA, "background:#0D0D0C"), (
        "OSV1-005 (Core 4) REGRESSION: webpwa.py's offline body carries the retired "
        "pre-blend-3 ground again. It was the worst specimen in this census -- a "
        "palette three generations stale, in a document that only ever renders when "
        "the network is down, so nobody sees the drift."
    )
    assert contains(WEBTRUST, "T.trust_style_tag()"), (
        "OSV1-005 (Core 4) REGRESSION: webtrust.py no longer emits the token module's "
        "own style tag. It is the plain-HTTP trust page: it must stay SELF-CONTAINED "
        "(inlined, never fetched), and `webtheme.TRUST_CSS` is how it gets the live "
        "tokens inlined without re-declaring a palette of its own."
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
        "webapp.py:1127",  # flex:{n} 1 0            -- state-bar segment ratio
        "webapp.py:1823",  # width:{today_w}px       -- throughput bar, today
        "webapp.py:1826",  # width:{prior_w}px       -- throughput bar, prior 6d
        "webtheme.py:4197",  # {style}               -- axis ruler numeral offset
        "webtheme.py:4216",  # left:{_grad_x(f):.1f}px -- graduation tick offset
        "webtheme.py:4223",  # width:{px}px          -- age bar length
        "widgets.py:837",  # width:{pct}%            -- status-mix segment (hatched)
        "widgets.py:839",  # width:{pct}%            -- status-mix segment
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


#: Live regions present BEFORE the forced swap, per level, as the 2026-09-05
#: re-recorded run measures them. L0 renders exactly ONE since the hero
#: rebuild landed (`widgets.py:1379`, the verdict hero's `role="status"`); L1
#: still renders none. Pinned per level rather than as a single number,
#: because the two levels answer Core 6's announcement half differently and a
#: shared pin would let one move under the other.
_LIVE_REGIONS_BEFORE_SWAP = {"L0": 1, "L1": 0}


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
        assert m["live_regions_before"] == _LIVE_REGIONS_BEFORE_SWAP[level], (
            f"OSV1-008 (Core 6) PIN MOVED on {level}: the page renders "
            f"{m['live_regions_before']} live region(s) before the swap, pinned at "
            f"{_LIVE_REGIONS_BEFORE_SWAP[level]}. Movement in either direction "
            f"changes what Core 6's announcement half is even asking -- re-derive "
            f"this row from the new swap measurement (work_item_pipeline-qgo)."
        )
        assert m["marked_live_regions_after"] == 0, (
            f"OSV1-008 (Core 6) PIN BROKE THE RIGHT WAY on {level}: "
            f"{m['marked_live_regions_after']} of the live region(s) tagged before "
            f"the swap SURVIVED it. On L0 that is the announcement half closing -- "
            f"re-derive this row from the new measurement."
        )
    assert count(WEBAPP, "aria-live") == 0 and count(WEBTHEME, "aria-live") == 0, (
        "OSV1-008 (Core 6) PIN BROKE THE RIGHT WAY: an `aria-live` region appeared "
        "in the source. Re-derive this row from the Tier-B snapshot rather than "
        "from its presence."
    )
    assert contains(WIDGETS, ' role="status">'), (
        'OSV1-008 (Core 6): the verdict hero\'s `role="status"` region is gone -- '
        "that is the ONE live region L0 renders, and the thing the swap destroys. "
        "Re-derive this row (and OSV1-001's hero rebuild) from a fresh run."
    )


# --------------------------------------------------------------- OSV1-009


#: The ink ramp's four canonical steps, brightest-to-quietest in dark mode and
#: darkest-to-lightest in light. `--dim`/`--ink` are deliberately excluded: they
#: are ALIASES onto two of these four, so including them would make the
#: distinctness check below trivially false.
_INK_RAMP = ("--ink-primary", "--ink-secondary", "--ink-tertiary", "--ink-quiet")


def test_row_osv1_009() -> None:
    """Core 7 CONFORMS: every declared token pair clears its floor, both themes.

    RETARGETED from the seed pin (work_item_pipeline-sxh, 2026-09-04). The pin
    froze six below-floor pairs -- all `--ink-quiet` in light mode, three
    grounds x the two duplicated light blocks -- plus the call site that made
    that token READING COPY rather than a decorative exemption. Both halves are
    closed by one token change (`--ink-quiet` #7c8ba0 -> #596473 in BOTH light
    blocks), so the reading-copy half needs no separate assert: the token is now
    above the text floor wherever it is used.

    Every number below is COMPUTED from the live token blocks in webtheme.py on
    each run -- nothing here is a transcribed ratio. The three guarded shapes:

      1. no declared ink x ground pair below 4.5:1, in any of the three blocks;
      2. no declared status x ground pair below 3:1 (the half that CONFORMED at
         seed and must not silently regress while the text half is worked on);
      3. the fix was made at the TOKEN and in BOTH light blocks, and did not
         buy contrast by collapsing the ink ramp.

    Honest limit, unchanged from the seed row and the reason OSV1-010 stays
    open: flat token-pair math models a swatch on a bare ground. The real
    surface puts `backdrop-filter` glass over an ambient radial gradient, which
    lifts perceived background luminance. Necessary, never sufficient.
    """
    pairs = text_pairs()
    assert len(pairs) >= 54, (
        f"OSV1-009 (Core 7): the declared ink x ground surface SHRANK to {len(pairs)} "
        f"pairs (54 at seed). A floor check over fewer pairs passes by measuring "
        f"less -- re-derive this row from what the token blocks actually declare."
    )
    below_text = sorted(
        (round(r, 2), ink, ground, block) for block, ink, ground, r in pairs if r < 4.5
    )
    assert not below_text, (
        f"OSV1-009 (Core 7) REGRESSION: {len(below_text)} declared text pair(s) fell "
        f"below the 4.5:1 floor. Fix the TOKEN, in BOTH light blocks -- they are held "
        f"in sync only by comment.\n  (ratio, ink, ground, block): {below_text}"
    )

    non_text = non_text_pairs()
    assert len(non_text) >= 9, (
        f"OSV1-009 (Core 7): the declared status x ground surface SHRANK to "
        f"{len(non_text)} pairs (9 at seed) -- re-derive this row."
    )
    below_non_text = sorted(
        (round(r, 2), hue, ground, block) for block, hue, ground, r in non_text if r < 3.0
    )
    assert not below_non_text, (
        f"OSV1-009 (Core 7) REGRESSION: {len(below_non_text)} declared non-text pair(s) "
        f"fell below the 3:1 floor.\n  (ratio, hue, ground, block): {below_non_text}"
    )

    blocks = token_blocks()
    assert set(blocks) == {"dark", "light-media", "light-attr"}, (
        f"OSV1-009 (Core 7): a declared token block appeared or vanished "
        f"({sorted(blocks)}). 'both themes' is measured over these three."
    )
    light = {
        name: {t: resolve_token(t, blocks[name]) for t in (*_INK_RAMP, *GROUND_TOKENS)}
        for name in ("light-media", "light-attr")
    }
    assert light["light-media"] == light["light-attr"], (
        f"OSV1-009 (Core 7): the two light token blocks DRIFTED on the tokens this "
        f"clause measures. webtheme.py's own comment says they are kept in sync only "
        f"by comment; a colour fixed in one and not the other is the exact hazard the "
        f"seed row's six pairs (three grounds x two blocks) recorded.\n"
        f"  @media (prefers-color-scheme:light): {light['light-media']}\n"
        f'  :root[data-theme="light"]:          {light["light-attr"]}'
    )
    for name, table in blocks.items():
        ramp = [resolve_token(t, table) for t in _INK_RAMP]
        assert len(set(ramp)) == len(_INK_RAMP), (
            f"OSV1-009 (Core 7): the ink ramp COLLAPSED in the {name!r} block -- two "
            f"of {list(_INK_RAMP)} now resolve to the same colour ({ramp}). Clearing "
            f"the floor by deleting a ramp step is not conformance; --ink-quiet must "
            f"stay quieter than --ink-tertiary while clearing 4.5:1."
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
    assert l1["text_below_floor"] == 3 and l1_light["text_below_floor"] == 4, (
        f"OSV1-010 (Core 7) PIN MOVED: L1 text below 4.5:1 measured "
        f"{l1['text_below_floor']} dark / {l1_light['text_below_floor']} light, "
        f"pinned at 3 / 4 (light was 5 before the contrast lane moved "
        f"`--ink-quiet`). Movement in either direction means the render changed "
        f"-- re-derive (work_item_pipeline-qgo)."
    )
    assert l0["controls_below_44px"] == 26 and l0["controls"] == 34, (
        f"OSV1-010 (Core 7) PIN MOVED: L0 measured {l0['controls_below_44px']} of "
        f"{l0['controls']} interactive controls under 44px, pinned at 26 of 34 "
        f"(35 before the hero rebuild replaced one control)."
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
    """Core 7 CONFORMS: reduced motion is ONE kernel-level rule -- and the
    browser confirms nothing runs under the preference.

    Three halves now, all load-bearing: exactly one block, its selector is
    universal, and (RE-DERIVED 2026-09-05) the recorded browser run measures
    ZERO running animations under `prefers-reduced-motion: reduce` in every
    one of the 18 renders it sweeps. A per-widget opt-in would satisfy a naive
    "is it handled?" check and is precisely what the clause forbids; a
    stylesheet that says the right thing while the page still animates would
    satisfy the static halves alone.
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

    # The browser half, re-read from the run summary rather than trusted from
    # the Tier-B tier's own green (Freeze 3). Every swept render, not one: the
    # count is only meaningful measured on a QUIESCENT page, and reading a
    # single scenario would let the other seventeen move unseen.
    swept = {
        scenario: headline["running_animations_under_reduced_motion"]
        for scenario, headline in tier_b_summary()["checks"]["perception.floors"].items()
        if scenario.startswith("calm/")
    }
    assert len(swept) == 18, (
        f"OSV1-011 (Core 7): the recorded run sweeps {len(swept)} renders, not the "
        f"18 (L0/L1/L2 x 430/900/1280 x dark/light) this row reads. A narrowed "
        f"sweep is a narrowed claim -- re-derive."
    )
    still_running = {s: n for s, n in sorted(swept.items()) if n}
    assert not still_running, (
        f"OSV1-011 (Core 7) REGRESSION: the recorded run measures animations still "
        f"running under `prefers-reduced-motion: reduce`: {still_running}. The "
        f"kernel rule collapses every duration to .001ms, so a running animation "
        f"means something escapes it -- read the run's "
        f"`motion`/`motion_at_preference_change` artifacts before flipping this row: "
        f"a transition created BEFORE the preference was applied and still finishing "
        f"is the page settling, and is recorded separately for exactly that reason."
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


#: Every adapter read that ACCEPTS a `limit` -- the calls Core 10's "every
#: adapter call reached from a view passes an explicit limit" is about. A
#: scalar read has nothing to bound, so it is not listed.
_BOUNDED_READS = frozenset(
    {
        "list",
        "list_bounded",
        "activity",
        "attention_items",
        "attention_items_from_rows",
        "recent_activity_feed",
    }
)

#: A helper that makes an unbounded listing call but is reached by NO route.
#: Dead code is not "reached from a view", so the clause as written does not
#: condemn it -- but the exemption is re-earned every run below, by proving it
#: is still dead.
_UNREACHED_UNCAPPED = ("_oldest_ready_item", WEBAPP)


def _module_int_constants(path) -> dict[str, int]:  # type: ignore[no-untyped-def]
    """Module-level `NAME = <int>` assignments, plus one alias hop through the
    adapter (`NAME = A.LIST_MAX_LIMIT`), read by PARSING -- never importing.
    Static reading is what lets this kit measure source it does not execute.
    """
    adapter_consts: dict[str, int] = {}
    for node in ast.parse(read(ADAPTER)).body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, int)
        ):
            adapter_consts[node.targets[0].id] = node.value.value
    out: dict[str, int] = {}
    for node in ast.parse(read(path)).body:
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            continue
        name = node.targets[0].id
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, int):
            out[name] = value.value
        elif isinstance(value, ast.Attribute) and value.attr in adapter_consts:
            out[name] = adapter_consts[value.attr]
    return out


def _limit_passed(call: ast.Call, consts: dict[str, int]) -> object:
    """The `limit=` this call passes: an int where it resolves, `None` when no
    `limit` keyword is present at all, `"?"` when one IS passed from an
    expression this static reading cannot evaluate.

    `"?"` is not a failure: the clause asks for an EXPLICIT limit at the call
    site, and a value computed from a parameter is explicit there. `None` is
    the failure -- an inherited default is a bound nobody at the call site
    can see.
    """

    def evaluate(node: ast.expr) -> object:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return consts.get(node.id, "?")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Sub | ast.Mult):
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(left, int) and isinstance(right, int):
                if isinstance(node.op, ast.Add):
                    return left + right
                return left - right if isinstance(node.op, ast.Sub) else left * right
        return "?"

    for kw in call.keywords:
        if kw.arg == "limit":
            return evaluate(kw.value)
    return None


def view_listing_calls() -> list[tuple[str, int, str, object]]:
    """`(module, line, handler, limit)` for every listing call a read-only
    route reaches -- the same module-local, depth-4 name-following the route
    audit above already uses, and the same honest bound: a call reached
    through a callable handed in from another module is invisible to it.
    """
    found: list[tuple[str, int, str, object]] = []
    for path in ROUTE_MODULES:
        tree = ast.parse(read(path))
        funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                funcs.setdefault(node.name, node)
        consts = _module_int_constants(path)
        for handler in funcs.values():
            methods: list[str] = []
            for dec in handler.decorator_list:
                methods += _route_methods(dec) or []
            if not any(m in {"GET", "HEAD"} for m in methods):
                continue
            reached = [handler]
            seen: set[str] = set()
            frontier = _called_names(handler)
            for _ in range(4):
                nxt: set[str] = set()
                for name in frontier - seen:
                    seen.add(name)
                    helper = funcs.get(name)
                    if helper is not None and helper is not handler:
                        reached.append(helper)
                        nxt |= _called_names(helper)
                frontier = nxt - seen
                if not frontier:
                    break
            for fn in reached:
                for node in ast.walk(fn):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr in _BOUNDED_READS
                    ):
                        found.append(
                            (path.name, node.lineno, handler.name, _limit_passed(node, consts))
                        )
    return found


def test_row_osv1_015() -> None:
    """Core 10 CONFORMS: every adapter listing call a read-only route reaches
    passes an explicit, finite limit -- MEASURED here, not asserted from a
    remembered line number.

    Retargeted from the pin on `webbrowse.py`'s `limit=0` when
    work_item_pipeline-8vv landed. The pin named ONE call; this audits the
    population, so the next unbounded view query fails here too rather than
    slipping in beside a fixed one.

    `limit=0` is bd's own "unlimited" (`adapter.Beads.list`'s docstring says
    so outright) and an omitted `limit` leaves bd's default in place
    implicitly -- the clause asks for an EXPLICIT bound, so both are failures.
    """
    calls = view_listing_calls()
    assert any(m == "webbrowse.py" and h == "project_view" for m, _, h, _ in calls), (
        f"OSV1-015 (Core 10): the traversal no longer reaches `project_view`'s item "
        f"listing -- an audit that matches nothing passes forever while proving "
        f"nothing. Re-derive this row. Found: {calls}"
    )
    offenders = [c for c in calls if c[3] is None or (isinstance(c[3], int) and c[3] <= 0)]
    assert not offenders, (
        "OSV1-015 (Core 10) REGRESSION -- a view-reached adapter read no longer "
        "passes an explicit, finite limit (`None` = no `limit=` at all, so the call "
        "silently inherits the seam's default; `0` = bd's own \"unlimited\"):\n  "
        + "\n  ".join(f"{m}:{ln} in {h}() -> limit={lim!r}" for m, ln, h, lim in offenders)
        + "\n This surface re-renders every 20 seconds; an unbounded read here runs "
        "three times a minute per open tab."
    )
    name, module = _UNREACHED_UNCAPPED
    app = read(module)
    assert app.count(name) == 1, (
        f"OSV1-015 (Core 10): `{name}` now has {app.count(name) - 1} caller(s). It "
        f"calls `bd.list(...)` with NO limit at all -- being reached by nothing was "
        f"the only reason it did not violate this clause. Give it a bound or delete it."
    )
    assert contains(WEBAPP, 'items = bd.list(lane=A.LANE_WORK, status="open")'), (
        "OSV1-015 (Core 10): the uncapped `bd.list` in `_oldest_ready_item` is gone -- "
        "welcome, and the row's exemption just changed. Re-derive."
    )


# --------------------------------------------------------------- OSV1-016


def test_row_osv1_016() -> None:
    """Core 10 CONFORMS: a chosen theme survives a refresh -- and so does the
    other preference on this surface.

    Retargeted from the pin on `wtSetTheme` persisting NOTHING, when
    work_item_pipeline-dg3 landed. Three facts hold it up, and all three are
    load-bearing:

      * the choice is WRITTEN (`wtSetTheme` -> `localStorage`);
      * it is READ BACK AT FIRST PAINT, from `<head>`, before `<body>` is
        parsed -- a body-end read applies it one paint too late, which is a
        flash, not a fix;
      * writer and reader name the SAME key, taken from ONE declaration. Two
        spellings would fail silently and look exactly like "the toggle does
        nothing".

    The server's `data-theme="dark"` default is asserted UNCHANGED: the
    resolver only ever replaces that attribute, never removes it, so PR #55's
    fix (a light-OS browser silently winning the token cascade because
    `<html>` carried no `data-theme` at all) stays fixed.

    Density is checked alongside, unchanged in meaning from the pin: under
    the 2026-09-04 aligned wording its `localStorage` persistence is exactly
    why it is conformant, and a row whose notes rule on density must notice
    if density stops persisting.
    """
    app = read(WEBAPP)
    theme_src = read(WEBTHEME)

    key_decl = 'THEME_STORAGE_KEY = "wt-theme"'
    assert key_decl in theme_src, (
        "OSV1-016 (Core 10): `webtheme.THEME_STORAGE_KEY` is gone or renamed. It is "
        "the ONE declaration the writer and the first-paint reader both take their "
        "key from -- re-derive this row before letting them drift apart."
    )

    assert "function wtSetTheme(t){" in app, (
        "OSV1-016 (Core 10): `wtSetTheme` is gone or renamed -- the mechanism this row "
        "measures moved. Re-derive."
    )
    setter = app[app.index("function wtSetTheme(t){") :][:200]
    assert "localStorage.setItem(" in setter, (
        "OSV1-016 (Core 10) REGRESSION: `wtSetTheme` no longer persists the choice. "
        "A theme held only in page memory dies on the next load -- that is this "
        "clause's anti-goal in its own words (work_item_pipeline-dg3)."
    )

    assert "def theme_boot_js()" in theme_src, (
        "OSV1-016 (Core 10) REGRESSION: `webtheme.theme_boot_js` is gone. Without a "
        "first-paint resolver a stored theme is written and never read back."
    )
    boot = theme_src[theme_src.index("def theme_boot_js()") :]
    boot = boot[: boot.index("\ndef ")]
    assert "localStorage.getItem(" in boot and "setAttribute('data-theme'" in boot, (
        "OSV1-016 (Core 10) REGRESSION: the first-paint resolver no longer reads the "
        "stored theme and applies it. Written-but-never-read is not persistence."
    )
    assert "removeAttribute" not in boot, (
        "OSV1-016 (Core 10): the resolver now REMOVES `data-theme` rather than only "
        "replacing it -- that is how a light-OS browser silently wins the token "
        "cascade again (PR #55). Re-derive."
    )

    page_src = theme_src[theme_src.index("def page(") :]
    page_src = page_src[: page_src.index("\n# ---")]
    assert "<script>{theme_boot_js()}</script>" in page_src, (
        "OSV1-016 (Core 10) REGRESSION: `page()` no longer inlines the first-paint "
        "resolver at all, so a stored theme is never applied on load."
    )
    head_at = page_src.index('<html lang="en" data-theme="dark"><head>')
    script_at = page_src.index("<script>{theme_boot_js()}</script>")
    body_at = page_src.index("</style></head><body")
    assert head_at < script_at < body_at, (
        "OSV1-016 (Core 10) REGRESSION: the first-paint resolver is no longer inlined "
        "in `<head>` ahead of the body. Applying a stored theme after the body is "
        "parsed is a flash of the wrong theme on every single load."
    )
    assert contains(WEBTHEME, '<html lang="en" data-theme="dark">'), (
        'OSV1-016 (Core 10): the server no longer renders `data-theme="dark"` as the '
        "first-paint default. That attribute is what the resolver REPLACES; without "
        "it a light-OS browser wins the cascade before any script runs (PR #55)."
    )

    # The OTHER preference on this surface, and the one the true-up's aligned
    # wording rules CONFORMANT: density persists, so it survives a refresh.
    assert "var KEY='wt-density';" in theme_src and contains(
        WEBTHEME, "localStorage.setItem(KEY, next ? 'compact' : 'comfortable')"
    ), (
        "OSV1-016 (Core 10): the density preference no longer persists in "
        "`localStorage`. Under the 2026-09-04 aligned wording that persistence is "
        "exactly why density is CONFORMANT alongside theme -- if it stopped, density "
        "became a violation of this clause and this row's ruling note is stale. "
        "Re-derive."
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
    """Conformance 2 CONFORMS: BOTH tiers' halves landed and both discriminate.

    RE-DERIVED 2026-09-05 at the wave-2 integration. This is the only
    Conformance fixture that spans both tiers, so it was pinned twice -- once
    by each lane, each pinning the OTHER half's absence. Both halves are now
    present, so neither pin is true any more and the row is derived from what
    the two kits actually measure:

      TIER-A half (work_item_pipeline-c1a) `state.not_colour_only` exists in
        the Tier-A kit, ships a bad half, and is NOT deferred behind an xfail --
        a deferred good half is a check that does not currently pass.
      TIER-B half (work_item_pipeline-qgo) the alarm region paints a RESERVED
        hue, and every status-bearing element on L0/L1/L2 carries a word after
        CSS has had its say.

    Each half keeps its own lane's assertions: this row goes red if EITHER
    stops holding, which is the only way a two-tier fixture can be honest.
    """
    # --- the Tier-A half: present, ships its bad half, and not deferred -----
    assert _exists(TIER_A_KIT), (
        f"OSV1-021 (Conformance 2) REGRESSION: {TIER_A_KIT} is gone. This row went "
        f"CONFORMS on BOTH halves landing (work_item_pipeline-c1a); losing the "
        f"Tier-A half puts it back to red."
    )
    kit = _kit_source()
    assert "check_state_not_colour_only" in _kit_defs(kit), (
        "OSV1-021 (Conformance 2) REGRESSION: the Tier-A accessible-name half is gone from the kit."
    )
    assert _kit_bad_halves(kit, "test_state_not_colour_only"), (
        "OSV1-021 (Conformance 2) REGRESSION: the Tier-A half no longer ships a bad "
        "half. A fixture whose bad half nobody runs is a claim, not a fixture "
        "(Freeze 4)."
    )
    deferred = _kit_deferred_rows(kit, "test_state_not_colour_only")
    assert not deferred, (
        f"OSV1-021 (Conformance 2) REGRESSION: the Tier-A good half is deferred "
        f"behind an xfail naming {sorted(deferred)}. A green Conformance row whose "
        f"good half does not currently pass is a claim."
    )
    # --- the Tier-B half: re-read from the committed run summary ------------
    assert _exists(TIER_B_KIT), (
        f"OSV1-021 (Conformance 2) REGRESSION: {TIER_B_KIT} is gone -- the hue half "
        f"(work_item_pipeline-qgo) is what took this row green alongside Tier A."
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

    The contrast bad half carries its own control -- a literal below-floor pair
    must come back under 4.5:1 and a literal above-floor pair at or over it, in
    BOTH themes -- which is what separates "the probe measures" from "the probe
    always says no".
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
    for theme in ("light", "dark"):
        measured = summary.get(f"bad-low-contrast/L0/{theme}")
        assert measured, f"OSV1-023 (Conformance 4): the contrast bad half did not run in {theme}."
        assert measured["min_ratio"] < 4.5 <= measured["control_ratio"], (
            f"OSV1-023 (Conformance 4): in {theme} the injected literal pair measured "
            f"{measured['min_ratio']}:1 and its control {measured['control_ratio']}:1. "
            f"The bad half needs BOTH -- the below-floor pair under 4.5:1 AND the "
            f"control at or above it -- or it is not demonstrating a measurement, it "
            f"is a probe that always says no. RE-DERIVED 2026-09-05: the pair is now "
            f"LITERAL (#9aa3b2 on #eef2fb, 2.27:1) in both themes, because the "
            f"live-token version stopped naming a defect when the contrast lane fixed "
            f"`--ink-quiet` (OSV1-009, OSV1-030)."
        )
    theme = read(WEBTHEME)
    for width in ("1280px", "900px", "430px"):
        assert f"max-width:{width}" in theme or f"min-width:{width}" in theme, (
            f"OSV1-023 (Conformance 4): the {width} breakpoint is gone from "
            f"webtheme.py. Conformance 4 sweeps 430, 900 and 1280 -- a viewport the "
            f"stylesheet no longer knows about is a different test."
        )


def test_row_osv1_024() -> None:
    """Conformance 5 CONFORMS: the fixture exists, discriminates, and its GOOD
    half runs UNDEFERRED against the rebuilt hero (OSV1-001 closed 2026-09-05).

    Flipped at highway wave-1 integration: the hero lane closed OSV1-001 and the
    orchestrator removed the kit's xfail(strict) deferral in the same change; the
    good half now passes on the real L0 (kit run: 38 passed / 4 xfailed).
    """
    kit = _kit_source()
    assert "check_hero_velocity_and_counts" in _kit_defs(kit), (
        f"OSV1-024 (Conformance 5): {TIER_A_KIT} no longer implements "
        f"`hero.velocity_and_counts` at the location the contract names."
    )
    assert _kit_bad_halves(kit, "test_hero_velocity_and_counts"), (
        "OSV1-024 (Conformance 5): the fixture no longer ships a bad half -- a fixture "
        "that cannot be watched failing is a claim (Freeze 4)."
    )
    assert not _kit_deferred_rows(kit, "test_hero_velocity_and_counts"), (
        "OSV1-024 (Conformance 5) REGRESSION: the good half is deferred again -- a "
        "Conformance row cannot read CONFORMS while its good half carries an xfail. "
        "Either the hero regressed (re-open OSV1-001) or the marker is stale."
    )
    assert row("OSV1-001")["disposition"] == "CONFORMS", (
        "OSV1-024 (Conformance 5) REGRESSION: OSV1-001 is red again, so Conformance 5's "
        "good half cannot pass against the shipped hero. Re-derive both rows together."
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
    assert not _kit_deferred_rows(kit, "test_visual_single_source"), (
        "OSV1-025 (Conformance 6) REGRESSION: Conformance 6's good half is deferred "
        "again. This row is green because the pair PASSES -- the bad half reports the "
        'contract\'s own `style="color:#D9A253"` specimen and an unregistered computed '
        "site, and the good half passes over the real `src/` tree."
    )
    assert row("OSV1-005")["disposition"] not in PINNING_DISPOSITIONS, (
        "OSV1-025 (Conformance 6) REGRESSION: OSV1-005 is red again, so Conformance 6 "
        "is no longer demonstrated end-to-end. These two move together by "
        "construction -- re-derive both."
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

    NARROWED 2026-09-05 (work_item_pipeline-qgo's narrowing, kept through the
    wave-2 integration and turned round to the CONFORMS direction): the Tier-B
    browser kit is now wired too (Makefile `test-conformance-b`, CI "Tier 7"),
    so bare containment of `tests/conformance` would be satisfied by wiring
    that has nothing to do with Freeze 1. The Tier-B path is stripped from
    each file BEFORE the check, so what remains can only be the Tier-A wiring
    this row is about.
    """
    assert _exists(TIER_A_KIT), f"OSV1-027 (Freeze 1) REGRESSION: {TIER_A_KIT} is gone."
    make = read(MAKEFILE)
    assert "test-conformance-a:" in make, (
        "OSV1-027 (Freeze 1) REGRESSION: the Makefile no longer carries the "
        "`test-conformance-a` target. Existing is not the same as running."
    )
    ci = read(CI_WORKFLOW)
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
    tier_b_dir = TIER_B_KIT.rsplit("/", 1)[0]
    for path, where in ((MAKEFILE, "the Makefile"), (CI_WORKFLOW, "ci.yml")):
        remainder = read(path).replace(TIER_B_KIT, "").replace(tier_b_dir, "")
        assert TIER_A_KIT.rsplit("/", 1)[0] in remainder, (
            f"OSV1-027 (Freeze 1) REGRESSION: {where} no longer wires the TIER-A kit "
            f"path (the Tier-B browser wiring is stripped before this check, so it "
            f"cannot stand in for it). Freeze 1's second half is 'runs on every pull "
            f"request'."
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


#: What Conformance 4's contrast bad half injects: a LITERAL below-floor pair
#: and a LITERAL above-floor control, neither of them reachable from the token
#: set. It injected the LIVE tokens (`--ink-quiet` on `--ground`) until the
#: contrast lane closed OSV1-009 by moving `--ink-quiet` off the recorded
#: colour and the "defect" measured 5.36:1 -- above the floor. A fixture whose
#: bad input is the product's own current state stops naming a defect the
#: moment the product is fixed, which is the failure this row exists to catch.
_LITERAL_BELOW_FLOOR_INJECTION = "color:#9aa3b2;background:#eef2fb"
_LITERAL_CONTROL_INJECTION = "color:#1b2430;background:#eef2fb"
_LIVE_TOKEN_PAIR_INJECTION = "color:var(--ink-quiet);background:var(--ground)"

#: Freeze 4's population, enumerated: every Conformance fixture arm that has
#: to have been RUN and seen to bite. Nine Tier-B scenarios read back out of
#: the committed run summary, four Tier-A good halves whose bad halves are
#: read out of the kit's own source, and the kit's own tripwire that no check
#: may ship without one. Fourteen arms; a fixture that quietly drops one fails
#: here rather than narrowing the claim in silence.
_TIER_B_DEMONSTRATIONS = (
    ("calm.zero_alarm_pixels", "bad-alarm-chip/L0/dark"),
    ("calm.zero_alarm_pixels", "bad-retired-palette/L0/dark"),
    ("calm.zero_alarm_pixels", "bad-alarm-fixture/L0/dark"),
    ("state.not_colour_only", "bad-wordless-chips/L1/dark"),
    ("swap.survives", "bad-naive-replacement/L0/dark"),
    ("swap.survives", "bad-naive-replacement-reflow/L0/dark"),
    ("perception.floors", "bad-wide-element/L0/430/dark"),
    ("perception.floors", "bad-low-contrast/L0/light"),
    ("perception.floors", "bad-low-contrast/L0/dark"),
)

_TIER_A_DEMONSTRATIONS = (
    ("Conformance 2", "test_state_not_colour_only"),
    ("Conformance 5", "test_hero_velocity_and_counts"),
    ("Conformance 6", "test_visual_single_source"),
    ("Conformance 7", "test_calm_keeps_slot"),
)


def test_row_osv1_030() -> None:
    """Freeze 4 CONFORMS: all fourteen Conformance fixture arms demonstrate on
    THIS tree, re-read from a run rather than taken on either kit's word.

    RE-DERIVED 2026-09-05 (second wave-2 integration pass), VIOLATION ->
    CONFORMS. The pin this row carried was Conformance 4's contrast bad half:
    it injected the LIVE `--ink-quiet`/`--ground` pair, which WAS the recorded
    4.27:1 specimen until the contrast lane closed OSV1-009 by moving the
    token -- after which the same injection measured 5.36:1 in light, above
    the floor, and the bad half named no defect at all. Two Tier-A bad halves
    had lost their specimens the same way in the same wave (the `limit=0` call
    and the non-persisting theme setter, both fixed by the core10 lane).

    All three were rebuilt to own their bad input -- literal colours here, a
    fabricated view module and a fabricated script module in the Tier-A kit --
    and the kit was re-run: `make test-conformance-b` on this tree is 52
    passed / 35 xfailed / 0 failed, `make test-conformance-a` 38 passed /
    4 xfailed / 0 failed. The pin is retargeted onto the invariant it was
    waiting for: every arm ran, and each one still bites.
    """
    # --- the Tier-A half -----------------------------------------------------
    assert _exists(TIER_A_KIT), (
        f"OSV1-030 (Freeze 4): {TIER_A_KIT} is gone -- the Conformance 5/6/7 (and "
        f"Core 3) demonstrations went with it."
    )
    kit = _kit_source()
    for fixture, good in _TIER_A_DEMONSTRATIONS:
        assert _kit_bad_halves(kit, good), (
            f"OSV1-030 (Freeze 4): {fixture}'s bad half is gone from the Tier-A "
            f"kit. A bad half that has never been executed is a claim."
        )
    assert "test_every_check_ships_a_bad_half" in _kit_defs(kit), (
        "OSV1-030 (Freeze 4): the Tier-A kit dropped the tripwire that every check "
        "ships a bad half -- without it the demonstration can narrow silently, "
        "which is the failure this clause exists to prevent."
    )
    # A bad half must own its bad INPUT. Both of these fabricate their
    # specimen; before the 2026-09-05 rebuild they borrowed the shipped
    # `webbrowse.py` call and the shipped theme setter, and both stopped
    # discriminating the moment those were fixed.
    for owned in ("_UNBOUNDED_VIEW_SPECIMEN", "_UNPERSISTED_STATE_SPECIMEN"):
        assert owned in kit, (
            f"OSV1-030 (Freeze 4): the Tier-A kit no longer fabricates `{owned}`. "
            f"Core 10's bad halves used the SHIPPED defects as their specimens and "
            f"went red when the product was fixed -- a fixture that depends on the "
            f"product staying broken demonstrates nothing."
        )

    # --- the Tier-B half: nine scenarios, all read back from the run ---------
    assert _exists(TIER_B_KIT), (
        f"OSV1-030 (Freeze 4): {TIER_B_KIT} is gone -- Conformance 1-4's "
        f"demonstrations went with it."
    )
    checks = tier_b_summary()["checks"]
    missing = sorted(f"{c}/{s}" for c, s in _TIER_B_DEMONSTRATIONS if s not in checks.get(c, {}))
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
    chip = checks["calm.zero_alarm_pixels"]["bad-alarm-chip/L0/dark"]
    retired = checks["calm.zero_alarm_pixels"]["bad-retired-palette/L0/dark"]
    real = checks["calm.zero_alarm_pixels"]["bad-alarm-fixture/L0/dark"]
    assert chip["alarm"] > 0 and retired["retired_amber"] > 0, (
        f"OSV1-030 (Freeze 4): a Conformance 1 injection stopped painting its hue "
        f"({chip['alarm']} --alarm px for the chip, {retired['retired_amber']} px "
        f"for the reinstated retired palette)."
    )
    assert real["alarm"] > 0 or real["blocked"] > 0, (
        "OSV1-030 (Freeze 4): the genuinely-alarming fixture painted no reserved "
        "status hue -- the strongest of Conformance 1's three arms, and the only "
        "one with nothing injected."
    )
    naive = checks["swap.survives"]["bad-naive-replacement/L0/dark"]
    reflow = checks["swap.survives"]["bad-naive-replacement-reflow/L0/dark"]
    assert not naive["open_details_preserved"] and not reflow["scroll_preserved"], (
        "OSV1-030 (Freeze 4): a Conformance 3 bad half stopped losing what it "
        "exists to lose (the naive replacement's open `<details>`, the reflow "
        "variant's scroll offset)."
    )
    assert checks["perception.floors"]["bad-wide-element/L0/430/dark"][
        "elements_beyond_viewport_moved"
    ], (
        "OSV1-030 (Freeze 4): Conformance 4's overflow bad half stopped moving the "
        "element-level reading -- the only reading `overflow-x: clip` cannot hide."
    )

    # --- the arm this row was red for: it must own its specimen now ---------
    probe_lib = read(REPO_ROOT / TIER_B_PROBE_LIB)
    assert _LIVE_TOKEN_PAIR_INJECTION not in probe_lib, (
        "OSV1-030 (Freeze 4) REGRESSION: Conformance 4's contrast bad half injects "
        "the LIVE token pair again. That is precisely how this row went red at the "
        "wave-2 integration: `--ink-quiet` moved and the bad half's defect moved "
        "with it, leaving a fixture that measures whatever the product currently "
        "does. Inject a literal below-floor pair."
    )
    assert _LITERAL_BELOW_FLOOR_INJECTION in probe_lib, (
        f"OSV1-030 (Freeze 4): the contrast bad half no longer injects the literal "
        f"below-floor pair ({_LITERAL_BELOW_FLOOR_INJECTION}). Its specimen must be "
        f"its own, not the token set's."
    )
    assert _LITERAL_CONTROL_INJECTION in probe_lib, (
        f"OSV1-030 (Freeze 4): the contrast bad half lost its literal control "
        f"({_LITERAL_CONTROL_INJECTION}). Without a pair that must come back ABOVE "
        f"the floor, a probe that always says no would satisfy the bad half."
    )
    for theme in ("light", "dark"):
        measured = checks["perception.floors"][f"bad-low-contrast/L0/{theme}"]
        assert measured["min_ratio"] < 4.5 <= measured["control_ratio"], (
            f"OSV1-030 (Freeze 4): in {theme} the recorded run measures the contrast "
            f"bad half at {measured['min_ratio']}:1 with its control at "
            f"{measured['control_ratio']}:1. Freeze 4 asks for a bad half that FAILS "
            f"the check it names, demonstrated by running it -- re-derive this row "
            f"and OSV1-023 together."
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
    assert len(red) == 4, (
        f"OSV1-031 (Freeze 5): pinned 4 red Core-carrying rows, observed {len(red)}: "
        f"{red}. Movement in either direction means this gate's tally changed -- update "
        f"the pin and the row's notes in the same change. (10 at seed; OSV1-009 went "
        f"green 2026-09-04, work_item_pipeline-sxh; OSV1-015 and -016 went green "
        f"2026-09-04, work_item_pipeline-8vv and -dg3; OSV1-001 and OSV1-004 went green "
        f"2026-09-05, work_item_pipeline-ujy and the Tier-A kit; OSV1-005 went green "
        f"2026-09-05, work_item_pipeline-np3.)"
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
    """Freeze 6 CONFORMS: the register is enumerated AND no literal site remains.

    FLIPPED 2026-09-05 from GAP (VIOLATION-MOVEMENT). Freeze 6's second
    conjunct -- "no literal colour, font, or size site remaining" -- reads
    through Core 4, so the 2026-09-04 true-up made "site" mean BOTH an inline
    `style=` attribute and a declaration in a `<style>` block outside the token
    module. Both are now zero, so both conjuncts hold and this gate closes.

    Still asserted as two separate halves: the failure mode this row exists to
    prevent is stamping a Freeze gate on a green inline census while a
    page-local stylesheet quietly hardcodes a palette. That failure mode does
    not go away because the count reached zero once.
    """
    literal = style_sites_in(LITERAL)
    assert literal == [], (
        f"OSV1-032 (Freeze 6) REGRESSION (inline half): {len(literal)} literal "
        f"colour/font/size inline site(s) are back, so Freeze 6's second conjunct no "
        f"longer holds: {literal}. See OSV1-005, which owns the census."
    )
    block_literals = style_block_literal_sites()
    assert block_literals == [], (
        f"OSV1-032 (Freeze 6) REGRESSION (`<style>`-block half): "
        f"{len(block_literals)} literal declaration(s) are back in a page-local "
        f"stylesheet. See OSV1-005, which owns that census too."
    )
    computed = style_sites_in("COMPUTED")
    assert len(computed) == 8, (
        f"OSV1-032 (Freeze 6): the enumerated half moved -- 8 computed-geometry sites "
        f"were enumerated when this gate closed, observed {len(computed)}. See "
        f"OSV1-006, which owns the register itself; a DECREASE is convergent and "
        f"welcome, and AT ZERO it fires Backlogged 2's promotion trigger."
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
