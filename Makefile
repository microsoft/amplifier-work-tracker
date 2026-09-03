.PHONY: venv test test-unit test-integration test-cli test-ledger ledger-mutate test-module check lint types doctor clean

PYTHON  ?= python3.12
VENV    := .venv
PY      := $(VENV)/bin/python
PYTEST  := $(PY) -m pytest

# One-time (or after dependency changes) environment setup. Uses `uv` for
# speed; falls back to nothing fancier than a normal editable install.
#
# ONE venv, ONE command. The second editable target is the amplifier tool
# module under modules/ -- it is a separate installable package with its own
# pyproject.toml, and without it `import amplifier_module_tool_work_tracker`
# raises ModuleNotFoundError in this venv, which is exactly why its test
# suite ran in nothing (ledger row CCV1-022). Its `[dev]` extra carries the
# two test-only dependencies that suite needs and the root package does not
# (amplifier-core, pytest-asyncio); they are declared there rather than
# duplicated into the root `dev` extra so each package keeps owning its own
# dependencies.
venv:
	uv venv $(VENV) --python $(PYTHON)
	uv pip install --python $(PY) -e ".[dev,web]" -e "modules/tool-work-tracker[dev]"

## Tier 1 -- unit: pure logic, no bd, no network. Target: whole tier < 5s.
test-unit:
	$(PYTEST) tests/unit -v

## Tier 2 -- integration: real bd + real shared dolt server required.
test-integration:
	$(PYTEST) -m integration tests/integration -v

## Tier 3 -- cli: the real amplifier-work-tracker subprocess surface, requires real bd.
test-cli:
	$(PYTEST) -m cli tests/cli -v

## Tier 4 -- conformance ledger: one probe per row of ledger/rows.yaml, plus
## the coverage tripwires. In-process only (no bd, no dolt, no network, no
## subprocess) and sub-second on purpose: a ledger that is slow does not get
## run, and a ledger that is not run is a remembered audit.
test-ledger:
	$(PYTEST) ledger/checks -v

## The other half of the ledger's honesty. `test-ledger` proves the probes
## PASS; it cannot prove any of them would notice if the world changed. This
## runs every probe against a counterfactual repo -- for a pinning GAP/
## VIOLATION row, the FIXED behaviour; for a green row, the known-wrong shape
## it forbids -- and requires each to go RED. Injection only: nothing on disk
## is edited, no product code runs, no subprocess. Prints `proven N / M` and
## names every unproven mutation with its reason; exits non-zero if any hole
## exists, because a harness that reports a hole and still exits 0 is a
## harness nobody notices going hollow.
ledger-mutate:
	$(PY) -m ledger.checks.mutation_harness

## Tier 5 -- tool module: modules/tool-work-tracker's own suite, the only
## place the post-reclaim custody behaviour of the AGENT SEAM (work_claim /
## work_declare / work_resolve / work_release) is asserted mechanically.
## Deliberately its own pytest invocation rather than another path argument
## on `test` below: that suite ships its own session-scoped isolated dolt
## server fixture (a copy of the root suite's, since fixtures cannot cross
## a pytest run), and folding the two together would stand up two servers
## in one session for no gain. Requires `make venv` (the module must be
## installed into the venv) and a real `bd` on PATH -- without bd the
## real-storage tests skip rather than fail.
test-module:
	$(PYTEST) modules/tool-work-tracker/tests -v

## All five tiers. Two pytest invocations (see `test-module` above), and
## deliberately NOT fail-fast between them: the whole point of wiring the
## module suite in (ledger row CCV1-022) is that it stops being silently
## skippable, and a pre-existing failure in the root suite must not go back
## to hiding tier 5's result. Both always run; the target still fails if
## either did.
test:
	@rc=0; \
	$(PYTEST) tests ledger/checks -v || rc=$$?; \
	$(PYTEST) modules/tool-work-tracker/tests -v || rc=$$?; \
	exit $$rc

## Lint + type-check.
check: lint types

lint:
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

types:
	$(VENV)/bin/pyright src tests

## Re-verify our assumptions about the installed bd against the live binary.
doctor:
	$(PY) -m amplifier_work_tracker.cli doctor

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache **/__pycache__
