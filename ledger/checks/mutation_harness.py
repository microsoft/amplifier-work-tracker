"""Mutation harness -- proof that each ledger probe is actually discriminating.

A probe that has never been observed to FAIL is a probe that might assert
nothing. `pytest ledger/checks -q` proves the probes pass; it cannot prove any
of them would notice if the world changed. This module supplies the missing
half.

## What it does

For every `test_row_ccv1_NNN` probe, it assembles a COUNTERFACTUAL view of the
repo in memory, runs the probe against that view, and requires the probe to go
RED. Nothing on disk is touched: the mutation is an injection over the check
kit's own readers (`read` / `contains` / `count` / `function_names` /
`sha256`), never an edit to product code, and never a subprocess.

## The direction each mutation pushes, and why it differs per row

The direction is derived from the ledger, not chosen per probe
(`_support.expected_flip_direction`):

  * **VIOLATION-MOVEMENT** -- the row is red (GAP/VIOLATION) and its probe
    PINS the current, known-wrong shape. The counterfactual is therefore the
    **fixed behaviour**, and the probe must go red under it. That is the whole
    point of a pin: a silent fix fails as loudly as a regression. This is the
    direction the protocol-authority's Ruling-1 required evidence for.

  * **REGRESSION** -- the row is green and its probe asserts the invariant.
    The counterfactual is the **known-wrong shape the row exists to forbid**
    (for the four rows that were VIOLATION before this highway: literally the
    behaviour they closed). A retargeted probe that no longer notices the
    original defect is a probe that stopped earning its row.

  * **LEDGER-INTEGRITY** -- the SYNC row. The counterfactual is the governed
    contract moving under the ledger.

## Reading the output

`proven N / M` is the record. An undeclared or non-flipping mutation is
reported by name with its reason -- never rounded away, never omitted.

Run: `make ledger-mutate` (or `python -m ledger.checks.mutation_harness`).
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import sys
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from . import _support
from . import test_custody_rows as probes
from ._support import (
    ADAPTER,
    AWARENESS,
    CI_WORKFLOW,
    CLAIM_SKILL,
    CONTRACT_PATH,
    FLIP_VIOLATION_MOVEMENT,
    MAKEFILE,
    TOOL_MODULE,
    collapse,
    expected_flip_direction,
    is_pinning,
    rows,
)

CLI = probes.CLI


class HarnessOutOfDate(Exception):
    """A mutation's anchor text is no longer in the file it targets.

    Loud on purpose: it means the source moved and this harness now proves
    less than it claims. Never downgraded to a skip -- a silently-skipped
    mutation is exactly the "green claim nobody ran" this kit exists to
    prevent.
    """


# --------------------------------------------------------------------- world


@dataclass
class World:
    """A counterfactual repo, assembled in memory.

    `raw()` is the single source of file text for a mutated run; every patched
    reader goes through it, so a mutation stated once is seen consistently by
    whichever accessor a probe happens to use.
    """

    _text: dict[Path, str] = field(default_factory=dict)
    repo_root: Path | None = None
    _tmp: tempfile.TemporaryDirectory[str] | None = None

    def raw(self, path: Path) -> str:
        path = Path(path)
        if path not in self._text:
            self._text[path] = path.read_text(encoding="utf-8")
        return self._text[path]

    def replace(self, path: Path, old: str, new: str) -> None:
        """Substitute a UNIQUE anchor. Non-unique or missing is an error."""
        src = self.raw(path)
        found = src.count(old)
        if found != 1:
            raise HarnessOutOfDate(
                f"anchor occurs {found}x (expected exactly 1) in {path}:\n  {old[:120]!r}"
            )
        self._text[path] = src.replace(old, new)

    def append(self, path: Path, text: str) -> None:
        self._text[path] = self.raw(path) + text

    def fake_root(self) -> Path:
        """A throwaway repo root, for mutations about a file EXISTING."""
        if self._tmp is None:
            self._tmp = tempfile.TemporaryDirectory(prefix="ledger-mutation-")
            root = Path(self._tmp.name)
            (root / "tests").mkdir(parents=True, exist_ok=True)
            (root / "modules" / "tool-work-tracker" / "tests").mkdir(parents=True, exist_ok=True)
            self.repo_root = root
        assert self.repo_root is not None
        return self.repo_root

    def close(self) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None


_PATCHED_IN_SUPPORT = ("read", "read_collapsed", "contains", "count", "function_names", "sha256")
_PATCHED_IN_PROBES = ("read", "contains", "count", "function_names", "sha256")


@contextlib.contextmanager
def applied(world: World) -> Iterator[None]:
    """Run the body with every check-kit reader served from `world`.

    Product code is never edited, imported or executed -- the probes are
    source-shape assertions, so substituting what they READ is the faithful
    way to ask "what would this probe do if the code were different?".
    """

    def read(path: Path) -> str:
        return world.raw(Path(path))

    def read_collapsed(path: Path) -> str:
        return collapse(read(path))

    def contains(path: Path, snippet: str) -> bool:
        return collapse(snippet) in read_collapsed(path)

    def count(path: Path, needle: str) -> int:
        return read(path).count(needle)

    def function_names(path: Path) -> frozenset[str]:
        tree = ast.parse(read(path))
        return frozenset(
            n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        )

    def sha256(path: Path) -> str:
        return hashlib.sha256(read(path).encode("utf-8")).hexdigest()

    replacements = {
        "read": read,
        "read_collapsed": read_collapsed,
        "contains": contains,
        "count": count,
        "function_names": function_names,
        "sha256": sha256,
    }
    saved: list[tuple[object, str, object]] = []
    try:
        for module, names in ((_support, _PATCHED_IN_SUPPORT), (probes, _PATCHED_IN_PROBES)):
            for name in names:
                saved.append((module, name, getattr(module, name)))
                setattr(module, name, replacements[name])
        if world.repo_root is not None:
            saved.append((probes, "REPO_ROOT", probes.REPO_ROOT))
            probes.REPO_ROOT = world.repo_root
        yield
    finally:
        for module, name, original in reversed(saved):
            setattr(module, name, original)


# ----------------------------------------------------------------- mutations


@dataclass(frozen=True)
class Mutation:
    """One counterfactual, and the story it tells if the probe survives it."""

    row_id: str
    label: str
    apply: Callable[[World], None]


def _m000_contract_moved(w: World) -> None:
    w.append(CONTRACT_PATH, "\n<!-- a governed clause moved under the ledger -->\n")


def _m003_bare_failure(w: World) -> None:
    w.replace(
        TOOL_MODULE,
        "output=self._release_after_failed_custody(bd, item.id, e),",
        'output=f"custody could not be established: {e}",',
    )


def _m004_renewal_keeps_ticking(w: World) -> None:
    w.replace(
        TOOL_MODULE,
        "held.lost_reason = str(e)\n                    held.stop.set()\n",
        "held.lost_reason = str(e)\n",
    )


def _m005_reassurance_returns(w: World) -> None:
    w.append(
        CLAIM_SKILL,
        "\nUnder normal operation you do not need to do anything to keep it fresh.\n",
    )


def _m008_clock_releases_it(w: World) -> None:
    w.append(
        AWARENESS,
        "\nAn unrenewed 15-minute hold releases the item back to the queue.\n",
    )


def _m009_fence_regated_on_status(w: World) -> None:
    w.replace(
        ADAPTER,
        "elif cust_holder == who and current.holder != who:",
        'elif cust_holder == who and current.status == "held":',
    )


def _m011_generation_fence_dropped(w: World) -> None:
    w.replace(
        ADAPTER,
        'if current.get("holder") != holder or int(current.get("generation", -1)) != generation:',
        'if current.get("holder") != holder:',
    )


def _m012_outcome_from_exit_code(w: World) -> None:
    w.replace(
        ADAPTER,
        'return ReleaseOutcome(item_id=item_id, already_closed=(seen[-1].status == "resolved"))',
        "return ReleaseOutcome(item_id=item_id, already_closed=False)",
    )


def _m013_claim_returns_writer_stdout(w: World) -> None:
    w.replace(
        ADAPTER,
        'self._verified_write(_do_claim, _verify, what=f"claim {item_id} as {actor!r}")\n'
        "        return self.get(item_id)",
        'self._verified_write(_do_claim, _verify, what=f"claim {item_id} as {actor!r}")\n'
        "        return Item.from_beads(p.stdout)",
    )


def _m015_success_path_unverified(w: World) -> None:
    w.replace(ADAPTER, "if not verify():", "if False:  # trust the exit code")


def _m016_transaction_guarantee_returns(w: World) -> None:
    w.append(
        AWARENESS,
        "\nBy dolt's own transaction semantics the write genuinely did not happen.\n",
    )


def _m017_single_hold_check_removed(w: World) -> None:
    w.replace(
        TOOL_MODULE,
        "if self._held is not None:",
        "if False:  # single-hold refusal removed",
    )


def _m021_make_test_drops_the_ledger(w: World) -> None:
    w.replace(MAKEFILE, "$(PYTEST) tests ledger/checks -v", "$(PYTEST) tests -v")


def _m022_ci_drops_the_editable_install(w: World) -> None:
    w.replace(CI_WORKFLOW, '-e "modules/tool-work-tracker[dev]"', '-e "."')


def _m023_named_fixture_now_exists(w: World) -> None:
    root = w.fake_root()
    (root / "tests" / "test_single_hold.py").write_text(
        "def test_a_second_claim_is_refused() -> None: ...\n", encoding="utf-8"
    )


def _m023_single_hold_fixture_now_exists(w: World) -> None:
    root = w.fake_root()
    (root / "modules" / "tool-work-tracker" / "tests" / "test_holds.py").write_text(
        'def test_refusal() -> None:\n    assert "already holding" in out\n', encoding="utf-8"
    )


def _m023_contract_pointer_corrected(w: World) -> None:
    w.replace(
        CONTRACT_PATH,
        "**Test location:** `tests/test_single_hold.py` (to be added).",
        "**Test location:** `tests/integration/test_single_hold.py`.",
    )


#: One entry per counterfactual. Rows with several separable halves get one
#: mutation per half, so a probe that would notice only ONE of them is caught
#: rather than credited for the whole row.
MUTATIONS: tuple[Mutation, ...] = (
    Mutation("CCV1-000", "the governed contract moved under the pinned hash", _m000_contract_moved),
    Mutation(
        "CCV1-003",
        "the failed-custody arm returns a bare failure again (no compensating release)",
        _m003_bare_failure,
    ),
    Mutation(
        "CCV1-004",
        "a failed renewal no longer stops the loop (retry returns)",
        _m004_renewal_keeps_ticking,
    ),
    Mutation(
        "CCV1-005",
        "the custody-keeps-itself-fresh reassurance returns to the skill",
        _m005_reassurance_returns,
    ),
    Mutation(
        "CCV1-008",
        "awareness.md states the TTL release as automatic again",
        _m008_clock_releases_it,
    ),
    Mutation(
        "CCV1-009",
        "the close fence is re-gated on item status (the original post-reclaim gap)",
        _m009_fence_regated_on_status,
    ),
    Mutation(
        "CCV1-011",
        "renewal fences on holder only -- a zombie's generation matches again",
        _m011_generation_fence_dropped,
    ),
    Mutation(
        "CCV1-012",
        "release reports its outcome from the exit code, not the read-back",
        _m012_outcome_from_exit_code,
    ),
    Mutation(
        "CCV1-013",
        "claim_item returns an Item parsed from the writing process's own stdout",
        _m013_claim_returns_writer_stdout,
    ),
    Mutation(
        "CCV1-015",
        "_verified_write stops verifying the SUCCESS path",
        _m015_success_path_unverified,
    ),
    Mutation(
        "CCV1-016",
        "the transaction-was-aborted guarantee Incident B disproved returns to the prose",
        _m016_transaction_guarantee_returns,
    ),
    Mutation(
        "CCV1-017",
        "the single-hold refusal is removed from the tool seam",
        _m017_single_hold_check_removed,
    ),
    Mutation(
        "CCV1-021", "`make test` stops collecting ledger/checks", _m021_make_test_drops_the_ledger
    ),
    Mutation(
        "CCV1-022",
        "CI stops installing the tool module editable (suite runs in nothing again)",
        _m022_ci_drops_the_editable_install,
    ),
    Mutation(
        "CCV1-023",
        "FIXED: the contract's named fixture file tests/test_single_hold.py now exists",
        _m023_named_fixture_now_exists,
    ),
    Mutation(
        "CCV1-023",
        "FIXED: a single-hold fixture now exists in the tool module suite",
        _m023_single_hold_fixture_now_exists,
    ),
    Mutation(
        "CCV1-023",
        "FIXED: the contract's Fixture 4 location line points at a real path",
        _m023_contract_pointer_corrected,
    ),
)


# ------------------------------------------------------------------- running


@dataclass(frozen=True)
class Result:
    row_id: str
    probe: str
    disposition: str
    direction: str
    pinning: bool
    label: str
    proven: bool
    reason: str = ""


def _probe_for(row_id: str) -> str:
    return f"test_row_{row_id.lower().replace('-', '_')}"


def declared_row_ids() -> frozenset[str]:
    return frozenset(m.row_id for m in MUTATIONS)


def declared_probe_names() -> frozenset[str]:
    return frozenset(_probe_for(rid) for rid in declared_row_ids())


def _probe_rows() -> list[dict]:
    return [r for r in rows() if r["assertion"]["kind"] in {"probe", "absence"}]


def run_all() -> list[Result]:
    """Every declared mutation, plus an explicit UNPROVEN row for any probe
    nobody declared one for. The denominator is the full probe population --
    never quietly narrowed to the ones that happen to be covered.
    """
    by_row = {r["id"]: r for r in _probe_rows()}
    results: list[Result] = []

    for mutation in MUTATIONS:
        row = by_row.get(mutation.row_id)
        if row is None:
            results.append(
                Result(
                    mutation.row_id,
                    _probe_for(mutation.row_id),
                    "?",
                    "?",
                    False,
                    mutation.label,
                    False,
                    "no ledger row with this id (harness out of date)",
                )
            )
            continue
        probe = getattr(probes, row["assertion"]["ref"])
        world = World()
        proven, reason = False, ""
        try:
            mutation.apply(world)
            with applied(world):
                try:
                    probe()
                except AssertionError:
                    proven = True
                else:
                    reason = (
                        "probe still PASSED under the counterfactual -- it does not discriminate"
                    )
        except HarnessOutOfDate as exc:
            reason = f"mutation could not be applied: {exc}"
        except Exception as exc:  # noqa: BLE001 -- reported, never swallowed
            reason = f"{type(exc).__name__} while mutating: {exc}"
        finally:
            world.close()
        results.append(
            Result(
                row["id"],
                row["assertion"]["ref"],
                row["disposition"],
                expected_flip_direction(row),
                is_pinning(row),
                mutation.label,
                proven,
                reason,
            )
        )

    for row in _probe_rows():
        if row["id"] in declared_row_ids():
            continue
        results.append(
            Result(
                row["id"],
                row["assertion"]["ref"],
                row["disposition"],
                expected_flip_direction(row),
                is_pinning(row),
                "(none declared)",
                False,
                "no mutation declared for this probe -- its discriminating power is unproven",
            )
        )
    return results


def _render(results: list[Result]) -> tuple[str, int]:
    lines: list[str] = []
    add = lines.append
    add("LEDGER MUTATION HARNESS -- discriminating-power evidence")
    add("Each probe is run against a counterfactual repo and must go RED.")
    add("Injection only: no product-code edit, no subprocess, nothing written to the repo.")
    add("")

    groups = (
        (
            "PINNING PROBES  (row is red; probe pins the CURRENT non-conformant shape;",
            "                 counterfactual = the FIXED behaviour)",
            [r for r in results if r.pinning],
        ),
        (
            "CONFORMANCE PROBES  (row is green; probe asserts the invariant;",
            "                     counterfactual = the known-wrong shape it forbids)",
            [r for r in results if not r.pinning],
        ),
    )
    for head, sub, group in groups:
        add(head)
        add(sub)
        if not group:
            add("  (none)")
        for r in sorted(group, key=lambda r: (r.row_id, r.label)):
            mark = "PROVEN " if r.proven else "UNPROVEN"
            add(f"  [{mark}] {r.row_id}  {r.direction}  ({r.disposition})")
            add(f"             {r.probe} :: {r.label}")
            if not r.proven:
                add(f"             REASON: {r.reason}")
        add("")

    pin = [r for r in results if r.pinning]
    con = [r for r in results if not r.pinning]
    pin_ok = [r for r in pin if r.proven]
    con_ok = [r for r in con if r.proven]
    pin_rows = {r.row_id for r in pin}
    pin_rows_ok = {r.row_id for r in pin if r.proven}

    add("DENOMINATOR (this is the record)")
    add(f"  pinning mutations       proven {len(pin_ok)} / {len(pin)}")
    add(f"  pinning probes covered  proven {len(pin_rows_ok)} / {len(pin_rows)}")
    add(f"  conformance mutations   proven {len(con_ok)} / {len(con)}")
    add(f"  ALL mutations           proven {len(pin_ok) + len(con_ok)} / {len(results)}")
    add("")

    unproven = [r for r in results if not r.proven]
    add("UNPROVEN, named with reason")
    if not unproven:
        add("  (none)")
    for r in unproven:
        add(f"  {r.row_id} :: {r.label}")
        add(f"    {r.reason}")
    add("")
    add(f"Flip direction for every pinning probe above: {FLIP_VIOLATION_MOVEMENT}.")
    add("A pinning probe going red means the behaviour moved TOWARD the contract:")
    add("update the row to CONFORMS and retarget the probe in the SAME change.")

    # Exit non-zero on any unproven mutation. A harness that reports a hole and
    # still exits 0 is a harness nobody's CI will ever notice going hollow.
    return "\n".join(lines), (1 if unproven else 0)


def main() -> int:
    report, code = _render(run_all())
    print(report)
    return code


if __name__ == "__main__":
    sys.exit(main())
