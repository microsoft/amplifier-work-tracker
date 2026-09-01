.PHONY: venv test test-unit test-integration test-cli test-ledger check lint types doctor clean

PYTHON  ?= python3.12
VENV    := .venv
PY      := $(VENV)/bin/python
PYTEST  := $(PY) -m pytest

# One-time (or after dependency changes) environment setup. Uses `uv` for
# speed; falls back to nothing fancier than a normal editable install.
venv:
	uv venv $(VENV) --python $(PYTHON)
	uv pip install --python $(PY) -e ".[dev,web]"

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

## All four tiers.
test:
	$(PYTEST) tests ledger/checks -v

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
