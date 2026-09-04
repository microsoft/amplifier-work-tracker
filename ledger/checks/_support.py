"""Shared helpers for the conformance-ledger checks.

In-process only: no LLM, no network, no subprocess -- per the ledger format
this repo adopted (`LEDGER-FORMAT.md` sec.1). A ledger that is slow does not
get run, and a ledger that is not run is a remembered audit.
"""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_DIR = REPO_ROOT / "ledger"
ROWS_PATH = LEDGER_DIR / "rows.yaml"
CONTRACT_PATH = REPO_ROOT / "contracts" / "custody-coordination.v1.md"
OPERATOR_CONTRACT_PATH = REPO_ROOT / "contracts" / "operator-surface.v1.md"

SRC_DIR = REPO_ROOT / "src" / "amplifier_work_tracker"
ADAPTER = SRC_DIR / "adapter.py"
CUSTODY = SRC_DIR / "custody.py"
SUPERVISOR = SRC_DIR / "supervisor.py"

# --- the operator surface's own modules (operator-surface.v1 rows) ---
WEBAPP = SRC_DIR / "webapp.py"
WEBBROWSE = SRC_DIR / "webbrowse.py"
WEBTHEME = SRC_DIR / "webtheme.py"
WEBTRUST = SRC_DIR / "webtrust.py"
WEBPWA = SRC_DIR / "webpwa.py"
WEBPUSH = SRC_DIR / "webpush.py"
WIDGETS = SRC_DIR / "widgets.py"
CHARTSVG = SRC_DIR / "chartsvg.py"
PYPROJECT = REPO_ROOT / "pyproject.toml"
#: The three modules that register HTTP routes (Core 5's route audit).
ROUTE_MODULES = (WEBAPP, WEBBROWSE, WEBTRUST)
TOOL_MODULE = (
    REPO_ROOT
    / "modules"
    / "tool-work-tracker"
    / "amplifier_module_tool_work_tracker"
    / "__init__.py"
)
AWARENESS = REPO_ROOT / "context" / "awareness.md"
CLAIM_SKILL = REPO_ROOT / "skills" / "claiming-work-safely" / "SKILL.md"
MAKEFILE = REPO_ROOT / "Makefile"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# =============================================================================
# Families. One ledger file, two contracts (`rows.yaml`'s own header explains
# why they share a file). Everything that used to be hardcoded to the custody
# contract -- which contract a row's quote verifies against, which clause ids
# are legal, which probe module owns its probes -- is resolved through here, so
# adding a third contract is a table entry rather than a fork of the tripwires.
# =============================================================================


@dataclass(frozen=True)
class Family:
    """One contract, and the row family that ledgers it."""

    prefix: str
    contract: Path
    contract_rel: str
    probe_module: str
    #: Clause ids this contract offers no bare number for -- a reported
    #: deviation from LEDGER-FORMAT sec.2, never a silent local dialect.
    unnumbered: frozenset[str]


FAMILIES: tuple[Family, ...] = (
    Family(
        prefix="CCV1",
        contract=CONTRACT_PATH,
        contract_rel="contracts/custody-coordination.v1.md",
        probe_module="test_custody_rows",
        # The 2026-09-03 amendment numbered the Conformance FIXTURES and the
        # Freeze Bar, but not the separate `Checks` subsection.
        unnumbered=frozenset({"Conformance: Checks"}),
    ),
    Family(
        prefix="OSV1",
        contract=OPERATOR_CONTRACT_PATH,
        contract_rel="contracts/operator-surface.v1.md",
        probe_module="test_operator_rows",
        unnumbered=frozenset(),
    ),
)


def family_of(row_id: str) -> Family:
    for fam in FAMILIES:
        if row_id.startswith(f"{fam.prefix}-"):
            return fam
    raise AssertionError(
        f"row id {row_id!r} belongs to no declared family "
        f"({', '.join(f.prefix for f in FAMILIES)}). A row nobody's tripwires cover is "
        f"a row nobody is watching."
    )


#: `### Core 1: ...` style headings AND `**Freeze 1:** ...` style bold labels.
#: operator-surface.v1 numbers its Freeze Bar and Reserved namespaces inline
#: rather than as headings, and both forms are bare numbered identifiers.
_HEADING_CLAUSE = re.compile(r"^### ([^\n:]+):", re.MULTILINE)
_BOLD_CLAUSE = re.compile(r"^\*\*([A-Za-z][A-Za-z ]* \d+):\*\*", re.MULTILINE)


def clause_ids(contract: Path) -> frozenset[str]:
    """Every clause id the contract actually names, in either form."""
    text = read(contract)
    return frozenset(_HEADING_CLAUSE.findall(text)) | frozenset(_BOLD_CLAUSE.findall(text))


def required_clause_ids(contract: Path) -> frozenset[str]:
    """The clauses coverage tripwire 1 demands a row for: Core, plus any the
    contract itself files under NOT-ASSERTABLE.

    Backlogged, Reserved, Conformance and Freeze ids are deliberately NOT
    required: Backlogged and Reserved are not promises, and Conformance/Freeze
    are rowed where they carry an in-repo check rather than universally.
    """
    return frozenset(c for c in clause_ids(contract) if c.startswith(("Core ", "NOT-ASSERTABLE ")))


DISPOSITIONS = {
    "CONFORMS",
    "GAP",
    "VIOLATION",
    "OPEN-PINNED",
    "NOT-ASSERTABLE",
    "EXCLUDED",
    "DIVERGED",
}
ASSERTION_KINDS = {"probe", "indexed", "absence", "none"}

#: Dispositions whose probe deliberately pins the CURRENT, KNOWN-WRONG shape
#: (`LEDGER-FORMAT.md` sec.2 `assertion.kind: absence`, and this repo's reading
#: of PROTOCOL.md sec.3.3 "drift is bidirectional"). A probe on one of these
#: rows passing is NOT evidence of conformance -- see the row's disposition.
PINNING_DISPOSITIONS = frozenset({"GAP", "VIOLATION"})

# --------------------------------------------------------------- flip directions
#
# WHY a ledger check that used to pass now fails. `LEDGER-FORMAT.md` names
# four directions; none of them covers the flip a *pinning* probe makes
# possible, so this repo defines a fifth LOCALLY and reports it as a format
# deviation (reconcile-report.md sec.11) -- data for `ledger-format.v1`, not a
# silent local dialect.
FLIP_REGRESSION = "REGRESSION"
FLIP_UN_DIVERGENCE = "UN-DIVERGENCE"
FLIP_UNDECIDED_MOVEMENT = "UNDECIDED-MOVEMENT"
FLIP_LEDGER_INTEGRITY = "LEDGER-INTEGRITY"

#: LOCAL EXTENSION -- not in `LEDGER-FORMAT.md`.
FLIP_VIOLATION_MOVEMENT = "VIOLATION-MOVEMENT"

FLIP_DIRECTIONS: dict[str, str] = {
    FLIP_REGRESSION: (
        "a CONFORMS row went red: the repo moved AWAY from the contract. "
        "Action: fix the repo, or amend the contract."
    ),
    FLIP_UN_DIVERGENCE: (
        "a DIVERGED row went red: an external contract's owner adopted our "
        "position. Action: retire the divergence."
    ),
    FLIP_UNDECIDED_MOVEMENT: (
        "an OPEN-PINNED row went red: the pinned undecided surface moved "
        "before the decision was taken. Action: take the decision."
    ),
    FLIP_LEDGER_INTEGRITY: (
        "the ledger stopped describing the contract it claims to describe "
        "(SYNC hash mismatch, quote drift, dangling assertion ref). Action: "
        "MANDATORY full-ledger re-review -- never a silent hash bump."
    ),
    FLIP_VIOLATION_MOVEMENT: (
        "a pinning GAP/VIOLATION probe went red because the behaviour moved "
        "TOWARD the contract -- a silent fix, which this ledger refuses to let "
        "pass unrecorded. Action: update the row to CONFORMS and retarget the "
        "probe at the fixed shape IN THE SAME CHANGE. A passing pin is not "
        "conformance; only the retargeted probe is."
    ),
}

#: Directions this repo added on top of `LEDGER-FORMAT.md`'s four.
LOCAL_FLIP_DIRECTIONS = frozenset({FLIP_VIOLATION_MOVEMENT})


def is_pinning(r: dict[str, Any]) -> bool:
    """True when this row's assertion pins the currently-wrong shape.

    The distinction the ruling turns on: a probe here passing means the drift
    is still exactly where the ledger says it is -- never that the clause
    conforms.
    """
    return r["disposition"] in PINNING_DISPOSITIONS and r["assertion"]["kind"] in {
        "probe",
        "absence",
    }


def expected_flip_direction(r: dict[str, Any]) -> str:
    """The direction to read into THIS row's check going red.

    One row, one direction -- so a red ledger names its own meaning instead
    of leaving the reader to guess whether a fix or a regression landed.
    """
    if r["id"].endswith("-000"):
        return FLIP_LEDGER_INTEGRITY
    if is_pinning(r):
        return FLIP_VIOLATION_MOVEMENT
    if r["disposition"] == "DIVERGED":
        return FLIP_UN_DIVERGENCE
    if r["disposition"] == "OPEN-PINNED":
        return FLIP_UNDECIDED_MOVEMENT
    return FLIP_REGRESSION


def collapse(text: str) -> str:
    """Collapse every whitespace run to a single space.

    The ledger format's quote-matching semantics: words, markup and
    character order are exact; only whitespace/reflow is tolerated.
    """
    return re.sub(r"\s+", " ", text).strip()


@cache
def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@cache
def read_collapsed(path: Path) -> str:
    return collapse(read(path))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contains(path: Path, snippet: str) -> bool:
    """Whitespace-collapsed containment -- the same matching semantics the
    ledger uses for contract quotes, applied to source files so a probe
    survives reformatting but never survives a real change of wording.
    """
    return collapse(snippet) in read_collapsed(path)


def count(path: Path, needle: str) -> int:
    return read(path).count(needle)


@cache
def rows() -> list[dict[str, Any]]:
    """The ledger, parsed. Top-level YAML LIST of row mappings (no wrapper
    mapping, no `meta:` key) -- `LEDGER-FORMAT.md` sec.2.
    """
    import yaml  # deferred: only the ledger kit needs a YAML parser

    data = yaml.safe_load(read(ROWS_PATH))
    if not isinstance(data, list):
        raise AssertionError(
            f"{ROWS_PATH} must parse as a top-level YAML list of rows, got {type(data).__name__}"
        )
    return data


def row(row_id: str) -> dict[str, Any]:
    for r in rows():
        if r.get("id") == row_id:
            return r
    raise AssertionError(f"no ledger row with id {row_id!r}")


@cache
def function_names(path: Path) -> frozenset[str]:
    """Every top-level (and class-nested) test function name in a python
    file, found by PARSING -- never importing. Static verification is what
    lets a row cite a test that lives in a different environment (e.g. the
    separately-packaged tool module) without importing it here.
    """
    tree = ast.parse(read(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(node.name)
    return frozenset(names)


# =============================================================================
# Measurement engines for `contracts/operator-surface.v1.md` (OSV1-###).
#
# Three of that contract's Core clauses name a check that is a MEASUREMENT over
# the tree, not a containment assertion: the inline-style census (Core 4), the
# token-pair luminance math (Core 7) and the route audit (Core 5). They live
# here rather than in the probe module so the mutation harness's reader
# injection reaches them: each one calls the module-global `read` by name, so
# `applied()` swapping `_support.read` swaps what they measure.
#
# NONE of them is cached -- a cache would make a mutated world invisible, which
# would silently hollow out exactly the discriminating-power evidence the
# harness exists to produce.
# =============================================================================


def src_modules() -> list[Path]:
    """Every top-level module of the package, sorted. Core 4 scopes its check
    to "anywhere in `src/`", so the census must not be a hand-kept file list
    that a new module could quietly escape.
    """
    return sorted(SRC_DIR.glob("*.py"))


# --------------------------------------------------------- inline-style census

#: Two ADJACENT Python string literals across a line break -- `...;'\n  "...` or
#: `...)"\n  f'...` or `...' +\n  '...`. Splicing these out first is what lets an
#: HTML attribute that was split across concatenated literals be read as ONE
#: attribute (webapp.py's kpi labels, webbrowse.py's chip badges).
#:
#: A NEWLINE IS MANDATORY, and that is load-bearing: `600"' if is_today else ""`
#: puts a `"` immediately beside a `'`, which is an attribute-close beside a
#: literal-close -- NOT a concatenation. Allowing same-line adjacency spliced
#: those away and ran two real attributes together.
_SPLICE = re.compile(r"['\"][ \t]*(?:\+[ \t]*)?\n[ \t]*(?:\+[ \t]*)?[fFrRbB]{0,2}['\"]")
_STYLE_ATTR = re.compile(r'style="([^"]*)"')

_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_COLOUR_FUNC = re.compile(r"\b(rgb|rgba|hsl|hsla)\s*\(")
_COLOUR_PROP = re.compile(
    r"\b(color|background|background-color|fill|stroke|border-color|box-shadow)\s*:\s*([^;]*)"
)
_FONT_PROP = re.compile(r"\bfont(-family|-size|-weight|-style|-variant)?\s*:\s*([^;]*)")
_SIZE_PROP = re.compile(
    r"\b(width|height|min-width|max-width|min-height|max-height|gap|"
    r"margin|margin-top|margin-bottom|margin-left|margin-right|"
    r"padding|padding-top|padding-bottom|padding-left|padding-right|"
    r"top|left|right|bottom|line-height|letter-spacing|border|border-top|"
    r"border-bottom|border-left|border-right|border-width|border-radius|flex)\s*:\s*([^;]*)"
)
_LEN_LITERAL = re.compile(r"(?<![\w-])\d*\.?\d+(px|rem|em|%|ch|vh|vw|pt)(?![\w-])")
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")

LITERAL = "LITERAL"
COMPUTED = "COMPUTED"
TOKEN = "TOKEN"


def classify_style(decl: str) -> tuple[str, list[str]]:
    """Bucket one inline `style=` declaration, with its reasons.

    The rule, stated once here so the census is REPRODUCIBLE rather than
    asserted (operator-surface.v1 Core 4, and the Phase-1 Need-2 ruling that
    put the register and its census in `ledger/`):

      LITERAL   a hex/rgb()/hsl() colour not routed through `var(--token)`, OR a
                font property carrying a literal value, OR a length literal
                (px/rem/em/%/...) on a size or spacing property.
      COMPUTED  the declaration carries an interpolated `{...}` placeholder.
      TOKEN     only `var(--token)` values and/or properties that are none of
                colour, font or size.

    LITERAL wins over COMPUTED: a declaration that interpolates an accent AND
    hardcodes a padding is a violation, not an exemption.
    """
    reasons: list[str] = []
    literal = False

    for m in _COLOUR_PROP.finditer(decl):
        val = m.group(2)
        if _HEX.search(val) or (_COLOUR_FUNC.search(val) and "var(" not in val):
            literal = True
            reasons.append(f"literal colour in `{m.group(1)}`")
    if _HEX.search(decl) and not any("literal colour" in r for r in reasons):
        literal = True
        reasons.append("literal hex colour")

    for m in _FONT_PROP.finditer(decl):
        prop, val = (m.group(1) or ""), m.group(2)
        if "var(" in val or "inherit" in val or _PLACEHOLDER.search(val):
            continue
        literal = True
        reasons.append(f"literal font{prop}")

    for m in _SIZE_PROP.finditer(decl):
        val = m.group(2)
        if _PLACEHOLDER.search(val) or "var(" in val:
            continue
        if _LEN_LITERAL.search(val):
            literal = True
            reasons.append(f"literal {m.group(1)}")

    if literal:
        return LITERAL, reasons
    if _PLACEHOLDER.search(decl):
        return COMPUTED, ["computed geometry / interpolated value"]
    return TOKEN, ["tokens and/or non-colour/font/size properties only"]


def inline_style_sites() -> list[tuple[str, int, str, str]]:
    """Every inline `style=` site in `src/`, as (file, line, bucket, decl).

    Raises if a file's parsed count disagrees with its raw `style="` count --
    a parser that silently loses a site would UNDERSTATE the violation, which
    is the one direction a census must never fail in.
    """
    out: list[tuple[str, int, str, str]] = []
    for path in src_modules():
        text = read(path)
        raw = text.count('style="')
        if raw == 0:
            continue
        found = _STYLE_ATTR.findall(_SPLICE.sub("", text))
        if len(found) != raw:
            raise AssertionError(
                f'inline-style census cannot parse {path.name}: {raw} raw `style="` '
                f"occurrences but {len(found)} parsed attributes. The census is only "
                f"honest while these agree -- fix the splice rule, never the count."
            )
        linenos = [text.count("\n", 0, m.start()) + 1 for m in re.finditer(r'style="', text)]
        for lineno, decl in zip(linenos, found, strict=True):
            out.append((path.name, lineno, classify_style(decl)[0], decl))
    return out


def style_sites_in(bucket: str) -> list[str]:
    """`file:line` for every site in one census bucket, sorted."""
    return sorted(f"{f}:{n}" for f, n, b, _d in inline_style_sites() if b == bucket)


# ------------------------------------------------------ token-pair luminance

_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_CSS_DECL = re.compile(r"(--[a-z0-9-]+)\s*:\s*([^;]+);")
_HEX_EXACT = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_VAR_ONLY = re.compile(r"var\((--[a-z0-9-]+)\)")


def _css_block(text: str, start_pat: str) -> str:
    """The brace-balanced body of the first block matching `start_pat`."""
    m = re.search(start_pat, text, flags=re.MULTILINE)
    if m is None:
        raise AssertionError(f"token block not found in webtheme.py: {start_pat}")
    i = text.index("{", m.start())
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i : j + 1]
    raise AssertionError(f"unbalanced token block for {start_pat}")


def _declared(block_src: str) -> dict[str, str]:
    # Comments are stripped FIRST: webtheme.py's token block carries long prose
    # comments that mention token names, and a naive scan reads one of them as
    # a declaration (it silently swallowed `--blocked` the first time).
    return {
        m.group(1): m.group(2).strip() for m in _CSS_DECL.finditer(_CSS_COMMENT.sub(" ", block_src))
    }


def token_blocks() -> dict[str, dict[str, str]]:
    """The three declared token blocks, light overlaid on the dark base.

    Keyed by the name this ledger reports them under; the two light blocks are
    kept SEPARATE on purpose -- webtheme.py's own comment says they are held in
    sync only by comment, so a check that merged them could not see them drift.
    """
    text = read(WEBTHEME)
    dark = _declared(_css_block(text, r"^:root\{"))
    media = _declared(_css_block(text, r"@media \(prefers-color-scheme:light\)"))
    attr = _declared(_css_block(text, r'^:root\[data-theme="light"\]\{'))
    return {
        "dark": dark,
        "light-media": {**dark, **media},
        "light-attr": {**dark, **attr},
    }


def resolve_token(name: str, table: dict[str, str], depth: int = 0) -> str | None:
    """A token's literal value, following `var(--alias)` chains."""
    if depth > 8:
        return None
    val = table.get(name)
    if val is None:
        return None
    m = _VAR_ONLY.fullmatch(val.strip())
    return resolve_token(m.group(1), table, depth + 1) if m else val.strip()


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hexval: str) -> float | None:
    m = _HEX_EXACT.match(hexval)
    if m is None:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _srgb_to_linear(r) + 0.7152 * _srgb_to_linear(g) + 0.0722 * _srgb_to_linear(b)


def contrast_ratio(a: str, b: str) -> float | None:
    """WCAG contrast ratio for two hex colours, or None if either is not one."""
    la, lb = relative_luminance(a), relative_luminance(b)
    if la is None or lb is None:
        return None
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


#: The ink tokens that carry reading copy, and the grounds they sit on.
INK_TOKENS = ("--ink-primary", "--ink-secondary", "--ink-tertiary", "--ink-quiet", "--dim", "--ink")
GROUND_TOKENS = ("--color-ground", "--color-ground-elevated", "--color-ground-sunken")
STATUS_TOKENS = ("--alarm", "--blocked", "--watch")


def text_pairs() -> list[tuple[str, str, str, float]]:
    """(block, ink, ground, ratio) for every declared ink x ground pair."""
    out: list[tuple[str, str, str, float]] = []
    for label, table in token_blocks().items():
        for ink in INK_TOKENS:
            iv = resolve_token(ink, table)
            if iv is None:
                continue
            for ground in GROUND_TOKENS:
                gv = resolve_token(ground, table)
                if gv is None:
                    continue
                r = contrast_ratio(iv, gv)
                if r is not None:
                    out.append((label, ink, ground, r))
    return out


def non_text_pairs() -> list[tuple[str, str, str, float]]:
    """(block, status hue, ground, ratio) for every declared status x ground pair."""
    out: list[tuple[str, str, str, float]] = []
    for label, table in token_blocks().items():
        for hue in STATUS_TOKENS:
            hv = resolve_token(hue, table)
            if hv is None:
                continue
            gv = resolve_token("--color-ground", table)
            if gv is None:
                continue
            r = contrast_ratio(hv, gv)
            if r is not None:
                out.append((label, hue, "--color-ground", r))
    return out


# ------------------------------------------------------------- route audit

#: Every write verb on the adapter seam. A GET handler reaching any of these is
#: what Core 5's `reads.never_write` forbids.
MUTATING_VERBS = frozenset(
    {
        "create", "update", "comment", "edit_item", "supersede", "claim_item", "claim_next",
        "release", "reopen", "resolve", "resolve_outcome", "defer", "undefer", "block",
        "unblock", "add_dependency", "take_custody", "renew_custody", "move_item", "remove",
        "rename", "delete", "erratum",
    }
)  # fmt: skip


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute):
                names.add(f.attr)
            elif isinstance(f, ast.Name):
                names.add(f.id)
    return names


def _route_methods(dec: ast.expr) -> list[str] | None:
    if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
        return None
    attr = dec.func.attr
    if attr in {"get", "post", "put", "patch", "delete", "head"}:
        return [attr.upper()]
    if attr == "api_route":
        for kw in dec.keywords:
            if kw.arg == "methods" and isinstance(kw.value, ast.List):
                return [
                    e.value
                    for e in kw.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                ]
        return ["GET"]
    return None


def route_audit() -> list[dict[str, Any]]:
    """Every registered route, and whether a read-only one reaches a write verb.

    Static and module-local, bounded at depth 4 -- the honest limit is recorded
    in ledger row OSV1-007's notes rather than hidden here.
    """
    audited: list[dict[str, Any]] = []
    for path in ROUTE_MODULES:
        tree = ast.parse(read(path))
        funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                funcs.setdefault(node.name, node)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for dec in node.decorator_list:
                methods = _route_methods(dec)
                if methods is None:
                    continue
                assert isinstance(dec, ast.Call)
                route = (
                    dec.args[0].value if dec.args and isinstance(dec.args[0], ast.Constant) else "?"
                )
                read_only = any(m in {"GET", "HEAD"} for m in methods)
                hits: set[str] = set()
                if read_only:
                    seen: set[str] = set()
                    frontier = _called_names(node)
                    for _ in range(4):
                        nxt: set[str] = set()
                        for name in frontier:
                            if name in MUTATING_VERBS:
                                hits.add(name)
                            if name in seen:
                                continue
                            seen.add(name)
                            helper = funcs.get(name)
                            if helper is not None and helper is not node:
                                nxt |= _called_names(helper)
                        frontier = nxt - seen
                        if not frontier:
                            break
                audited.append(
                    {
                        "module": path.name,
                        "line": node.lineno,
                        "handler": node.name,
                        "route": route,
                        "methods": methods,
                        "read_only": read_only,
                        "mutating_reached": sorted(hits),
                    }
                )
    return audited
