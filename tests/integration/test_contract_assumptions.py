"""Tier 2 -- every declared Beads assumption, proven against the live binary.

This deliberately *reuses* `amplifier_work_tracker.contract`'s check functions
rather than reimplementing them: those functions ARE the "concurrent claim
safety", "custody fresh/stale/idle-not-exempt", and "fencing refusals"
coverage this tier is required to have, and they are the exact functions that
caught the real double-claim and no-fencing bugs. Wrapping them as individual
pytest cases (instead of only running them via `amplifier-work-tracker
doctor`) gets per-assumption pass/fail reporting, junit-friendly output, and
CI enforcement, for free, with zero duplicated logic.

One real project (`probe`, module-scoped) is shared across every check --
each check function uses its own private lane label internally, so they
never interfere with each other regardless of run order.
"""

from __future__ import annotations

import pytest

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import contract

pytestmark = pytest.mark.integration


def test_bd_version_is_within_the_supported_window():
    v, warn = A.check_version()
    assert v >= A.MIN_VERSION, (
        f"bd {v} is below the supported floor {A.MIN_VERSION} -- "
        f"`ready --claim` is not guaranteed to exist"
    )
    # A warning (newer-than-tested) is informational, not a failure.
    if warn:
        pytest.skip(f"note (not a failure): {warn}")


@pytest.mark.parametrize(
    "check_id,check_fn",
    contract.CHECKS,
    ids=[c[0] for c in contract.CHECKS],
)
def test_contract_assumption_holds(probe, check_id, check_fn):
    result = check_fn(probe)
    assert result.ok, f"[{check_id}] {result.detail}"
