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

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid importing heavy siblings at module import time
    from . import adapter as A

__all__ = [
    "DashboardContext",
    "FirewallViolation",
    "Widget",
    "WidgetRegistry",
    "WidgetSize",
    "firewall_check",
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
