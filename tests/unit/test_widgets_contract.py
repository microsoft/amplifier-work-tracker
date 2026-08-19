"""Tier 1 -- the INTERNAL dashboard widget contract (goal wtv2/plugin): the
typed :class:`WidgetRegistry` / :class:`DashboardContext` / :class:`Widget`
seam, its design-system firewall, and the proof that the four real overview
panels (`workspace-composition`, `ready-queue-by-age`, `throughput`,
`needs-you`) render byte-for-byte identically whether the route calls their
builder inline or routes them through the registry.

Everything here is a pure function of constructed `ProjectSummary` values and
plain strings -- no `bd`, no dolt server, no running FastAPI app. The `webapp`
import is guarded with `pytest.importorskip` exactly like
`tests/unit/test_overview_needs_you.py`, since `webapp.py` imports `fastapi` at
module scope; the contract module itself (`widgets.py`) has no web dependency.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import widgets as WD

pytest.importorskip("fastapi", reason="the 'web' extra is not installed")

from amplifier_work_tracker import webapp as W  # noqa: E402

NOW = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)


def _summary(name: str, **kwargs: Any) -> A.ProjectSummary:
    defaults: dict[str, Any] = dict(
        status=A.STATUS_OK,
        total=0,
        ready=0,
        held=0,
        intake=0,
        blocked=0,
        resolved=0,
        deferred=0,
        held_stale=0,
        blocked_stale=0,
        held_stale_oldest_age_seconds=None,
        oldest_unclaimed_age_seconds=None,
        resolved_24h=0,
        resolved_7d=0,
        ready_age_buckets={"0-1": 0, "2-3": 0, "4-6": 0, "7+": 0, A.UNKNOWN_READY_AGE: 0},
    )
    defaults.update(kwargs)
    return A.ProjectSummary(name=name, **defaults)


def _ctx(**over: Any) -> WD.DashboardContext:
    base: dict[str, Any] = dict(
        summaries=(),
        ok=(),
        rendered_at=NOW,
        buckets={"0-1": 0, "2-3": 0, "4-6": 0, "7+": 0},
        reconciled_items=0,
        ready_total=0,
        held_total=0,
        blocked_total=0,
        deferred_total=0,
        resolved_total=0,
        resolved_24h_total=0,
        resolved_7d_total=0,
        prior6d_rate=0.0,
        delta_pct=None,
        older_than_7d=0,
        n_measurable_with_resolutions=0,
        n_with_resolutions=0,
    )
    base.update(over)
    return WD.DashboardContext(**base)


def _attention_ctx() -> WD.DashboardContext:
    """A context that makes every registered panel render real, non-empty
    content -- so the firewall/parity checks see the panels' full output, not
    just their empty states."""
    cust = _summary("cust", held=2, held_stale=2, held_stale_oldest_age_seconds=5 * 3600, total=2)
    blk = _summary("blk", blocked=1, blocked_stale=1, total=1)
    aged = _summary(
        "aged",
        ready=4,
        total=4,
        oldest_unclaimed_age_seconds=9 * 86400,
        ready_age_buckets={"0-1": 0, "2-3": 0, "4-6": 0, "7+": 4, A.UNKNOWN_READY_AGE: 0},
    )
    ok = (cust, blk, aged)
    return _ctx(
        summaries=ok,
        ok=ok,
        buckets={"0-1": 1, "2-3": 0, "4-6": 0, "7+": 4},
        reconciled_items=7,
        ready_total=4,
        held_total=2,
        blocked_total=1,
        deferred_total=0,
        resolved_total=0,
        resolved_24h_total=1,
        resolved_7d_total=3,
        prior6d_rate=0.5,
        delta_pct=12,
        older_than_7d=2,
        n_measurable_with_resolutions=1,
        n_with_resolutions=1,
    )


# ---------------------------------------------------------------------------
# registry mechanics (item 1)
# ---------------------------------------------------------------------------


def test_register_and_get_roundtrip() -> None:
    reg = WD.WidgetRegistry()
    w = WD.Widget(id="x", title="X", size=WD.WidgetSize.FULL, render=lambda c: "<div></div>")
    assert reg.register(w) is w
    assert reg.get("x") is w
    assert "x" in reg
    assert reg.ids() == ("x",)
    assert reg.widgets() == (w,)
    assert len(reg) == 1


def test_register_duplicate_id_fails_loud() -> None:
    reg = WD.WidgetRegistry()
    reg.register(WD.Widget(id="dup", title="A", size=WD.WidgetSize.FULL, render=lambda c: ""))
    with pytest.raises(ValueError, match="already registered"):
        reg.register(WD.Widget(id="dup", title="B", size=WD.WidgetSize.HALF, render=lambda c: ""))


def test_get_unknown_id_names_known_ids() -> None:
    reg = WD.WidgetRegistry()
    reg.register(WD.Widget(id="a", title="A", size=WD.WidgetSize.FULL, render=lambda c: ""))
    with pytest.raises(KeyError, match="no widget registered.*missing.*known: a"):
        reg.get("missing")


def test_registry_preserves_registration_order() -> None:
    reg = WD.WidgetRegistry()
    for wid in ("first", "second", "third"):
        reg.register(WD.Widget(id=wid, title=wid, size=WD.WidgetSize.FULL, render=lambda c: ""))
    assert reg.ids() == ("first", "second", "third")


def test_render_passes_context_and_returns_fragment() -> None:
    reg = WD.WidgetRegistry()
    reg.register(
        WD.Widget(
            id="e",
            title="Echo",
            size=WD.WidgetSize.FULL,
            render=lambda c: f'<div class="comp">{c.ready_total}</div>',
        )
    )
    assert reg.render("e", _ctx(ready_total=42)) == '<div class="comp">42</div>'


# ---------------------------------------------------------------------------
# design-system firewall (item 1: enforceable at the contract level)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "html",
    [
        '<i style="background:#ff0000"></i>',  # raw hex -> would-be new status hue
        '<i style="background:#abc"></i>',  # short hex
        '<i style="color:rgba(1,2,3,.5)"></i>',  # raw colour function
        '<i style="color:hsl(1,2%,3%)"></i>',
        '<i style="background:var(--glass-fill)"></i>',  # glass on data-ink
        '<i style="background:linear-gradient(var(--amber),var(--crimson))"></i>',  # gradient
        '<i style="background:var(--brand-gradient-rim)"></i>',
        '<i style="backdrop-filter:blur(4px)"></i>',  # glass blur
        '<i style="filter:blur(2px)"></i>',
    ],
)
def test_firewall_flags_raw_colour_and_gloss(html: str) -> None:
    assert WD.firewall_check(html) != []


@pytest.mark.parametrize(
    "html",
    [
        '<i style="flex:2 1 0;background:var(--amber);min-width:16px"></i>',  # reserved status hue
        '<span style="color:var(--crimson)">x</span>',
        '<i style="background:var(--st-ready)"></i>',  # a component token, not forbidden
        "a &#8217; b &middot; c",  # numeric HTML entity is NOT a hex colour
        '<a href="/projects/x#top">y</a>',  # a URL fragment is not a colour
        '<div class="thru"><span class="tn">4</span></div>',  # class-driven, no inline colour
    ],
)
def test_firewall_passes_token_only_and_avoids_false_positives(html: str) -> None:
    assert WD.firewall_check(html) == []


def test_render_enforce_raises_on_violation() -> None:
    reg = WD.WidgetRegistry()
    reg.register(
        WD.Widget(
            id="bad",
            title="Bad",
            size=WD.WidgetSize.FULL,
            render=lambda c: '<i style="background:#ff0000"></i>',
        )
    )
    # Fast path (default) does not enforce -- it must not alter or reject output.
    assert reg.render("bad", _ctx()) == '<i style="background:#ff0000"></i>'
    with pytest.raises(WD.FirewallViolation, match="design firewall"):
        reg.render("bad", _ctx(), enforce=True)


# ---------------------------------------------------------------------------
# the real dashboard registry: contents, firewall, and needs-validity
# ---------------------------------------------------------------------------


def test_dashboard_registry_has_the_four_v2_panels() -> None:
    assert set(W.DASHBOARD_WIDGETS.ids()) == {
        "workspace-composition",
        "ready-queue-by-age",
        "throughput",
        "needs-you",
    }


def test_dashboard_widget_needs_are_real_context_fields() -> None:
    valid = WD.context_field_names()
    for widget in W.DASHBOARD_WIDGETS.widgets():
        unknown = [name for name in widget.needs if name not in valid]
        assert unknown == [], f"{widget.id} declares unknown context fields: {unknown}"


def test_every_dashboard_widget_obeys_the_firewall_when_populated() -> None:
    # The contract-level enforcement gate: every registered panel, rendered with
    # real (non-empty) content, must draw only through design tokens.
    ctx = _attention_ctx()
    for widget in W.DASHBOARD_WIDGETS.widgets():
        assert W.DASHBOARD_WIDGETS.render(widget.id, ctx, enforce=True)


def test_every_dashboard_widget_obeys_the_firewall_when_empty() -> None:
    # Empty states (no ready work, nothing needs a human) must pass too.
    ctx = _ctx()
    for widget in W.DASHBOARD_WIDGETS.widgets():
        # needs-you is absent (empty string) when calm; that is firewall-clean.
        W.DASHBOARD_WIDGETS.render(widget.id, ctx, enforce=True)


# ---------------------------------------------------------------------------
# byte-identical parity: routed output == the original inline builder output
# ---------------------------------------------------------------------------


def _direct(ctx: WD.DashboardContext) -> dict[str, str]:
    """Render each panel the OLD way -- calling its builder directly with the
    exact argument mapping `dashboard()` used before the refactor."""
    return {
        "workspace-composition": W._workspace_composition_html(  # noqa: SLF001
            {
                "ready": ctx.ready_total,
                "held": ctx.held_total,
                "blocked": ctx.blocked_total,
                "deferred": ctx.deferred_total,
                "resolved": ctx.resolved_total,
            },
            ctx.reconciled_items,
        ),
        "ready-queue-by-age": W._heartbeat_html(dict(ctx.buckets)),  # noqa: SLF001
        "throughput": W._throughput_html(  # noqa: SLF001
            ctx.resolved_24h_total,
            ctx.prior6d_rate,
            ctx.delta_pct,
            ctx.resolved_7d_total,
            ctx.older_than_7d,
            ctx.n_measurable_with_resolutions,
            ctx.n_with_resolutions,
        ),
        "needs-you": W._needs_you_html(  # noqa: SLF001
            W._attention_entries(list(ctx.ok)),  # noqa: SLF001
            ctx.rendered_at,
        ),
    }


@pytest.mark.parametrize("scenario", ["empty", "populated"])
def test_routed_output_is_byte_identical_to_inline_builder(scenario: str) -> None:
    ctx = _ctx() if scenario == "empty" else _attention_ctx()
    before = _direct(ctx)
    for wid, expected in before.items():
        assert W.DASHBOARD_WIDGETS.render(wid, ctx) == expected, f"{wid} drifted ({scenario})"
