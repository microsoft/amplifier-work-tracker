"""Shared helpers for the conformance-ledger checks.

In-process only: no LLM, no network, no subprocess -- per the ledger format
this repo adopted (`LEDGER-FORMAT.md` sec.1). A ledger that is slow does not
get run, and a ledger that is not run is a remembered audit.
"""

from __future__ import annotations

import ast
import hashlib
import re
from functools import cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_DIR = REPO_ROOT / "ledger"
ROWS_PATH = LEDGER_DIR / "rows.yaml"
CONTRACT_PATH = REPO_ROOT / "contracts" / "custody-coordination.v1.md"

ADAPTER = REPO_ROOT / "src" / "amplifier_work_tracker" / "adapter.py"
CUSTODY = REPO_ROOT / "src" / "amplifier_work_tracker" / "custody.py"
SUPERVISOR = REPO_ROOT / "src" / "amplifier_work_tracker" / "supervisor.py"
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
