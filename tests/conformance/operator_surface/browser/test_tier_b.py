"""Tier-B conformance kit for `contracts/operator-surface.v1.md`.

This is the file the contract names by path in Conformance 1, 2, 3 and 4 and
in Freeze 2. It drives a pinned chromium against a live app served on an
ephemeral loopback port over isolated fixture data, and asserts the contract's
Tier-B checks by their contract names:

    calm.zero_alarm_pixels   Core 2  / Conformance 1
    state.not_colour_only    Core 3  / Conformance 2   (rendered half)
    swap.survives            Core 6  / Conformance 3
    perception.floors        Core 7  / Conformance 4   (rendered half)

The three rules this kit runs under
-----------------------------------

**1. Measure, write, read back, assert (Freeze 3).** Every check computes
numbers in the browser, writes them to a JSON artifact under `_artifacts/`,
reads that file back through `_artifacts.read`, and asserts against what came
off disk. No assertion here rests on a value that only lived in a local
variable, and none rests on a screenshot. Screenshots ARE saved beside the
JSON -- as evidence for a human's Freeze 8 look, never as an input to a pass.

**2. Every fixture discriminates (Freeze 4).** Each check has a bad half that
is RUN, not asserted about: a defect is injected (or a genuinely-alarming data
fixture is substituted), the same measurement code runs, and the test asserts
the measurement CATCHES it. A good half with no demonstrated bad half is a
claim; this file contains none of those.

**3. A known violation is `xfail(strict=True)` with its ledger row, never a
skip and never a softened floor.** Where the shipped surface fails a floor
today, the test still runs, still emits its artifact, and is expected to fail
by name. `strict=True` means the day the product is fixed, THIS FILE fails --
which is the instruction to re-derive the ledger row and drop the marker.

Where the numbers go
--------------------
`tests/conformance/operator_surface/browser/_artifacts/<run-id>/` -- gitignored,
one JSON record and one PNG per measurement, plus an `index.json`. See
`_artifacts.py` for the envelope.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import pytest

from . import _artifacts, _png, _probe
from .conftest import AppServer, goto

pytestmark = pytest.mark.tier_b

# ---------------------------------------------------------------------------
# The status hues, quoted from the token block (`webtheme.py:169-188`). Core 2:
# "The token set defines exactly three status hues -- `--alarm`, `--blocked`,
# `--watch`. Only `--alarm` and `--blocked` carry status meaning".
# ---------------------------------------------------------------------------

#: The specimen the contract's own Conformance 1 bad half names -- "the
#: retired-palette region reinstated -- a hardcoded amber outside the token
#: set". Still in the tree at `webtrust.py`'s page-local `<style>` block as
#: `--amber:#D9A253` (see ledger rows OSV1-003, OSV1-005). A fixed literal
#: because it is, by definition, OUTSIDE the token set -- there is no token to
#: resolve it from.
RETIRED_AMBER = "#D9A253"

#: Chebyshev tolerance for "this pixel is that hue". Antialiasing moves a
#: rendered edge a long way off the source colour, so a tight tolerance would
#: under-count a real alarm chip; a loose one would start catching neighbouring
#: hues. 8/255 keeps the three status hues mutually exclusive by a wide margin
#: in both themes.
HUE_TOLERANCE = 8

#: The viewports Core 7 and Conformance 4 name, and nothing else.
VIEWPORTS = (430, 900, 1280)
THEMES = ("dark", "light")
LEVELS = ("L0", "L1", "L2")


def known_violation(row: str, what: str):
    """`xfail(strict=True)` naming the ledger row that owns the violation.

    Three properties, all deliberate:

    * the test still RUNS and still emits its artifact, so the number stays
      measured rather than becoming an unrun claim;
    * `strict=True` means the day the surface is fixed, THIS FILE goes red --
      which is the instruction to re-derive the row from the new measurement
      and delete the marker, in the same change;
    * no floor is ever softened to make a check pass. A softened floor is a
      contract amendment performed by a test file, which is exactly the drift
      `ledger/` exists to catch.
    """
    return pytest.mark.xfail(strict=True, reason=f"{row}: {what}")


#: Levels whose rendered text contrast is below the floor today (OSV1-010).
#: L0 passes in both themes and is NOT marked -- a blanket marker would hide
#: a future L0 regression behind an expected failure.
_CONTRAST_LEVELS = [
    pytest.param("L0"),
    pytest.param(
        "L1",
        marks=known_violation(
            "OSV1-010",
            "L1's `.status-chip.st-resolved` reads 3.13:1 in dark and 2.26:1 in "
            "light against its own chip surface; light also drops "
            "`.actions-drawer summary .count` to 2.83:1 and `.st-held` to 3.99:1",
        ),
    ),
    pytest.param(
        "L2",
        marks=known_violation(
            "OSV1-010",
            "L2's `.actions-drawer summary .count` reads 3.77:1 in dark and below "
            "the floor in light -- the `--ink-quiet` reading-copy pair OSV1-009 "
            "recorded, measured here in the render",
        ),
    ),
]

#: The calm pixel sweep: L0 is clean in both themes, L1 is not (OSV1-003).
_CALM_LEVELS = [
    pytest.param("L0"),
    pytest.param(
        "L1",
        marks=known_violation(
            "OSV1-003",
            "a calm L1 paints 97 `--blocked` pixels in both themes -- the legend "
            "swatch (`span.sw`), the live `span.dot`, and the destructive "
            "`button.btn.danger`'s border -- with nothing blocked in the project",
        ),
    ),
]


# ---------------------------------------------------------------------------
# sweeping
# ---------------------------------------------------------------------------


def _sweep_hues(png: bytes, tokens: dict[str, str]) -> dict[str, Any]:
    """Decode a screenshot and count pixels of each status hue.

    `tokens` comes from the LIVE page (`_probe.RESOLVE_STATUS_TOKENS_JS`), not
    from a constant here, because the light theme redefines all three status
    hues (`--alarm:#92400e` vs dark's `#f59e0b`). Sweeping a light render for
    the dark values reports a confident zero for a page nobody examined --
    measured, and the reason this argument exists.

    Returns the numbers, never a verdict: the caller writes them to an
    artifact and the assertion reads them back from there.
    """
    image = _png.decode(png)
    hist: Counter[tuple[int, int, int]] = _png.histogram(image)
    hues = {k: tokens[k] for k in ("alarm", "blocked", "watch")}
    hues["retired_amber"] = RETIRED_AMBER
    counts = {
        name: _png.count_near(hist, _png.parse_hex(value), tolerance=HUE_TOLERANCE)
        for name, value in hues.items()
    }
    return {
        "width": image.width,
        "height": image.height,
        "pixel_count": image.pixel_count,
        "distinct_colours": len(hist),
        "tolerance": HUE_TOLERANCE,
        "theme": tokens.get("theme"),
        "hues": hues,
        "pixels": counts,
    }


def _sweep_page(page, artifacts, browser_info, *, check, clause, scenario) -> dict[str, Any]:
    """Screenshot -> decode -> count -> write -> read back. Returns the record."""
    tokens = page.evaluate(_probe.RESOLVE_STATUS_TOKENS_JS)
    png = page.screenshot(full_page=True)
    artifacts.save_screenshot(check=check, scenario=scenario, png=png)
    measurement = _sweep_hues(png, tokens)
    path = artifacts.write(
        check=check,
        clause=clause,
        scenario=scenario,
        browser=browser_info,
        measurement=measurement,
        headline=measurement["pixels"] | {"pixels_swept": measurement["pixel_count"]},
    )
    return _artifacts.read(path)


# ===========================================================================
# Core 2 / Conformance 1 -- calm.zero_alarm_pixels
# ===========================================================================


@pytest.mark.parametrize("level", _CALM_LEVELS)
@pytest.mark.parametrize("theme", THEMES)
def test_calm_zero_alarm_pixels(
    calm_app: AppServer, context_factory, artifacts, browser_info, level, theme
):
    """GOOD half of Conformance 1.

        **Good:** the sweep reports zero pixels matching `--alarm` or
        `--blocked`.

    Against a fixture that is calm but NOT empty: ready work, one healthily
    held item, resolved throughput. An empty page would be trivially free of
    alarm colour and would prove nothing.
    """
    page = context_factory(calm_app).new_page()
    goto(page, calm_app, calm_app.url(level), theme=theme)
    record = _sweep_page(
        page,
        artifacts,
        browser_info,
        check="calm.zero_alarm_pixels",
        clause="Core 2",
        scenario=f"calm/{level}/{theme}",
    )
    pixels = record["measurement"]["pixels"]
    assert pixels["alarm"] == 0 and pixels["blocked"] == 0, (
        f"calm.zero_alarm_pixels FAILED on a calm {level} in {theme}: "
        f"{pixels['alarm']} --alarm and {pixels['blocked']} --blocked pixels painted "
        f"across {record['measurement']['pixel_count']} swept "
        f"({record['measurement']['width']}x{record['measurement']['height']}). "
        f"Core 2: that absence is what makes the alarm pop."
    )


@pytest.mark.parametrize("theme", THEMES)
def test_calm_sweep_catches_an_injected_alarm_chip(
    calm_app: AppServer, context_factory, artifacts, browser_info, theme
):
    """BAD half A of Conformance 1 -- one alarm chip on an otherwise calm page.

    Painted with `var(--alarm)` itself, so this is the contract's own hue and
    not a lookalike. If the sweep cannot see one chip, it cannot see any.
    """
    page = context_factory(calm_app).new_page()
    goto(page, calm_app, calm_app.url("L0"), theme=theme)
    page.evaluate(_probe.INJECT_ALARM_CHIP_JS)
    page.wait_for_timeout(80)
    record = _sweep_page(
        page,
        artifacts,
        browser_info,
        check="calm.zero_alarm_pixels",
        clause="Core 2 (bad half: injected alarm chip)",
        scenario=f"bad-alarm-chip/L0/{theme}",
    )
    assert record["measurement"]["pixels"]["alarm"] > 0, (
        "the Conformance 1 bad half did NOT discriminate: an --alarm chip was "
        "injected into a calm L0 and the sweep still reported zero --alarm pixels. "
        "The good half above is therefore proving nothing."
    )


@pytest.mark.parametrize("theme", THEMES)
def test_calm_sweep_catches_the_reinstated_retired_palette(
    calm_app: AppServer, context_factory, artifacts, browser_info, theme
):
    """BAD half B of Conformance 1 -- the contract's own named defect.

        **Bad:** the same page with the retired-palette region reinstated -- a
        hardcoded amber outside the token set -- is reported as alarm-coloured
        pixels on a calm page.

    Recorded honestly: `#D9A253` is a DIFFERENT hue from `--alarm` (#f59e0b),
    far enough away that the token sweep does not classify it as `--alarm` at
    all. So the sweep carries a third bucket for it, and this test asserts on
    THAT bucket -- rather than pretending a tolerance wide enough to swallow
    the retired amber would still be a `--alarm` measurement.
    """
    page = context_factory(calm_app).new_page()
    goto(page, calm_app, calm_app.url("L0"), theme=theme)
    page.evaluate(_probe.INJECT_RETIRED_PALETTE_JS)
    page.wait_for_timeout(80)
    record = _sweep_page(
        page,
        artifacts,
        browser_info,
        check="calm.zero_alarm_pixels",
        clause="Core 2 (bad half: retired palette reinstated)",
        scenario=f"bad-retired-palette/L0/{theme}",
    )
    pixels = record["measurement"]["pixels"]
    assert pixels["retired_amber"] > 0, (
        "the Conformance 1 bad half did NOT discriminate: the retired "
        f"{RETIRED_AMBER} palette region was reinstated on a calm L0 and the sweep "
        "reported zero pixels of it."
    )


def test_calm_sweep_catches_the_genuinely_alarming_fixture(
    alarm_app: AppServer, context_factory, artifacts, browser_info
):
    """BAD half C of Conformance 1 -- no injection at all, just real data.

    The strongest of the three: the same page, the same sweep, the same code
    path, and the ONLY difference is one genuinely blocked item in the
    project. Nothing here is styled by the test.
    """
    page = context_factory(alarm_app).new_page()
    goto(page, alarm_app, alarm_app.url("L0"), theme="dark")
    record = _sweep_page(
        page,
        artifacts,
        browser_info,
        check="calm.zero_alarm_pixels",
        clause="Core 2 (bad half: one genuinely blocked item)",
        scenario="bad-alarm-fixture/L0/dark",
    )
    pixels = record["measurement"]["pixels"]
    assert pixels["alarm"] > 0 or pixels["blocked"] > 0, (
        "the alarm fixture painted neither --alarm nor --blocked pixels. Either "
        "the sweep cannot see the status hues, or a blocked item does not reach "
        "the operator's eye in colour at all -- both are findings, and both make "
        "the calm half above vacuous."
    )


# ===========================================================================
# Core 2 + Core 3 / Conformance 2 -- the alarm render
# ===========================================================================


def test_alarm_region_carries_a_reserved_status_hue(
    alarm_app: AppServer, context_factory, artifacts, browser_info
):
    """GOOD half of Conformance 2, Tier-B arm.

    **Good:** the alarm region is present, its hue is `--alarm` or
    `--blocked` [...]
    """
    page = context_factory(alarm_app).new_page()
    goto(page, alarm_app, alarm_app.url("L1"), theme="dark")
    record = _sweep_page(
        page,
        artifacts,
        browser_info,
        check="alarm.reserved_hue",
        clause="Core 2 / Conformance 2",
        scenario="alarm/L1/dark",
    )
    pixels = record["measurement"]["pixels"]
    assert pixels["alarm"] > 0 or pixels["blocked"] > 0, (
        f"Conformance 2: L1 rendered with a blocked item present painted "
        f"{pixels['alarm']} --alarm and {pixels['blocked']} --blocked pixels. The "
        f"alarm region must carry a RESERVED status hue."
    )


@pytest.mark.parametrize("level", LEVELS)
def test_state_is_never_colour_only(
    alarm_app: AppServer, context_factory, artifacts, browser_info, level
):
    """`state.not_colour_only`, measured on the RENDERED page (Core 3).

    The contract runs Core 3 at Tier A; this is the same invariant checked
    where the operator meets it -- in a real layout engine, after CSS has had
    its say -- because a chip can carry a word in the markup and still render
    it invisible.
    """
    page = context_factory(alarm_app).new_page()
    goto(page, alarm_app, alarm_app.url(level), theme="dark")
    measurement = page.evaluate(_STATUS_ELEMENT_JS)
    path = artifacts.write(
        check="state.not_colour_only",
        clause="Core 3 / Conformance 2",
        scenario=f"alarm/{level}/dark",
        browser=browser_info,
        measurement=measurement,
        headline={
            "status_elements": measurement["total"],
            "wordless": len(measurement["wordless"]),
        },
    )
    record = _artifacts.read(path)
    wordless = record["measurement"]["wordless"]
    assert record["measurement"]["total"] > 0, (
        f"no status-bearing element was found on {level} at all -- this check "
        f"cannot pass vacuously."
    )
    assert not wordless, (
        f"state.not_colour_only FAILED on {level}: {len(wordless)} status-bearing "
        f"element(s) carry a status class and no word or accessible name:\n"
        + _probe.summarise(wordless, ("path", "classes"))
    )


def test_status_word_check_catches_a_chip_stripped_of_its_word(
    alarm_app: AppServer, context_factory, artifacts, browser_info
):
    """BAD half of Conformance 2.

        **Bad:** a fixture whose status chips carry only a status class fails
        the accessible-name assertion.

    Produced by stripping the text (and any accessible name) off every status
    chip in the live DOM -- exactly the defect the clause names -- and running
    the SAME probe.
    """
    page = context_factory(alarm_app).new_page()
    goto(page, alarm_app, alarm_app.url("L1"), theme="dark")
    stripped = page.evaluate(_STRIP_STATUS_WORDS_JS)
    measurement = page.evaluate(_STATUS_ELEMENT_JS)
    path = artifacts.write(
        check="state.not_colour_only",
        clause="Core 3 / Conformance 2 (bad half: chips stripped to a class)",
        scenario="bad-wordless-chips/L1/dark",
        browser=browser_info,
        measurement=measurement | {"stripped": stripped},
        headline={"stripped": stripped, "wordless": len(measurement["wordless"])},
    )
    record = _artifacts.read(path)
    assert record["measurement"]["stripped"] > 0, (
        "the bad half stripped nothing -- there were no status chips to strip, so "
        "this fixture demonstrates nothing."
    )
    assert record["measurement"]["wordless"], (
        "the Conformance 2 bad half did NOT discriminate: every status chip's word "
        "and accessible name were removed and the probe still reported none wordless."
    )


#: Status-bearing elements, and whether each carries a word or accessible name.
#: "Status-bearing" is decided by the surface's own class vocabulary
#: (`webbrowse.py`'s `_ITEM_STATUS_CHIP_CLASS`, `webapp.py`'s chip/pill
#: classes), never by colour -- deciding it by colour would make the check
#: circular with Core 2.
_STATUS_ELEMENT_JS = r"""
(() => {
  var sel = '.chip, .pill, .badge, .status, [class*="status-"], [class*="chip-"]';
  var out = [], wordless = [];
  document.querySelectorAll(sel).forEach(function(el){
    var cs = getComputedStyle(el);
    if(cs.display === 'none' || cs.visibility === 'hidden') return;
    var r = el.getBoundingClientRect();
    if(r.width === 0 || r.height === 0) return;
    var text = (el.textContent || '').replace(/\s+/g, ' ').trim();
    var name = (el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
    var entry = {
      path: el.tagName.toLowerCase() + (el.id ? '#' + el.id : ''),
      classes: (typeof el.className === 'string' ? el.className : '').trim().slice(0, 60),
      text: text.slice(0, 40),
      accessible_name: name.slice(0, 40)
    };
    out.push(entry);
    if(!text && !name) wordless.push(entry);
  });
  return {total: out.length, elements: out.slice(0, 60), wordless: wordless};
})()
"""

#: The bad half's defect injection: leave the status CLASS (so the element is
#: still status-bearing and still coloured) and remove every word.
_STRIP_STATUS_WORDS_JS = r"""
(() => {
  var sel = '.chip, .pill, .badge, .status, [class*="status-"], [class*="chip-"]';
  var n = 0;
  document.querySelectorAll(sel).forEach(function(el){
    if(!(el.textContent || '').trim()) return;
    el.textContent = '';
    el.removeAttribute('aria-label');
    el.removeAttribute('title');
    n++;
  });
  return n;
})()
"""


# ===========================================================================
# Core 6 / Conformance 3 -- swap.survives
# ===========================================================================


def _arrange_swap_scenario(context_factory, app: AppServer, level: str):
    """Load `level` with the scenario Conformance 3 describes, and return the
    page plus its pre-swap snapshot.

        **Scenario:** L0 loaded in a real browser, scrolled, one `<details>`
        opened, the poll paused; a body-swap is forced.

    The poller's `setInterval` registration is CAPTURED rather than scheduled
    (`SWAP_CAPTURE_INIT_JS`), so the only body-swap in the run is the one the
    test forces -- no race against a 20-second timer.
    """
    ctx = context_factory(app)
    ctx.add_init_script(_probe.SWAP_CAPTURE_INIT_JS)
    page = ctx.new_page()
    goto(page, app, app.url(level), theme="dark")

    page.evaluate("window.scrollTo(0, Math.min(400, document.body.scrollHeight))")
    # Open the first CLOSED `<details>`. Closed on purpose: L0's activity feed
    # renders open from the server, so re-finding it open after a swap would
    # prove nothing about survival. Keyed by ordinal + class, because NO
    # `<details>` on this surface carries an id (measured) and `restoreState`
    # only ever re-opens `details[id]`.
    opened = page.evaluate(
        """(() => {
             var all = document.querySelectorAll('details');
             for(var i = 0; i < all.length; i++){
               if(!all[i].open){
                 all[i].open = true;
                 return {index: i, id: all[i].id,
                         signature: i + ':' + (all[i].className || '').trim()};
               }
             }
             return null;
           })()"""
    )
    paused = page.evaluate(
        """(() => {
             var b = document.getElementById('refreshToggle');
             if(!b) return false;
             b.click();
             return true;
           })()"""
    )
    page.evaluate(_probe.SWAP_MARK_LIVE_REGIONS_JS)
    page.evaluate(_probe.SWAP_SENTINEL_JS)
    page.wait_for_timeout(60)
    before = page.evaluate(_probe.SWAP_STATE_JS)
    return page, before, {"opened_details": opened, "pause_control_clicked": paused}


def _assert_swap_happened(page, mechanism: str, *, diagnostics: Any = None) -> None:
    """Wait for the body to actually be replaced, and fail loudly if it is not.

    The poller swallows every error by design (`.catch(function(){})`), so a
    forced tick whose fetch failed leaves the page untouched -- and an
    untouched page trivially "preserves" scroll, disclosures and the pause
    control. Every survival assertion in this section would then pass while
    measuring nothing at all. The sentinel is what makes that impossible.

    Polled rather than slept on: the swap is a network round-trip plus a
    parse, and a fixed sleep is either flaky or slow.
    """
    try:
        page.wait_for_function(f"() => {_probe.SWAP_SENTINEL_PRESENT_JS} === false", timeout=8000)
    except Exception as exc:  # noqa: BLE001 -- re-raised as the real diagnosis
        raise AssertionError(
            f"no body-swap occurred ({mechanism}): the pre-swap sentinel is still in "
            f"the DOM after 8s. Every survival assertion downstream would have "
            f"passed vacuously, so this is a KIT failure, not a conformance result. "
            f"Poller guards at the moment of the forced tick: {diagnostics}"
        ) from exc


def _force_swap(page) -> dict[str, Any]:
    # The poller's first guard is `document.hidden`, and chromium marks every
    # page that is not the front page of its window as hidden. Without this
    # the forced tick returns immediately, nothing swaps, and (before the
    # sentinel existed) every survival check passed on an untouched page.
    page.bring_to_front()
    forced = page.evaluate(_probe.SWAP_FORCE_TICK_JS)
    if not forced.get("forced"):
        raise AssertionError(f"could not force a body-swap: {forced}")
    _assert_swap_happened(
        page, "the surface's own poller, forced", diagnostics=forced.get("guards")
    )
    return forced


def _swap_record(artifacts, browser_info, *, scenario, clause, before, after, arrangement, forced):
    path = artifacts.write(
        check="swap.survives",
        clause=clause,
        scenario=scenario,
        browser=browser_info,
        measurement={
            "arrangement": arrangement,
            "forced": forced,
            "before": before,
            "after": after,
        },
        headline={
            "scroll_preserved": after["scroll_y"] == before["scroll_y"],
            "open_details_preserved": after["open_details"] == before["open_details"],
            "pause_control_preserved": (
                after["pause_control_pressed"] == before["pause_control_pressed"]
            ),
            "pause_flag_preserved": after["pause_flag"] == before["pause_flag"],
            "live_regions_before": before["live_region_count"],
            "marked_live_regions_after": after["surviving_marked_live_regions"],
            "details_with_id": before["details_with_id"],
        },
    )
    return _artifacts.read(path)


@pytest.fixture(scope="session")
def swap_l0(calm_app, context_factory, artifacts, browser_info):
    """One forced L0 body-swap, measured once and read by several checks.

    Session-scoped because forcing the swap is the expensive part and all four
    of Core 6's named survivals are read from the SAME snapshot pair -- which
    is also the honest way to do it: the clause is about one swap, not four.
    """
    page, before, arrangement = _arrange_swap_scenario(context_factory, calm_app, "L0")
    forced = _force_swap(page)
    after = page.evaluate(_probe.SWAP_STATE_JS)
    return _swap_record(
        artifacts,
        browser_info,
        scenario="calm/L0/dark",
        clause="Core 6 / Conformance 3",
        before=before,
        after=after,
        arrangement=arrangement,
        forced=forced,
    )


@pytest.fixture(scope="session")
def swap_l1(calm_app, context_factory, artifacts, browser_info):
    """The same forced swap on L1 -- Core 6 names both levels."""
    page, before, arrangement = _arrange_swap_scenario(context_factory, calm_app, "L1")
    forced = _force_swap(page)
    after = page.evaluate(_probe.SWAP_STATE_JS)
    return _swap_record(
        artifacts,
        browser_info,
        scenario="calm/L1/dark",
        clause="Core 6 / Conformance 3",
        before=before,
        after=after,
        arrangement=arrangement,
        forced=forced,
    )


@pytest.mark.parametrize("level", ["L0", "L1"])
def test_swap_preserves_scroll_offset(request, level):
    record = request.getfixturevalue(f"swap_{level.lower()}")
    m = record["measurement"]
    assert m["before"]["scroll_y"] > 0, (
        f"{level}: the page did not scroll before the swap, so 'scroll offset "
        f"survived' would be vacuously true."
    )
    assert m["after"]["scroll_y"] == m["before"]["scroll_y"], (
        f"swap.survives FAILED on {level}: scroll offset was "
        f"{m['before']['scroll_y']} before the body-swap and "
        f"{m['after']['scroll_y']} after."
    )


@known_violation(
    "OSV1-008",
    "`restoreState` only re-opens `details[id]`, and NO `<details>` on this "
    "surface carries an id -- the help popover, the activity feed and the actions "
    "drawer are all id-less, so the restore mechanism has zero targets",
)
@pytest.mark.parametrize("level", ["L0", "L1"])
def test_swap_preserves_open_disclosures(request, level):
    record = request.getfixturevalue(f"swap_{level.lower()}")
    m = record["measurement"]
    assert m["before"]["open_details"], (
        f"{level}: no `<details>` was open before the swap, so 'disclosure state "
        f"survived' would be vacuously true."
    )
    assert m["after"]["open_details"] == m["before"]["open_details"], (
        f"swap.survives FAILED on {level}: open disclosures were "
        f"{m['before']['open_details']} before the body-swap and "
        f"{m['after']['open_details']} after."
    )


@known_violation(
    "OSV1-008",
    "the flag survives on `window` but the control does not: the server "
    're-renders `#refreshToggle` at aria-pressed="false" (webapp.py:3549) and '
    "nothing re-applies the flag to it, so a paused page shows itself as running",
)
@pytest.mark.parametrize("level", ["L0", "L1"])
def test_swap_preserves_the_pause_control(request, level):
    """The pause CONTROL's state, not just the flag behind it.

    Core 6 names "the pause control's state", and an operator reads the
    control, not `window.__wtRefreshPaused`. Both are recorded in the artifact
    so the split outcome is legible: the flag lives on `window` and survives;
    the button is re-rendered by the server at `aria-pressed="false"`
    (webapp.py:3549) and nothing re-applies the flag to it.
    """
    record = request.getfixturevalue(f"swap_{level.lower()}")
    m = record["measurement"]
    assert m["before"]["pause_control_pressed"] == "true", (
        f"{level}: the pause control was not pressed before the swap, so this "
        f"check would be vacuous."
    )
    assert m["after"]["pause_control_pressed"] == "true", (
        f"swap.survives FAILED on {level}: the pause control read "
        f"aria-pressed={m['before']['pause_control_pressed']!r} before the body-swap "
        f"and {m['after']['pause_control_pressed']!r} after, while the underlying "
        f"flag went {m['before']['pause_flag']} -> {m['after']['pause_flag']}. "
        f"The operator sees the control."
    )


@known_violation(
    "OSV1-008",
    "there is no live region to preserve: `aria-live` has zero occurrences in "
    "`src/`, and neither `role=status` nor `role=alert` renders on a calm L0/L1 "
    "at all, so nothing is ever announced across the swap",
)
@pytest.mark.parametrize("level", ["L0", "L1"])
def test_swap_preserves_a_pending_announcement(request, level):
    """Core 6's fourth named survival.

        [...] and an assistive-technology announcement pending at the moment
        of the swap is not silently destroyed by it.

    Measured by tagging every live region BEFORE the swap and counting how
    many tagged nodes survive it. A whole-body `innerHTML` replacement
    destroys them all and builds fresh, empty ones -- which is precisely the
    Conformance 3 bad half, and precisely what the shipped surface does.
    """
    record = request.getfixturevalue(f"swap_{level.lower()}")
    m = record["measurement"]
    assert m["before"]["live_region_count"] > 0, (
        f"swap.survives FAILED on {level} before the swap even happened: the "
        f"rendered page carries NO live region at all "
        f"(`[aria-live]`, `[role=status]`, `[role=alert]`, `[role=log]` all "
        f"absent), so there is no announcement for a body-swap to destroy -- and "
        f"none for the operator to hear either. Core 6 requires the region to be "
        f"present and announcing after the swap."
    )
    assert m["after"]["surviving_marked_live_regions"] > 0, (
        f"swap.survives FAILED on {level}: all "
        f"{m['before']['live_region_count']} live region(s) present before the "
        f"body-swap were destroyed by it "
        f"({m['after']['surviving_marked_live_regions']} of the tagged nodes "
        f"survived); the page now carries "
        f"{m['after']['live_region_count']} fresh region(s) with nothing announced."
    )


def test_naive_replacement_loses_the_open_disclosure(
    calm_app: AppServer, context_factory, artifacts, browser_info
):
    """BAD half of Conformance 3, as the contract literally words it, RUN.

        **Bad:** a whole-body innerHTML replacement that recreates the region
        loses all four; the snapshot shows offset zero, the disclosure closed,
        the pause flag cleared, and a fresh live region with nothing announced.

    The same arrangement and the same snapshot probe, but the swap is a naive
    `document.body.innerHTML = ...` with no capture/restore -- the surface
    minus `captureState`/`restoreState`.

    Measured, and recorded rather than glossed: it does NOT lose all four.
    On chromium 148 a synchronous whole-body replacement preserves
    `window.scrollY` by itself, so the contract's own bad half does not
    discriminate on the scroll half. It does lose the open disclosure, which
    is what this test asserts; the scroll half is discriminated by
    `test_naive_replacement_with_reflow_loses_the_scroll_offset` below.
    """
    page, before, arrangement = _arrange_swap_scenario(context_factory, calm_app, "L0")
    page.bring_to_front()
    page.evaluate(_probe.SWAP_NAIVE_REPLACEMENT_JS)
    _assert_swap_happened(page, "naive innerHTML replacement")
    after = page.evaluate(_probe.SWAP_STATE_JS)
    record = _swap_record(
        artifacts,
        browser_info,
        scenario="bad-naive-replacement/L0/dark",
        clause="Core 6 / Conformance 3 (bad half: naive innerHTML replacement)",
        before=before,
        after=after,
        arrangement=arrangement,
        forced={
            "forced": True,
            "mechanism": "naive innerHTML replacement, no capture/restore",
            "scroll_preserved_by_the_engine": after["scroll_y"] == before["scroll_y"],
        },
    )
    m = record["measurement"]
    assert m["before"]["open_details"], (
        "the bad half was not arranged (no `<details>` was open), so it demonstrates nothing."
    )
    assert m["after"]["open_details"] != m["before"]["open_details"], (
        "the Conformance 3 bad half did NOT discriminate on disclosures: a naive "
        "whole-body replacement with no restore left "
        f"{m['after']['open_details']} open, the same as before the swap."
    )


def test_naive_replacement_with_reflow_loses_the_scroll_offset(
    calm_app: AppServer, context_factory, artifacts, browser_info
):
    """The bad half that discriminates on Core 6's SCROLL survival.

    Same whole-body replacement, written the other common way: clear the body,
    force layout, refill. The document collapses for one layout pass and the
    engine clamps the offset -- so if `test_swap_preserves_scroll_offset`
    cannot tell this apart from the shipped poller, it is asserting nothing.
    """
    page, before, arrangement = _arrange_swap_scenario(context_factory, calm_app, "L0")
    page.bring_to_front()
    page.evaluate(_probe.SWAP_NAIVE_REPLACEMENT_WITH_REFLOW_JS)
    _assert_swap_happened(page, "innerHTML='' + forced layout + refill")
    after = page.evaluate(_probe.SWAP_STATE_JS)
    record = _swap_record(
        artifacts,
        browser_info,
        scenario="bad-naive-replacement-reflow/L0/dark",
        clause="Core 6 / Conformance 3 (bad half: replacement with a forced reflow)",
        before=before,
        after=after,
        arrangement=arrangement,
        forced={"forced": True, "mechanism": "innerHTML='' + forced layout + refill"},
    )
    m = record["measurement"]
    assert m["before"]["scroll_y"] > 0, (
        "the bad half was not arranged (the page did not scroll), so it demonstrates nothing."
    )
    assert m["after"]["scroll_y"] != m["before"]["scroll_y"], (
        "the Conformance 3 scroll bad half did NOT discriminate: a whole-body "
        "replacement with a forced reflow left the scroll offset at "
        f"{m['after']['scroll_y']}."
    )


# ===========================================================================
# Core 7 / Conformance 4 -- perception.floors
# ===========================================================================


@pytest.fixture(scope="session")
def perception(calm_app, context_factory, artifacts, browser_info):
    """`perception(level, width, theme)` -> the artifact record for that render.

    One page load per combination, memoised, carrying every Core 7 rendered
    measurement: horizontal overflow, computed text contrast, interactive
    target boxes, non-text contrast, and a reduced-motion trace. They share a
    load because the clause is about ONE rendered page at one viewport, and
    reloading four times would measure four subtly different pages.
    """
    cache: dict[tuple[str, int, str], dict[str, Any]] = {}

    def _measure(level: str, width: int, theme: str) -> dict[str, Any]:
        key = (level, width, theme)
        if key in cache:
            return cache[key]
        page = context_factory(calm_app, width=width, height=900).new_page()
        goto(page, calm_app, calm_app.url(level), theme=theme)
        contrast = page.evaluate(_probe.TEXT_CONTRAST_JS)
        targets = page.evaluate(_probe.TARGET_SIZE_JS)
        overflow = page.evaluate(_probe.OVERFLOW_JS)
        non_text = page.evaluate(_probe.NON_TEXT_JS)
        page.emulate_media(reduced_motion="reduce")
        page.wait_for_timeout(120)
        motion = page.evaluate(_probe.MOTION_JS)

        scenario = f"calm/{level}/{width}/{theme}"
        artifacts.save_screenshot(
            check="perception.floors", scenario=scenario, png=page.screenshot(full_page=True)
        )
        path = artifacts.write(
            check="perception.floors",
            clause="Core 7 / Conformance 4",
            scenario=scenario,
            browser=browser_info,
            measurement={
                "viewport": {"width": width, "height": 900},
                "theme": theme,
                "level": level,
                "overflow": overflow,
                "text_contrast": contrast,
                "targets": targets,
                "non_text_contrast": non_text,
                "motion": motion,
            },
            headline={
                "scroll_width": overflow["scroll_width"],
                "client_width": overflow["client_width"],
                "overflow_x_style": overflow["overflow_x_style"],
                "elements_beyond_viewport": overflow["elements_beyond_viewport"],
                "text_scored": len(contrast["scored"]),
                "text_below_floor": len(_probe.below_text_floor(contrast)),
                "controls": sum(1 for t in targets if t["kind"] == "control"),
                "controls_below_44px": len(_probe.undersized_controls({"targets": targets})),
                "non_text_measured": len(non_text["measured"]),
                "non_text_below_floor": len(_probe.below_non_text_floor(non_text)),
                "running_animations_under_reduced_motion": len(_probe.running_animations(motion)),
            },
        )
        page.close()
        cache[key] = _artifacts.read(path)
        return cache[key]

    return _measure


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("width", VIEWPORTS)
def test_no_horizontal_overflow(perception, level, width):
    """Conformance 4's LITERAL metric: "`scrollWidth == clientWidth`".

    Recorded honestly, because this metric is vacuous on this surface: the
    stylesheet sets `overflow-x: clip` on `html` and `body`, so content wider
    than the viewport is clipped and `scrollWidth` never grows. The check
    still runs (the clause names it, and a future stylesheet that drops the
    clip must not silently start overflowing), and the artifact records the
    computed `overflow-x` next to the numbers so nobody reads this pass as
    "nothing extends past the viewport". That question is asked by
    `test_no_element_extends_past_the_viewport` below, which clipping cannot
    hide from -- and by the bad half, which demonstrates that a 900px element
    at a 430px viewport does NOT move this metric at all.
    """
    m = perception(level, width, "dark")["measurement"]["overflow"]
    assert m["scroll_width"] == m["client_width"], (
        f"perception.floors FAILED on {level} at {width}px: scrollWidth "
        f"{m['scroll_width']} != clientWidth {m['client_width']} "
        f"({m['overflow_px']}px of horizontal overflow, with overflow-x="
        f"{m['overflow_x_style']!r}). Widest beyond the viewport:\n"
        + _probe.summarise(m["widest_beyond"], ("path", "right", "width"))
    )


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("width", VIEWPORTS)
def test_no_element_extends_past_the_viewport(perception, level, width):
    """The measurement `overflow-x: clip` cannot hide.

    Conformance 4 asks whether the page fits its viewport. `scrollWidth`
    answers "is there anything to scroll to", which a clip suppresses; an
    element's own border box running past `clientWidth` answers the question
    actually asked. Two horizontal-overflow defects are already recorded
    in-code as previously observed at <=480px and 415px (`webtheme.py:1838`,
    `:2624-2630`) -- this is the check that sees them.
    """
    m = perception(level, width, "dark")["measurement"]["overflow"]
    assert m["elements_beyond_viewport"] == 0, (
        f"perception.floors FAILED on {level} at {width}px: "
        f"{m['elements_beyond_viewport']} element(s) extend past the "
        f"{m['client_width']}px viewport (hidden from scrollWidth by "
        f"overflow-x={m['overflow_x_style']!r}). Widest:\n"
        + _probe.summarise(m["widest_beyond"], ("path", "right", "width"))
    )


@pytest.mark.parametrize("level", _CONTRAST_LEVELS)
@pytest.mark.parametrize("width", VIEWPORTS)
@pytest.mark.parametrize("theme", THEMES)
def test_text_contrast_floor(perception, level, width, theme):
    """Core 7: "Text contrast is at least 4.5:1 [...] in both themes"."""
    m = perception(level, width, theme)["measurement"]["text_contrast"]
    assert m["scored"], f"no text was scored on {level}/{width}/{theme} -- vacuous pass"
    bad = _probe.below_text_floor(m)
    assert not bad, (
        f"perception.floors FAILED on {level} at {width}px in {theme}: "
        f"{len(bad)} of {len(m['scored'])} visible text elements are below the "
        f"{_probe.TEXT_CONTRAST_FLOOR}:1 floor "
        f"({len(m['unresolved'])} more could not be scored -- background not a "
        f"single colour). Worst:\n"
        + _probe.summarise(bad, ("ratio", "foreground_hex", "background_hex", "path", "text"))
    )


@known_violation(
    "OSV1-010",
    "26 of 35 interactive controls on L0 (22 of 41 on L1, 11 of 20 on L2) measure "
    "under 44px on their smaller side -- among them the pause control itself at "
    "26x26, every window-selector link at 28px tall, and the footer links at 11.5px",
)
@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("width", VIEWPORTS)
def test_interactive_targets_meet_the_floor(perception, level, width):
    """Core 7: "interactive targets are at least 44px".

    Asserted over CONTROLS. An `<a>` rendered `display:inline` inside flowing
    text is WCAG 2.5.8's own inline exception; those are counted and emitted
    in the artifact rather than silently dropped.
    """
    record = perception(level, width, "dark")["measurement"]
    targets = record["targets"]
    controls = [t for t in targets if t["kind"] == "control"]
    assert controls, f"no interactive control was found on {level}/{width} -- vacuous pass"
    bad = _probe.undersized_controls({"targets": targets})
    assert not bad, (
        f"perception.floors FAILED on {level} at {width}px: {len(bad)} of "
        f"{len(controls)} interactive controls are under "
        f"{_probe.TARGET_SIZE_FLOOR_PX}px on their smaller side "
        f"({len(targets) - len(controls)} inline links exempt). Smallest:\n"
        + _probe.summarise(bad, ("path", "label", "width", "height"))
    )


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("width", VIEWPORTS)
def test_reduced_motion_stops_every_animation(perception, level, width):
    """Core 7: "no animation runs under the preference"."""
    m = perception(level, width, "dark")["measurement"]["motion"]
    assert m["reduced_motion_matches"], (
        "the reduced-motion preference was not applied to the page, so this check "
        "would pass without measuring anything"
    )
    running = _probe.running_animations(m)
    assert not running, (
        f"perception.floors FAILED on {level} at {width}px: {len(running)} "
        f"animation(s) still run under `prefers-reduced-motion: reduce`:\n"
        + _probe.summarise(running, ("target", "state", "duration_ms"))
    )


@known_violation(
    "OSV1-010",
    "17 of 82 interactive-control borders and icon strokes on L0 are below 3:1 in "
    "dark (29 in light); L1 23/73 dark and 44/73 light; L2 11/33 and 13/33. The "
    "icon-button border is #303238 on #1e2027 -- 1.27:1",
)
@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("theme", THEMES)
def test_non_text_contrast_floor(perception, level, theme):
    """Core 7: "non-text contrast at least 3:1, in both themes".

    A NAMED SUBSET: element borders and SVG strokes against their resolved
    background. A decorative gradient edge or an icon painted as a background
    image is not reachable this way, and the artifact records how many
    elements had to be skipped for exactly that reason.
    """
    m = perception(level, 1280, theme)["measurement"]["non_text_contrast"]
    assert m["measured"], f"no non-text surface was scored on {level}/{theme} -- vacuous pass"
    bad = _probe.below_non_text_floor(m)
    assert not bad, (
        f"perception.floors FAILED on {level} at 1280px in {theme}: {len(bad)} of "
        f"{len(m['measured'])} measured non-text surfaces are below the "
        f"{_probe.NON_TEXT_CONTRAST_FLOOR}:1 floor "
        f"({m['unresolved_backgrounds']} elements skipped -- background not a "
        f"single colour). Worst:\n"
        + _probe.summarise(bad, ("ratio", "kind", "colour", "background_hex", "path"))
    )


def test_overflow_check_catches_an_injected_wide_element(
    calm_app: AppServer, context_factory, artifacts, browser_info
):
    """BAD half of Conformance 4, overflow arm -- and the reason the clause's
    own metric had to be supplemented.

        **Bad:** a fixture with a fixed-width element wider than 430px emits
        `scrollWidth > clientWidth`.

    Run, and the result recorded as measured: a 900px fixed-width element at a
    430px viewport does NOT move `scrollWidth` on this surface, because
    `overflow-x: clip` swallows it. The element-level metric catches it. The
    assertion therefore lands on the metric that discriminates, and the
    artifact carries BOTH readings so the clause's literal wording is shown to
    be non-discriminating here rather than quietly reinterpreted.
    """
    page = context_factory(calm_app, width=430, height=900).new_page()
    goto(page, calm_app, calm_app.url("L0"), theme="dark")
    before = page.evaluate(_probe.OVERFLOW_JS)
    page.evaluate(_probe.INJECT_WIDE_ELEMENT_JS)
    page.wait_for_timeout(80)
    after = page.evaluate(_probe.OVERFLOW_JS)
    path = artifacts.write(
        check="perception.floors",
        clause="Core 7 / Conformance 4 (bad half: 900px fixed-width element at 430px)",
        scenario="bad-wide-element/L0/430/dark",
        browser=browser_info,
        measurement={
            "before": before,
            "after": after,
            "scroll_width_moved": after["scroll_width"] > before["scroll_width"],
            "elements_beyond_viewport_moved": (
                after["elements_beyond_viewport"] > before["elements_beyond_viewport"]
            ),
        },
        headline={
            "scroll_width_moved": after["scroll_width"] > before["scroll_width"],
            "elements_beyond_viewport_moved": (
                after["elements_beyond_viewport"] > before["elements_beyond_viewport"]
            ),
            "overflow_x_style": after["overflow_x_style"],
        },
    )
    m = _artifacts.read(path)["measurement"]
    assert m["elements_beyond_viewport_moved"], (
        "the Conformance 4 overflow bad half did NOT discriminate: a 900px "
        f"fixed-width element at a 430px viewport moved neither scrollWidth "
        f"({before['scroll_width']} -> {after['scroll_width']}) nor the count of "
        f"elements past the viewport "
        f"({before['elements_beyond_viewport']} -> {after['elements_beyond_viewport']})."
    )


def test_contrast_check_catches_the_recorded_below_floor_pair(
    calm_app: AppServer, context_factory, artifacts, browser_info
):
    """BAD half of Conformance 4, contrast arm -- with its own control.

        **Bad:** [...] a fixture using the recorded 4.27:1 ink pair emits a
        contrast number below the floor.

    `--ink-quiet` on `--ground` is the pair `ledger/rows.yaml` OSV1-009
    recorded from the token-pair luminance math, and OSV1-009 records it as a
    LIGHT-mode failure specifically. Injected as real copy into the real page,
    so the browser -- not the ledger's arithmetic -- computes it.

    Both themes are measured and BOTH are asserted, in opposite directions:
    the same pair must come back below the floor in light and at or above it
    in dark. A probe that reported "below floor" for everything would satisfy
    the first assertion and fail the second, so the pair together is what
    proves the number is a measurement rather than a foregone conclusion.
    """
    scores: dict[str, list[float]] = {}
    for theme in THEMES:
        page = context_factory(calm_app).new_page()
        goto(page, calm_app, calm_app.url("L0"), theme=theme)
        page.evaluate(_probe.INJECT_BELOW_FLOOR_PAIR_JS)
        page.wait_for_timeout(80)
        contrast = page.evaluate(_probe.TEXT_CONTRAST_JS)
        path = artifacts.write(
            check="perception.floors",
            clause="Core 7 / Conformance 4 (bad half: recorded --ink-quiet/--ground pair)",
            scenario=f"bad-low-contrast/L0/{theme}",
            browser=browser_info,
            measurement=contrast,
            headline={
                "min_ratio": min(
                    (
                        float(e["ratio"])
                        for e in contrast["scored"]
                        if "wt-bad-half-low-contrast" in e["path"]
                    ),
                    default=-1.0,
                ),
            },
        )
        m = _artifacts.read(path)["measurement"]
        injected = [e for e in m["scored"] if "wt-bad-half-low-contrast" in e["path"]]
        assert injected, (
            f"the injected below-floor element was not scored at all in {theme}, so "
            f"this bad half demonstrates nothing about the contrast probe."
        )
        scores[theme] = [float(e["ratio"]) for e in injected]
        page.close()

    assert min(scores["light"]) < _probe.TEXT_CONTRAST_FLOOR, (
        "the Conformance 4 contrast bad half did NOT discriminate: the recorded "
        f"--ink-quiet/--ground pair scored {scores['light']} in light mode, at or "
        f"above the {_probe.TEXT_CONTRAST_FLOOR}:1 floor."
    )
    assert min(scores["dark"]) >= _probe.TEXT_CONTRAST_FLOOR, (
        "the contrast probe reported the SAME token pair below the floor in dark "
        f"({scores['dark']}) as well as light ({scores['light']}). OSV1-009 records "
        f"this pair as a light-mode failure only -- a probe that fails it in both "
        f"themes is not measuring the render, and the good halves above rest on it."
    )


# ===========================================================================
# Freeze 2 / Freeze 3 -- the kit's own preconditions
# ===========================================================================


def test_the_run_is_driven_by_a_pinned_chromium(browser_info, artifacts):
    """Freeze 2: "drives a pinned chromium".

    The pin lives in `pyproject.toml` (`playwright==1.60.0`); a playwright
    release ships exactly one chromium build. This records the resolved pair
    in the run index so every other artifact's numbers are attributable to a
    named engine.
    """
    path = artifacts.write(
        check="kit.pinned_browser",
        clause="Freeze 2",
        scenario="run/environment",
        browser=browser_info,
        measurement={"engine": browser_info},
        headline=dict(browser_info),
    )
    record = _artifacts.read(path)
    assert record["measurement"]["engine"]["name"] == "chromium"
    assert record["measurement"]["engine"]["version"], "chromium reported no version"
    assert record["measurement"]["engine"]["playwright"] == "1.60.0", (
        "the pinned playwright version moved. That moves the chromium build with "
        "it, and every recorded contrast ratio and pixel count with THAT -- "
        "re-run the kit and re-derive the ledger rows before changing the pin."
    )
