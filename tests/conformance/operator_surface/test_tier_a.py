"""Tier-A conformance kit for `contracts/operator-surface.v1.md`.

One test per **Machine check:** name the contract states, plus a BAD HALF for
each. That pairing is the whole point (Conformance preamble: "Each fixture is
a discriminating pair: a good input the check passes, a bad input the same
check fails") -- a check nobody has watched fail is a check that might assert
nothing.

## How to read a check here

Every machine check is a pure function `check_<name>(...) -> list[str]`
returning one string per violation. Two tests wrap each one:

  * `test_<name>` -- the GOOD half, run against the real artifact (this repo's
    `src/`, its token block, or a rendered fixture page). It asserts the
    clause holds.
  * `test_<name>_bad_half_*` -- the BAD half, run against a deliberately wrong
    artifact. It asserts the SAME function reports the defect the contract's
    Conformance section names. These always pass; a failure here means the
    check stopped discriminating.

## `xfail(strict=True)` is a ledger row, never a skip

Four clauses do not hold on today's code, and each has an open `ledger/` row
saying so. Their good halves are `pytest.mark.xfail(strict=True)` with the row
id in the reason -- never `skip`, never deleted:

    hero.velocity_and_counts  OSV1-001  the L0 hero is a verdict line
    visual.single_source      OSV1-005  66 literal inline sites + 40 in blocks
    perception.floors         OSV1-009  six declared text pairs below 4.5:1
    calm.keeps_slot           OSV1-012  an empty widget keeps its slot but
                                        says nothing
    antigoals.enforced        OSV1-015  the L1 view queries with `limit=0`
                              OSV1-016  the theme choice dies on refresh

`strict=True` is load-bearing: when the fix lands the test XPASSes, which
FAILS the run. That failure is the instruction -- delete the marker and flip
the row, in the same change.

## One census, one register

Core 4's inline-style census and its exemption register live in `ledger/`
by Phase-1 ruling ("the register and the ceiling live in `ledger/`"), and this
kit IMPORTS both (`ledger.checks._support`, `ledger.checks.test_operator_rows.
EXEMPTION_REGISTER`) rather than reimplementing them. OSV1-025's notes name
the alternative as the failure to avoid: two censuses will disagree, silently.

## Scope

Tier A only. Anything needing a real browser -- pixel sweeps (Core 2's calm
half), computed contrast and target boxes (Core 7's rendered half), post-swap
DOM snapshots (Core 6) -- is Tier B and lives in `browser/test_tier_b.py`.
Core 12 and Core 13 are NOT-ASSERTABLE by the contract's own text and carry no
check here, deliberately.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from ledger.checks import _support as S
from ledger.checks.test_operator_rows import EXEMPTION_REGISTER

# ===========================================================================
# A minimal HTML tree. `html.parser` only, no new dependency -- Core 9 forbids
# this surface a build step, and a conformance kit that needed one to read the
# surface's own output would be a poor advertisement for the clause.
# ===========================================================================

_VOID = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
)  # fmt: skip


@dataclass
class Node:
    """One element. `text` is the whole subtree's visible text."""

    tag: str
    attrs: dict[str, str]
    parent: Node | None = None
    children: list[Node] = field(default_factory=list)
    own_text: list[str] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def text(self) -> str:
        parts = list(self.own_text)
        parts += [c.text() for c in self.children]
        return " ".join(p for p in parts if p).strip()

    def accessible_name(self) -> str:
        """Text, or the attributes that give an element a name without it."""
        for attr in ("aria-label", "title", "alt", "aria-labelledby"):
            if (self.attrs.get(attr) or "").strip():
                return self.attrs[attr].strip()
        return self.text()

    def ancestors(self) -> list[Node]:
        out: list[Node] = []
        n = self.parent
        while n is not None:
            out.append(n)
            n = n.parent
        return out

    def describe(self) -> str:
        cls = " ".join(sorted(self.classes))
        ident = self.attrs.get("id")
        return f"<{self.tag}{f' id={ident}' if ident else ''}{f' class={cls!r}' if cls else ''}>"


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document", {})
        self._cur = self.root

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, {k: (v or "") for k, v in attrs}, parent=self._cur)
        self._cur.children.append(node)
        if tag not in _VOID:
            self._cur = node

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._cur.children.append(Node(tag, {k: (v or "") for k, v in attrs}, parent=self._cur))

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        node: Node | None = self._cur
        while node is not None and node is not self.root and node.tag != tag:
            node = node.parent
        if node is not None and node is not self.root and node.parent is not None:
            self._cur = node.parent

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._cur.own_text.append(data.strip())


def parse_html(html: str) -> Node:
    """Parse a rendered page, minus `<style>`/`<script>` bodies.

    Both are stripped before parsing: neither is visible content, and both are
    full of `<`/`>` that would otherwise be read as markup.
    """
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    builder = _TreeBuilder()
    builder.feed(html)
    return builder.root


def walk(node: Node):
    for child in node.children:
        yield child
        yield from walk(child)


def find_one(root: Node, *, node_id: str) -> Node | None:
    for n in walk(root):
        if n.attrs.get("id") == node_id:
            return n
    return None


# ===========================================================================
# Core 1 -- hero.velocity_and_counts
#
#   "the rendered L0 hero region contains a velocity figure with its window
#    stated, and each of the four named counts."
#
# The four the clause names: in flight (held), blocked, needs attention, and
# open/ready.
# ===========================================================================

#: Each count, with every word the surface could legitimately label it with.
#: Named in the clause's own order.
_HERO_COUNTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("in flight (held)", ("in flight", "in-flight", "held", "holding")),
    ("blocked", ("blocked",)),
    ("needs attention", ("needs attention", "needs you", "attention", "needs-you")),
    ("open/ready", ("open", "ready", "unclaimed")),
)

#: A throughput word -- the figure itself must be one of these, not any number.
_THROUGHPUT_WORDS = ("resolved", "velocity", "throughput", "completed", "closed", "burn")

#: A stated window. `24h`/`7d`/`30d`, "last 7 days", "per day", "/day".
_WINDOW = re.compile(
    r"(\b\d+\s*(h|hr|hrs|hours?|d|days?|w|weeks?)\b|\bper day\b|/day\b|\blast \d+\b|\btoday\b)",
    re.IGNORECASE,
)
_HAS_DIGIT = re.compile(r"\d")


def _leaf_phrases(region: Node, *, max_len: int = 140) -> list[str]:
    """Short text runs in the region -- a count and its label read together.

    Bounded, because "the hero contains the word `blocked` somewhere and the
    digit `3` somewhere" is not a count: the clause asks for the counts to be
    PRESENTED, so the number and its label must sit in one readable run.
    """
    out: list[str] = []
    for n in walk(region):
        txt = " ".join(n.text().split())
        if txt and len(txt) <= max_len:
            out.append(txt)
    return out


def check_hero_velocity_and_counts(l0_html: str) -> list[str]:
    """Core 1's `hero.velocity_and_counts`, against a rendered L0."""
    root = parse_html(l0_html)
    hero = find_one(root, node_id="verdict-hero")
    if hero is None:
        return ["no L0 hero region (`#verdict-hero`) in the rendered page at all"]

    phrases = _leaf_phrases(hero)
    problems: list[str] = []

    velocity = [
        p
        for p in phrases
        if _HAS_DIGIT.search(p)
        and any(w in p.lower() for w in _THROUGHPUT_WORDS)
        and _WINDOW.search(p)
    ]
    if not velocity:
        problems.append(
            "no velocity figure with its window stated -- the hero carries no run "
            f"pairing a number, a throughput word {_THROUGHPUT_WORDS} and a window"
        )

    for label, words in _HERO_COUNTS:
        if not any(_HAS_DIGIT.search(p) and any(w in p.lower() for w in words) for p in phrases):
            problems.append(f"the hero states no `{label}` count")
    return problems


def test_hero_velocity_and_counts_bad_half_verdict_line_only() -> None:
    """Conformance 5's bad half, verbatim: "a hero carrying only a verdict line".

    Not synthesised from nothing -- this IS `widgets.render_verdict_hero`'s
    own output shape (OSV1-024's notes: "the bad half needs no synthetic
    construction"), rendered around the calm verdict the shipped L0 emits.
    """
    bad = """<div id="verdict-hero" class="section"><div class="hero is-calm">
      <div class="eyebrow2">Environment verdict &middot; 21 projects</div>
      <div class="verdict">All clear</div>
      <div class="detail">Nothing stuck, nothing waiting past its TTL.</div>
    </div></div>"""
    problems = check_hero_velocity_and_counts(bad)
    assert problems, "the check passed a hero carrying only a verdict line"
    assert any("velocity figure" in p for p in problems)
    for label, _ in _HERO_COUNTS:
        assert any(label in p for p in problems), f"the check did not name `{label}` as missing"


def test_hero_velocity_and_counts_bad_half_figure_without_the_counts() -> None:
    """Conformance 5's other bad half: "a figure without the four counts"."""
    bad = """<div id="verdict-hero"><div class="hero">
      <div class="verdict">14 resolved in the last 24h</div>
    </div></div>"""
    problems = check_hero_velocity_and_counts(bad)
    assert not any("velocity figure" in p for p in problems), (
        "the figure IS present with its window -- the check must not report it missing"
    )
    assert len(problems) == len(_HERO_COUNTS), (
        f"expected all four counts reported missing, got {problems}"
    )


def test_hero_velocity_and_counts_bad_half_a_loose_number_is_not_a_count() -> None:
    """A number somewhere and a word somewhere else is not a presented count."""
    bad = """<div id="verdict-hero"><div class="hero">
      <div class="verdict">All clear</div>
      <div class="detail">7 resolved in the last 24h.</div>
      <div class="detail">Nothing is blocked, and nothing needs attention, and
        the ready queue and everything in flight are described here at length
        in a sentence that never actually puts a number beside any of them.</div>
    </div></div>"""
    problems = check_hero_velocity_and_counts(bad)
    assert any("blocked" in p for p in problems), (
        "a status word in a long prose run with no adjacent number was credited as a count"
    )


@pytest.mark.xfail(
    strict=True,
    reason="OSV1-001 (Core 1): the L0 hero is a verdict line; velocity is a chart "
    "below it and `blocked`/`needs attention` are only in the KPI strip outside "
    "the hero. Flip the row and delete this marker in the same change.",
)
def test_hero_velocity_and_counts(calm_dataset) -> None:
    """Conformance 5's GOOD half: L0 rendered against a populated fixture."""
    problems = check_hero_velocity_and_counts(calm_dataset.l0)
    assert not problems, "Core 1 (`hero.velocity_and_counts`):\n  " + "\n  ".join(problems)


# ===========================================================================
# Core 3 -- state.not_colour_only
#
#   "every status-bearing element in the rendered L0/L1/L2 fixtures has
#    non-empty text or an accessible name, not merely a status class."
# ===========================================================================

#: The status vocabulary, read out of the app's OWN maps rather than written
#: down here: `webbrowse._ITEM_STATUS_CHIP_LABEL`'s keys (the item statuses),
#: `widgets._HERO_ICON`'s keys (the verdict states) and
#: `webapp._ATTENTION_SEVERITY`'s severities. A status the app grows and this
#: kit does not know about would otherwise be silently unchecked.
_STATUS_CLASS_PREFIXES = ("st", "is", "sev", "tab", "status")


def _dict_keys_in(path: Path, name: str) -> set[str]:
    """The string keys of a module-level `NAME: ... = {...}` dict literal."""
    tree = ast.parse(S.read(path))
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
        if not any(isinstance(t, ast.Name) and t.id == name for t in targets):
            continue
        value = node.value if isinstance(node, ast.AnnAssign | ast.Assign) else None
        if isinstance(value, ast.Dict):
            return {
                k.value
                for k in value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
    raise AssertionError(f"{path.name}: no module-level dict literal named {name!r}")


def _dict_values_in(path: Path, name: str) -> set[str]:
    tree = ast.parse(S.read(path))
    for node in ast.walk(tree):
        targets = (
            [node.target]
            if isinstance(node, ast.AnnAssign)
            else list(node.targets)
            if isinstance(node, ast.Assign)
            else []
        )
        if not any(isinstance(t, ast.Name) and t.id == name for t in targets):
            continue
        value = node.value if isinstance(node, ast.AnnAssign | ast.Assign) else None
        if isinstance(value, ast.Dict):
            return {
                v.value
                for v in value.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)
            }
    raise AssertionError(f"{path.name}: no module-level dict literal named {name!r}")


def status_vocabulary() -> set[str]:
    """Every word this surface uses to name a state, from its own source."""
    words = set(_dict_keys_in(S.WEBBROWSE, "_ITEM_STATUS_CHIP_LABEL"))
    words |= {v.lower() for v in _dict_values_in(S.WEBBROWSE, "_ITEM_STATUS_CHIP_LABEL")}
    words |= set(_dict_keys_in(S.WIDGETS, "_HERO_ICON"))
    # The status hues themselves -- `--alarm` -> `alarm` -- so `is-alarm` and
    # `sev-blocked` are recognised even though no dict literal names them.
    words |= {t.lstrip("-") for t in S.STATUS_TOKENS}
    return {w for w in words if w}


def status_classes(rendered: set[str]) -> set[str]:
    """Which of a page's classes are STATUS classes.

    A class is status-bearing when it is a status word, or a status word under
    one of this surface's status-class prefixes (`st-blocked`, `is-alarm`,
    `sev-cr`, `tab-blocked`). The chip vocabulary is taken from
    `_ITEM_STATUS_CHIP_CLASS` directly as well, so a chip class that does not
    follow the prefix convention is still caught.
    """
    vocab = status_vocabulary()
    chips = _dict_values_in(S.WEBBROWSE, "_ITEM_STATUS_CHIP_CLASS")
    out = {c for c in rendered if c in chips}
    for c in rendered:
        if c in vocab:
            out.add(c)
            continue
        head, _, tail = c.partition("-")
        if head in _STATUS_CLASS_PREFIXES and tail in vocab:
            out.add(c)
    return out


def check_state_not_colour_only(html: str, *, page: str) -> list[str]:
    """Core 3's `state.not_colour_only`, against one rendered page."""
    root = parse_html(html)
    nodes = list(walk(root))
    rendered_classes = {c for n in nodes for c in n.classes}
    status = status_classes(rendered_classes)
    if not status:
        return [f"{page}: no status-bearing element on the page at all -- nothing was checked"]

    problems: list[str] = []
    for n in nodes:
        if not (n.classes & status):
            continue
        if n.accessible_name():
            continue
        # A decorative mark INSIDE a status-bearing element that is itself
        # named carries no state of its own -- the state is already in that
        # ancestor's words. Colour is redundant there, which is the clause.
        if any(a.classes & status and a.accessible_name() for a in n.ancestors()):
            continue
        problems.append(
            f"{page}: {n.describe()} carries status class(es) "
            f"{sorted(n.classes & status)} and NO text or accessible name"
        )
    return problems


def test_state_not_colour_only_bad_half_chip_with_only_a_class() -> None:
    """Conformance 2's bad half, verbatim: "a fixture whose status chips carry
    only a status class fails the accessible-name assertion"."""
    bad = '<div class="item-row"><span class="chip st-blocked"></span></div>'
    problems = check_state_not_colour_only(bad, page="BAD")
    assert problems, "a status chip carrying only a class was accepted"
    assert "st-blocked" in problems[0]


def test_state_not_colour_only_bad_half_an_accessible_name_is_enough() -> None:
    """The other direction: a chip with no text but a real name PASSES.

    Without this the check would be asserting "has text", not the clause's
    "non-empty text OR an accessible name" -- and would fail the surface for
    an icon-only control that is correctly labelled.
    """
    good = '<span class="st-blocked" aria-label="Blocked"></span>'
    assert not check_state_not_colour_only(good, page="GOOD")


def test_state_not_colour_only_bad_half_an_ancestors_name_does_not_travel_sideways() -> None:
    """A named status ancestor excuses only its own decorative descendants."""
    bad = (
        # A decorative, unlabelled mark INSIDE a named status control: excused.
        '<a class="tab-blocked">Blocked 3<span class="is-blocked"></span></a>'
        # A status chip standing on its own with nothing at all: reported.
        '<span class="st-held"></span>'
    )
    problems = check_state_not_colour_only(bad, page="BAD")
    assert len(problems) == 1 and "st-held" in problems[0], problems


@pytest.mark.parametrize("level", ["l0", "l1", "l2"])
def test_state_not_colour_only(alarm_dataset, level: str) -> None:
    """Conformance 2's Tier-A GOOD half, on all three IA levels.

    Run against the ALARM dataset, which is Conformance 2's own scenario --
    "the same fixture with one item held past TTL and one blocked" -- so every
    status chip the surface can render is actually on the page.
    """
    if level == "l2":
        html = alarm_dataset.l2(alarm_dataset.item_ids[1])  # the blocked item
    else:
        html = getattr(alarm_dataset, level)
    problems = check_state_not_colour_only(html, page=f"{alarm_dataset.label} {level.upper()}")
    assert not problems, "Core 3 (`state.not_colour_only`):\n  " + "\n  ".join(problems)


# ===========================================================================
# Core 4 -- visual.single_source
#
#   "zero inline `style=` attributes carrying a literal colour, font, or size
#    anywhere in `src/`; every inline `style=` site carrying computed geometry
#    appears on the ledger's exemption register; and zero literal colour/font/
#    size declarations in any `<style>` block outside the token module."
#
# Three conjuncts, all measured by `ledger/checks/_support.py`'s engines and
# the register in `ledger/checks/test_operator_rows.py`. This kit calls them;
# it does not reimplement them.
# ===========================================================================


def check_visual_single_source() -> list[str]:
    problems: list[str] = []

    literal = S.style_sites_in(S.LITERAL)
    if literal:
        problems.append(
            f"{len(literal)} inline `style=` site(s) carry a literal colour, font or "
            f"size; zero are tolerated: {literal[:8]}{' ...' if len(literal) > 8 else ''}"
        )

    unregistered = sorted(set(S.style_sites_in(S.COMPUTED)) - EXEMPTION_REGISTER)
    if unregistered:
        problems.append(
            f"computed-geometry inline site(s) not on the ledger's exemption "
            f"register: {unregistered}"
        )

    blocks = S.style_block_literal_sites()
    if blocks:
        named = [f"{f}:{n}" for f, n, _d, _w in blocks]
        problems.append(
            f"{len(blocks)} literal colour/font/size declaration(s) in a `<style>` "
            f"block outside the token module: {named[:8]}"
            f"{' ...' if len(named) > 8 else ''}"
        )
    return problems


def test_visual_single_source_bad_half_a_literal_colour_attribute() -> None:
    """Conformance 6's named bad specimen, verbatim: a file carrying
    `style="color:#D9A253"` is reported as a literal-colour violation."""
    bucket, why = S.classify_style("color:#D9A253")
    assert bucket == S.LITERAL, f"the census classified a hardcoded amber as {bucket}: {why}"


def test_visual_single_source_bad_half_an_unregistered_computed_site(monkeypatch) -> None:
    """Conformance 6's other bad half: "a computed-geometry site absent from
    the register is reported as unregistered".

    Injected over the census's own reader, so the REAL engine does the
    classifying -- nothing on disk is touched.
    """
    real = S.read

    def fake(path: Path) -> str:
        text = real(path)
        if Path(path) == S.WIDGETS:
            text += "\n_INJECTED = f'<i style=\"width:{pct}%\"></i>'\n"
        return text

    monkeypatch.setattr(S, "read", fake)
    unregistered = sorted(set(S.style_sites_in(S.COMPUTED)) - EXEMPTION_REGISTER)
    assert unregistered, "an unregistered computed-geometry site was not reported"
    assert all(u.startswith("widgets.py:") for u in unregistered), unregistered


def test_visual_single_source_bad_half_the_register_is_the_ledgers_own() -> None:
    """One census, one register (OSV1-025): this kit must not grow a copy."""
    assert EXEMPTION_REGISTER, "the imported exemption register is empty"
    assert EXEMPTION_REGISTER == set(S.style_sites_in(S.COMPUTED)), (
        "the ledger's exemption register and the live computed-geometry census "
        "disagree. They are the same register by ruling -- fix `ledger/`, and "
        "never a second copy here."
    )


@pytest.mark.xfail(
    strict=True,
    reason="OSV1-005 (Core 4): 66 inline `style=` sites and 40 `<style>`-block "
    "declarations still carry a literal colour, font or size. Flip the row and "
    "delete this marker in the same change.",
)
def test_visual_single_source() -> None:
    """Conformance 6's GOOD half: a static pass over `src/` plus the register."""
    problems = check_visual_single_source()
    assert not problems, "Core 4 (`visual.single_source`):\n  " + "\n  ".join(problems)


# ===========================================================================
# Core 5 -- reads.never_write
#
#   "a route audit over every registered handler: no GET handler reaches a
#    mutating adapter call."
# ===========================================================================


def check_reads_never_write(audited: list[dict[str, Any]]) -> list[str]:
    if not audited:
        return ["the route audit found no routes at all -- nothing was checked"]
    return [
        f"{r['module']}:{r['line']} {r['methods']} {r['route']} ({r['handler']}) reaches "
        f"{r['mutating_reached']}"
        for r in audited
        if r["read_only"] and r["mutating_reached"]
    ]


def test_reads_never_write_bad_half_a_get_handler_reaches_a_write(monkeypatch) -> None:
    """A GET route that mutates must be reported -- by the real audit engine,
    over an injected source, not by a hand-built audit table."""
    real = S.read

    def fake(path: Path) -> str:
        text = real(path)
        if Path(path) == S.WEBBROWSE:
            text = text.replace(
                '    @app.get("/projects/{name}", response_class=HTMLResponse)\n'
                "    async def project_view(request: Request, name: str):"
                "  # type: ignore[no-untyped-def]\n",
                '    @app.get("/projects/{name}", response_class=HTMLResponse)\n'
                "    async def project_view(request: Request, name: str):"
                "  # type: ignore[no-untyped-def]\n"
                "        workspace.project(name).resolve('x', 'y')\n",
                1,
            )
        return text

    monkeypatch.setattr(S, "read", fake)
    problems = check_reads_never_write(S.route_audit())
    assert problems, "a GET handler reaching `resolve` was not reported"
    assert any("project_view" in p and "resolve" in p for p in problems), problems


def test_reads_never_write_bad_half_an_empty_audit_is_not_a_pass() -> None:
    """A route audit that found nothing is a broken audit, not a clean one."""
    assert check_reads_never_write([])


def test_reads_never_write() -> None:
    """Core 5's GOOD half, over every registered handler."""
    problems = check_reads_never_write(S.route_audit())
    assert not problems, (
        "Core 5 (`reads.never_write`) -- the surface polls itself every 20s, so a "
        "mutation on a GET is a write every 20 seconds:\n  " + "\n  ".join(problems)
    )


# ===========================================================================
# Core 8 -- calm.keeps_slot
#
#   "against an all-empty fixture, every widget region present on the
#    populated fixture is present, each carries its empty sentence, and no
#    numeral renders at hero scale outside the Core 1 hero."
# ===========================================================================

_REM_PX = 16.0
_LEN = re.compile(r"^([0-9.]+)(px|rem|em)$")


def _px(value: str) -> float | None:
    m = _LEN.match(value.strip())
    if not m:
        return None
    n = float(m.group(1))
    return n if m.group(2) == "px" else n * _REM_PX


def _css_rules(css: str) -> list[tuple[str, str]]:
    return re.findall(r"([^{}@]+)\{([^{}]*)\}", css)


def hero_scale_px() -> float:
    """The Core 1 hero's own type size, read out of the token block.

    Derived, never asserted: "hero scale" means "as big as the hero", so the
    floor moves if the hero's own size does.
    """
    css = S.read(S.WEBTHEME)
    tokens = S.token_blocks()["dark"]
    for selector, decls in _css_rules(css):
        if ".hero .verdict" not in selector:
            continue
        m = re.search(r"font-size\s*:\s*([^;]+)", decls)
        if not m:
            continue
        raw = m.group(1).strip()
        var = re.fullmatch(r"var\((--[a-z0-9-]+)\)", raw)
        if var:
            resolved = S.resolve_token(var.group(1), tokens)
            raw = resolved if resolved else raw
        size = _px(raw)
        if size:
            return size
    raise AssertionError(
        "cannot read the hero's own font-size from webtheme.py -- `hero scale` is "
        "defined as the hero's size and cannot be guessed."
    )


def hero_scale_classes() -> set[str]:
    """Every class the stylesheet sets at or above hero scale."""
    css = S.read(S.WEBTHEME)
    tokens = S.token_blocks()["dark"]
    floor = hero_scale_px()
    out: set[str] = set()
    for selector, decls in _css_rules(css):
        m = re.search(r"font-size\s*:\s*([^;]+)", decls)
        if not m:
            continue
        raw = m.group(1).strip()
        var = re.fullmatch(r"var\((--[a-z0-9-]+)\)", raw)
        if var:
            resolved = S.resolve_token(var.group(1), tokens)
            if resolved is None:
                continue
            raw = resolved
        size = _px(raw)
        if size is None or size < floor:
            continue
        for one in selector.split(","):
            last = re.split(r"[ >+~]+", one.strip())[-1]
            out |= set(re.findall(r"\.([A-Za-z][\w-]*)", last))
    return out


#: What counts as the panel a heading titles: the nearest enclosing card, or
#: failing that the page section. The CARD matters -- L0 puts two independent
#: widgets inside one `.two-up.section`, and resolving both to that shared
#: parent would let one widget's empty sentence silently cover the other's
#: silence.
_PANEL_CLASSES = frozenset({"chart-card", "section"})


def widget_regions(root: Node, *, project: str) -> dict[str, Node]:
    """Every widget region on a rendered page, by a stable name.

    A region is a `.section` (by `id` where it has one) or a titled panel (by
    its own `<h2>`/`<h3>`). The project name is masked out so two renders of
    two different projects compare on structure, not on data.
    """
    regions: dict[str, Node] = {}
    for n in walk(root):
        if "section" in n.classes and n.attrs.get("id"):
            regions[f"#{n.attrs['id']}"] = n
    for n in walk(root):
        if n.tag not in {"h2", "h3"}:
            continue
        title = " ".join(n.text().split()).replace(project, "<project>")
        panel = n.parent
        while panel is not None and not (panel.classes & _PANEL_CLASSES):
            panel = panel.parent
        regions[title] = panel if panel is not None else n
    return regions


#: A sentence: several words ending in a full stop, or a plain-language
#: statement of absence. `webapp.py`'s "Nothing is waiting to be claimed in
#: this queue right now." and `chartsvg.py`'s "No activity in this window" are
#: both real examples from this surface.
#: The character before the full stop must be a letter or a closing bracket,
#: so that a decimal ("0.0%") is never mistaken for the end of a sentence --
#: an empty widget rendering a table of zeroes says nothing, and must not be
#: credited with having said it.
_SENTENCE = re.compile(r"[A-Za-z][^.]*\s[^.]*[A-Za-z)\]]\.(?:\s|$)")
_ABSENCE = re.compile(r"\b(no|none|nothing|never|empty|idle|all clear)\b", re.IGNORECASE)


def _says_something(region: Node) -> bool:
    text = " ".join(region.text().split())
    return bool(_SENTENCE.search(text) or _ABSENCE.search(text))


def check_calm_keeps_slot(
    populated_html: str,
    empty_html: str,
    *,
    populated_project: str,
    empty_project: str,
) -> list[str]:
    """Core 8's `calm.keeps_slot`, over a populated and an all-empty render."""
    populated = widget_regions(parse_html(populated_html), project=populated_project)
    empty_root = parse_html(empty_html)
    empty = widget_regions(empty_root, project=empty_project)

    problems: list[str] = []
    if not populated:
        return ["the populated render has no widget regions at all -- nothing was compared"]

    for name in sorted(set(populated) - set(empty)):
        problems.append(f"region {name!r} is on the populated render and GONE from the empty one")

    for name in sorted(set(populated) & set(empty)):
        if not _says_something(empty[name]):
            problems.append(
                f"region {name!r} keeps its slot on the empty render but says nothing -- "
                f"a widget with nothing to show must say so in a sentence"
            )

    hero_classes = hero_scale_classes()
    hero = find_one(empty_root, node_id="verdict-hero")
    hero_nodes = {id(n) for n in walk(hero)} | {id(hero)} if hero is not None else set()
    for n in walk(empty_root):
        if id(n) in hero_nodes or not (n.classes & hero_classes):
            continue
        text = " ".join(n.text().split())
        if _HAS_DIGIT.search(text):
            problems.append(
                f"a numeral renders at hero scale OUTSIDE the Core 1 hero: "
                f"{n.describe()} -> {text[:40]!r}"
            )
    return problems


def test_calm_keeps_slot_bad_half_a_dropped_region() -> None:
    """Conformance 7's bad half: "a render that drops empty widgets"."""
    populated = (
        '<div id="verdict-hero" class="section"><p>All clear. Nothing stuck.</p></div>'
        '<div id="fleet" class="section"><h2>Fleet</h2><p>One project is busy.</p></div>'
    )
    empty = '<div id="verdict-hero" class="section"><p>Idle. Nothing in flight.</p></div>'
    problems = check_calm_keeps_slot(populated, empty, populated_project="p", empty_project="e")
    assert problems, "a dropped widget region was not reported"
    assert any("#fleet" in p and "GONE" in p for p in problems), problems


def test_calm_keeps_slot_bad_half_a_hero_scale_zero() -> None:
    """Conformance 7's other bad half: "or renders a hero-scale `0`"."""
    hero_class = sorted(hero_scale_classes())[0]
    populated = (
        '<div id="verdict-hero" class="section"><p>All clear. Nothing stuck.</p></div>'
        '<div id="fleet" class="section"><h2>Fleet</h2><p>One project is busy.</p></div>'
    )
    empty = (
        '<div id="verdict-hero" class="section"><p>Idle. Nothing in flight.</p></div>'
        f'<div id="fleet" class="section"><h2>Fleet</h2>'
        f'<span class="{hero_class}">0</span> nothing here.</div>'
    )
    problems = check_calm_keeps_slot(populated, empty, populated_project="p", empty_project="e")
    assert any("hero scale" in p for p in problems), problems


def test_calm_keeps_slot_bad_half_a_slot_that_says_nothing() -> None:
    """The clause's own second limb: keeping the slot is not enough."""
    populated = '<div id="fleet" class="section"><h2>Fleet</h2><p>Three projects moving.</p></div>'
    empty = '<div id="fleet" class="section"><h2>Fleet</h2><div class="attn-list"></div></div>'
    problems = check_calm_keeps_slot(populated, empty, populated_project="p", empty_project="e")
    assert any("says nothing" in p for p in problems), problems


def test_calm_keeps_slot_hero_scale_is_read_from_the_stylesheet() -> None:
    """`hero scale` is derived from the hero, never a number written here."""
    assert hero_scale_px() > 0
    assert hero_scale_classes(), "no class in the stylesheet reaches hero scale"


@pytest.mark.xfail(
    strict=True,
    reason="OSV1-012 (Core 8): `render_attention_queue` emits a bare "
    "`<div class='attn-list'></div>` with zero rows -- the slot survives, the "
    "sentence does not. Flip the row and delete this marker in the same change.",
)
def test_calm_keeps_slot(alarm_dataset, empty_dataset) -> None:
    """Conformance 7's GOOD half: L0 empty vs populated.

    The populated half is the ALARM dataset rather than the calm one: on a
    calm fixture the attention queue is empty too, and a comparison where both
    sides are empty would compare nothing.
    """
    problems = check_calm_keeps_slot(
        alarm_dataset.l0,
        empty_dataset.l0,
        populated_project=alarm_dataset.project,
        empty_project=empty_dataset.project,
    )
    assert not problems, "Core 8 (`calm.keeps_slot`) on L0:\n  " + "\n  ".join(problems)


@pytest.mark.xfail(
    strict=True,
    reason="OSV1-012 (Core 8): on L1 the same defect appears twice more -- "
    "`render_agents_panel` emits a bare `<div class='agents-list'></div>` with "
    "zero rows, and the status-breakdown donut renders a legend of zeroes with no "
    "sentence. Flip the row and delete this marker in the same change.",
)
def test_calm_keeps_slot_l1(alarm_dataset, empty_dataset) -> None:
    """Conformance 7 names L0 AND L1, so L1 is asserted separately rather than
    folded into the L0 half -- fixing one and not the other is progress this
    kit must be able to show."""
    problems = check_calm_keeps_slot(
        alarm_dataset.l1,
        empty_dataset.l1,
        populated_project=alarm_dataset.project,
        empty_project=empty_dataset.project,
    )
    assert not problems, "Core 8 (`calm.keeps_slot`) on L1:\n  " + "\n  ".join(problems)


# ===========================================================================
# Core 9 -- deps.no_framework
#
#   "the dependency manifest declares no front-end framework, bundler, or
#    template engine, and the repo contains no build step producing served
#    assets."
# ===========================================================================

_FRONT_END_PACKAGES = (
    "jinja2", "mako", "chameleon", "react", "vue", "svelte", "htmx", "alpine",
    "webpack", "vite", "rollup", "esbuild", "parcel",
)  # fmt: skip

_BUILD_FILES = (
    "package.json", "webpack.config.js", "vite.config.js", "vite.config.ts",
    "rollup.config.js", "tsconfig.json",
)  # fmt: skip


def check_deps_no_framework(manifest: str, repo_root: Path) -> list[str]:
    problems = [
        f"the dependency manifest declares {pkg!r}"
        for pkg in _FRONT_END_PACKAGES
        if pkg in manifest.lower()
    ]
    problems += [
        f"{name} exists -- a build step producing served assets"
        for name in _BUILD_FILES
        if (repo_root / name).exists()
    ]
    return problems


def test_deps_no_framework_bad_half_a_template_engine_is_declared(tmp_path) -> None:
    problems = check_deps_no_framework('dependencies = ["jinja2>=3"]', tmp_path)
    assert problems and "jinja2" in problems[0], problems


def test_deps_no_framework_bad_half_a_build_step_appears(tmp_path) -> None:
    (tmp_path / "package.json").write_text("{}")
    problems = check_deps_no_framework("dependencies = []", tmp_path)
    assert any("package.json" in p for p in problems), problems


def test_deps_no_framework() -> None:
    problems = check_deps_no_framework(S.read(S.PYPROJECT), S.REPO_ROOT)
    assert not problems, "Core 9 (`deps.no_framework`):\n  " + "\n  ".join(problems)


# ===========================================================================
# Core 10 -- antigoals.enforced
#
#   "the dependency manifest declares no charting or drag-and-drop library;
#    every adapter call reached from a view passes an explicit limit; no view
#    holds state that does not survive a refresh (state persisted in
#    `localStorage` or on the server survives; state held only in page memory
#    does not)."
# ===========================================================================

_CHART_AND_DRAG_PACKAGES = (
    "chart.js", "chartjs", "d3", "plotly", "echarts", "highcharts", "recharts",
    "apexcharts", "sortable", "dragula", "interact.js", "react-dnd", "dnd-kit",
)  # fmt: skip

#: The adapter read verbs a view can call unbounded. `list` takes a `limit`
#: that `0` disables; `list_bounded` is the bounded one by construction.
_LIMITED_VERBS = frozenset({"list"})

#: Writing a presentation preference onto the document root or body.
_PRESENTATION_WRITE = re.compile(
    r"document\.(documentElement|body)\.(setAttribute\(\s*['\"]data-[a-z-]+"
    r"|classList\.toggle\(\s*['\"])"
)
#: Anything that outlives a refresh.
_PERSISTENCE = ("localStorage", "sessionStorage", "document.cookie", "fetch(")


def unbounded_view_queries() -> list[str]:
    """Every `.list(...)` in a route module with no limit, or with `limit=0`."""
    out: list[str] = []
    for path in S.ROUTE_MODULES:
        tree = ast.parse(S.read(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in _LIMITED_VERBS:
                continue
            limit = next((k for k in node.keywords if k.arg == "limit"), None)
            if limit is None:
                out.append(f"{path.name}:{node.lineno} `.{node.func.attr}(...)` passes no limit")
            elif isinstance(limit.value, ast.Constant) and not limit.value.value:
                out.append(
                    f"{path.name}:{node.lineno} `.{node.func.attr}(..., "
                    f"limit={limit.value.value!r})` -- a limit that does not bound"
                )
    return out


def unpersisted_view_state() -> list[str]:
    """Every JS block that writes a presentation preference without saving it.

    The enclosing block is the module-level Python definition that produces
    the script -- `_OBSERVATORY_THEME_JS`, `list_controls_js`, and so on --
    because that is the unit a preference and its persistence are written in.
    """
    out: list[str] = []
    for path in (S.WEBAPP, S.WEBTHEME):
        src = S.read(path)
        lines = src.splitlines()
        tree = ast.parse(src)
        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.Assign | ast.AnnAssign | ast.FunctionDef):
                continue
            end = getattr(node, "end_lineno", None) or node.lineno
            block = "\n".join(lines[node.lineno - 1 : end])
            if not _PRESENTATION_WRITE.search(block):
                continue
            if any(p in block for p in _PERSISTENCE):
                continue
            name = (
                node.name
                if isinstance(node, ast.FunctionDef)
                else ast.unparse(node.targets[0] if isinstance(node, ast.Assign) else node.target)
            )
            out.append(
                f"{path.name}:{node.lineno} `{name}` writes a presentation preference "
                f"onto the document and persists it nowhere -- it dies on refresh"
            )
    return out


def check_antigoals_enforced(manifest: str) -> list[str]:
    problems = [
        f"the dependency manifest declares {pkg!r} -- a charting or drag-and-drop library"
        for pkg in _CHART_AND_DRAG_PACKAGES
        if pkg in manifest.lower()
    ]
    problems += unbounded_view_queries()
    problems += unpersisted_view_state()
    return problems


def test_antigoals_enforced_bad_half_a_chart_library_is_declared() -> None:
    problems = check_antigoals_enforced('web = ["chart.js"]')
    assert any("chart.js" in p for p in problems), problems


def test_antigoals_enforced_bad_half_an_unbounded_view_query(monkeypatch) -> None:
    """`limit=0` and a missing limit must BOTH be reported -- the shipped L1
    view is the specimen for the first (OSV1-015)."""
    problems = unbounded_view_queries()
    assert any("limit=0" in p for p in problems), problems
    assert any("passes no limit" in p for p in problems), problems

    real = S.read

    def fake(path: Path) -> str:
        text = real(path)
        if Path(path) == S.WEBBROWSE:
            text = text.replace(
                "bd.list(status=status_filter, include_resolved=True, limit=0)",
                "bd.list(status=status_filter, include_resolved=True, limit=500)",
                1,
            )
        return text

    monkeypatch.setattr(S, "read", fake)
    fixed = unbounded_view_queries()
    assert not any("limit=0" in p for p in fixed), (
        "a real bound was still reported as unbounded -- the check does not "
        "discriminate, it just always fails"
    )


def test_antigoals_enforced_bad_half_state_that_dies_on_refresh(monkeypatch) -> None:
    """The theme setter is the shipped specimen (OSV1-016); the density block
    beside it persists, and must NOT be reported."""
    problems = unpersisted_view_state()
    assert any("_OBSERVATORY_THEME_JS" in p for p in problems), problems
    assert not any("list_controls_js" in p for p in problems), (
        "the density preference persists in localStorage and was still reported"
    )

    real = S.read

    def fake(path: Path) -> str:
        text = real(path)
        if Path(path) == S.WEBAPP:
            text = text.replace(
                "  document.documentElement.setAttribute('data-theme', t);",
                "  document.documentElement.setAttribute('data-theme', t);\n"
                "  localStorage.setItem('wt-theme', t);",
                1,
            )
        return text

    monkeypatch.setattr(S, "read", fake)
    assert not any("_OBSERVATORY_THEME_JS" in p for p in unpersisted_view_state()), (
        "a persisted theme was still reported as dying on refresh"
    )


@pytest.mark.xfail(
    strict=True,
    reason="OSV1-015 (Core 10): the L1 project view runs `bd.list(..., limit=0)` on "
    "every 20s poll, and `_oldest_ready_item` calls `bd.list` with no limit at all. "
    "OSV1-016 (Core 10): the theme choice is client-side state that dies on refresh. "
    "Flip both rows and delete this marker in the same change.",
)
def test_antigoals_enforced() -> None:
    problems = check_antigoals_enforced(S.read(S.PYPROJECT))
    assert not problems, "Core 10 (`antigoals.enforced`):\n  " + "\n  ".join(problems)


# ===========================================================================
# Core 11 -- push.alarm_only
#
#   "exactly one call site fires the push channel, and it is the reclaim path;
#    no other code path reaches the sender."
# ===========================================================================

_SENDER = ("fire_reclaim_alarm", "send_alarm(")


def push_call_sites() -> list[tuple[str, int]]:
    """Every call site of the push sender, outside the sender's own module."""
    return [
        (path.name, lineno)
        for path in S.src_modules()
        if path != S.WEBPUSH
        for lineno, line in enumerate(S.read(path).splitlines(), start=1)
        if any(marker in line for marker in _SENDER)
    ]


def check_push_alarm_only(sites: list[tuple[str, int]]) -> list[str]:
    if len(sites) != 1:
        return [
            f"the push channel has {len(sites)} call site(s), not exactly one: {sites}. "
            f"Core 11 freezes the channel at ONE event class -- a custody-TTL reclaim."
        ]
    module, _line = sites[0]
    if module != S.SUPERVISOR.name:
        return [f"the single push call site is in {module}, not the reclaim sweep"]

    sup = S.read(S.SUPERVISOR)
    try:
        reclaim = sup[sup.index("if eligible:") :][:1200]
    except ValueError:
        return ["the reclaim branch (`if eligible:`) is gone from supervisor.py"]
    if "bd.release(item.id)" not in reclaim or "WP.fire_reclaim_alarm(" not in reclaim:
        return ["the push no longer fires from inside the reclaim branch, after the release"]
    if reclaim.index("bd.release(item.id)") > reclaim.index("WP.fire_reclaim_alarm("):
        return ["the alarm fires BEFORE the release it announces"]
    return []


def test_push_alarm_only_bad_half_a_second_call_site(monkeypatch) -> None:
    real = S.read

    def fake(path: Path) -> str:
        text = real(path)
        if Path(path) == S.WEBAPP:
            text += "\n# WP.fire_reclaim_alarm(item)  -- a second sender\n"
        return text

    monkeypatch.setattr(S, "read", fake)
    problems = check_push_alarm_only(push_call_sites())
    assert problems and "2 call site" in problems[0], problems


def test_push_alarm_only_bad_half_calm_must_not_be_able_to_send() -> None:
    """Zero senders is not a pass either -- it means the check lost the channel."""
    assert check_push_alarm_only([])


def test_push_alarm_only() -> None:
    problems = check_push_alarm_only(push_call_sites())
    assert not problems, "Core 11 (`push.alarm_only`):\n  " + "\n  ".join(problems)


# ===========================================================================
# Core 2 (token half) -- palette.status_hue_set
#
#   "the token block declares exactly the three hues and no other status hue
#    is defined."
#
# The rendered half (`calm.zero_alarm_pixels`) is Tier B.
# ===========================================================================

#: The two compatibility aliases. They are NOT a fourth and fifth hue only for
#: as long as they resolve INTO the set -- which is exactly what is checked.
_HUE_ALIASES = (("--amber", "--alarm"), ("--crimson", "--blocked"))


def check_palette_status_hue_set(tokens: dict[str, str]) -> list[str]:
    problems: list[str] = []
    declared = {t for t in tokens if re.fullmatch(r"--(alarm|blocked|watch)", t)}
    if declared != set(S.STATUS_TOKENS):
        problems.append(
            f"the status hue set is {sorted(declared)}, not exactly {sorted(S.STATUS_TOKENS)}"
        )
    for hue in S.STATUS_TOKENS:
        value = S.resolve_token(hue, tokens)
        if value is None or not value.startswith("#"):
            problems.append(f"{hue} does not resolve to a literal colour (got {value!r})")
    for alias, target in _HUE_ALIASES:
        if alias in tokens and tokens[alias] != f"var({target})":
            problems.append(
                f"{alias} no longer resolves to var({target}) (got {tokens[alias]!r}) -- "
                f"it has become a bespoke status hue outside the closed set"
            )
    return problems


def test_palette_status_hue_set_bad_half_a_bespoke_fourth_hue() -> None:
    """Conformance 1's specimen: a hardcoded amber outside the token set."""
    tokens = dict(S.token_blocks()["dark"])
    tokens["--amber"] = "#D9A253"
    problems = check_palette_status_hue_set(tokens)
    assert any("--amber" in p for p in problems), problems


def test_palette_status_hue_set_bad_half_a_fourth_status_token() -> None:
    tokens = dict(S.token_blocks()["dark"])
    tokens["--watch"] = "var(--alarm)"  # still three names...
    tokens_with_extra = dict(tokens)
    del tokens_with_extra["--watch"]
    problems = check_palette_status_hue_set(tokens_with_extra)
    assert any("status hue set" in p for p in problems), problems


def test_palette_status_hue_set() -> None:
    """Every declared token block, not a hand-listed pair.

    `token_blocks()` keeps the two light blocks SEPARATE (webtheme.py holds
    them in sync only by comment), and a fourth block appearing must be
    checked without anyone remembering to add it here.
    """
    blocks = S.token_blocks()
    assert set(blocks) >= {"dark"}, f"no token blocks parsed at all: {sorted(blocks)}"
    problems: list[str] = []
    for name, tokens in sorted(blocks.items()):
        problems += [f"{name}: {p}" for p in check_palette_status_hue_set(tokens)]
    assert not problems, "Core 2 (`palette.status_hue_set`):\n  " + "\n  ".join(problems)


# ===========================================================================
# Core 7 (token half) -- perception.floors
#
#   "token-pair relative-luminance math over the declared token set" -- text
#   contrast at least 4.5:1, non-text at least 3:1, in both themes. The
#   browser half (computed ratios, target boxes, motion trace) is Tier B.
# ===========================================================================

TEXT_FLOOR = 4.5
NON_TEXT_FLOOR = 3.0


def check_perception_floors(
    text: list[tuple[str, str, str, float]],
    non_text: list[tuple[str, str, str, float]],
) -> list[str]:
    if not text or not non_text:
        return ["the token-pair census produced no pairs at all -- nothing was measured"]
    problems = [
        f"text pair {ink} on {ground} ({block}) is {ratio:.2f}:1, below the {TEXT_FLOOR}:1 floor"
        for block, ink, ground, ratio in sorted(text, key=lambda r: r[3])
        if ratio < TEXT_FLOOR
    ]
    problems += [
        f"non-text pair {a} on {b} ({block}) is {ratio:.2f}:1, below the {NON_TEXT_FLOOR}:1 floor"
        for block, a, b, ratio in sorted(non_text, key=lambda r: r[3])
        if ratio < NON_TEXT_FLOOR
    ]
    return problems


def test_perception_floors_bad_half_the_recorded_below_floor_pair() -> None:
    """Conformance 4's named specimen: "a fixture using the recorded 4.27:1
    ink pair emits a contrast number below the floor". The math is the ledger's
    own engine, so the number is computed here, not transcribed."""
    problems = check_perception_floors(
        [("light", "--ink-quiet", "--color-ground", 4.27)],
        [("light", "--alarm", "--color-ground", 4.0)],
    )
    assert len(problems) == 1 and "4.27:1" in problems[0], problems


def test_perception_floors_bad_half_an_empty_census_is_not_a_pass() -> None:
    assert check_perception_floors([], [])


def test_perception_floors_bad_half_the_engine_really_computes_the_ratio() -> None:
    """Black on white is 21:1 and white on white is 1:1 -- if the ledger's
    luminance math ever stopped computing, every pair would look fine."""
    assert S.contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)
    assert S.contrast_ratio("#ffffff", "#ffffff") == pytest.approx(1.0, abs=0.01)


@pytest.mark.xfail(
    strict=True,
    reason="OSV1-009 (Core 7): six declared text pairs sit below the 4.5:1 floor "
    "(worst 2.72:1, all --ink-quiet in light mode) and that token paints real "
    "reading copy. Flip the row and delete this marker in the same change.",
)
def test_perception_floors() -> None:
    problems = check_perception_floors(S.text_pairs(), S.non_text_pairs())
    assert not problems, "Core 7 (`perception.floors`, token half):\n  " + "\n  ".join(problems)


# ===========================================================================
# The kit's own coverage tripwire.
#
# Every Tier-A-checkable clause the contract names must have a check here, and
# every check must have a bad half. Without this, the way this kit fails is by
# quietly covering less than it claims -- which is the exact failure the
# contract's Freeze 1 and Freeze 4 exist to prevent.
# ===========================================================================

#: Machine-check name -> the test function implementing its GOOD half.
TIER_A_CHECKS: dict[str, str] = {
    "hero.velocity_and_counts": "test_hero_velocity_and_counts",
    "state.not_colour_only": "test_state_not_colour_only",
    "visual.single_source": "test_visual_single_source",
    "reads.never_write": "test_reads_never_write",
    "calm.keeps_slot": "test_calm_keeps_slot",
    "deps.no_framework": "test_deps_no_framework",
    "antigoals.enforced": "test_antigoals_enforced",
    "push.alarm_only": "test_push_alarm_only",
    "palette.status_hue_set": "test_palette_status_hue_set",
    "perception.floors": "test_perception_floors",
}


def test_every_tier_a_machine_check_the_contract_names_is_implemented_here() -> None:
    """The contract's own **Machine check:** names, matched against this file.

    Read out of `contracts/operator-surface.v1.md`, never listed by hand: a
    clause that grows a Tier-A check this kit does not implement fails here.
    """
    contract = S.read(S.OPERATOR_CONTRACT_PATH)
    clauses = re.split(r"^### ", contract, flags=re.MULTILINE)[1:]
    named: set[str] = set()
    for clause in clauses:
        tier = re.search(r"^\*\*Tier:\*\*\s*(.+)$", clause, flags=re.MULTILINE)
        if not tier or "A" not in re.split(r"[\s,]+", tier.group(1)):
            continue
        # Only the **Machine check:** paragraph -- a clause body also cites
        # source files (`webtheme.py`), which look like a dotted name and are
        # not one.
        check_line = re.search(
            r"^\*\*Machine check:\*\*(.+?)(?:\n\n|\Z)", clause, flags=re.MULTILINE | re.DOTALL
        )
        if not check_line:
            continue
        for name in re.findall(r"`([a-z]+\.[a-z_]+)`", check_line.group(1)):
            named.add(name)

    # Tier B's own half of a two-tier clause is named in the same clause body.
    tier_b_only = {"calm.zero_alarm_pixels"}
    expected = named - tier_b_only
    missing = expected - set(TIER_A_CHECKS)
    assert not missing, (
        f"the contract names Tier-A machine check(s) this kit does not implement: {sorted(missing)}"
    )
    stale = set(TIER_A_CHECKS) - expected
    assert not stale, (
        f"this kit implements check(s) the contract no longer names as Tier A: {sorted(stale)}"
    )


def test_every_check_ships_a_bad_half() -> None:
    """Freeze 4: "every Conformance fixture discriminates"."""
    source = Path(__file__).read_text(encoding="utf-8")
    defined = set(re.findall(r"^def (test_\w+)", source, flags=re.MULTILINE))
    for name, good in sorted(TIER_A_CHECKS.items()):
        assert good in defined, f"{name}: good half {good!r} is not defined in this file"
        bad = [d for d in defined if d.startswith(f"{good}_bad_half_")]
        assert bad, f"{name}: no bad half -- a check nobody watched fail asserts nothing"
