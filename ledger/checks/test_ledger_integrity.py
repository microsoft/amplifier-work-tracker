"""Ledger integrity + coverage tripwires -- run with the ledger, every time.

These are `LEDGER-FORMAT.md` sec.6's three tripwires plus the structural
invariants of sec.2-4:

  1. every Core clause of every governed contract is cited by >= 1 row
  2. every row's quote verifies against ITS OWN contract's actual bytes
  3. every assertion ref resolves, and every GAP/VIOLATION row carries a
     live work ref

plus two this repo added, because a probe nobody has ever seen FAIL might be
asserting nothing:

  4. every probe has a declared mutation
  5. the mutation harness is RUN here, and every mutation flips its probe red

They exist because the expensive failure is not a red row -- it is a ledger
that has quietly stopped describing the contract it claims to describe.

## Two families, one file

`rows.yaml` carries two row families against two contracts (`CCV1-###` for
custody-coordination.v1, `OSV1-###` for operator-surface.v1). Every tripwire
below resolves per-family through `_support.FAMILIES` rather than against a
single hardcoded contract -- so a row can never be checked against the wrong
contract's bytes, and a family cannot be added without the tripwires reaching
it.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from ._support import (
    ASSERTION_KINDS,
    DISPOSITIONS,
    FAMILIES,
    REPO_ROOT,
    collapse,
    family_of,
    function_names,
    read_collapsed,
    required_clause_ids,
    rows,
)
from ._support import (
    clause_ids as contract_clause_ids,
)


def _probe_module_path(module: str) -> Path:
    return Path(__file__).with_name(f"{module}.py")


def probe_names() -> dict[str, str]:
    """Every `test_row_*` probe in every family's module -> its module name.

    Collected across families so the probe<->row pairing is checked over the
    WHOLE probe population; a per-family check would let a probe in the wrong
    module pass both halves.
    """
    found: dict[str, str] = {}
    for fam in FAMILIES:
        for name in function_names(_probe_module_path(fam.probe_module)):
            if name.startswith("test_row_"):
                assert name not in found, (
                    f"probe {name!r} is defined in BOTH {found[name]} and "
                    f"{fam.probe_module}. A duplicated probe name means one row's "
                    f"assertion silently shadows another's."
                )
                found[name] = fam.probe_module
    return found


def test_rows_parse_as_a_top_level_list_with_each_family_sync_row_first() -> None:
    data = rows()
    assert isinstance(data, list) and data, "rows.yaml must be a non-empty top-level list"
    for fam in FAMILIES:
        fam_rows = [r for r in data if r["id"].startswith(f"{fam.prefix}-")]
        assert fam_rows, f"no rows for declared family {fam.prefix}"
        first = fam_rows[0]
        assert first["id"] == f"{fam.prefix}-000", (
            f"{fam.prefix}: the SYNC row is `<PREFIX>-000` and comes first within its "
            f"family (LEDGER-FORMAT.md sec.2/sec.4); observed {first['id']}"
        )
        assert "files" in first["contract"], (
            f"{first['id']}: the SYNC row pins contract file(s) by path + hash"
        )


def test_row_ids_are_well_formed_unique_and_ordered() -> None:
    ids = [r["id"] for r in rows()]
    for row_id in ids:
        fam = family_of(row_id)  # raises, naming the id, if it belongs to no family
        assert len(row_id) == len(fam.prefix) + 4 and row_id[len(fam.prefix) + 1 :].isdigit(), (
            f"malformed row id {row_id!r} (expected {fam.prefix}-NNN)"
        )
    assert len(set(ids)) == len(ids), "row ids are stable forever and never reused"
    assert ids == sorted(ids), "rows are kept in id order for reviewability"


def test_every_row_has_a_legal_disposition_and_its_required_fields() -> None:
    for r in rows():
        rid = r["id"]
        disp = r["disposition"]
        assert disp in DISPOSITIONS, f"{rid}: unknown disposition {disp!r}"
        assert disp != "DIVERGED", (
            f"{rid}: DIVERGED is illegal for a self-governed contract -- if we own the "
            f"contract and disagree with it, the move is an amendment, not a ledgered "
            f"divergence"
        )
        if disp in {"GAP", "VIOLATION"}:
            assert r.get("work"), f"{rid}: a red row without a filed item is a ledger that lies"
        if disp in {"OPEN-PINNED", "NOT-ASSERTABLE"}:
            assert r.get("justification"), f"{rid}: {disp} requires a justification"


def test_every_row_quote_verifies_against_its_own_contract_bytes() -> None:
    """Tripwire 2, resolved per family -- a row is verified against the contract
    it names, never against whichever contract happens to be first.
    """
    for r in rows():
        rid = r["id"]
        if rid.endswith("-000"):
            continue  # the SYNC row anchors on hashes, not a quote
        fam = family_of(rid)
        c = r["contract"]
        assert c["file"] == fam.contract_rel, (
            f"{rid}: family {fam.prefix} governs {fam.contract_rel}, but this row cites "
            f"{c['file']}. A row quoting one contract while filed under another's family "
            f"is verified against the wrong bytes."
        )
        assert "quote" in c, f"{rid}: the quote must live nested under `contract:`"
        quote = collapse(c["quote"])
        assert quote in read_collapsed(fam.contract), (
            f"{rid}: quote does not verify against {c['file']}\n  quote: {quote[:120]}..."
        )


def test_every_clause_id_is_a_bare_identifier_the_contract_actually_names() -> None:
    for r in rows():
        rid = r["id"]
        if rid.endswith("-000"):
            continue
        fam = family_of(rid)
        clause = r["contract"]["clause"]
        legal = contract_clause_ids(fam.contract) | fam.unnumbered
        assert clause in legal, (
            f"{rid}: clause {clause!r} is not a clause {fam.contract_rel} names "
            f"(and clause ids are never paraphrased or parenthetical-decorated)"
        )


def test_every_core_clause_of_every_contract_is_cited_by_at_least_one_row() -> None:
    """Tripwire 1: coverage. A clause nobody ledgered is a clause nobody is
    watching -- and with two contracts, a clause of the NEWER one is exactly
    what a single-contract tripwire would have missed.
    """
    for fam in FAMILIES:
        cited = {
            r["contract"]["clause"]
            for r in rows()
            if r["id"].startswith(f"{fam.prefix}-") and not r["id"].endswith("-000")
        }
        missing = required_clause_ids(fam.contract) - cited
        assert not missing, f"{fam.contract_rel}: clauses with no ledger row: {sorted(missing)}"


def test_every_assertion_ref_resolves() -> None:
    """Tripwire 3a: an assertion that cannot be found is not an assertion."""
    known_probes = probe_names()
    for r in rows():
        a = r["assertion"]
        kind = a["kind"]
        assert kind in ASSERTION_KINDS, f"{r['id']}: unknown assertion kind {kind!r}"
        if kind == "none":
            assert r["disposition"] == "NOT-ASSERTABLE", (
                f"{r['id']}: `kind: none` is legal only for NOT-ASSERTABLE"
            )
            continue
        if kind in {"probe", "absence"}:
            ref = a["ref"]
            assert ref in known_probes, f"{r['id']}: probe {ref!r} not found"
            fam = family_of(r["id"])
            assert known_probes[ref] == fam.probe_module, (
                f"{r['id']}: probe {ref!r} lives in {known_probes[ref]}, but family "
                f"{fam.prefix} owns {fam.probe_module}. A row's probe must live in its "
                f"own family's module, or the mutation harness patches the wrong one."
            )
            continue
        for cite in a["refs"]:  # indexed
            path = REPO_ROOT / cite["file"]
            assert path.exists(), f"{r['id']}: cited test file {cite['file']} does not exist"
            assert cite["name"] in function_names(path), (
                f"{r['id']}: cited test {cite['name']}  not found in {cite['file']}"
            )


def test_every_probe_belongs_to_a_row() -> None:
    """Tripwire 3b, the other direction: a probe with no row is a check whose
    meaning nobody wrote down.
    """
    declared = {
        r["assertion"]["ref"] for r in rows() if r["assertion"]["kind"] in {"probe", "absence"}
    }
    found = set(probe_names())
    assert found == declared, (
        f"probe/row mismatch\n  probes with no row: {sorted(found - declared)}\n"
        f"  rows with no probe: {sorted(declared - found)}"
    )


def test_every_probe_module_declared_by_a_family_exists_and_is_importable() -> None:
    """A family whose probe module is missing would make every other tripwire
    quietly weaker (an empty probe set trivially satisfies set equality on one
    side), so it is asserted directly rather than inferred.
    """
    for fam in FAMILIES:
        path = _probe_module_path(fam.probe_module)
        assert path.exists(), f"{fam.prefix}: probe module {path.name} does not exist"
        module = importlib.import_module(f".{fam.probe_module}", package=__package__)
        probes_here = [n for n in dir(module) if n.startswith("test_row_")]
        assert probes_here, f"{fam.prefix}: {path.name} declares no probes"


def test_every_probe_has_a_declared_mutation() -> None:
    """Tripwire 4: discriminating power. A probe nobody has ever observed to
    FAIL is a probe that might assert nothing -- `test-ledger` proves the
    probes pass, and cannot prove any of them would notice a change.
    `mutation_harness.py` supplies the missing half; this asserts it covers
    the whole probe population rather than a convenient subset.
    """
    from .mutation_harness import declared_probe_names

    declared = declared_probe_names()
    found = set(probe_names())
    assert found == declared, (
        f"mutation-harness coverage gap\n  probes with no mutation: {sorted(found - declared)}\n"
        f"  mutations with no probe: {sorted(declared - found)}"
    )


def test_the_mutation_harness_runs_and_every_mutation_flips_its_probe_red() -> None:
    """Tripwire 5: the harness is RUN here, not merely present. An unproven
    mutation means either the probe stopped discriminating or the source it
    anchors on moved -- both make the ledger claim more than it can show.
    """
    from .mutation_harness import run_all

    results = run_all()
    assert results, "the mutation harness declared nothing"
    unproven = [f"{r.row_id} :: {r.label} -- {r.reason}" for r in results if not r.proven]
    assert not unproven, (
        "mutation harness has unproven mutations (run `make ledger-mutate` for the "
        "full report):\n  " + "\n  ".join(unproven)
    )
    pinning = [r for r in results if r.pinning]
    assert all(r.direction == "VIOLATION-MOVEMENT" for r in pinning), (
        "every pinning probe's flip direction must be the locally-defined "
        "VIOLATION-MOVEMENT (reconcile-report.md sec.11)"
    )


def test_indexed_cites_are_reserved_for_measured_rows() -> None:
    """An `indexed` cite proves a test EXISTS, never that it still asserts the
    claim. Every indexed row must therefore record when its cited tests were
    last actually run -- an unrun cite is a self-report, and a self-report is
    not proof.
    """
    for r in rows():
        if r["assertion"]["kind"] == "indexed":
            assert r["assertion"].get("last_measured"), (
                f"{r['id']}: an indexed row must record `last_measured` (the date its "
                f"cited tests were actually executed and observed passing)"
            )
