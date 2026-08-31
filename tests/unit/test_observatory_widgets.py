"""Tier 1 -- amplifier_work_tracker.widgets: the wt-v4 "Observatory" render
functions, `verdict_line`, and the Observatory widget registry (Lane B:
obs-widgets).

Fake data below is lifted from the approved mockups
(`.amplifier/design-gauntlet/wt-v4-observatory/{mock-L0,mock-L1,mock-L2}.html`)
at believable scale -- these are the exact shapes Lane C's page-assembly
code will construct from real adapter data and pass to each `render_*`
function directly (see this lane's own build-report for the full data-dict
contract).

Everything here is a pure function of plain dicts/TypedDicts -- no `bd`, no
dolt server, no running FastAPI app.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from amplifier_work_tracker import chartsvg as C
from amplifier_work_tracker import widgets as WD


def _firewall_clean(html: str) -> None:
    violations = WD.firewall_check(html)
    assert violations == [], f"firewall violations: {violations}"


# ---------------------------------------------------------------------------
# verdict_line -- state selection, pluralization, both scopes
# ---------------------------------------------------------------------------


def test_verdict_line_environment_alarm() -> None:
    data = WD.VerdictLineData(
        scope="environment",
        attention_count=8,
        reasons=[
            "2 claims sitting past custody TTL",
            "3 items blocked with no owner",
            "3 ready items aging past 6 days",
        ],
        agents_active=20,
        resolved_count=29,
        resolved_period_label="24h",
        ready_total=118,
        held_total=56,
    )
    v = WD.verdict_line(data)
    assert v["state"] == "alarm"
    assert v["headline"] == "8 items need you"
    assert v["detail_html"].startswith("2 claims sitting past custody TTL, 3 items blocked")
    assert "Everything else —" in v["detail_html"]
    assert "<b>20 agents</b>" in v["detail_html"]
    assert "<b>118 ready</b>" in v["detail_html"]
    assert "<b>56 held</b>" in v["detail_html"]
    assert "<b>29 resolved in the last 24h</b>" in v["detail_html"]


def test_verdict_line_environment_calm() -> None:
    data = WD.VerdictLineData(
        scope="environment",
        attention_count=0,
        reasons=[],
        agents_active=20,
        resolved_count=29,
        resolved_period_label="24h",
        ready_total=118,
        held_total=56,
    )
    v = WD.verdict_line(data)
    assert v["state"] == "calm"
    assert v["headline"] == "All clear"
    assert v["detail_html"].startswith("Nothing stuck, nothing waiting past its TTL.")


def test_verdict_line_environment_idle() -> None:
    data = WD.VerdictLineData(
        scope="environment",
        attention_count=0,
        reasons=[],
        agents_active=0,
        resolved_count=29,
        resolved_period_label="24h",
        ready_total=0,
        held_total=0,
    )
    v = WD.verdict_line(data)
    assert v["state"] == "idle"
    assert v["headline"] == "Idle"
    assert (
        v["detail_html"]
        == "Nothing in flight. 29 items resolved in the last 24h; no agents active."
    )


def test_verdict_line_project_alarm() -> None:
    data = WD.VerdictLineData(
        scope="project",
        attention_count=2,
        reasons=[
            '<a href="#">cortex-t22p</a> stale custody, 5h 42m past TTL',
            '<a href="#">cortex-m04j</a> blocked by cortex-l88q with no owner',
        ],
        agents_active=6,
        resolved_count=71,
        resolved_period_label="7 days",
        created_count=72,
    )
    v = WD.verdict_line(data)
    assert v["state"] == "alarm"
    assert v["headline"] == "Needs you — 2 items require attention"
    assert " · " in v["detail_html"]
    assert "Otherwise healthy:" in v["detail_html"]
    assert "<b>6 agents</b>" in v["detail_html"]
    assert "<b>71 resolved</b>" in v["detail_html"]
    assert "<b>72 created</b>" in v["detail_html"]


def test_verdict_line_project_calm() -> None:
    data = WD.VerdictLineData(
        scope="project",
        attention_count=0,
        reasons=[],
        agents_active=6,
        resolved_count=71,
        resolved_period_label="7 days",
        created_count=72,
    )
    v = WD.verdict_line(data)
    assert v["state"] == "calm"
    assert v["headline"] == "All clear"


def test_verdict_line_project_idle() -> None:
    data = WD.VerdictLineData(
        scope="project",
        attention_count=0,
        reasons=[],
        agents_active=0,
        resolved_count=0,
        resolved_period_label="7 days",
        created_count=0,
    )
    v = WD.verdict_line(data)
    assert v["state"] == "idle"
    assert v["headline"] == "Idle"


@pytest.mark.parametrize(
    ("count", "expected_headline"),
    [
        (1, "1 item needs you"),
        (2, "2 items need you"),
    ],
)
def test_verdict_line_environment_alarm_pluralization(count: int, expected_headline: str) -> None:
    data = WD.VerdictLineData(
        scope="environment",
        attention_count=count,
        reasons=["a reason"] * count,
        agents_active=1,
        resolved_count=1,
        resolved_period_label="24h",
        ready_total=1,
        held_total=1,
    )
    assert WD.verdict_line(data)["headline"] == expected_headline


@pytest.mark.parametrize(
    ("count", "expected_headline"),
    [
        (1, "Needs you — 1 item requires attention"),
        (2, "Needs you — 2 items require attention"),
    ],
)
def test_verdict_line_project_alarm_pluralization(count: int, expected_headline: str) -> None:
    data = WD.VerdictLineData(
        scope="project",
        attention_count=count,
        reasons=["a reason"] * count,
        agents_active=1,
        resolved_count=1,
        resolved_period_label="7 days",
        created_count=1,
    )
    assert WD.verdict_line(data)["headline"] == expected_headline


def test_verdict_line_single_agent_is_not_pluralized() -> None:
    data = WD.VerdictLineData(
        scope="environment",
        attention_count=0,
        reasons=[],
        agents_active=1,
        resolved_count=5,
        resolved_period_label="24h",
        ready_total=2,
        held_total=1,
    )
    assert "<b>1 agent</b>" in WD.verdict_line(data)["detail_html"]


def test_verdict_line_alarm_requires_reasons() -> None:
    data = WD.VerdictLineData(
        scope="environment",
        attention_count=3,
        reasons=[],
        agents_active=1,
        resolved_count=1,
        resolved_period_label="24h",
        ready_total=1,
        held_total=1,
    )
    with pytest.raises(ValueError, match="attention_count > 0"):
        WD.verdict_line(data)


# ---------------------------------------------------------------------------
# Observatory widget registry
# ---------------------------------------------------------------------------


def test_all_nine_observatory_widgets_are_registered() -> None:
    assert set(WD.observatory_widget_ids()) == {
        "verdict-hero",
        "kpi-strip",
        "attention-queue",
        "fleet-table",
        "agents-now",
        "activity-feed",
        "status-breakdown",
        "ready-age-histogram",
        "agents-panel",
    }


def test_get_observatory_widget_unknown_id_names_known_ids() -> None:
    with pytest.raises(KeyError, match="no observatory widget registered.*missing.*known:"):
        WD.get_observatory_widget("missing")


def test_get_observatory_widget_roundtrip() -> None:
    widget = WD.get_observatory_widget("verdict-hero")
    assert widget.id == "verdict-hero"
    assert widget.render is WD.render_verdict_hero


def test_register_observatory_duplicate_id_fails_loud() -> None:
    dup = WD.ObservatoryWidget(
        id="verdict-hero",  # already registered by the module itself
        title="Duplicate",
        size=WD.WidgetSize.FULL,
        render=lambda _data: "",
    )
    with pytest.raises(ValueError, match="already registered"):
        WD._register_observatory(dup)  # noqa: SLF001 -- exercising the guard directly


# ---------------------------------------------------------------------------
# render_verdict_hero
# ---------------------------------------------------------------------------


def test_render_verdict_hero_alarm() -> None:
    data = WD.VerdictHeroData(
        state="alarm",
        eyebrow="Environment verdict · 21 projects",
        headline="8 items need you",
        detail_html="2 claims sitting past custody TTL. <b>20 agents</b> are moving.",
    )
    html = WD.render_verdict_hero(data)
    _firewall_clean(html)
    assert 'class="glass-panel strong rim-glow hero is-alarm"' in html
    assert "#i-alert-triangle" in html
    assert "8 items need you" in html
    assert "<b>20 agents</b> are moving." in html
    assert "meta-row" not in html  # no meta_row supplied


def test_render_verdict_hero_calm_with_meta_row() -> None:
    data = WD.VerdictHeroData(
        state="calm",
        eyebrow="Project verdict · cortex",
        headline="All clear",
        detail_html="Nothing stuck.",
        meta_row=[
            WD.MetaCell(k="Total items", v="465"),
            WD.MetaCell(k="Resolved 24h", v="12"),
        ],
    )
    html = WD.render_verdict_hero(data)
    _firewall_clean(html)
    assert "is-calm" in html
    assert "#i-check-circle" in html
    assert '<div class="meta-row">' in html
    assert "Total items" in html
    assert "465" in html


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("465", ("465", "")),
        ("0", ("0", "")),
        ("\u2014", ("\u2014", "")),  # em dash ("no data") -- no leading number at all
        ("6d", ("6", "d")),
        ("3h ago", ("3", "h ago")),
        ("-2d", ("-2", "d")),
    ],
)
def test_split_meta_value(raw: str, expected: tuple[str, str]) -> None:
    """Visual-polish punchlist item 6: a `.meta-row` value's leading number
    and trailing unit suffix split apart so they can render at different
    sizes/weights while sharing one baseline."""
    assert WD._split_meta_value(raw) == expected  # noqa: SLF001 -- exercising the helper directly


def test_render_verdict_hero_meta_row_splits_suffix_into_its_own_span() -> None:
    data = WD.VerdictHeroData(
        state="calm",
        eyebrow="Project verdict \u00b7 cortex",
        headline="All clear",
        detail_html="Nothing stuck.",
        meta_row=[
            WD.MetaCell(k="Total items", v="465"),
            WD.MetaCell(k="Oldest ready", v="6d"),
            WD.MetaCell(k="Last activity", v="3h ago"),
        ],
    )
    html = WD.render_verdict_hero(data)
    _firewall_clean(html)
    # A plain count never gets a suffix span.
    assert '<span class="v">465</span>' in html
    # A number+unit value splits: bare number, then a separate suffix span.
    assert '<span class="v">6<span class="v-suffix">d</span></span>' in html
    assert '<span class="v">3<span class="v-suffix">h ago</span></span>' in html


def test_render_verdict_hero_idle() -> None:
    data = WD.VerdictHeroData(
        state="idle", eyebrow="e", headline="Idle", detail_html="Nothing in flight."
    )
    html = WD.render_verdict_hero(data)
    _firewall_clean(html)
    assert "is-idle" in html
    assert "#i-clock" in html


# ---------------------------------------------------------------------------
# render_kpi_strip
# ---------------------------------------------------------------------------


def test_render_kpi_strip_blocked_zero_gets_quiet_class() -> None:
    data = WD.KpiStripData(
        cards=[
            WD.KpiCard(key="agents", label="Agents active now", value=20, href="#", icon="i-bot"),
            WD.KpiCard(key="held", label="Held", value=56, href="#"),
            WD.KpiCard(key="ready", label="Ready", value=118, href="#"),
            WD.KpiCard(
                key="blocked",
                label="Blocked",
                value=0,
                href="#",
                icon="i-octagon-x",
                icon_color_var="--blocked",
                is_blocked=True,
            ),
            WD.KpiCard(key="resolved24h", label="Resolved 24h", value=29, href="#"),
        ]
    )
    html = WD.render_kpi_strip(data)
    _firewall_clean(html)
    assert "is-blocked is-zero" in html
    assert html.count('class="glass-panel kpi-card') == 5


def test_render_kpi_strip_blocked_nonzero_has_no_is_zero() -> None:
    data = WD.KpiStripData(
        cards=[WD.KpiCard(key="blocked", label="Blocked", value=19, href="#", is_blocked=True)]
    )
    html = WD.render_kpi_strip(data)
    assert "is-zero" not in html
    assert "is-blocked" in html


# ---------------------------------------------------------------------------
# render_attention_queue
# ---------------------------------------------------------------------------


def test_render_attention_queue_ranked_rows() -> None:
    data = WD.AttentionQueueData(
        rows=[
            WD.AttentionRow(
                severity="alarm",
                icon="i-alert-triangle",
                priority="P0",
                project="cortex",
                title="Fix retention window off-by-one in chunker",
                reason_html=(
                    '<span title="Custody held past its TTL without renewal">Stale custody</span>'
                    ' — <span class="who">agent-spark-1-8823410</span>'
                ),
                rank=1,
                age_label="5h 42m over",
                href="#",
            ),
            WD.AttentionRow(
                severity="watch",
                icon="i-clock",
                priority="P2",
                project="amplifier_app_cli",
                title="CLI --json output for `status`",
                reason_html="Ready, unclaimed",
                rank=6,
                age_label="9d",
                href="#",
            ),
        ],
        total=2,
    )
    html = WD.render_attention_queue(data)
    _firewall_clean(html)
    assert html.count('class="attn-row is-') == 2
    assert "is-alarm" in html and "is-watch" in html
    assert '<span class="priority-chip p0"' in html
    assert '<span class="priority-chip p2"' in html
    assert "#1" in html and "#6" in html
    # Bonus fix: a real space/separator between the project prefix and the
    # item title, not just a CSS margin -- so plain-text extraction (and
    # screen readers) never read "cortexFix retention..." run together.
    assert '<span class="title"><span class="proj">cortex</span> ' in html
    assert "Stale custody" in html
    # total == len(rows) -- no truncation note when nothing was cut.
    assert "truncation-note" not in html


def test_render_attention_queue_truncation_note_when_capped() -> None:
    """`total` > `len(rows)` -- the caller already capped the DISPLAYED rows
    (webapp.py's `_L0_ATTENTION_QUEUE_SHOWN`) -- must print an honest
    "Showing N of M" footer, matching `render_agents_now`/
    `render_activity_feed`'s own truncation-note convention. The live
    dashboard defect this guards: the attention queue rendering all 50
    ranked rows and dominating the page instead of a compact panel."""
    rows = [
        WD.AttentionRow(
            severity="watch",
            icon="i-clock",
            priority="P3",
            project="proj",
            title=f"item {i}",
            reason_html="Ready, unclaimed",
            rank=i + 1,
            age_label="1d",
            href="#",
        )
        for i in range(10)
    ]
    html = WD.render_attention_queue(WD.AttentionQueueData(rows=rows, total=50))
    assert html.count('class="attn-row is-') == 10
    assert '<div class="truncation-note">Showing 10 of 50' in html


def test_render_attention_queue_no_truncation_note_when_not_capped() -> None:
    data = WD.AttentionQueueData(
        rows=[
            WD.AttentionRow(
                severity="blocked",
                icon="i-octagon-x",
                priority="P1",
                project="proj",
                title="blocked item",
                reason_html="Blocked, no owner",
                rank=1,
                age_label="",
                href="#",
            )
        ],
        total=1,
    )
    html = WD.render_attention_queue(data)
    assert "truncation-note" not in html


# ---------------------------------------------------------------------------
# render_fleet_table
# ---------------------------------------------------------------------------


def test_render_fleet_table_mix_bar_and_dormant_section() -> None:
    data = WD.FleetTableData(
        total_projects=21,
        rows=[
            WD.FleetRow(
                name="cortex",
                subtitle="465 items · flagship",
                mix=WD.FleetStatusMix(
                    resolved=398, ready=34, held=18, intake=5, deferred=3, blocked=7
                ),
                mix_legend_html="398r · 34rd · 18h · 5in · 3df · 7b",
                sparkline_values=[22, 28, 25, 33, 30, 19, 30],
                sparkline_label="Resolved-per-day sparkline for cortex",
                agents=6,
                last_activity="2m ago",
                last_activity_title="2026-08-30T18:36:40+00:00",
                href="mock-L1-project.html",
            ),
            WD.FleetRow(
                name="work_tracker",
                subtitle="29 items · all resolved",
                mix=WD.FleetStatusMix(
                    resolved=29, ready=0, held=0, intake=0, deferred=0, blocked=0
                ),
                mix_legend_html="29r · 0rd · 0h · 0in · 0df · 0b",
                sparkline_values=[0, 0, 0, 0, 0, 0, 0],
                sparkline_label="Resolved-per-day sparkline for work_tracker, flat -- dormant",
                agents=0,
                last_activity="3h ago",
                last_activity_title="",
                href="#",
            ),
        ],
        dormant=[
            WD.DormantProject(
                name="beadsworks",
                href="#",
                items=15,
                open_count=0,
                resolved=15,
                last_activity="21d ago",
                last_activity_title="2026-08-09T12:00:00+00:00",
            ),
        ],
    )
    html = WD.render_fleet_table(data)
    _firewall_clean(html)
    assert html.count('class="fleet-row"') == 2
    assert "is-zero" in html  # work_tracker has 0 agents
    assert '<span class="mix-legend">398r' in html
    assert "pat-hatch" in html  # deferred segment for cortex (3 deferred)
    assert '<details class="dormant-details">' in html
    assert "beadsworks" in html
    assert "Dormant — 1 projects" in html
    # Regression: `last_activity` must render as PLAIN TEXT with the raw
    # timestamp on a `title=` attribute -- never a pre-rendered HTML string
    # the widget then escapes (the live-dashboard defect where every fleet
    # row literally displayed `<span title="...">3h ago</span>` as text).
    assert "&lt;span" not in html
    assert 'class="last" title="2026-08-30T18:36:40+00:00">2m ago</span>' in html
    assert 'class="last">3h ago</span>' in html  # no title attr when none given
    assert '<td class="n" title="2026-08-09T12:00:00+00:00">21d ago</td>' in html


def test_render_fleet_table_no_dormant_omits_section() -> None:
    data = WD.FleetTableData(
        total_projects=1,
        rows=[
            WD.FleetRow(
                name="solo",
                subtitle="1 item",
                mix=WD.FleetStatusMix(resolved=1, ready=0, held=0, intake=0, deferred=0, blocked=0),
                mix_legend_html="1r",
                sparkline_values=[1.0],
                sparkline_label="solo spark",
                agents=1,
                last_activity="now",
                last_activity_title="",
                href="#",
            )
        ],
        dormant=[],
    )
    html = WD.render_fleet_table(data)
    assert "dormant-details" not in html


# ---------------------------------------------------------------------------
# render_agents_now
# ---------------------------------------------------------------------------


def test_render_agents_now_stale_row() -> None:
    data = WD.AgentsNowData(
        rows=[
            WD.AgentNowRow(
                agent_id="agent-spark-1-8823410",
                project="cortex",
                item_id="t22p",
                item_title="Fix retention window off-by-one in chunker",
                freshness_label="5h 42m over TTL",
                is_stale=True,
                href="#",
            ),
            WD.AgentNowRow(
                agent_id="agent-spark-1-1102938",
                project="muxplex",
                item_id="d81r",
                item_title="Pane title truncation on narrow splits",
                freshness_label="fresh, 6m",
                is_stale=False,
                href="#",
            ),
        ],
        shown=8,
        total=20,
    )
    html = WD.render_agents_now(data)
    _firewall_clean(html)
    assert "agents-now-row has-stale" in html
    assert html.count('class="agents-now-row') == 2
    assert "Showing 8 of 20 active agents." in html


# ---------------------------------------------------------------------------
# render_activity_feed
# ---------------------------------------------------------------------------


def test_render_activity_feed_links_and_window_tabs() -> None:
    data = WD.ActivityFeedData(
        items=[
            WD.ActivityFeedItem(
                kind="claim",
                actor="agent-spark-1-3406950",
                verb="claimed",
                project_item="cortex-v5fq",
                description="Recall must return contiguous transcript chunks",
                time_label="1m ago",
                href="#",
            ),
            WD.ActivityFeedItem(
                kind="resolve",
                actor="agent-spark-1-2201884",
                verb="resolved",
                project_item="amplifier-q02x",
                description="Dedup bundle cache entries on reload",
                time_label="4m ago",
                href="#",
            ),
        ],
        since_label="since 08:14",
        window_tabs=[
            WD.WindowTab(label="1H", href="?feed=1h", is_active=False),
            WD.WindowTab(label="12H", href="?feed=12h", is_active=True),
            WD.WindowTab(label="24H", href="?feed=24h", is_active=False),
        ],
        shown=10,
        total_estimate=340,
    )
    html = WD.render_activity_feed(data)
    _firewall_clean(html)
    # Regression: the feed must be OPEN by default -- a collapsed feed reads
    # as empty/missing rather than a populated panel (live-dashboard defect;
    # a user can still collapse it, and the refresh-preservation JS
    # persists whatever state they leave it in).
    assert '<details class="dormant-details feed-details" open>' in html
    assert 'class="window-tab is-active">12H</a>' in html
    assert html.count('class="feed-item k-') == 2
    assert "Showing 10 most recent of ~340 events today across all projects." in html


# ---------------------------------------------------------------------------
# render_status_breakdown
# ---------------------------------------------------------------------------


def test_render_status_breakdown_full_legend() -> None:
    counts = C.StatusCounts(resolved=398, ready=34, held=18, intake=5, deferred=3, blocked=7)
    data = WD.StatusBreakdownData(
        counts=counts, total=465, aria_label="Status mix donut, 465 total items"
    )
    html = WD.render_status_breakdown(data)
    _firewall_clean(html)
    root = ET.fromstring(html.replace("<svg", "<svg xmlns='http://www.w3.org/2000/svg'", 1))  # noqa: S314
    assert root is not None
    assert "Resolved" in html and "Blocked" in html
    assert html.count('class="li">') == 6
    assert "85.6%" in html  # 398/465 rounded to 1dp


def test_render_status_breakdown_zero_total_has_zero_percent() -> None:
    counts = C.StatusCounts(resolved=0, ready=0, held=0, intake=0, deferred=0, blocked=0)
    data = WD.StatusBreakdownData(counts=counts, total=0, aria_label="empty")
    html = WD.render_status_breakdown(data)
    _firewall_clean(html)
    assert "0.0%" in html or "0%" in html


# ---------------------------------------------------------------------------
# render_ready_age_histogram
# ---------------------------------------------------------------------------


def test_render_ready_age_histogram_with_flagged_note() -> None:
    data = WD.ReadyAgeHistogramData(
        buckets=[
            C.AgeBucket(label="0-1d", count=14, is_watch=False),
            C.AgeBucket(label="2-3d", count=11, is_watch=False),
            C.AgeBucket(label="4-6d", count=6, is_watch=False),
            C.AgeBucket(label="7+d", count=3, is_watch=True),
        ],
        ready_total=34,
        aria_label="Ready item age histogram, 4 buckets",
        flagged_note="7+ day bucket flagged — 3 items aging past the point they'd surface.",
    )
    html = WD.render_ready_age_histogram(data)
    _firewall_clean(html)
    # The widget must NOT render its own "N ready items" counter -- the L1
    # card head already does, and both together produced a visibly duplicated
    # subtitle on the Ready-age card (owner-reported, micro-nits pass).
    assert "34 ready items" not in html
    assert "watch (aging, not an alarm)" in html
    assert "7+ day bucket flagged" in html


def test_render_ready_age_histogram_without_flagged_note() -> None:
    data = WD.ReadyAgeHistogramData(
        buckets=[C.AgeBucket(label="0-1d", count=1, is_watch=False)],
        ready_total=1,
        aria_label="one bucket",
    )
    html = WD.render_ready_age_histogram(data)
    _firewall_clean(html)
    assert "truncation-note" not in html


# ---------------------------------------------------------------------------
# render_agents_panel
# ---------------------------------------------------------------------------


def test_render_agents_panel_stale_and_fresh_rows() -> None:
    data = WD.AgentsPanelData(
        rows=[
            WD.AgentPanelRow(
                agent_id="agent-spark-1-8823410",
                held_count=4,
                recent_kind="stalest",
                recent_item_id="cortex-t22p",
                freshness_label="5h 42m over TTL",
                is_stale=True,
                href="#",
            ),
            WD.AgentPanelRow(
                agent_id="agent-spark-1-3406950",
                held_count=3,
                recent_kind="latest",
                recent_item_id="cortex-v5fq",
                freshness_label="fresh, 3m",
                is_stale=False,
                href="#",
            ),
        ],
        active_count=6,
        held_count=18,
    )
    html = WD.render_agents_panel(data)
    _firewall_clean(html)
    assert "agent-row has-stale" in html
    assert "stalest: " in html and "latest: " in html
    assert '<span class="held-n">4 held</span>' in html
