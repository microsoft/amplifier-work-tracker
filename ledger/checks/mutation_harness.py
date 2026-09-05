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
from . import test_operator_rows as op_probes
from ._support import (
    ADAPTER,
    AWARENESS,
    CHARTSVG,
    CI_WORKFLOW,
    CLAIM_SKILL,
    CONTRACT_PATH,
    FLIP_VIOLATION_MOVEMENT,
    MAKEFILE,
    OPERATOR_CONTRACT_PATH,
    PYPROJECT,
    ROWS_PATH,
    TOOL_MODULE,
    WEBAPP,
    WEBBROWSE,
    WEBPWA,
    WEBTHEME,
    WEBTRUST,
    WIDGETS,
    collapse,
    expected_flip_direction,
    is_pinning,
    rows,
)

CLI = probes.CLI

#: Every module that owns `test_row_*` probes. Readers are patched in ALL of
#: them, so a mutation is seen the same way whichever family's probe runs --
#: the alternative (patching only the family under test) would let a probe that
#: happens to read through a sibling module silently see UNMUTATED source.
PROBE_MODULES = (probes, op_probes)


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

    def touch(self, rel: str) -> Path:
        """Make a repo-relative path EXIST in the throwaway root.

        The counterfactual most of the operator family's GAP rows need: those
        probes pin the ABSENCE of a conformance-kit file, so the fixed world is
        simply one where the file is there. Deliberately writes a stub with no
        assertions in it -- the point is that a probe pinning "this path does
        not exist" must go red the instant it does, BEFORE anyone has proved
        the kit inside it discriminates.
        """
        path = self.fake_root() / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# stub created by the ledger mutation harness\n", encoding="utf-8")
        return path

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
        targets: list[tuple[object, tuple[str, ...]]] = [(_support, _PATCHED_IN_SUPPORT)]
        targets += [(m, _PATCHED_IN_PROBES) for m in PROBE_MODULES]
        for module, names in targets:
            for name in names:
                if not hasattr(module, name):
                    continue  # a probe module need not import every reader
                saved.append((module, name, getattr(module, name)))
                setattr(module, name, replacements[name])
        if world.repo_root is not None:
            for module in PROBE_MODULES:
                if hasattr(module, "REPO_ROOT"):
                    saved.append((module, "REPO_ROOT", module.REPO_ROOT))
                    module.REPO_ROOT = world.repo_root
        # `rows()` memoises the PARSED ledger, so a mutation of rows.yaml would
        # otherwise be invisible to the one probe that reads the ledger itself
        # (OSV1-031). Cleared on the way in AND on the way out, so the mutated
        # parse can never leak into a later probe.
        _support.rows.cache_clear()
        yield
    finally:
        for module, name, original in reversed(saved):
            setattr(module, name, original)
        _support.rows.cache_clear()


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


def _m023_test_location_regresses(w: World) -> None:
    """REGRESSION (2026-09-03 amendment retargeted this row's probe from a
    pin to a genuine conformance check -- see the three retired `_m023_*`
    mutations this replaced, git-blame). The contract's corrected Fixture 1
    Test-location line reverts to the stale, never-existed path -- exactly
    the drift CCV1-023's part 5 now forbids rather than records.
    """
    w.replace(
        CONTRACT_PATH,
        "**Test location:** `tests/integration/test_phantom_conflict_recovery.py`.",
        "**Test location:** `tests/test_incident_b.py` (to be added).",
    )


# =============================================================================
# OSV1 -- contracts/operator-surface.v1.md
#
# Twenty of that family's rows are red, so most counterfactuals below are the
# FIXED world (direction VIOLATION-MOVEMENT): the probe pins the current wrong
# shape and must go red the moment the shape is right. The seven green rows get
# the known-wrong shape they forbid instead (direction REGRESSION).
#
# Eleven rows pin the absence of a conformance-kit file, and their
# counterfactual is `world.touch(...)` -- the file simply existing. That is a
# WEAKER mutation than the source-shape ones, deliberately and visibly: the
# thing being proven is only that the pin notices the path appearing, which is
# exactly what those rows claim and no more. Four of them carry a SECOND
# mutation against their substantive half, so the weak half is never the only
# evidence.
# =============================================================================

TIER_A_KIT = op_probes.TIER_A_KIT
TIER_B_KIT = op_probes.TIER_B_KIT


def _mo000_operator_contract_moved(w: World) -> None:
    w.append(OPERATOR_CONTRACT_PATH, "\n<!-- a governed clause moved under the ledger -->\n")


def _mo001_hero_gains_the_missing_count(w: World) -> None:
    """FIXED: the needs-attention count Core 1 names joins the strip."""
    w.replace(
        WEBAPP,
        'WD.KpiCard(key="ready", label="Ready", value=ready_total, href="#fleet"),',
        'WD.KpiCard(key="attention", label="Needs attention", value=0, href="#x"),\n'
        "                    "
        'WD.KpiCard(key="ready", label="Ready", value=ready_total, href="#fleet"),',
    )


def _mo002_alias_becomes_a_bespoke_hue(w: World) -> None:
    """REGRESSION: `--amber` stops resolving into the set and becomes a fourth hue."""
    w.replace(WEBTHEME, "--amber:var(--alarm);", "--amber:#D9A253;")


def _mo003_retired_palette_removed(w: World) -> None:
    """FIXED: the specimen a calm pixel sweep would catch is tokenised."""
    w.replace(
        WEBPWA,
        "background:#0D0D0C;color:#F2EEE6;",
        "background:var(--color-ground);color:var(--ink-primary);",
    )


def _mo004_a_status_loses_its_word(w: World) -> None:
    """REGRESSION-shaped: a chip carries only its class. This is the defect Core
    3 forbids, and the row is GAP only because no RENDERED check exists -- the
    vocabulary itself must still be watched.
    """
    w.replace(WEBBROWSE, '"open": "READY",', '"open": "",')


def _mo005_the_worst_literal_site_is_migrated(w: World) -> None:
    """FIXED (partially): the retired-palette inline body is tokenised, so the
    census drops from 66 to 65 and the named specimen leaves the bucket.

    BOTH halves of that one site must go: it carries a literal COLOUR pair AND
    a literal `font:16px`/`padding:32px`. Replacing only the palette left the
    site in the LITERAL bucket and the count unchanged at 66 -- the harness
    caught that as a non-discriminating mutation, which is what it is for.
    """
    w.replace(
        WEBPWA,
        "background:#0D0D0C;color:#F2EEE6;",
        "background:var(--color-ground);color:var(--ink-primary);",
    )
    w.replace(WEBPWA, "font:16px -apple-system,sans-serif;padding:32px;", "")


def _mo005b_the_page_local_palette_goes(w: World) -> None:
    """FIXED (the OTHER half): webtrust.py's page-local `<style>` block stops
    declaring its own retired palette -- the eight literal colour declarations
    at webtrust.py:258-259 go, as they would if the module imported the token
    CSS instead of copying it.

    This is the half Core 4's frozen text could not reach until the 2026-09-04
    DRAFT true-up widened it, so it gets its OWN mutation: `_mo005_...` proves
    the INLINE bucket discriminates and says nothing about a `<style>` block.
    """
    w.replace(
        WEBTRUST,
        "  --ground:#0D0D0C; --raise:#151513; --ink:#F2EEE6; --mid:#A6A199;\n"
        "  --quiet:#9C978F; --amber:#D9A253; --rule:#1F1F1D; --rule-hi:#333330;\n",
        "",
    )


_UNREGISTERED_SITE = "\n_LEDGER_MUTATION = f'<div style=\"height:{0}px\"></div>'\n"


def _mo006_an_unregistered_computed_site_appears(w: World) -> None:
    """REGRESSION: a new inline computed-geometry site that nobody registered.
    This is the direction that matters -- the register may shrink freely.
    """
    w.append(WIDGETS, _UNREGISTERED_SITE)


def _mo007_a_get_handler_reaches_a_write(w: World) -> None:
    """REGRESSION: the L1 GET view acquires a mutating adapter call."""
    # Re-anchored 2026-09-04: this used to hang off the L1 view's `limit=0`
    # call, which OSV1-015's fix (work_item_pipeline-8vv) removed. The anchor
    # is incidental to what this mutation proves -- it needs ANY line inside
    # the L1 GET handler to hang a write off -- so it moved to the bounded
    # call that replaced it rather than the row being re-derived.
    w.replace(
        WEBBROWSE,
        "query_capped = len(fetched) > _L1_ITEM_QUERY_LIMIT",
        "query_capped = len(fetched) > _L1_ITEM_QUERY_LIMIT\n            bd.update(name)",
    )


def _mo008_swap_restores_the_pause_flag(w: World) -> None:
    """FIXED: `restoreState` starts touching the pause control."""
    w.replace(
        WEBTHEME,
        "window.scrollTo(0, state.scrollY);",
        "window.scrollTo(0, state.scrollY);\n    window.__wtRefreshPaused;",
    )


def _mo009_the_below_floor_token_stops_painting_copy(w: World) -> None:
    """FIXED: the empty-state caption moves off the below-floor token."""
    w.replace(
        CHARTSVG,
        'style="fill:var(--ink-quiet)">',
        'style="fill:var(--ink-tertiary)">',
    )


def _mo010_a_browser_driver_appears(w: World) -> None:
    """FIXED: something in the repo starts driving a browser."""
    w.append(PYPROJECT, '\n# test-only: "playwright>=1.40"\n')


def _mo011_a_second_motion_block_appears(w: World) -> None:
    """REGRESSION: reduced motion becomes per-widget opt-in."""
    w.append(
        WEBTHEME,
        "\n_LEDGER_MUTATION_CSS = '@media (prefers-reduced-motion: reduce)"
        "{ .widget{animation:none} }'\n",
    )


def _mo012_the_empty_sentence_becomes_a_zero(w: World) -> None:
    """REGRESSION: the calm queue is celebrated as a numeral instead of said."""
    w.replace(WEBAPP, "Nothing is waiting to be claimed in this queue right now.", "0")


def _mo013_a_template_engine_is_declared(w: World) -> None:
    """REGRESSION: the manifest acquires a template engine."""
    w.replace(PYPROJECT, '"pyyaml>=6.0",', '"pyyaml>=6.0",\n    "jinja2>=3.1",')


def _mo014_a_chart_library_is_declared(w: World) -> None:
    """REGRESSION: the manifest acquires a charting library."""
    w.replace(PYPROJECT, '"itsdangerous>=2.1",', '"itsdangerous>=2.1",\n    "plotly>=5.20",')


def _mo015_the_bounded_query_goes_unbounded_again(w: World) -> None:
    """REGRESSION: the L1 view goes back to asking for everything -- literally
    the shape this row closed (`limit=0` is bd's own "unlimited").
    """
    w.replace(WEBBROWSE, "limit=_L1_ITEM_QUERY_LIMIT + 1,", "limit=0,")


def _mo016_the_theme_stops_persisting(w: World) -> None:
    """REGRESSION: the chosen theme goes back to dying on refresh -- the setter
    applies it and remembers nothing, exactly as before dg3.
    """
    w.replace(WEBAPP, "  try{ localStorage.setItem(WT_THEME_KEY, t); }catch(e){}\n", "")


def _mo016_the_first_paint_resolver_moves_out_of_head(w: World) -> None:
    """REGRESSION, the OTHER half: the choice is still stored, but nothing
    reads it before the body paints -- persistence written and never applied
    is not persistence.
    """
    w.replace(WEBTHEME, '        f"<script>{theme_boot_js()}</script>"\n', "")


def _mo017_a_second_push_call_site_appears(w: World) -> None:
    """REGRESSION: the push channel acquires a second event class (Backlogged 5
    without the owner ratifying it).
    """
    w.append(WEBAPP, "\ndef _ledger_mutation():\n    WP.fire_reclaim_alarm(1, 2, 3)\n")


def _mo_tier_a_kit_appears(w: World) -> None:
    w.touch(TIER_A_KIT)


def _mo_tier_b_kit_appears(w: World) -> None:
    w.touch(TIER_B_KIT)


def _mo022_the_swap_mechanism_changes(w: World) -> None:
    """The substantive half of Conformance 3's pin: the whole-body innerHTML
    replacement IS the mechanism the bad fixture describes.
    """
    w.replace(
        WEBTHEME,
        "document.body.innerHTML = doc.body.innerHTML;",
        "document.body.replaceChildren(...doc.body.children);",
    )


def _mo023_a_swept_breakpoint_disappears(w: World) -> None:
    """The substantive half of Conformance 4's pin: a viewport the stylesheet
    no longer knows about is a different test.

    Targets 1280px specifically because it is the only one of the three swept
    widths declared exactly once -- 430px appears in two separate `@media`
    blocks, so moving one would leave the probe's containment check satisfied
    and prove nothing.
    """
    w.replace(WEBTHEME, "@media (max-width:1280px){", "@media (max-width:1281px){")


def _mo027_the_makefile_wires_the_kit(w: World) -> None:
    """The wiring half of Freeze 1: existing is not the same as running."""
    w.append(MAKEFILE, "\ntest-conformance:\n\t$(PYTEST) tests/conformance -v\n")


def _mo029_an_artifact_directory_appears(w: World) -> None:
    """The substantive half of Freeze 3: artifacts start being emitted."""
    w.touch("tests/conformance/operator_surface/browser/artifacts/.keep")


def _mo031_a_red_core_row_goes_green(w: World) -> None:
    """FIXED: one of the ten red Core-carrying rows flips, so the gate's tally
    moves. Reaches the ledger through the patched reader plus the cache clear
    `applied()` performs -- `rows()` memoises the parse.
    """
    w.replace(
        ROWS_PATH,
        "  disposition: VIOLATION\n  work: work_item_pipeline-ujy",
        "  disposition: CONFORMS\n  work: work_item_pipeline-ujy",
    )


def _mo032_the_register_grows(w: World) -> None:
    """Freeze 6's enumerated half moves. NOTE, honestly: the OTHER half (zero
    literal sites remaining) is not simulable in memory -- it would mean
    rewriting 66 real sites -- so this mutation proves the enumerated half
    only. OSV1-005's own mutation is what proves the LITERAL bucket
    discriminates.
    """
    w.append(WIDGETS, _UNREGISTERED_SITE)


def _mo033_the_emphasis_comes_back(w: World) -> None:
    """REGRESSION (2026-09-04 true-up #1 retargeted this row's probe from a pin
    to a genuine conformance check -- the seed pin `_mo033_the_contract_quote_
    is_corrected` it replaced asserted the OPPOSITE direction, git-blame).

    The corrected Changelog quotation re-acquires the markdown emphasis that
    broke Freeze 7 at seed: markup is part of the exact match, so an emphasised
    quote stops being a substring of the plain source sentence it cites.
    """
    w.replace(
        OPERATOR_CONTRACT_PATH,
        "unclaimed item, never a count",
        "unclaimed item, **never a count**",
    )


def _mo034_the_changelog_records_a_look(w: World) -> None:
    """FIXED: a Changelog entry records the owner's rendered-page look."""
    w.append(
        OPERATOR_CONTRACT_PATH,
        "\n- **2026-09-05 — owner looked at the rendered L0, L1 and L2 at 430, 900 and "
        "1280px in both themes.**\n",
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
        "the contract's corrected Fixture 1 Test-location line regresses to the stale path",
        _m023_test_location_regresses,
    ),
    # ------------------------------------------------------------------ OSV1
    Mutation(
        "OSV1-000",
        "a governed contract moved under the pinned hash",
        _mo000_operator_contract_moved,
    ),
    Mutation(
        "OSV1-001",
        "the missing needs-attention count joins the L0 strip",
        _mo001_hero_gains_the_missing_count,
    ),
    Mutation(
        "OSV1-002",
        "the --amber alias acquires its own literal value (a bespoke fourth status hue)",
        _mo002_alias_becomes_a_bespoke_hue,
    ),
    Mutation(
        "OSV1-003",
        "the retired palette a calm sweep would catch is tokenised away",
        _mo003_retired_palette_removed,
    ),
    Mutation(
        "OSV1-004",
        "a status chip loses its word and carries only a class",
        _mo004_a_status_loses_its_word,
    ),
    Mutation(
        "OSV1-005",
        "the worst literal INLINE site is migrated (census 66 -> 65)",
        _mo005_the_worst_literal_site_is_migrated,
    ),
    Mutation(
        "OSV1-005",
        "webtrust.py's page-local `<style>` block stops declaring its own retired "
        "palette (block census 40 -> 32) -- the half Core 4 could not reach before "
        "the 2026-09-04 true-up",
        _mo005b_the_page_local_palette_goes,
    ),
    Mutation(
        "OSV1-006",
        "an inline computed-geometry site appears that nobody registered",
        _mo006_an_unregistered_computed_site_appears,
    ),
    Mutation(
        "OSV1-007",
        "the L1 GET view acquires a mutating adapter call",
        _mo007_a_get_handler_reaches_a_write,
    ),
    Mutation(
        "OSV1-008",
        "the body-swap starts restoring the pause flag",
        _mo008_swap_restores_the_pause_flag,
    ),
    Mutation(
        "OSV1-009",
        "the below-floor token stops painting the empty-state caption",
        _mo009_the_below_floor_token_stops_painting_copy,
    ),
    Mutation("OSV1-010", "a browser driver appears in the repo", _mo010_a_browser_driver_appears),
    Mutation(
        "OSV1-011",
        "reduced motion becomes per-widget opt-in (a second @media block)",
        _mo011_a_second_motion_block_appears,
    ),
    Mutation(
        "OSV1-012",
        "the calm queue's empty sentence becomes a bare zero",
        _mo012_the_empty_sentence_becomes_a_zero,
    ),
    Mutation(
        "OSV1-013", "the manifest declares a template engine", _mo013_a_template_engine_is_declared
    ),
    Mutation(
        "OSV1-014", "the manifest declares a charting library", _mo014_a_chart_library_is_declared
    ),
    Mutation(
        "OSV1-015",
        "the L1 view's bounded query goes unbounded again",
        _mo015_the_bounded_query_goes_unbounded_again,
    ),
    Mutation(
        "OSV1-016",
        "the theme choice stops surviving a refresh",
        _mo016_the_theme_stops_persisting,
    ),
    Mutation(
        "OSV1-016",
        "the first-paint resolver leaves <head>, so the stored theme is never applied",
        _mo016_the_first_paint_resolver_moves_out_of_head,
    ),
    Mutation(
        "OSV1-017",
        "the push channel acquires a second call site",
        _mo017_a_second_push_call_site_appears,
    ),
    Mutation("OSV1-020", "the Tier-B kit file appears", _mo_tier_b_kit_appears),
    Mutation("OSV1-021", "the Tier-A kit file appears", _mo_tier_a_kit_appears),
    Mutation("OSV1-022", "the Tier-B kit file appears", _mo_tier_b_kit_appears),
    Mutation(
        "OSV1-022",
        "the whole-body innerHTML swap (the bad fixture's own premise) changes shape",
        _mo022_the_swap_mechanism_changes,
    ),
    Mutation("OSV1-023", "the Tier-B kit file appears", _mo_tier_b_kit_appears),
    Mutation(
        "OSV1-023",
        "a swept breakpoint disappears from the stylesheet",
        _mo023_a_swept_breakpoint_disappears,
    ),
    Mutation("OSV1-024", "the Tier-A kit file appears", _mo_tier_a_kit_appears),
    Mutation("OSV1-025", "the Tier-A kit file appears", _mo_tier_a_kit_appears),
    Mutation("OSV1-026", "the Tier-A kit file appears", _mo_tier_a_kit_appears),
    Mutation("OSV1-027", "the Tier-A kit file appears", _mo_tier_a_kit_appears),
    Mutation(
        "OSV1-027",
        "the Makefile wires a conformance target (the 'runs in a gate' half)",
        _mo027_the_makefile_wires_the_kit,
    ),
    Mutation("OSV1-028", "the Tier-B kit file appears", _mo_tier_b_kit_appears),
    Mutation("OSV1-029", "the Tier-B kit file appears", _mo_tier_b_kit_appears),
    Mutation(
        "OSV1-029",
        "a Tier-B artifact directory appears",
        _mo029_an_artifact_directory_appears,
    ),
    Mutation("OSV1-030", "the Tier-A kit file appears", _mo_tier_a_kit_appears),
    Mutation(
        "OSV1-031",
        "one of the ten red Core-carrying rows flips to CONFORMS",
        _mo031_a_red_core_row_goes_green,
    ),
    Mutation(
        "OSV1-032",
        "the exemption register grows (the zero-literal half is not in-memory simulable "
        "-- OSV1-005's mutation is what proves the LITERAL bucket discriminates)",
        _mo032_the_register_grows,
    ),
    Mutation(
        "OSV1-033",
        "the corrected Changelog quotation re-acquires the markdown emphasis that "
        "broke Freeze 7 at seed",
        _mo033_the_emphasis_comes_back,
    ),
    Mutation(
        "OSV1-034",
        "a Changelog entry records the owner's rendered-page look",
        _mo034_the_changelog_records_a_look,
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


def _resolve_probe(ref: str) -> Callable[[], None]:
    """The probe function named `ref`, from whichever family's module owns it.

    Raises rather than returning None: a mutation naming a probe nobody
    defines is a harness that proves less than it claims, and that must be
    loud (`test_ledger_integrity` separately enforces that a probe lives in
    its own family's module).
    """
    found = [getattr(m, ref) for m in PROBE_MODULES if hasattr(m, ref)]
    if len(found) != 1:
        raise HarnessOutOfDate(
            f"probe {ref!r} resolves in {len(found)} probe modules (expected exactly 1) "
            f"across {[m.__name__ for m in PROBE_MODULES]}"
        )
    return found[0]


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
        probe = _resolve_probe(row["assertion"]["ref"])
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
