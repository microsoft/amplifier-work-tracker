# Check record

One entry per integration, written by the MANAGER session in its own commit (never by a lane): what it covers, the command run, what it printed.

## 2026-09-06 12:27 UTC — merge of lane/apply-v2 (owner-ratified operator-surface v2 amendment)
- Covers: merge commit b8ee617 on `converge/apply-operator-surface-v2` = main 37fba54 + lane/apply-v2 4f407c0 (one lane; no post-merge pair gate needed).
- Ran, in this session, on the merged tree:
  - `.venv/bin/python -m pytest ledger/checks -q` → 60 passed
  - `make ledger-mutate` → ALL mutations proven 69 / 69; UNPROVEN: (none)
  - `pytest tests/conformance/operator_surface/test_tier_a.py -q` → 41 passed, 1 xfailed (OSV1-015 residual, item zhv)
  - `ruff check ledger` → All checks passed!
  - `sha256sum contracts/operator-surface.v1.md` = a1f304b11b17… == OSV1-000's operator-surface pin (custody pin ec4b736f… unchanged)
  - Status line still `**Status:** FROZEN`; candidate carries "Ratified by owner — 2026-09-06"; Changelog head is the v2 amendment entry; 12 rows carry the dated amendment note; OSV1 33 CONFORMS / 3 NOT-ASSERTABLE.
- Contract reading after re-run: operator-surface.v1 **Kept** (every Core clause CONFORMS or NOT-ASSERTABLE with cadence); custody-coordination.v1 **Kept** (CCV1 rows unchanged).
