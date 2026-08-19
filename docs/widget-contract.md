# The dashboard widget contract

The overview dashboard is a column of **panels** — the workspace-by-state bar,
the ready-queue-by-age histogram, the throughput reading, the ranked "needs
you" queue, and more. Historically each panel was a private free function that
`dashboard()` hand-called in sequence and interpolated into one big f-string.

The **widget contract** (`src/amplifier_work_tracker/widgets.py`) is a small,
typed seam over that pattern: a panel declares what it is and what data it
needs, reads that data from one shared read-only bag, and returns its HTML
fragment. The route builds the bag once and renders panels by id.

It is **internal-first and ruthlessly simple** by design:

- **No dynamic loading, no discovery.** Widgets are registered in Python by the
  app that owns them. There is no plugin path, no entry-point scan, no
  import-by-name. This is not a public plugin API — it earns one later by
  having real widgets that target it.
- **No layout engine.** `size` is a *declared hint*, not a directive. The route
  still owns placement this pass. Per-user / per-host arrangement is a **future**
  concern the contract is shaped not to preclude — see
  [Shared / hosted instances](#shared--hosted-instances).
- **No new rendering.** A routed panel produces the *same* fragment its builder
  produced inline before. The registry routes; it never restyles.

---

## The interface

Everything lives in `amplifier_work_tracker.widgets`.

### `DashboardContext`

A frozen dataclass: the single, read-only bag of already-reduced figures the
route computes **once** and hands to every panel. It carries two shapes on
purpose, because real panels need both:

- **flat aggregates** — `ready_total`, `held_total`, `resolved_24h_total`,
  `prior6d_rate`, the `buckets` age histogram, … (the composition bar, the
  histogram, throughput read these);
- **the summary objects themselves** — `ok: tuple[ProjectSummary, ...]` and
  `summaries` (the needs-you queue *ranks* projects, so it needs the summaries,
  not a pre-flattened count), plus `rendered_at`, the one instant every
  duration on the page is measured against.

Rendering never mutates it.

### `Widget`

A frozen dataclass describing one panel:

| field | meaning |
|-------|---------|
| `id` | stable, unique, kebab-case identifier the route renders by |
| `title` | human title (the panel's own eyebrow words); metadata for menus/arrangers |
| `size` | a `WidgetSize` placement **hint** (`FULL` / `HALF`) |
| `render` | `(DashboardContext) -> str`, the panel's HTML fragment |
| `needs` | the `DashboardContext` field names it reads — an honest, tested self-description of its data dependencies |
| `description` | optional one-liner about what it shows |

`needs` is documentation-grade: it declares intent and is validated against the
real context fields by the test suite (a typo fails CI), but it does not
restrict what `render` may touch.

### `WidgetRegistry`

An ordered, in-process registry:

```python
reg = WidgetRegistry()
reg.register(widget)  # explicit; duplicate id raises ValueError
reg.get("throughput")  # unknown id raises KeyError naming the known ids
reg.render("throughput", ctx)  # fast path: the fragment, untouched
reg.render("throughput", ctx, enforce=True)  # + firewall, raises on breach
reg.ids()
reg.widgets()
len(reg)
"throughput" in reg
```

### The design-system firewall

The one thing the contract *enforces*. A widget **cannot introduce a new status
hue or put gloss on data-ink** — this is checked at the contract level, not left
to reviewer vigilance.

`firewall_check(html) -> list[str]` is a pure inspector (it reads a fragment and
reports violations; it never rewrites output). It rejects:

- **raw colours** — hex literals (`#f59e0b`) and `rgb()/rgba()/hsl()/hsla()`
  functions. A literal colour is a would-be new status hue that bypasses the
  reserved tokens.
- **glass** — any `--glass-*` token. Glass is chrome-only.
- **gradient** — `--brand-gradient-*` or a raw `linear-gradient()/radial-gradient()`.
- **blur** — `backdrop-filter` or `blur()`.

It is a **deny-list, not an allow-list**, on purpose: panels legitimately reach
for many component tokens (`var(--st-ready)`, `var(--mid)`, `var(--rule)`), and
an allow-list would fight every honest one. What is forbidden is narrow and
durable.

The **only** two colours a panel may lean on for *meaning* are the reserved
status hues, and it reaches them through tokens, never literals:

| meaning | token | never |
|---------|-------|-------|
| attention / alarm | `var(--amber)` | a raw amber hex, a second "warning" hue |
| blocked / escalation | `var(--crimson)` | a raw red hex |
| everything else | component tokens (`--st-*`, `--ink*`, `--mid`, `--dim`, `--rule`) | `--brand-*` gradients, `--glass-*`, raw colour |

`--brand-cyan` / `--brand-purple` are chrome/interaction accents and **never**
mean status — the firewall does not forbid a brand accent used as chrome, but it
does forbid the gradient/glass forms that would gloss data-ink.

**Where it is enforced:** `reg.render(..., enforce=True)` runs the firewall and
raises `FirewallViolation` on any breach. The contract's test suite renders
*every* registered panel — populated and empty — with `enforce=True`, so a panel
that smuggles in a raw colour or gloss fails CI before it can merge. The default
`render(...)` path does **not** enforce, so production rendering is the panel's
exact bytes and can never regress to a 500 over a firewall check.

---

## Worked example — adding a widget

Say you want a panel that shows the workspace's blocked count. Two steps.

**1. Make sure the data is in the context.** `blocked_total` already is. If your
panel needed a figure the context does not carry, you would add a field to
`DashboardContext` and populate it once in `_dashboard_context(...)` in
`webapp.py` — never recompute inside a widget.

**2. Register the widget** (in `webapp.py`, next to the other
`DASHBOARD_WIDGETS.register(...)` calls):

```python
def _blocked_panel_html(blocked: int) -> str:
    # Draws ONLY through tokens: crimson is reached via --crimson, never a hex.
    tone = "var(--crimson)" if blocked else "var(--dim)"
    return (
        '<div class="comp"><div class="chead">'
        '<span class="eyebrow">Blocked</span></div>'
        f'<div style="font-size:44px;color:{tone}">{blocked}</div></div>'
    )


DASHBOARD_WIDGETS.register(
    Widget(
        id="blocked-count",
        title="Blocked",
        size=WidgetSize.HALF,
        needs=("blocked_total",),
        description="How many items are blocked across the workspace.",
        render=lambda c: _blocked_panel_html(c.blocked_total),
    )
)
```

Then render it wherever you want it in `dashboard()`:

```python
blocked = DASHBOARD_WIDGETS.render("blocked-count", ctx)
# ... interpolate `blocked` into the body where you place the section ...
```

That is the whole surface. Note what you did **not** do: no CSS framework, no
base class, no plugin manifest. And the firewall test picks up your new panel
automatically — if `_blocked_panel_html` had used `#ef4444` instead of
`var(--crimson)`, CI would fail with a `FirewallViolation` naming the literal.

> **Keep the builder a plain function.** The panel's HTML lives in an ordinary
> `_..._html(...)` function; the `Widget` is a thin registration around it. That
> keeps the fragment unit-testable on its own and the registration trivial.

---

## Multi-author

A second author adds a panel with exactly the step above — one
`DASHBOARD_WIDGETS.register(...)` call and one `render(...)` at the placement
site. Because registration is explicit and insertion-ordered, and ids must be
unique (a duplicate raises `ValueError` rather than silently overwriting), two
authors adding panels in the same file get a clean merge conflict at worst, not
a silent shadowing bug.

Guidance for a second author:

- **Own your builder function and your id.** Pick a distinct kebab-case `id`;
  keep the `_..._html` builder next to the others.
- **Declare `needs` honestly.** List the `DashboardContext` fields you read. The
  test suite validates every declared name against the real context fields, so a
  drifted `needs` is caught in CI, and a reader can see your data dependencies
  without reading the render body.
- **Add context fields, don't recompute.** If you need a figure the context does
  not carry, add a `DashboardContext` field and populate it once in
  `_dashboard_context(...)`. Do not re-reduce `summaries` inside a widget — the
  point of the shared bag is that no two panels compute the same figure two
  different ways.
- **Stay behind the firewall.** Draw through tokens; run the contract test suite
  (`tests/unit/test_widgets_contract.py`) — the `enforce=True` sweep already
  covers every registered panel, including yours.

---

## Shared / hosted instances

The contract anticipates a shared, hosted, multi-user instance **without
building for it** this pass. What the shape already gives that path:

- **Stable ids.** Every panel has a stable, addressable `id`. A per-user or
  per-team arrangement (which panels, in what order) is expressible as an
  ordered list of ids over the registry — no code change to the panels.
- **A declared `size` hint.** `FULL` / `HALF` is exactly the granularity a
  future arranger needs to place panels into rows without re-deriving intent
  from CSS.
- **A pure, read-only context.** Rendering is a pure function of
  `DashboardContext`. A hosted renderer can build the context once per request
  and render whatever subset/order a given user's arrangement asks for, because
  no panel mutates shared state or depends on render order.
- **A firewall that travels.** The design-system firewall is enforced at the
  contract level, so third-party or per-team panels on a shared instance cannot
  introduce a rogue status hue or gloss on data-ink — the visual invariants hold
  no matter who authored the panel.

**Explicitly NOT built this pass** (future work, intentionally out of scope):

- **Per-user / per-team arrangement.** No storage of "user X wants panels A, C, B
  in this order", no arrangement UI, no drag-to-reorder. The route still owns a
  single fixed placement. The contract is shaped so this can be added later as an
  ordered-id list consumed by the route, without touching any panel.
- **A public / dynamic plugin loader.** No entry-point scanning, no
  import-by-name, no loading panels from outside the app. Registration stays
  explicit Python. A public API is earned by real internal widgets targeting the
  contract first — which is what this pass establishes.

The rule of thumb: **the contract must not *preclude* the hosted/multi-user path,
but it must not *build* it either.** Adding a field, a panel, or an arrangement
list should be additive; nothing here bakes in single-user assumptions.
