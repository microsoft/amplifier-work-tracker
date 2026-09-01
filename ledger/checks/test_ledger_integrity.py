"""Ledger integrity + coverage tripwires -- run with the ledger, every time.

These are `LEDGER-FORMAT.md` sec.6's three tripwires plus the structural
invariants of sec.2-4:

  1. every Core clause of the contract is cited by >= 1 row
  2. every row's quote verifies against the contract's actual bytes
  3. every assertion ref resolves, and every GAP/VIOLATION row carries a
     live work ref

They exist because the expensive failure is not a red row -- it is a ledger
that has quietly stopped describing the contract it claims to describe.
"""

from __future__ import annotations

import re
from pathlib import Path

from ._support import (
    ASSERTION_KINDS,
    CONTRACT_PATH,
    DISPOSITIONS,
    REPO_ROOT,
    collapse,
    function_names,
    read,
    read_collapsed,
    rows,
)

PROBE_MODULE = Path(__file__).with_name("test_custody_rows.py")
ROW_ID = re.compile(r"^CCV1-\d{3}$")


def test_rows_parse_as_a_top_level_list_with_the_sync_row_first() -> None:
    data = rows()
    assert isinstance(data, list) and data, "rows.yaml must be a non-empty top-level list"
    first = data[0]
    assert first["id"] == "CCV1-000", "the SYNC row is `<PREFIX>-000` and comes first"
    assert "files" in first["contract"], "the SYNC row pins contract file(s) by path + hash"


def test_row_ids_are_well_formed_unique_and_ordered() -> None:
    ids = [r["id"] for r in rows()]
    for row_id in ids:
        assert ROW_ID.match(row_id), f"malformed row id {row_id!r}"
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


def test_every_row_quote_verifies_against_the_contract_bytes() -> None:
    contract = read_collapsed(CONTRACT_PATH)
    for r in rows():
        if r["id"] == "CCV1-000":
            continue  # the SYNC row anchors on hashes, not a quote
        c = r["contract"]
        assert c["file"] == "contracts/custody-coordination.v1.md"
        assert "quote" in c, f"{r['id']}: the quote must live nested under `contract:`"
        quote = collapse(c["quote"])
        assert quote in contract, (
            f"{r['id']}: quote does not verify against {c['file']}\n  quote: {quote[:120]}..."
        )


def test_every_clause_id_is_a_bare_identifier_the_contract_actually_names() -> None:
    contract = read(CONTRACT_PATH)
    headings = set(re.findall(r"^### ([^\n:]+):", contract, flags=re.MULTILINE))
    # Sections the contract does not number get a section-name clause id --
    # a deliberate, reported deviation from the format's "bare numbered
    # identifier" rule, because the contract itself offers no number there.
    unnumbered = {"Conformance: Checks", "Freeze Bar"}
    for r in rows():
        if r["id"] == "CCV1-000":
            continue
        clause = r["contract"]["clause"]
        assert clause in headings or clause in unnumbered, (
            f"{r['id']}: clause {clause!r} is not a clause the contract names "
            f"(and clause ids are never paraphrased or parenthetical-decorated)"
        )


def test_every_core_clause_is_cited_by_at_least_one_row() -> None:
    """Tripwire 1: coverage. A clause nobody ledgered is a clause nobody is
    watching.
    """
    contract = read(CONTRACT_PATH)
    clauses = {
        c
        for c in re.findall(r"^### ([^\n:]+):", contract, flags=re.MULTILINE)
        if c.startswith(("Core ", "NOT-ASSERTABLE "))
    }
    cited = {r["contract"]["clause"] for r in rows() if r["id"] != "CCV1-000"}
    missing = clauses - cited
    assert not missing, f"contract clauses with no ledger row: {sorted(missing)}"


def test_every_assertion_ref_resolves() -> None:
    """Tripwire 3a: an assertion that cannot be found is not an assertion."""
    probe_names = function_names(PROBE_MODULE)
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
            assert a["ref"] in probe_names, f"{r['id']}: probe {a['ref']!r} not found"
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
    found = {n for n in function_names(PROBE_MODULE) if n.startswith("test_row_")}
    assert found == declared, (
        f"probe/row mismatch\n  probes with no row: {sorted(found - declared)}\n"
        f"  rows with no probe: {sorted(declared - found)}"
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
