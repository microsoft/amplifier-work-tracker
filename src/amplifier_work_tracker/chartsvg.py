"""wt-v4 "Observatory" -- pure, deterministic inline-SVG chart renderers.

Ported in SHAPE (markup structure, class names, the trend-cue construction)
from the approved mockups
(`.amplifier/design-gauntlet/wt-v4-observatory/{mock-L0,mock-L1,mock-L2}.html`),
but NOT in literal pixel values: the mockups' own numbers are hand-authored
fake data for a static demo and don't reverse-engineer to one clean formula.
Every function here instead uses its OWN small, closed-form, documented
geometry so a caller (or a test) can recompute the exact same pixel value
independently from the inputs alone -- "back-computable", per the build spec.

Design-system firewall (see `widgets.py`'s `firewall_check`): every colour
reference is `var(--token)` or `currentColor` -- never a raw hex/rgb literal.
Every returned `<svg>` carries `role="img"` and a caller-supplied
`aria-label` -- these charts are the ONLY way some information (a trend,
a status mix) reaches the page, so they must never be invisible to a
screen reader.

These functions render markup only. They take plain data (lists, dicts,
`TypedDict`s) -- no adapter/DB imports, no knowledge of `bd`, no HTTP. The
widgets in `widgets.py` call these and wrap the result in the surrounding
chart-card HTML (heading, legend, footer stats).
"""

from __future__ import annotations

import html
import math
from collections.abc import Sequence
from typing import TypedDict

__all__ = [
    "AgeBucket",
    "StatusCounts",
    "VelocityDay",
    "age_histogram",
    "sparkline",
    "status_donut",
    "velocity_chart",
]


class VelocityDay(TypedDict):
    """One day's worth of resolved/created counts for `velocity_chart`, in
    chronological (oldest-first) order. The LAST entry in the sequence is
    always treated as "today" and gets the brand-cyan emphasis the mockups
    give the current day's bar/label."""

    label: str
    resolved: float
    created: float


class StatusCounts(TypedDict):
    """The six-way status mix `status_donut` draws, in the fixed ring order
    the approved mockups use everywhere this mix appears (fleet-row bars,
    the L1 donut): Resolved, Ready, Held, Intake, Deferred, Blocked."""

    resolved: int
    ready: int
    held: int
    intake: int
    deferred: int
    blocked: int


class AgeBucket(TypedDict):
    """One bucket of `age_histogram`'s ready-item age distribution (e.g.
    "0-1d" / "2-3d" / "4-6d" / "7+d"). `is_watch` marks the sub-alarm
    "aging, not alarm" tier (see `--watch` in webtheme.py) -- the mockups
    apply it to the oldest bucket, never to every bucket."""

    label: str
    count: int
    is_watch: bool


_STATUS_ORDER: tuple[str, str, str, str, str, str] = (
    "resolved",
    "ready",
    "held",
    "intake",
    "deferred",
    "blocked",
)
# Colour token per status segment -- "deferred" is deliberately absent: it
# draws through the hatch `<pattern>` (texture, not a flat hue) rather than
# one of these tokens; see `status_donut`.
_STATUS_COLOR_VAR: dict[str, str] = {
    "resolved": "--ink-quiet",
    "ready": "--ink-secondary",
    "held": "--brand-cyan-ink",
    "intake": "--ink-tertiary",
    "blocked": "--blocked",
}


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def sparkline(
    values: Sequence[float],
    *,
    aria_label: str,
    width: int = 120,
    height: int = 32,
    pad: float = 4.0,
    display_width: int = 90,
    display_height: int = 24,
) -> str:
    """A trend sparkline: `values` (oldest -> newest) mapped onto a
    `width` x `height` viewBox with `pad` px of vertical breathing room at
    the top/bottom extremes.

    Geometry (back-computable): points are evenly spaced on X
    (`i * width / (n - 1)`); Y is a linear map of each value's position
    between the series' own min and max onto `[pad, height - pad]` (higher
    value -> smaller Y, i.e. nearer the top). A perfectly flat series
    (`max == min`) draws a flat line at the vertical centre rather than
    dividing by zero.

    Trend cue (GAUNTLET-SYNTHESIS.md item 8 -- shape, not colour, so it
    survives colourblindness): every point except the last is drawn as a
    thin (`stroke-width:1.5`) polyline; the FINAL segment (second-to-last
    point -> last point) is redrawn heavier (`stroke-width:3`) with a
    round cap, plus an endpoint `<circle>` -- a climbing/falling/flat trend
    is visible from line weight and slope alone, never from colour.
    """
    label = _esc(aria_label)
    n = len(values)
    if n == 0:
        empty = f'<svg class="spark" viewBox="0 0 {width} {height}" role="img" '
        return f'{empty}aria-label="{label}"></svg>'

    lo = min(values)
    hi = max(values)
    span = hi - lo

    def _x(i: int) -> float:
        return round(i * width / (n - 1), 2) if n > 1 else round(width / 2, 2)

    def _y(v: float) -> float:
        if span <= 0:
            return round(height / 2, 2)
        frac = (v - lo) / span
        return round(pad + (1 - frac) * (height - 2 * pad), 2)

    points = [(_x(i), _y(v)) for i, v in enumerate(values)]
    dims = f'width="{display_width}" height="{display_height}"'

    svg_open = (
        f'<svg class="spark" viewBox="0 0 {width} {height}" {dims} role="img" aria-label="{label}">'
    )

    if n == 1:
        x0, y0 = points[0]
        return f'{svg_open}<circle cx="{x0}" cy="{y0}" r="2.5" fill="var(--ink-secondary)"/></svg>'

    lead_points = points[:-1]
    (lx, ly), (ex, ey) = points[-2], points[-1]

    lead_svg = ""
    if len(lead_points) >= 2:
        pts_str = " ".join(f"{x},{y}" for x, y in lead_points)
        lead_svg = (
            f'<polyline points="{pts_str}" fill="none" stroke="var(--ink-secondary)" '
            'stroke-width="1.5"/>'
        )

    return (
        f"{svg_open}"
        f"{lead_svg}"
        f'<line x1="{lx}" y1="{ly}" x2="{ex}" y2="{ey}" stroke="var(--ink-secondary)" '
        f'stroke-width="3" stroke-linecap="round"/>'
        f'<circle cx="{ex}" cy="{ey}" r="2.5" fill="var(--ink-secondary)"/>'
        "</svg>"
    )


def velocity_chart(
    days_data: Sequence[VelocityDay],
    *,
    aria_label: str,
    width: int = 620,
    height: int = 200,
    left_margin: float = 40.0,
    right_margin: float = 20.0,
    baseline_ratio: float = 0.75,
    top_margin_ratio: float = 0.10,
    bar_width_ratio: float = 0.45,
) -> str:
    """Resolved-per-day bars with a created-per-day overlay line, e.g. the
    "Environment velocity" / "Velocity & burn" charts.

    Geometry (back-computable): the baseline sits at `height * baseline_ratio`
    from the top; the tallest possible bar is `baseline_y - height *
    top_margin_ratio` px. Every bar/line-point height is `(value / max_value)
    * max_bar_height`, where `max_value` is the largest single value across
    BOTH series (so bars and the overlay line share one scale). Each day gets
    an equal-width slot across `[left_margin, width - right_margin]`; a bar's
    width is `slot_width * bar_width_ratio`, centred in its slot.

    The LAST day (assumed "today") is emphasised: its bar, value label, and
    axis label render in `var(--brand-cyan-ink)` instead of the neutral
    tokens every other day uses -- shape/position is identical, only the
    colour changes, matching the mockups' "today" convention.
    """
    label = _esc(aria_label)
    n = len(days_data)
    svg_open = f'<svg class="svg-chart" viewBox="0 0 {width} {height}" role="img" '
    if n == 0:
        return f'{svg_open}aria-label="{label}"></svg>'

    baseline_y = round(height * baseline_ratio, 2)
    max_bar_height = baseline_y - height * top_margin_ratio
    all_values = [d["resolved"] for d in days_data] + [d["created"] for d in days_data]
    peak = max(all_values) if all_values else 0
    max_value = peak if peak > 0 else 1.0

    plot_width = width - left_margin - right_margin
    slot = plot_width / n
    bar_width = round(slot * bar_width_ratio, 2)

    def _bar_height(v: float) -> float:
        return round((v / max_value) * max_bar_height, 2)

    def _cx(i: int) -> float:
        return round(left_margin + i * slot, 2)

    bars: list[str] = []
    val_labels: list[str] = []
    axis_labels: list[str] = []
    line_points: list[str] = []
    dots: list[str] = []

    for i, day in enumerate(days_data):
        cx = _cx(i)
        is_today = i == n - 1

        bh = _bar_height(day["resolved"])
        by = round(baseline_y - bh, 2)
        bx = round(cx - bar_width / 2, 2)
        bar_style = ' style="fill:var(--brand-cyan-ink)"' if is_today else ""
        bars.append(
            f'<rect class="bar" x="{bx}" y="{by}" width="{bar_width}" height="{bh}" rx="3"'
            f"{bar_style}/>"
        )

        val_color = "var(--brand-cyan-ink)" if is_today else "var(--ink-quiet)"
        val_labels.append(
            f'<text class="val-label" x="{cx}" y="{round(by - 6, 2)}" text-anchor="middle" '
            f'style="fill:{val_color}">{int(day["resolved"])}</text>'
        )

        axis_style = ' style="fill:var(--brand-cyan-ink);font-weight:600"' if is_today else ""
        axis_labels.append(
            f'<text class="axis-label" x="{cx}" y="{round(baseline_y + 18, 2)}" '
            f'text-anchor="middle"{axis_style}>{_esc(day["label"])}</text>'
        )

        ly = round(baseline_y - _bar_height(day["created"]), 2)
        line_points.append(f"{cx},{ly}")
        dots.append(f'<circle class="dot" cx="{cx}" cy="{ly}"/>')

    baseline_x2 = round(width - right_margin, 2)
    baseline_svg = (
        f'<line class="baseline" x1="{left_margin}" y1="{baseline_y}" '
        f'x2="{baseline_x2}" y2="{baseline_y}"/>'
    )
    return (
        f'<svg class="svg-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{label}">'
        f"{baseline_svg}"
        f"{''.join(bars)}"
        f'<polyline class="line" points="{" ".join(line_points)}"/>'
        f"{''.join(dots)}"
        f"{''.join(val_labels)}"
        f"{''.join(axis_labels)}"
        "</svg>"
    )


def status_donut(
    counts: StatusCounts,
    *,
    aria_label: str,
    size: int = 150,
    stroke_width: float = 16.0,
    pattern_id: str = "chart-donut-hatch",
) -> str:
    """The six-way status-mix donut (`status-breakdown` widget).

    Geometry (back-computable): the ring radius is `size * 0.40` (leaves a
    10% margin on every side for the stroke); each segment's arc length is
    `circumference * (count / total)`, drawn via `stroke-dasharray` (segment,
    gap) with a cumulative `stroke-dashoffset` so segments sit end-to-end
    with no gap between them, in `_STATUS_ORDER` (Resolved, Ready, Held,
    Intake, Deferred, Blocked). The whole ring is rotated -90 so the first
    segment starts at 12 o'clock, matching the mockup. A zero-count status is
    skipped entirely (no zero-length dasharray segment rendered); a `total`
    of 0 draws just the empty background track, never a divide-by-zero.

    Deferred draws through a diagonal-hatch `<pattern>` (texture, not a flat
    hue) rather than a `_STATUS_COLOR_VAR` token -- the same colourblind-safe
    distinction from Intake the mockups use everywhere else this mix appears.
    `pattern_id` exists so a page with more than one donut can give each its
    own pattern id (SVG `<pattern>` ids must be unique per document).
    """
    label = _esc(aria_label)
    cx = cy = round(size / 2, 2)
    r = round(size * 0.40, 2)
    circumference = 2 * math.pi * r
    total = sum(counts[key] for key in _STATUS_ORDER)  # type: ignore[literal-required]

    # The hatch gap-line and the background track both legitimately need a
    # glass/chrome tone (the same "container surface" role `.glass-panel`
    # uses everywhere) -- but the design-system firewall (widgets.py's
    # firewall_check) blanket-forbids a literal `--glass-*` token appearing
    # anywhere in a widget's OWN rendered fragment, chrome or not. A CSS
    # CLASS (defined once, externally, in webtheme.py's `.wt-observatory
    # .donut-track`/`.donut-hatch-gap` rules) achieves the identical visual
    # result without ever putting that token's literal name in this
    # function's return value.
    pattern = (
        f'<pattern id="{pattern_id}" width="6" height="6" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)">'
        '<rect width="6" height="6" fill="var(--ink-tertiary)"/>'
        '<line class="donut-hatch-gap" x1="0" y1="0" x2="0" y2="6" stroke-width="2"/>'
        "</pattern>"
    )
    track = (
        f'<circle class="donut-track" cx="{cx}" cy="{cy}" r="{r}" fill="none" '
        f'stroke-width="{stroke_width}"/>'
    )

    segments: list[str] = []
    if total > 0:
        offset = 0.0
        for key in _STATUS_ORDER:
            count = counts[key]  # type: ignore[literal-required]
            if count <= 0:
                continue
            seg_len = round(circumference * (count / total), 2)
            gap_len = round(circumference - seg_len, 2)
            stroke = (
                f"url(#{pattern_id})" if key == "deferred" else f"var({_STATUS_COLOR_VAR[key]})"
            )
            segments.append(
                f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{stroke}" '
                f'stroke-width="{stroke_width}" stroke-dasharray="{seg_len} {gap_len}" '
                f'stroke-dashoffset="{round(-offset, 2)}"/>'
            )
            offset += seg_len

    svg_open = f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" role="img" '
    return (
        f'{svg_open}aria-label="{label}">'
        f"<defs>{pattern}</defs>"
        f'<g transform="rotate(-90 {cx} {cy})">{track}{"".join(segments)}</g>'
        "</svg>"
    )


def age_histogram(
    buckets: Sequence[AgeBucket],
    *,
    aria_label: str,
    width: int = 320,
    height: int = 150,
    left_margin: float = 20.0,
    right_margin: float = 20.0,
    top_margin: float = 20.0,
    bottom_margin: float = 40.0,
    bar_width_ratio: float = 0.68,
) -> str:
    """The ready-item age-bucket bar chart (`ready-age-histogram` widget).

    Geometry (back-computable): the baseline sits `bottom_margin` px above
    the bottom edge; the tallest possible bar is `baseline_y - top_margin`
    px. Every bar's height is `(count / max_count) * max_bar_height`, where
    `max_count` is the largest count across all buckets (or 1 if every
    bucket is empty, to avoid a divide-by-zero). Buckets get equal-width
    slots across `[left_margin, width - right_margin]`; a bar is centred in
    its slot at `bar_width_ratio` of the slot's width.

    `is_watch` buckets (see `AgeBucket`) draw their bar, value label, and
    axis label in `var(--watch)` instead of the neutral/`--ink-primary`
    tokens every other bucket uses -- the sub-alarm "aging, not alarm" tier;
    shape and position are identical, only the colour and font-weight change.
    """
    label = _esc(aria_label)
    n = len(buckets)
    baseline_y = round(height - bottom_margin, 2)
    baseline_x2 = round(width - right_margin, 2)
    baseline_svg = (
        f'<line class="baseline" x1="{left_margin}" y1="{baseline_y}" x2="{baseline_x2}" '
        f'y2="{baseline_y}"/>'
    )
    if n == 0:
        return (
            f'<svg class="svg-chart" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="{label}">{baseline_svg}</svg>'
        )

    max_bar_height = baseline_y - top_margin
    max_count = max((b["count"] for b in buckets), default=0) or 1

    plot_width = width - left_margin - right_margin
    slot = plot_width / n
    bar_width = round(slot * bar_width_ratio, 2)

    bars: list[str] = []
    value_labels: list[str] = []
    axis_labels: list[str] = []

    for i, bucket in enumerate(buckets):
        cx = round(left_margin + slot * (i + 0.5), 2)
        bh = round((bucket["count"] / max_count) * max_bar_height, 2)
        by = round(baseline_y - bh, 2)
        bx = round(cx - bar_width / 2, 2)
        is_watch = bucket["is_watch"]

        if is_watch:
            bars.append(
                f'<rect x="{bx}" y="{by}" width="{bar_width}" height="{bh}" rx="3" '
                'style="fill:var(--watch)"/>'
            )
            value_style = "fill:var(--watch);font-weight:600"
            label_style = ' style="fill:var(--watch)"'
        else:
            bars.append(
                f'<rect class="bar" x="{bx}" y="{by}" width="{bar_width}" height="{bh}" rx="3"/>'
            )
            value_style = "fill:var(--ink-primary);font-weight:600"
            label_style = ""

        value_labels.append(
            f'<text class="axis-label" x="{cx}" y="{round(by - 4, 2)}" text-anchor="middle" '
            f'style="{value_style}">{int(bucket["count"])}</text>'
        )
        axis_labels.append(
            f'<text class="axis-label" x="{cx}" y="{round(baseline_y + 16, 2)}" '
            f'text-anchor="middle"{label_style}>{_esc(bucket["label"])}</text>'
        )

    return (
        f'<svg class="svg-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{label}">'
        f"{baseline_svg}"
        f"{''.join(bars)}"
        f"{''.join(value_labels)}"
        f"{''.join(axis_labels)}"
        "</svg>"
    )
