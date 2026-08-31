"""The dashboard widget contract -- an INTERNAL, ruthlessly-simple seam for the
overview dashboard's panels.

A *widget* is one self-describing panel of the dashboard: it declares an
`id`/`title`/`size`, reads the reduced data it needs from a single shared,
read-only :class:`DashboardContext`, and returns an HTML fragment that draws
ONLY through the design tokens. A :class:`WidgetRegistry` holds the widgets in
registration order; the route builds the context once and renders panels by id
instead of hand-calling a dozen free functions in sequence.

Three deliberate non-goals this pass (mechanism, not policy -- see
`docs/widget-contract.md`):

* **No dynamic loading / no discovery.** Widgets are registered in Python by
  the app that owns them. There is no plugin path, no entry-point scan, no
  import-by-name. A second author adds a widget by calling `register(...)`.
* **No layout engine.** `size` is a *declared hint* about how a panel wants to
  sit (full-width vs. sharing a row); the route still owns placement this pass.
  Per-user / per-host arrangement is a FUTURE concern the contract is shaped
  not to preclude, not one it implements now.
* **No new rendering.** A registered widget produces the SAME fragment the
  route produced inline before -- the registry routes, it never restyles.

The one thing the contract *does* enforce is the design-system firewall
(:func:`firewall_check`): a widget cannot introduce a raw colour (a would-be
new status hue) or glass/gradient/blur gloss on data-ink. Glass and gradient
are chrome-only; the two reserved status hues (`--amber`, `--crimson`) are the
only colours a panel may lean on for meaning, and it reaches them through the
tokens, never a literal. The firewall is a pure inspector: it reads a fragment
and reports violations, it never rewrites output. See
:meth:`WidgetRegistry.render`'s ``enforce`` flag and the contract's test suite
for where it is exercised as a merge gate.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypedDict

from . import chartsvg as C

if TYPE_CHECKING:  # avoid importing heavy siblings at module import time
    from . import adapter as A

__all__ = [
    "DashboardContext",
    "FirewallViolation",
    "Widget",
    "WidgetRegistry",
    "WidgetSize",
    "firewall_check",
    # -- wt-v4 "Observatory" (Lane B: obs-widgets) --
    "AgentNowRow",
    "AgentPanelRow",
    "AgentsNowData",
    "AgentsPanelData",
    "ActivityFeedData",
    "ActivityFeedItem",
    "AttentionQueueData",
    "AttentionRow",
    "DormantProject",
    "FleetRow",
    "FleetStatusMix",
    "FleetTableData",
    "KpiCard",
    "KpiStripData",
    "MetaCell",
    "ObservatoryWidget",
    "ReadyAgeHistogramData",
    "StatusBreakdownData",
    "Verdict",
    "VerdictHeroData",
    "VerdictLineData",
    "WindowTab",
    "get_observatory_widget",
    "observatory_widget_ids",
    "render_activity_feed",
    "render_agents_now",
    "render_agents_panel",
    "render_attention_queue",
    "render_fleet_table",
    "render_kpi_strip",
    "render_ready_age_histogram",
    "render_status_breakdown",
    "render_verdict_hero",
    "verdict_line",
]


class WidgetSize(Enum):
    """How a panel wants to sit on the page -- a *declared hint*, not a layout
    directive. `FULL` panels take their own full-width row (the workspace-by-
    state bar, the needs-you queue); `HALF` panels are happy sharing a row with
    a sibling (the heartbeat + throughput pair). The route still owns actual
    placement this pass; a future arranger (multi-author / hosted instance) can
    read this hint without re-deriving it from CSS."""

    FULL = "full"
    HALF = "half"


@dataclass(frozen=True)
class DashboardContext:
    """The single, read-only data bag every dashboard widget renders from.

    The route reduces the raw workspace exactly once into these already-computed
    figures, then hands the SAME frozen bag to every widget. Two shapes live
    here on purpose, because real panels need both: flat aggregate scalars/maps
    (throughput, the age histogram, the state bar) AND the summary objects
    themselves (the needs-you queue ranks projects, so it needs the `ok`
    summaries, not a pre-flattened count). A widget declares which of these
    fields it reads via `Widget.needs`; nothing here is mutated by rendering.
    """

    # -- the readable project summaries (raw shape, for ranking widgets) --
    summaries: tuple[A.ProjectSummary, ...]
    ok: tuple[A.ProjectSummary, ...]

    # -- the one render instant every duration on the page is measured against --
    rendered_at: datetime

    # -- ready-queue age histogram roll-up (label -> count) --
    buckets: Mapping[str, int]

    # -- reconciled workspace roll-up (readable queues only) --
    reconciled_items: int
    ready_total: int
    held_total: int
    blocked_total: int
    deferred_total: int
    resolved_total: int

    # -- throughput partition (measurable queues only) --
    resolved_24h_total: int
    resolved_7d_total: int
    prior6d_rate: float
    delta_pct: int | None
    older_than_7d: int
    n_measurable_with_resolutions: int
    n_with_resolutions: int

    # -- workspace-wide daily resolution counts, oldest -> newest, summed
    # across every measurable project (see adapter.DAILY_THROUGHPUT_WINDOW) --
    # the throughput sparkline's real data source. Defaulted to `()` (not a
    # required field) so existing widget-contract tests that construct a
    # `DashboardContext` without this field keep working unmodified; the real
    # route always supplies a populated tuple.
    resolved_daily_totals: tuple[int, ...] = ()

    # -- the workspace's most recent activity of ANY kind, as an ISO string
    # (the same value the verdict's own stall check reads) -- lets a widget
    # surface "last activity Nh ago" without re-deriving it a second way.
    # Defaulted to `None` for the same backward-compatibility reason as above.
    workspace_last_activity: str | None = None


# Callable that turns the shared context into one panel's HTML fragment.
WidgetRender = Callable[[DashboardContext], str]


@dataclass(frozen=True)
class Widget:
    """One dashboard panel, described by the contract.

    Attributes
    ----------
    id:
        Stable, unique, kebab-case identifier the route (and any future
        arranger) addresses the panel by.
    title:
        Human title for the panel -- the same words its own eyebrow renders
        ("Throughput", "Workspace by state"). Metadata for menus / arrangers;
        the render itself still draws its own heading.
    size:
        A :class:`WidgetSize` placement hint (see its docstring).
    render:
        ``(DashboardContext) -> str`` producing the panel's HTML fragment. It
        must draw only through design tokens (enforced by the firewall).
    needs:
        The `DashboardContext` field names this panel reads -- an honest, cheap
        self-description of its data dependencies (validated against the real
        context fields by the contract's tests). Documentation-grade: it does
        not restrict what `render` may touch, it declares intent.
    description:
        Optional one-line note about what the panel shows.
    """

    id: str
    title: str
    size: WidgetSize
    render: WidgetRender
    needs: tuple[str, ...] = ()
    description: str = ""


class FirewallViolation(Exception):
    """Raised when a widget's rendered fragment breaks the design-system
    firewall (a raw colour, or glass/gradient/blur gloss on data-ink)."""


# The firewall: patterns a widget-authored fragment must NEVER contain. Each is
# a raw colour (a would-be new status hue that bypasses `--amber`/`--crimson`)
# or a chrome-only gloss effect (glass / gradient / blur) leaking onto data-ink.
# The check is a deny-list, not an allow-list, on purpose: widgets legitimately
# reach for many component tokens (`var(--st-ready)`, `var(--mid)`, ...), and an
# allow-list would fight every honest one. What is forbidden is narrow and
# durable -- literal colours and gloss -- so the list stays stable as panels grow.
_HEX = r"(?<![&\w])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![0-9a-fA-F])"

_FIREWALL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # A raw hex colour literal. The `(?<!&)` guard keeps numeric HTML entities
    # like `&#8217;` from reading as a colour.
    ("raw hex colour", re.compile(_HEX)),
    # Raw colour functions -- another way to smuggle a literal status hue.
    ("raw colour function", re.compile(r"\b(?:rgba?|hsla?)\s*\(", re.IGNORECASE)),
    # Glass is chrome-only; a `--glass-*` token on a panel is gloss on data-ink.
    ("glass token (chrome-only)", re.compile(r"--glass-")),
    # Gradients are chrome-only, whether via the brand token or a raw function.
    (
        "gradient (chrome-only)",
        re.compile(r"--brand-gradient-|(?:linear|radial)-gradient\s*\(", re.IGNORECASE),
    ),
    # Backdrop blur is a glass effect; data-ink stays flat and legible.
    (
        "blur / backdrop-filter (chrome-only)",
        re.compile(r"backdrop-filter|\bblur\s*\(", re.IGNORECASE),
    ),
)


def firewall_check(html: str) -> list[str]:
    """Return a list of design-firewall violations found in `html` (empty when
    clean). Pure inspection -- it reads the fragment and never rewrites it.

    A violation is a raw colour (hex or `rgb()/hsl()` function -- a would-be new
    status hue) or a chrome-only gloss effect (a `--glass-*` token, a gradient,
    or `blur()/backdrop-filter`) appearing in panel-authored HTML. The two
    reserved status hues are reached through `--amber`/`--crimson`, never a
    literal, so those never trip this."""
    violations: list[str] = []
    for name, pattern in _FIREWALL_PATTERNS:
        match = pattern.search(html)
        if match is not None:
            violations.append(f"{name}: found {match.group(0)!r}")
    return violations


class WidgetRegistry:
    """An ordered, in-process registry of dashboard :class:`Widget`s.

    Registration is explicit Python -- there is no discovery, no dynamic import.
    Insertion order is preserved so the route (and the docs) can reason about a
    stable sequence. The registry renders a panel by id from a shared
    :class:`DashboardContext`; it never mutates the context and never restyles a
    panel's output. `render(..., enforce=True)` additionally runs the firewall
    and raises :class:`FirewallViolation` on any breach -- the contract-level
    hook the test suite drives as a merge gate.
    """

    def __init__(self) -> None:
        self._widgets: dict[str, Widget] = {}

    def register(self, widget: Widget) -> Widget:
        """Register `widget`. Raises `ValueError` on a duplicate id -- a
        silently-overwritten panel is a footgun, so collisions fail loud."""
        if widget.id in self._widgets:
            raise ValueError(f"widget id already registered: {widget.id!r}")
        self._widgets[widget.id] = widget
        return widget

    def get(self, widget_id: str) -> Widget:
        """Return the widget for `widget_id`, or raise `KeyError` naming the
        unknown id and the ids that do exist."""
        try:
            return self._widgets[widget_id]
        except KeyError:
            known = ", ".join(self._widgets) or "(none)"
            raise KeyError(f"no widget registered with id {widget_id!r}; known: {known}") from None

    def render(self, widget_id: str, ctx: DashboardContext, *, enforce: bool = False) -> str:
        """Render the panel `widget_id` from `ctx`.

        The default path is the fast one the route uses: it returns the panel's
        fragment untouched, so routed output is byte-for-byte what the inline
        call produced. With `enforce=True` the rendered fragment is run through
        :func:`firewall_check` and a `FirewallViolation` is raised on any breach
        -- the contract-level enforcement the tests exercise for every
        registered panel."""
        html = self.get(widget_id).render(ctx)
        if enforce:
            violations = firewall_check(html)
            if violations:
                raise FirewallViolation(
                    f"widget {widget_id!r} breaks the design firewall: " + "; ".join(violations)
                )
        return html

    def check(self, widget_id: str, ctx: DashboardContext) -> list[str]:
        """Render `widget_id` and return its firewall violations (empty when
        clean) without raising -- for reporting over a whole registry."""
        return firewall_check(self.get(widget_id).render(ctx))

    def ids(self) -> tuple[str, ...]:
        """The registered widget ids, in registration order."""
        return tuple(self._widgets)

    def widgets(self) -> tuple[Widget, ...]:
        """The registered widgets, in registration order."""
        return tuple(self._widgets.values())

    def __contains__(self, widget_id: object) -> bool:
        return widget_id in self._widgets

    def __len__(self) -> int:
        return len(self._widgets)


def context_field_names() -> frozenset[str]:
    """The set of valid :class:`DashboardContext` field names -- used by the
    contract's tests to catch a `Widget.needs` entry that has drifted from a
    real context field."""
    return frozenset(f.name for f in fields(DashboardContext))


# ===========================================================================
# wt-v4 "Observatory" (Lane B: obs-widgets) -- new observability panels.
#
# These are DELIBERATELY NOT routed through the legacy `Widget`/
# `WidgetRegistry` above: that pair's `render` is typed
# `Callable[[DashboardContext], str]`, one flat, scalar, frozen dataclass
# shared by every panel. The v4 Observatory's IA (BRIEF.md) is list/row-
# shaped -- a fleet table, a ranked attention queue, an agent roster, an
# activity feed -- data that does not fit one shared scalar context the way
# the old workspace-wide dashboard did. Forcing it in would mean either one
# giant DashboardContext field per new panel (coupling every panel to every
# other panel's data) or silently overloading the same frozen dataclass with
# unrelated shapes. Instead, each panel below has its OWN small `TypedDict`
# (the "PLAIN DATA dict" the build spec asks for) naming exactly what it
# needs -- and each one is exactly what a caller (Lane C's page-assembly
# code) constructs from real adapter/DB data and calls the matching
# `render_*` function with directly.
#
# `ObservatoryWidget` still reuses `WidgetSize` (FULL/HALF, a pure layout
# hint) so page-arranging code can read one consistent enum regardless of
# which registry a panel came from -- and `firewall_check` (above) still
# applies to every one of these render functions' output; see
# `tests/unit/test_chartsvg_and_observatory_widgets.py`.
# ===========================================================================


# ---------------------------------------------------------------------------
# verdict_line -- the hero's one-sentence narrative. Real logic (state
# selection + pluralization + two scope-specific phrasings), not a free
# widget -- GAUNTLET-SYNTHESIS.md scopes it as its own build item. Pure,
# data-driven, no adapter/DB imports: every number and reason clause is
# supplied by the caller.
# ---------------------------------------------------------------------------

VerdictState = Literal["alarm", "calm", "idle"]


class VerdictLineData(TypedDict):
    """Input to :func:`verdict_line`.

    `scope` selects which of the two mockup narrative shapes is produced:

    * ``"environment"`` (L0, Mission Control) -- the "otherwise healthy"
      clause reports ready/held totals and resolved-in-a-period; needs
      `ready_total`/`held_total`.
    * ``"project"`` (L1, Project Observatory) -- the clause instead reports
      agents active vs. resolved-vs-created over a period; needs
      `created_count`.

    The two scopes report genuinely different statistics (see BRIEF.md), so
    the scope-specific fields are `NotRequired` rather than forcing one
    scope to supply meaningless data for the other's shape.

    `reasons` are already-worded clauses (e.g. `"2 claims sitting past
    custody TTL"`, or for project scope an item link like `'<a
    href="...">cortex-t22p</a> stale custody, 5h 42m past TTL'`) -- this
    function composes them into the narrative and picks state/headline, it
    does not invent the wording of an individual reason.
    """

    scope: Literal["environment", "project"]
    attention_count: int
    reasons: list[str]
    agents_active: int
    resolved_count: int
    resolved_period_label: str
    ready_total: NotRequired[int]
    held_total: NotRequired[int]
    created_count: NotRequired[int]


class Verdict(TypedDict):
    """The composed result: `state` picks the hero's icon/border variant
    (`.hero.is-{state}`), `headline` is the short verdict word/phrase,
    `detail_html` is the one-sentence narrative (may contain `<b>`/`<a>`
    markup -- rendered as-is, not escaped, by `render_verdict_hero`)."""

    state: VerdictState
    headline: str
    detail_html: str


def _plural(n: int, singular: str, plural_form: str | None = None) -> str:
    word = singular if n == 1 else (plural_form or f"{singular}s")
    return f"{n} {word}"


def _env_headline(state: VerdictState, attention_count: int) -> str:
    if state == "alarm":
        noun = "item" if attention_count == 1 else "items"
        verb = "needs" if attention_count == 1 else "need"
        return f"{attention_count} {noun} {verb} you"
    if state == "calm":
        return "All clear"
    return "Idle"


def _project_headline(state: VerdictState, attention_count: int) -> str:
    if state == "alarm":
        noun = "item" if attention_count == 1 else "items"
        verb = "requires" if attention_count == 1 else "require"
        return f"Needs you — {attention_count} {noun} {verb} attention"
    if state == "calm":
        return "All clear"
    return "Idle"


def _env_stats_clause(data: VerdictLineData) -> str:
    agents = data["agents_active"]
    ready = data.get("ready_total", 0)
    held = data.get("held_total", 0)
    resolved = data["resolved_count"]
    period = data["resolved_period_label"]
    return (
        f"<b>{_plural(agents, 'agent')}</b> are moving <b>{ready} ready</b> items through "
        f"<b>{held} held</b> toward <b>{resolved} resolved in the last {period}</b>."
    )


def _env_detail(state: VerdictState, reasons: list[str], data: VerdictLineData) -> str:
    if state == "alarm":
        return f"{', '.join(reasons)}. Everything else — {_env_stats_clause(data)}"
    if state == "calm":
        return f"Nothing stuck, nothing waiting past its TTL. {_env_stats_clause(data)}"
    resolved = data["resolved_count"]
    period = data["resolved_period_label"]
    items = _plural(resolved, "item")
    return f"Nothing in flight. {items} resolved in the last {period}; no agents active."


def _project_stats_clause(data: VerdictLineData) -> str:
    agents = data["agents_active"]
    resolved = data["resolved_count"]
    created = data.get("created_count", 0)
    period = data["resolved_period_label"]
    agent_html = f"<b>{_plural(agents, 'agent')}</b>"
    resolved_html = f"<b>{resolved} resolved</b> in the last {period}"
    return f"{agent_html} active, {resolved_html} against <b>{created} created</b>."


def _project_detail(state: VerdictState, reasons: list[str], data: VerdictLineData) -> str:
    if state == "alarm":
        return f"{' · '.join(reasons)}. Otherwise healthy: {_project_stats_clause(data)}"
    if state == "calm":
        return f"Nothing stuck, nothing waiting past its TTL. {_project_stats_clause(data)}"
    resolved = data["resolved_count"]
    period = data["resolved_period_label"]
    items = _plural(resolved, "item")
    return f"Nothing in flight. {items} resolved in the last {period}; no agents active."


def _is_idle(data: VerdictLineData) -> bool:
    if data["scope"] == "environment":
        return data.get("ready_total", 0) == 0 and data.get("held_total", 0) == 0
    return data["resolved_count"] == 0 and data["agents_active"] == 0


def verdict_line(data: VerdictLineData) -> Verdict:
    """Compose the hero's one-sentence narrative for either scope.

    State is chosen purely from the numbers (never from the mere presence
    of a `reasons` list): `attention_count > 0` is "alarm"; otherwise, if
    nothing is in flight (`_is_idle`) it is "idle"; otherwise "calm".
    Raises `ValueError` if `attention_count > 0` but `reasons` is empty --
    an alarm state with nothing to enumerate is a caller bug, not a valid
    narrative.
    """
    scope = data["scope"]
    attention_count = data["attention_count"]
    reasons = data["reasons"]

    if attention_count > 0 and not reasons:
        raise ValueError("verdict_line: attention_count > 0 requires at least one reason")

    state: VerdictState
    if attention_count > 0:
        state = "alarm"
    elif _is_idle(data):
        state = "idle"
    else:
        state = "calm"

    if scope == "environment":
        headline = _env_headline(state, attention_count)
        detail = _env_detail(state, reasons, data)
    else:
        headline = _project_headline(state, attention_count)
        detail = _project_detail(state, reasons, data)

    return Verdict(state=state, headline=headline, detail_html=detail)


# ---------------------------------------------------------------------------
# The Observatory widget registry -- a lightweight, additive parallel to
# `WidgetRegistry` above (see the module-section docstring for why it's
# separate). `register()` refuses a duplicate id for the same reason the
# legacy registry does: a silently-overwritten panel is a footgun.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ObservatoryWidget:
    """One wt-v4 Observatory panel: id/title/size metadata plus its render
    function. `render` takes exactly ONE argument -- that panel's own
    `*Data` TypedDict (see this section's classes) -- and returns an HTML
    fragment, same as the legacy `Widget.render` contract, just not typed to
    the one shared `DashboardContext`."""

    id: str
    title: str
    size: WidgetSize
    render: Callable[[Any], str]
    description: str = ""


_OBSERVATORY_WIDGETS: dict[str, ObservatoryWidget] = {}


def _register_observatory(widget: ObservatoryWidget) -> ObservatoryWidget:
    if widget.id in _OBSERVATORY_WIDGETS:
        raise ValueError(f"observatory widget id already registered: {widget.id!r}")
    _OBSERVATORY_WIDGETS[widget.id] = widget
    return widget


def observatory_widget_ids() -> tuple[str, ...]:
    """The registered Observatory widget ids, in registration order."""
    return tuple(_OBSERVATORY_WIDGETS)


def get_observatory_widget(widget_id: str) -> ObservatoryWidget:
    """Return the Observatory widget for `widget_id`, or raise `KeyError`
    naming the unknown id and the ids that do exist."""
    try:
        return _OBSERVATORY_WIDGETS[widget_id]
    except KeyError:
        known = ", ".join(_OBSERVATORY_WIDGETS) or "(none)"
        raise KeyError(
            f"no observatory widget registered with id {widget_id!r}; known: {known}"
        ) from None


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _title_attr(raw: str) -> str:
    """`' title="..."'` (leading space included) for a non-empty tooltip
    value, or `""` when there's nothing to show one for. The one place a
    widget adds an optional `title=` attribute to an element it otherwise
    builds from plain-text fields -- see `FleetRow`'s docstring for why
    this split (plain text field + separate `_title` field) replaced
    accepting a pre-rendered `<span title=...>` HTML string from a route."""
    return f' title="{_esc(raw)}"' if raw else ""


# ---------------------------------------------------------------------------
# 1. verdict-hero
# ---------------------------------------------------------------------------


class MetaCell(TypedDict):
    """One `.meta-row` fact under the L1 project hero (e.g. `{"k": "Total
    items", "v": "465"}`). L0's environment hero has no meta-row."""

    k: str
    v: str


_META_VALUE_SUFFIX_RE = re.compile(r"^(-?\d+)(\D.*)$")


def _split_meta_value(v: str) -> tuple[str, str]:
    """Split a `.meta-row` value into (leading number, trailing unit
    suffix) -- e.g. `"6d"` -> `("6", "d")`, `"3h ago"` -> `("3", "h ago")`.
    A value with no leading number (a plain count like `"465"`, or the em
    dash `"\u2014"` for "no data") returns `(v, "")` -- unchanged, no
    suffix span (visual-polish punchlist item 6: mixed-unit meta-row
    values -- a plain count next to a duration like "6d" or "3h ago" --
    didn't share a visual baseline, and the unit suffix was set at the
    SAME size/weight as the number, reading as one run-on string rather
    than "a number, then its unit"."""
    m = _META_VALUE_SUFFIX_RE.match(v)
    return (m.group(1), m.group(2)) if m else (v, "")


class VerdictHeroData(TypedDict):
    """Wraps a composed :class:`Verdict` (see `verdict_line`) plus the hero
    chrome around it. `eyebrow` is the small label above the headline
    (e.g. `"Environment verdict · 21 projects"` / `"Project verdict ·
    cortex"`). `detail_html` is rendered UNESCAPED (it legitimately carries
    `<b>`/`<a>` markup composed by `verdict_line`/the caller)."""

    state: VerdictState
    eyebrow: str
    headline: str
    detail_html: str
    meta_row: NotRequired[list[MetaCell]]


_HERO_ICON: dict[VerdictState, str] = {
    "alarm": "i-alert-triangle",
    "calm": "i-check-circle",
    "idle": "i-clock",
}


def render_verdict_hero(data: VerdictHeroData) -> str:
    """Render the `.hero` panel. References icon ids `#i-alert-triangle`,
    `#i-check-circle`, `#i-clock` -- the page shell's icon sprite must
    define all three (see the mockups' `<svg>` `<defs>` block)."""
    state = data["state"]
    icon = _HERO_ICON[state]
    meta_html = ""
    rows = data.get("meta_row")
    if rows:
        cell_htmls = []
        for m in rows:
            main, suffix = _split_meta_value(m["v"])
            suffix_html = f'<span class="v-suffix">{_esc(suffix)}</span>' if suffix else ""
            cell_htmls.append(
                f'<div class="m"><span class="k">{_esc(m["k"])}</span><br>'
                f'<span class="v">{_esc(main)}{suffix_html}</span></div>'
            )
        meta_html = f'<div class="meta-row">{"".join(cell_htmls)}</div>'
    return (
        f'<div class="glass-panel strong rim-glow hero is-{state}">'
        f'<div class="eyebrow2">{_esc(data["eyebrow"])}</div>'
        f'<div class="verdict"><span class="icon"><svg><use href="#{icon}"/></svg></span> '
        f"{_esc(data['headline'])}</div>"
        f'<div class="detail">{data["detail_html"]}</div>'
        f"{meta_html}"
        "</div>"
    )


# ---------------------------------------------------------------------------
# 2. kpi-strip
# ---------------------------------------------------------------------------


class KpiCard(TypedDict):
    """One KPI card. `is_blocked`, when true, marks the Blocked KPI
    specifically -- it gets the `.is-blocked` class, and additionally
    `.is-zero` (a quiet, neutral treatment) once `value == 0`, so a healthy
    "0 blocked" environment never keeps reading as alarm-red for a status
    that no longer applies."""

    key: str
    label: str
    value: int
    href: str
    icon: NotRequired[str]
    icon_color_var: NotRequired[str]
    is_blocked: NotRequired[bool]


class KpiStripData(TypedDict):
    cards: list[KpiCard]


def render_kpi_strip(data: KpiStripData) -> str:
    """Render the `.kpi-strip` of `.kpi-card` links."""
    cards_html: list[str] = []
    for c in data["cards"]:
        classes = "glass-panel kpi-card"
        if c.get("is_blocked"):
            classes += " is-blocked"
            if c["value"] == 0:
                classes += " is-zero"
        icon_html = ""
        icon = c.get("icon")
        if icon:
            color_var = c.get("icon_color_var")
            style = f' style="color:var({color_var})"' if color_var else ""
            icon_html = f'<span class="icon sm"{style}><svg><use href="#{icon}"/></svg></span> '
        cards_html.append(
            f'<a href="{_esc(c["href"])}" class="{classes}">'
            f'<div class="k"><span>{icon_html}{_esc(c["label"])}</span>'
            f'<span class="icon sm chev"><svg><use href="#i-chevron"/></svg></span></div>'
            f'<div class="v">{c["value"]}</div></a>'
        )
    return f'<div class="kpi-strip">{"".join(cards_html)}</div>'


# ---------------------------------------------------------------------------
# 3. attention-queue
# ---------------------------------------------------------------------------


class AttentionRow(TypedDict):
    """One ranked "needs you" row. `severity` selects the bar/icon colour
    class (`is-alarm`/`is-blocked`/`is-watch` -- stale-custody, blocked, and
    aging-ready respectively). `reason_html` is rendered unescaped (it may
    carry a `title=` tooltip span, e.g. `'<span title="...">Stale
    custody</span> — <span class="who">agent-x</span>'`)."""

    severity: Literal["alarm", "blocked", "watch"]
    icon: str
    priority: str
    project: str
    title: str
    reason_html: str
    rank: int
    age_label: str
    href: str


class AttentionQueueData(TypedDict):
    """`rows` is the queue rows actually rendered -- already capped by the
    caller (see `_L0_ATTENTION_QUEUE_SHOWN` in webapp.py); this widget never
    re-slices. `total` is the FULL ranked-queue count before capping. When
    `total` exceeds `len(rows)` the widget prints an honest "Showing N of
    M" truncation-note footer, the same convention `render_agents_now`/
    `render_activity_feed` already use -- the mockup's queue is a compact
    ~8-row panel, never a full 50-row page-dominating list."""

    rows: list[AttentionRow]
    total: int


def render_attention_queue(data: AttentionQueueData) -> str:
    """Render the `.attn-list` of ranked `.attn-row` links. `.title`/
    `.reason` are `display:block` with `overflow:hidden;text-overflow:
    ellipsis` in the shared CSS -- the ellipsis fix GAUNTLET-SYNTHESIS.md
    item 7 calls for -- so no wrapping/overflow work is needed here beyond
    emitting the same `<span class="title">`/`<span class="reason">`
    structure the CSS targets."""
    rows_html: list[str] = []
    for r in data["rows"]:
        priority_label = _esc(r["priority"].upper())
        rows_html.append(
            f'<a href="{_esc(r["href"])}" class="attn-row is-{r["severity"]}">'
            '<span class="bar"></span>'
            f'<span class="icon si"><svg><use href="#{r["icon"]}"/></svg></span>'
            f'<span class="priority-chip {_esc(r["priority"].lower())}" '
            f'title="Priority {_esc(r["priority"].lstrip("Pp"))}">{priority_label}</span>'
            '<span class="main">'
            f'<span class="title"><span class="proj">{_esc(r["project"])}</span> '
            f"{_esc(r['title'])}</span>"
            f'<span class="reason">{r["reason_html"]}</span>'
            "</span>"
            f'<span class="rank">#{r["rank"]}</span>'
            f'<span class="age">{_esc(r["age_label"])}</span>'
            '<span class="icon sm chev"><svg><use href="#i-chevron"/></svg></span>'
            "</a>"
        )
    shown = len(data["rows"])
    total = data["total"]
    truncation = ""
    if total > shown:
        truncation = (
            f'<div class="truncation-note">Showing {shown} of {total} '
            "\u2014 drill into a project for the rest.</div>"
        )
    return f'<div class="attn-list">{"".join(rows_html)}</div>{truncation}'


# ---------------------------------------------------------------------------
# 4. fleet-table
# ---------------------------------------------------------------------------

# Fixed 6-way status-mix render order/colour, shared with `status-breakdown`
# below -- Resolved, Ready, Held, Intake, Deferred (hatched), Blocked.
_MIX_ORDER: tuple[str, str, str, str, str, str] = (
    "resolved",
    "ready",
    "held",
    "intake",
    "deferred",
    "blocked",
)
_MIX_COLOR_VAR: dict[str, str] = {
    "resolved": "--ink-quiet",
    "ready": "--ink-secondary",
    "held": "--brand-cyan-ink",
    "intake": "--ink-tertiary",
    "blocked": "--blocked",
}


class FleetStatusMix(TypedDict):
    resolved: int
    ready: int
    held: int
    intake: int
    deferred: int
    blocked: int


def _status_mix_bar_html(mix: FleetStatusMix) -> str:
    """The compact 6-segment `.status-mix` bar shared by fleet rows. Deferred
    draws through the `.pat-hatch` texture class (never a flat colour --
    the same colourblind-safe distinction from Intake used everywhere else
    this mix appears)."""
    total = sum(mix[key] for key in _MIX_ORDER)  # type: ignore[literal-required]
    total = total if total > 0 else 1
    segments: list[str] = []
    for key in _MIX_ORDER:
        pct = round(mix[key] * 100 / total, 1)  # type: ignore[literal-required]
        if key == "deferred":
            segments.append(f'<span style="width:{pct}%" class="pat-hatch"></span>')
        else:
            segments.append(
                f'<span style="width:{pct}%;background:var({_MIX_COLOR_VAR[key]})"></span>'
            )
    tooltip = (
        f"{mix['ready']} ready · {mix['held']} held · {mix['blocked']} blocked · "
        f"{mix['deferred']} deferred · {mix['intake']} intake · {mix['resolved']} resolved"
    )
    return f'<span class="status-mix" title="{_esc(tooltip)}">{"".join(segments)}</span>'


class FleetRow(TypedDict):
    """One fleet-table row. `mix_legend_html` is the always-visible compact
    legend text (e.g. `"398r · 34rd · 18h · 5in · 3df · 7b"`) -- rendered
    unescaped since it may carry a `<span style="color:var(--watch)">(N
    stale)</span>` fragment for a stale-custody call-out (see the
    `vcos_spike` row in mock-L0). `sparkline_values` feeds
    `chartsvg.sparkline` directly.

    `last_activity` is PLAIN TEXT (e.g. `"3h ago"`, `"never"`, `"\u2014"`)
    -- unlike `mix_legend_html`, it is HTML-escaped by `render_fleet_table`
    itself. `last_activity_title` is the raw ISO-8601 timestamp (empty
    string when there is none to show) that the renderer places on a
    `title=` tooltip attribute. This two-field split exists so the route
    never has to hand a pre-rendered `<span title=...>` HTML string
    through a field the widget then escapes (which previously rendered
    the tag markup itself as visible text) -- the widget is the only
    place that ever emits the wrapping span."""

    name: str
    subtitle: str
    mix: FleetStatusMix
    mix_legend_html: str
    sparkline_values: list[float]
    sparkline_label: str
    agents: int
    last_activity: str
    last_activity_title: str
    href: str


class DormantProject(TypedDict):
    """`last_activity`/`last_activity_title` follow the same plain-text +
    tooltip-title split as `FleetRow` -- see that class's docstring."""

    name: str
    href: str
    items: int
    open_count: int
    resolved: int
    last_activity: str
    last_activity_title: str


class FleetTableData(TypedDict):
    total_projects: int
    rows: list[FleetRow]
    dormant: list[DormantProject]


def render_fleet_table(data: FleetTableData) -> str:
    """Render the fleet `.fleet-col-head` + `.fleet-list` rows, plus a
    collapsed `<details class="dormant-details">` section for dormant
    projects (14d+ no activity). References icon id `#i-bot`, `#i-chevron`."""
    rows_html: list[str] = []
    for row in data["rows"]:
        agents_class = "agents is-zero" if row["agents"] == 0 else "agents"
        spark = C.sparkline(row["sparkline_values"], aria_label=row["sparkline_label"])
        rows_html.append(
            f'<a href="{_esc(row["href"])}" class="fleet-row">'
            f'<span class="pname">{_esc(row["name"])}'
            f'<span class="n">{_esc(row["subtitle"])}</span></span>'
            f"<span>{_status_mix_bar_html(row['mix'])}"
            f'<span class="mix-legend">{row["mix_legend_html"]}</span></span>'
            f"{spark}"
            f'<span class="{agents_class}">'
            f'<span class="icon sm"><svg><use href="#i-bot"/></svg></span>{row["agents"]}</span>'
            f'<span class="last"{_title_attr(row["last_activity_title"])}>'
            f"{_esc(row['last_activity'])}</span>"
            '<span class="icon sm chev"><svg><use href="#i-chevron"/></svg></span>'
            "</a>"
        )

    dormant_rows = "".join(
        f'<tr><td><a href="{_esc(d["href"])}" style="color:inherit;text-decoration:none">'
        f"{_esc(d['name'])}</a></td>"
        f'<td class="n">{d["items"]}</td><td class="n">{d["open_count"]}</td>'
        f'<td class="n">{d["resolved"]}</td>'
        f'<td class="n"{_title_attr(d["last_activity_title"])}>{_esc(d["last_activity"])}</td></tr>'
        for d in data["dormant"]
    )
    dormant_html = ""
    if data["dormant"]:
        dormant_html = (
            '<details class="dormant-details">'
            f"<summary>Dormant — {len(data['dormant'])} projects, no activity in 14+ days "
            '<span class="icon sm chev"><svg><use href="#i-chevron"/></svg></span></summary>'
            '<table class="dormant-table">'
            "<tr><th>Project</th><th>Items</th><th>Open</th><th>Resolved</th>"
            "<th>Last activity</th></tr>"
            f"{dormant_rows}</table></details>"
        )

    return (
        '<div class="fleet-col-head"><span>Project</span><span>Status mix</span>'
        "<span>Resolved/day</span><span>Agents</span><span>Last activity</span><span></span></div>"
        f'<div class="fleet-list">{"".join(rows_html)}</div>'
        f"{dormant_html}"
    )


# ---------------------------------------------------------------------------
# 5. agents-now
# ---------------------------------------------------------------------------


class AgentNowRow(TypedDict):
    agent_id: str
    project: str
    item_id: str
    item_title: str
    freshness_label: str
    is_stale: bool
    href: str


class AgentsNowData(TypedDict):
    rows: list[AgentNowRow]
    shown: int
    total: int


def render_agents_now(data: AgentsNowData) -> str:
    """Render the fleet-wide "Agents now" roster: `.agents-now-col-head` +
    `.agents-now-list` rows, `has-stale` marking a claim past its TTL."""
    rows_html: list[str] = []
    for r in data["rows"]:
        cls = "agents-now-row has-stale" if r["is_stale"] else "agents-now-row"
        title = ' title="Custody held past its TTL without renewal"' if r["is_stale"] else ""
        rows_html.append(
            f'<a href="{_esc(r["href"])}" class="{cls}">'
            '<span class="icon sm ai"><svg><use href="#i-bot"/></svg></span>'
            f'<span class="aid">{_esc(r["agent_id"])}</span>'
            f'<span class="aproj">{_esc(r["project"])}</span>'
            f'<span class="aitem"><span class="id">{_esc(r["item_id"])}</span>'
            f"{_esc(r['item_title'])}</span>"
            f'<span class="afresh"{title}>{_esc(r["freshness_label"])}</span>'
            "</a>"
        )
    shown, total = data["shown"], data["total"]
    return (
        '<div class="agents-now-col-head"><span>Agent</span><span>Project</span>'
        "<span>Holding</span><span>Custody</span></div>"
        f'<div class="agents-now-list">{"".join(rows_html)}</div>'
        f'<div class="truncation-note">Showing {shown} of {total} active agents.</div>'
    )


# ---------------------------------------------------------------------------
# 6. activity-feed
# ---------------------------------------------------------------------------


class WindowTab(TypedDict):
    """One `?window=`/`?feed=` real-link tab (GAUNTLET-SYNTHESIS.md item 6:
    tabs are anchors, not client-side JS state)."""

    label: str
    href: str
    is_active: bool


_FEED_ICON: dict[str, str] = {
    "claim": "i-bot",
    "resolve": "i-check-circle",
    "block": "i-octagon-x",
    "file": "i-plus-file",
}


class ActivityFeedItem(TypedDict):
    kind: Literal["claim", "resolve", "block", "file"]
    actor: str
    verb: str
    project_item: str
    description: str
    time_label: str
    href: str


class ActivityFeedData(TypedDict):
    items: list[ActivityFeedItem]
    since_label: str
    window_tabs: list[WindowTab]
    shown: int
    total_estimate: int


def render_activity_feed(data: ActivityFeedData) -> str:
    """Render the collapsed-by-default `<details class="dormant-details
    feed-details">` activity feed: window tabs, linked rows, truncation
    note. References icon ids from `_FEED_ICON`'s values plus `#i-chevron`."""
    tabs_html = "".join(
        f'<a href="{_esc(t["href"])}" class="window-tab{" is-active" if t["is_active"] else ""}">'
        f"{_esc(t['label'])}</a>"
        for t in data["window_tabs"]
    )
    items_html: list[str] = []
    for item in data["items"]:
        icon = _FEED_ICON[item["kind"]]
        items_html.append(
            f'<a href="{_esc(item["href"])}" class="feed-item k-{item["kind"]}">'
            f'<span class="dot"><span class="icon" style="width:.7em;height:.7em">'
            f'<svg><use href="#{icon}"/></svg></span></span>'
            f'<span class="txt"><b>{_esc(item["actor"])}</b> {_esc(item["verb"])} '
            f'<span class="proj">{_esc(item["project_item"])}</span> — '
            f"{_esc(item['description'])}</span>"
            f'<span class="time">{_esc(item["time_label"])}</span>'
            "</a>"
        )
    return (
        # `open` (unlike the dormant-projects `<details>`, which stays
        # collapsed by default): a collapsed activity feed reads as
        # empty/missing rather than as a real, populated panel -- DOM-
        # measured on the live dashboard. A user can still collapse it;
        # `T.auto_refresh_js`'s existing open-`<details>`-preservation
        # already persists whatever state the user leaves it in across
        # a refresh, so defaulting to open costs nothing on that front.
        '<details class="dormant-details feed-details" open>'
        '<summary>Activity feed <span class="note" style="font-weight:400;margin-left:8px">'
        "cross-project · reverse-chronological</span> "
        '<span class="icon sm chev"><svg><use href="#i-chevron"/></svg></span></summary>'
        '<div class="glass-panel chart-card" style="margin-top:var(--space-3)">'
        '<div class="chart-head" style="margin-bottom:var(--space-3)">'
        f'<span class="note">{_esc(data["since_label"])}</span>'
        f'<div class="window-tabs">{tabs_html}</div></div>'
        f'<div class="feed-list">{"".join(items_html)}</div>'
        f'<div class="truncation-note">Showing {data["shown"]} most recent of '
        f"~{data['total_estimate']} events today across all projects.</div>"
        "</div></details>"
    )


# ---------------------------------------------------------------------------
# 7. status-breakdown
# ---------------------------------------------------------------------------


_MIX_NAME: dict[str, str] = {
    "resolved": "Resolved",
    "ready": "Ready",
    "held": "Held",
    "intake": "Intake",
    "deferred": "Deferred",
    "blocked": "Blocked",
}


class StatusBreakdownData(TypedDict):
    counts: C.StatusCounts
    total: int
    aria_label: str


def render_status_breakdown(data: StatusBreakdownData) -> str:
    """Render the `.status-breakdown-wrap`: `chartsvg.status_donut` plus a
    `.donut-center` total and a full `.mix-legend-full` (name/count/pct per
    status, `deferred`'s swatch using `.pat-hatch`)."""
    counts = data["counts"]
    total = data["total"]
    donut = C.status_donut(counts, aria_label=data["aria_label"])
    legend_rows: list[str] = []
    for key in _MIX_ORDER:
        count = counts[key]  # type: ignore[literal-required]
        pct = round(count * 100 / total, 1) if total > 0 else 0.0
        swatch = (
            '<span class="sw pat-hatch"></span>'
            if key == "deferred"
            else f'<span class="sw" style="background:var({_MIX_COLOR_VAR[key]})"></span>'
        )
        legend_rows.append(
            f'<div class="li">{swatch}<span class="name">{_MIX_NAME[key]}</span>'
            f'<span class="cnt">{count}</span><span class="pct">{pct}%</span></div>'
        )
    return (
        '<div class="status-breakdown-wrap">'
        f'<div class="donut-wrap">{donut}'
        f'<div class="donut-center"><span class="n">{total}</span>'
        '<span class="l">total items</span></div></div>'
        f'<div class="mix-legend-full">{"".join(legend_rows)}</div>'
        "</div>"
    )


# ---------------------------------------------------------------------------
# 8. ready-age-histogram
# ---------------------------------------------------------------------------


class ReadyAgeHistogramData(TypedDict):
    buckets: list[C.AgeBucket]
    ready_total: int
    aria_label: str
    flagged_note: NotRequired[str]


def render_ready_age_histogram(data: ReadyAgeHistogramData) -> str:
    """Render the ready-age `chartsvg.age_histogram` plus its legend and an
    optional flagged-bucket note."""
    chart = C.age_histogram(data["buckets"], aria_label=data["aria_label"])
    note_html = ""
    flagged_note = data.get("flagged_note")
    if flagged_note:
        # line-height 1.6 (visual-polish punchlist item 11): this note can
        # wrap to 2 lines on a narrow card even after the copy trim below
        # -- the shared `.truncation-note` class (used elsewhere for
        # always-single-line text) doesn't itself set a line-height, so a
        # wrapped instance here read cramped at the browser default.
        note_html = (
            '<div class="truncation-note" style="text-align:left;line-height:1.6">'
            f"{_esc(flagged_note)}</div>"
        )
    # NOTE: no "N ready items" counter here -- the L1 card HEAD already renders
    # it (webbrowse's chart-card shell), and emitting it here too produced a
    # visibly duplicated subtitle on the Ready-age card (owner-reported).
    # `ready_total` stays in the data contract: it feeds the aria_label and any
    # future headless embedding of this widget.
    return (
        f"{chart}"
        '<div class="legend" style="margin-top:0">'
        '<span class="li"><span class="dot" style="background:var(--ink-secondary)"></span> '
        "0-6d, normal</span>"
        '<span class="li"><span class="dot" style="background:var(--watch)"></span> '
        "7+d, watch (aging, not an alarm)</span>"
        "</div>"
        f"{note_html}"
    )


# ---------------------------------------------------------------------------
# 9. agents-panel (L1 project page)
# ---------------------------------------------------------------------------


class AgentPanelRow(TypedDict):
    """One project-page agent row. `recent_kind` picks the "stalest:"/
    "latest:" prefix; `is_stale` marks `.has-stale` (past-TTL freshness
    pill)."""

    agent_id: str
    held_count: int
    recent_kind: Literal["stalest", "latest"]
    recent_item_id: str
    freshness_label: str
    is_stale: bool
    href: str


class AgentsPanelData(TypedDict):
    rows: list[AgentPanelRow]
    active_count: int
    held_count: int


def render_agents_panel(data: AgentsPanelData) -> str:
    """Render the L1 "Agents on {project}" panel: `.agents-list` of
    `.agent-row` links. `.agent-row .name` is `white-space:nowrap` +
    ellipsis in the shared CSS (GAUNTLET-SYNTHESIS.md's nowrap fix) --
    satisfied by emitting the same `<span class="name">` structure."""
    rows_html: list[str] = []
    for r in data["rows"]:
        cls = "agent-row has-stale" if r["is_stale"] else "agent-row"
        title = ' title="Custody held past its TTL without renewal"' if r["is_stale"] else ""
        rows_html.append(
            f'<a href="{_esc(r["href"])}" class="{cls}">'
            '<span class="icon ai"><svg><use href="#i-bot"/></svg></span>'
            f'<span class="name">{_esc(r["agent_id"])}'
            f'<span class="held-n">{r["held_count"]} held</span></span>'
            f'<span class="most-recent">{r["recent_kind"]}: '
            f'<span class="id">{_esc(r["recent_item_id"])}</span></span>'
            f'<span class="freshness"{title}>{_esc(r["freshness_label"])}</span>'
            "</a>"
        )
    return f'<div class="agents-list">{"".join(rows_html)}</div>'


_register_observatory(
    ObservatoryWidget(
        id="verdict-hero",
        title="Verdict",
        size=WidgetSize.FULL,
        render=render_verdict_hero,
        description="The hero panel's alarm/calm/idle narrative.",
    )
)
_register_observatory(
    ObservatoryWidget(
        id="kpi-strip",
        title="KPI strip",
        size=WidgetSize.FULL,
        render=render_kpi_strip,
        description="Agents active / held / ready / blocked / resolved-24h cards.",
    )
)
_register_observatory(
    ObservatoryWidget(
        id="attention-queue",
        title="Needs you — ranked",
        size=WidgetSize.HALF,
        render=render_attention_queue,
        description="Ranked stale-custody -> blocked -> aging-ready rows.",
    )
)
_register_observatory(
    ObservatoryWidget(
        id="fleet-table",
        title="Fleet",
        size=WidgetSize.FULL,
        render=render_fleet_table,
        description="Every project ranked by recent activity, plus a dormant section.",
    )
)
_register_observatory(
    ObservatoryWidget(
        id="agents-now",
        title="Agents now",
        size=WidgetSize.FULL,
        render=render_agents_now,
        description="Fleet-wide roster of active agents and what they hold.",
    )
)
_register_observatory(
    ObservatoryWidget(
        id="activity-feed",
        title="Activity feed",
        size=WidgetSize.FULL,
        render=render_activity_feed,
        description="Cross-project reverse-chronological event stream.",
    )
)
_register_observatory(
    ObservatoryWidget(
        id="status-breakdown",
        title="Status breakdown",
        size=WidgetSize.HALF,
        render=render_status_breakdown,
        description="Six-way status-mix donut plus full legend.",
    )
)
_register_observatory(
    ObservatoryWidget(
        id="ready-age-histogram",
        title="Ready-age",
        size=WidgetSize.HALF,
        render=render_ready_age_histogram,
        description="Ready-item age distribution (0-1d/2-3d/4-6d/7+d).",
    )
)
_register_observatory(
    ObservatoryWidget(
        id="agents-panel",
        title="Agents on project",
        size=WidgetSize.HALF,
        render=render_agents_panel,
        description="Per-project holder rows with custody freshness.",
    )
)
