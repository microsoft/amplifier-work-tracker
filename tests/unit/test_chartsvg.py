"""Tier 1 -- amplifier_work_tracker.chartsvg: pure, deterministic inline-SVG
chart renderers for the wt-v4 "Observatory" build (Lane B: obs-widgets).

Every test constructs the expected pixel geometry independently from the
same closed-form formula the function's own docstring describes ("back-
computable"), rather than hard-coding numbers lifted from the approved
mockups -- the mockups' own fake data is hand-authored for visual demo and
does not reverse-engineer to one clean formula (see chartsvg.py's module
docstring).
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

from amplifier_work_tracker import chartsvg as C
from amplifier_work_tracker import webtheme as T

# A raw hex/rgb colour literal -- the design-system firewall (widgets.py's
# firewall_check) forbids this anywhere in widget-authored HTML; chartsvg's
# own contract promises "zero raw hex" for the exact same reason.
_RAW_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\s*\(|\bhsla?\s*\(")


def _assert_valid_svg(svg: str) -> ET.Element:
    """Parse `svg` as XML (proves tag balance) and return the root element."""
    return ET.fromstring(svg)  # noqa: S314 -- test-only, trusted fixture input


def _assert_no_raw_color(svg: str) -> None:
    assert _RAW_COLOR.search(svg) is None, f"raw colour literal found in: {svg}"


def _assert_accessible(root: ET.Element, expected_label: str) -> None:
    assert root.tag == "svg"
    assert root.get("role") == "img"
    assert root.get("aria-label") == expected_label


# ---------------------------------------------------------------------------
# sparkline
# ---------------------------------------------------------------------------


def test_sparkline_geometry_is_back_computable() -> None:
    values = [10.0, 20.0, 0.0, 30.0]
    width, height, pad = 120, 32, 4.0
    svg = C.sparkline(values, aria_label="test spark", width=width, height=height, pad=pad)
    root = _assert_valid_svg(svg)
    _assert_accessible(root, "test spark")

    lo, span = 0.0, 30.0

    def expected_x(i: int) -> float:
        return round(i * width / (len(values) - 1), 2)

    def expected_y(v: float) -> float:
        frac = (v - lo) / span
        return round(pad + (1 - frac) * (height - 2 * pad), 2)

    # Lead polyline covers points[0..-2] (all but the last, heavier segment).
    polyline = root.find("polyline")
    assert polyline is not None
    pts = [tuple(map(float, p.split(","))) for p in polyline.get("points", "").split(" ")]
    assert pts == [
        (expected_x(0), expected_y(values[0])),
        (expected_x(1), expected_y(values[1])),
        (expected_x(2), expected_y(values[2])),
    ]

    # Heavy final segment + endpoint dot land exactly at the last two points.
    line = root.find("line")
    assert line is not None
    assert float(line.get("x1", "")) == expected_x(2)
    assert float(line.get("y1", "")) == expected_y(values[2])
    assert float(line.get("x2", "")) == expected_x(3)
    assert float(line.get("y2", "")) == expected_y(values[3])
    assert line.get("stroke-width") == "3"

    circle = root.find("circle")
    assert circle is not None
    assert float(circle.get("cx", "")) == expected_x(3)
    assert float(circle.get("cy", "")) == expected_y(values[3])

    _assert_no_raw_color(svg)


def test_sparkline_flat_series_draws_centre_line() -> None:
    svg = C.sparkline([5.0, 5.0, 5.0], aria_label="flat", height=32)
    root = _assert_valid_svg(svg)
    for line in root.findall("line"):
        assert float(line.get("y1", "")) == 16.0
        assert float(line.get("y2", "")) == 16.0


def test_sparkline_empty_is_valid_and_accessible() -> None:
    svg = C.sparkline([], aria_label="empty spark")
    root = _assert_valid_svg(svg)
    _assert_accessible(root, "empty spark")
    assert list(root) == []


def test_sparkline_single_value_draws_one_dot() -> None:
    svg = C.sparkline([42.0], aria_label="one point", width=120, height=32)
    root = _assert_valid_svg(svg)
    circles = root.findall("circle")
    assert len(circles) == 1
    assert float(circles[0].get("cx", "")) == 60.0  # width / 2


def test_sparkline_display_dimensions_are_separate_attrs() -> None:
    svg = C.sparkline(
        [1, 2, 3], aria_label="x", width=120, height=32, display_width=90, display_height=24
    )
    root = _assert_valid_svg(svg)
    assert root.get("width") == "90"
    assert root.get("height") == "24"
    assert root.get("viewBox") == "0 0 120 32"


# ---------------------------------------------------------------------------
# velocity_chart
# ---------------------------------------------------------------------------


def _days(n: int) -> list[C.VelocityDay]:
    return [
        C.VelocityDay(
            label=f"{n - i}d ago" if i < n - 1 else "today",
            resolved=float(10 + i),
            created=float(5 + i),
        )
        for i in range(n)
    ]


def test_velocity_chart_geometry_is_back_computable() -> None:
    days = [
        C.VelocityDay(label="2d ago", resolved=10.0, created=5.0),
        C.VelocityDay(label="yesterday", resolved=20.0, created=15.0),
        C.VelocityDay(label="today", resolved=5.0, created=30.0),
    ]
    width, height = 620, 200
    left, right = 40.0, 20.0
    baseline_ratio, top_ratio, bar_ratio = 0.75, 0.10, 0.45

    svg = C.velocity_chart(
        days,
        aria_label="velocity test",
        width=width,
        height=height,
        left_margin=left,
        right_margin=right,
        baseline_ratio=baseline_ratio,
        top_margin_ratio=top_ratio,
        bar_width_ratio=bar_ratio,
    )
    root = _assert_valid_svg(svg)
    _assert_accessible(root, "velocity test")
    _assert_no_raw_color(svg)

    baseline_y = round(height * baseline_ratio, 2)
    max_bar_height = baseline_y - height * top_ratio
    # Peak across BOTH series (resolved and created) -- here that's 30 (today's created).
    max_value = max(max(d["resolved"] for d in days), max(d["created"] for d in days))
    slot = (width - left - right) / len(days)
    bar_width = round(slot * bar_ratio, 2)

    def cx(i: int) -> float:
        return round(left + i * slot, 2)

    def bar_h(v: float) -> float:
        return round((v / max_value) * max_bar_height, 2)

    bars = root.findall("rect")
    assert len(bars) == len(days)
    for i, (bar, day) in enumerate(zip(bars, days, strict=True)):
        expected_h = bar_h(day["resolved"])
        assert float(bar.get("width", "")) == bar_width
        assert float(bar.get("height", "")) == expected_h
        assert float(bar.get("x", "")) == round(cx(i) - bar_width / 2, 2)
        assert float(bar.get("y", "")) == round(baseline_y - expected_h, 2)

    # "today" (last day) bar is emphasised in brand-cyan; earlier days are not.
    assert "fill:var(--brand-cyan-ink)" in (bars[-1].get("style") or "")
    assert bars[0].get("style") is None

    baseline = root.find("line[@class='baseline']")
    assert baseline is not None
    assert float(baseline.get("x1", "")) == left
    assert float(baseline.get("x2", "")) == round(width - right, 2)
    assert float(baseline.get("y1", "")) == baseline_y


def test_velocity_chart_empty_is_valid_and_accessible() -> None:
    svg = C.velocity_chart([], aria_label="no days")
    root = _assert_valid_svg(svg)
    _assert_accessible(root, "no days")
    assert list(root) == []


def test_velocity_chart_all_zero_values_do_not_divide_by_zero() -> None:
    days = [C.VelocityDay(label="today", resolved=0.0, created=0.0)]
    svg = C.velocity_chart(days, aria_label="zero")
    root = _assert_valid_svg(svg)
    bar = root.find("rect")
    assert bar is not None
    assert float(bar.get("height", "")) == 0.0


def test_velocity_chart_all_zero_renders_caption_not_isolated_zero_labels() -> None:
    """Visual-polish punchlist item 2b: all-zero data previously rendered
    a row of isolated "0" value labels along the baseline with no other
    visible geometry. Now: no per-day value labels, no created-line/dots,
    a single quiet caption, and the axis (day) labels are unaffected."""
    days = [
        C.VelocityDay(label="2d ago", resolved=0.0, created=0.0),
        C.VelocityDay(label="yesterday", resolved=0.0, created=0.0),
        C.VelocityDay(label="today", resolved=0.0, created=0.0),
    ]
    svg = C.velocity_chart(days, aria_label="all zero")
    root = _assert_valid_svg(svg)
    _assert_accessible(root, "all zero")
    _assert_no_raw_color(svg)

    assert root.findall("text[@class='val-label']") == []
    assert root.find("polyline") is None
    assert root.find("circle[@class='dot']") is None
    axis_labels = root.findall("text[@class='axis-label']")
    assert [t.text for t in axis_labels] == ["2d ago", "yesterday", "today"]

    caption = root.find("text[@class='chart-caption']")
    assert caption is not None
    assert caption.text == "No activity in this window"
    assert "fill:var(--ink-quiet)" in (caption.get("style") or "")

    # the baseline itself is still drawn
    assert root.find("line[@class='baseline']") is not None


def test_velocity_chart_nonzero_data_has_no_caption() -> None:
    days = [C.VelocityDay(label="today", resolved=3.0, created=1.0)]
    svg = C.velocity_chart(days, aria_label="has data")
    root = _assert_valid_svg(svg)
    assert root.find("text[@class='chart-caption']") is None
    assert root.findall("text[@class='val-label']") != []


# ---------------------------------------------------------------------------
# status_donut
# ---------------------------------------------------------------------------


def test_status_donut_segment_lengths_sum_to_circumference() -> None:
    counts = C.StatusCounts(resolved=398, ready=34, held=18, intake=5, deferred=3, blocked=7)
    size, stroke_width = 150, 16.0
    svg = C.status_donut(counts, aria_label="mix test", size=size, stroke_width=stroke_width)
    root = _assert_valid_svg(svg)
    _assert_accessible(root, "mix test")
    _assert_no_raw_color(svg)

    r = round(size * 0.40, 2)
    circumference = 2 * math.pi * r

    group = root.find("g")
    assert group is not None
    circles = group.findall("circle")
    # First circle is the background track; the rest are one per non-zero status.
    assert len(circles) == 1 + 6  # all six statuses are non-zero here
    seg_lengths = []
    for circle in circles[1:]:
        seg, _gap = circle.get("stroke-dasharray", "").split(" ")
        seg_lengths.append(float(seg))
    assert round(sum(seg_lengths), 1) == round(circumference, 1)

    # Order is Resolved, Ready, Held, Intake, Deferred, Blocked -- the first
    # real segment (Resolved) starts at offset 0.
    assert (
        circles[1].get("stroke-dashoffset") == "-0.0"
        or float(circles[1].get("stroke-dashoffset", "")) == 0.0
    )
    # Deferred (5th real segment) draws through the hatch pattern, not a token.
    deferred_circle = circles[1 + 4]
    assert deferred_circle.get("stroke", "").startswith("url(#")


def test_status_donut_zero_total_draws_only_track() -> None:
    counts = C.StatusCounts(resolved=0, ready=0, held=0, intake=0, deferred=0, blocked=0)
    svg = C.status_donut(counts, aria_label="empty mix")
    root = _assert_valid_svg(svg)
    group = root.find("g")
    assert group is not None
    assert len(group.findall("circle")) == 1  # just the background track


def test_status_donut_skips_zero_count_statuses() -> None:
    counts = C.StatusCounts(resolved=10, ready=0, held=0, intake=0, deferred=0, blocked=5)
    svg = C.status_donut(counts, aria_label="two of six")
    root = _assert_valid_svg(svg)
    group = root.find("g")
    assert group is not None
    assert len(group.findall("circle")) == 1 + 2  # track + resolved + blocked


def test_status_donut_single_full_segment_renders_cleanly() -> None:
    """Visual-polish punchlist item 2 (asks to check the donut's 100%-one-
    segment case too): every item in one status draws a full circle
    (seg_len == circumference, gap_len == 0) -- the segment must still be
    valid, non-empty, and distinct from the background track."""
    counts = C.StatusCounts(resolved=0, ready=29, held=0, intake=0, deferred=0, blocked=0)
    size, stroke_width = 150, 16.0
    svg = C.status_donut(counts, aria_label="all ready", size=size, stroke_width=stroke_width)
    root = _assert_valid_svg(svg)
    _assert_no_raw_color(svg)

    r = round(size * 0.40, 2)
    circumference = round(2 * math.pi * r, 2)

    group = root.find("g")
    assert group is not None
    circles = group.findall("circle")
    assert len(circles) == 2  # track + the one full-circumference segment

    segment = circles[1]
    seg_len, gap_len = (float(v) for v in segment.get("stroke-dasharray", "").split(" "))
    assert seg_len == circumference
    assert gap_len == 0.0
    assert segment.get("stroke") == "var(--ink-secondary)"  # ready's token, not the track's


def test_status_donut_unique_pattern_id_is_respected() -> None:
    svg = C.status_donut(
        C.StatusCounts(resolved=1, ready=0, held=0, intake=0, deferred=1, blocked=0),
        aria_label="pattern id",
        pattern_id="my-custom-hatch",
    )
    assert 'id="my-custom-hatch"' in svg
    assert "url(#my-custom-hatch)" in svg


# ---------------------------------------------------------------------------
# age_histogram
# ---------------------------------------------------------------------------


def test_age_histogram_geometry_is_back_computable() -> None:
    buckets = [
        C.AgeBucket(label="0-1d", count=14, is_watch=False),
        C.AgeBucket(label="2-3d", count=11, is_watch=False),
        C.AgeBucket(label="4-6d", count=6, is_watch=False),
        C.AgeBucket(label="7+d", count=3, is_watch=True),
    ]
    width, height = 320, 150
    left, right, top, bottom = 20.0, 20.0, 20.0, 40.0
    svg = C.age_histogram(
        buckets,
        aria_label="age test",
        width=width,
        height=height,
        left_margin=left,
        right_margin=right,
        top_margin=top,
        bottom_margin=bottom,
    )
    root = _assert_valid_svg(svg)
    _assert_accessible(root, "age test")
    _assert_no_raw_color(svg)

    baseline_y = round(height - bottom, 2)
    max_bar_height = baseline_y - top
    max_count = max(b["count"] for b in buckets)
    slot = (width - left - right) / len(buckets)

    bars = root.findall("rect")
    assert len(bars) == len(buckets)
    for i, (bar, bucket) in enumerate(zip(bars, buckets, strict=True)):
        expected_h = round((bucket["count"] / max_count) * max_bar_height, 2)
        cx = round(left + slot * (i + 0.5), 2)
        assert float(bar.get("height", "")) == expected_h
        assert float(bar.get("y", "")) == round(baseline_y - expected_h, 2)
        assert float(bar.get("x", "")) == round(cx - float(bar.get("width", "")) / 2, 2)

    # The watch bucket (last one) has no "bar" class and draws --watch inline;
    # every other bucket keeps the shared "bar" class (CSS default colour).
    assert bars[-1].get("class") is None
    assert "fill:var(--watch)" in (bars[-1].get("style") or "")
    for normal_bar in bars[:-1]:
        assert normal_bar.get("class") == "bar"


def test_age_histogram_empty_is_valid_and_accessible() -> None:
    svg = C.age_histogram([], aria_label="no buckets")
    root = _assert_valid_svg(svg)
    _assert_accessible(root, "no buckets")
    assert root.find("rect") is None
    assert root.find("line") is not None  # baseline still drawn


def test_age_histogram_all_zero_counts_do_not_divide_by_zero() -> None:
    """Was: a zero-height <rect> (no crash, but the faint stray-outline
    artifact visual-polish punchlist item 2 flags). Now: the deliberate
    2px zero-stub -- see test_age_histogram_zero_bucket_draws_a_deliberate_
    stub_no_value_label below for the full zero-state contract; this test
    keeps its original name/intent (no ZeroDivisionError with an all-zero
    bucket set)."""
    buckets = [C.AgeBucket(label="0-1d", count=0, is_watch=False)]
    svg = C.age_histogram(buckets, aria_label="zero counts")
    root = _assert_valid_svg(svg)
    bar = root.find("rect")
    assert bar is not None
    assert float(bar.get("height", "")) == 2.0


def test_age_histogram_zero_bucket_draws_a_deliberate_stub_no_value_label() -> None:
    """Visual-polish punchlist item 2a: a zero-count bucket previously drew
    a literal zero-height <rect> (a faint stray outline) plus a floating
    "0" value label. Now: a fixed 2px stub flush on the baseline, no value
    label -- the stub (and the axis label below it) say "zero" on their
    own. Non-zero buckets in the same chart are unaffected."""
    buckets = [
        C.AgeBucket(label="0-1d", count=0, is_watch=False),
        C.AgeBucket(label="2-3d", count=5, is_watch=False),
        C.AgeBucket(label="7+d", count=0, is_watch=True),
    ]
    height, bottom_margin = 150, 40.0
    svg = C.age_histogram(
        buckets, aria_label="mixed zero", height=height, bottom_margin=bottom_margin
    )
    root = _assert_valid_svg(svg)
    _assert_no_raw_color(svg)

    baseline_y = round(height - bottom_margin, 2)
    bars = root.findall("rect")
    assert len(bars) == 3

    zero_normal, nonzero, zero_watch = bars
    assert float(zero_normal.get("height", "")) == 2.0
    assert float(zero_normal.get("y", "")) == round(baseline_y - 2.0, 2)
    # The stub's fill is named ONCE, in the stylesheet -- the markup carries
    # only what the element IS (`zero-stub`) and, for the watch band, its
    # state. Both halves are asserted, or "it has the class" would pass with
    # no rule behind it.
    assert zero_normal.get("class") == "zero-stub"
    assert zero_normal.get("data-watch") is None
    assert ".svg-chart .zero-stub{fill:var(--ink-quiet)}" in T.CSS

    assert float(nonzero.get("height", "")) > 2.0
    assert nonzero.get("class") == "bar"

    assert float(zero_watch.get("height", "")) == 2.0
    assert zero_watch.get("class") == "zero-stub"
    assert zero_watch.get("data-watch") == "1"
    assert ".svg-chart .zero-stub[data-watch]{fill:var(--watch)}" in T.CSS

    value_labels = root.findall("text[@class='axis-label']")
    value_texts = [t.text for t in value_labels if t.text and t.text.isdigit()]
    # Only the non-zero bucket gets a value label ("5") -- neither zero
    # bucket contributes a floating "0".
    assert value_texts == ["5"]

    axis_label_texts = [t.text for t in value_labels]
    assert "0-1d" in axis_label_texts
    assert "2-3d" in axis_label_texts
    assert "7+d" in axis_label_texts


# ===========================================================================
# The chart ink used to be INLINE. Moving it to the stylesheet (Core 4,
# OSV1-005) is only equivalent if the new rules WIN the cascade -- an inline
# `style=` outranks every stylesheet rule, so a selector that merely exists is
# not a replacement for one. The first form of that migration shipped
# `.axis-label[data-watch]{fill:var(--watch)}` (0,2,0), which LOSES to the
# pre-existing `.wt-observatory .svg-chart .axis-label{fill:var(--ink-tertiary)}`
# (0,3,0): the watch band, the value labels and today's tick all silently
# reverted to tertiary ink, and the Tier-B sweep measured 182 fewer `--watch`
# pixels on a dark L1. These tests are the guard for that whole class of bug.
# ===========================================================================

_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
#: One `selector-list { declarations }` rule. Bodies never nest, so this also
#: finds the rules inside an `@media` block (the at-rule itself never matches).
_CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_FILL_DECL = re.compile(r"(?:^|;)\s*fill\s*:", re.MULTILINE)
_TYPE_SELECTOR = re.compile(r"(?:^|[\s>+~])[a-zA-Z]")


def _specificity(selector: str) -> tuple[int, int, int]:
    """CSS specificity (ids, classes+attributes+pseudo-classes, type names).

    Only the shapes this stylesheet actually uses are handled, and a selector
    carrying a TYPE name is rejected rather than mis-scored -- a helper that
    quietly returns the wrong number would make this whole file lie.
    """
    assert not _TYPE_SELECTOR.search(selector), (
        f"{selector!r} carries a type selector; this helper only scores the "
        f"class/attribute shapes the chart rules use. Extend it before using it."
    )
    ids = len(re.findall(r"#[\w-]+", selector))
    classes = len(re.findall(r"\.[\w-]+", selector))
    attrs = len(re.findall(r"\[[^\]]+\]", selector))
    return (ids, classes + attrs, 0)


def _fill_rules(css: str) -> list[tuple[str, int]]:
    """(selector, offset) for every selector in a rule that declares `fill`."""
    plain = _CSS_COMMENT.sub(" ", css)
    out: list[tuple[str, int]] = []
    for m in _CSS_RULE.finditer(plain):
        if not _FILL_DECL.search(m.group(2)):
            continue
        for sel in m.group(1).split(","):
            out.append((sel.strip(), m.start()))
    return out


def _wins(challenger: tuple[str, int], incumbent: tuple[str, int]) -> bool:
    """Does `challenger` beat `incumbent` in the cascade? Higher specificity,
    or equal specificity and declared later."""
    c_sel, c_at = challenger
    i_sel, i_at = incumbent
    c, i = _specificity(c_sel), _specificity(i_sel)
    return c > i or (c == i and c_at > i_at)


def test_chart_state_ink_outranks_the_generic_axis_label_rule() -> None:
    """Every `[data-*]` chart-ink rule must beat every unconditional rule that
    also paints an `.axis-label` -- otherwise the state never renders."""
    rules = _fill_rules(T.CSS)
    axis = [r for r in rules if ".axis-label" in r[0]]
    assert axis, "no rule paints `.axis-label` at all -- the chart ink is gone"

    generic = [r for r in axis if "[data-" not in r[0]]
    stateful = [r for r in axis if "[data-" in r[0]]
    assert generic, (
        "no unconditional `.axis-label` fill rule remains. That rule is the "
        "trap these tests exist for; if it really went away, delete this test "
        "deliberately rather than letting it pass vacuously."
    )
    assert stateful, "no stateful chart-ink rule found -- did the data attributes move?"

    for challenger in stateful:
        for incumbent in generic:
            assert _wins(challenger, incumbent), (
                f"`{challenger[0]}` {_specificity(challenger[0])} does NOT beat "
                f"`{incumbent[0]}` {_specificity(incumbent[0])} in the cascade, so the "
                f"state it encodes never paints. The ink it replaced was INLINE, which "
                f"outranks everything -- scope the selector (e.g. through `.svg-chart`) "
                f"rather than trusting declaration order alone."
            )


def test_every_chart_label_kind_has_a_default_ink() -> None:
    """`.val-label` and `.zero-stub` carried their fill INLINE on every render.
    Once that is removed, an SVG `<text>`/`<rect>` with no rule falls back to
    the initial `fill:black` -- invisible on the dark ground -- so each kind
    must keep an UNCONDITIONAL rule, not only its `[data-*]` states."""
    rules = _fill_rules(T.CSS)
    for kind in (".val-label", ".zero-stub", ".axis-label"):
        unconditional = [r for r in rules if kind in r[0] and "[data-" not in r[0]]
        assert unconditional, (
            f"`{kind}` has no unconditional fill rule. Its ink used to be inline on "
            f"every render; without a default the element falls back to the SVG "
            f"initial value (black), which reads as invisible in dark mode and as a "
            f"colour nobody chose in light."
        )
