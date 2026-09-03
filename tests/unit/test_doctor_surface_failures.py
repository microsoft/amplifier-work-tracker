"""Tier 1 -- `_util.doctor_surface_failures` / `assert_doctor_run_is_clean`:
the DE-MASKING property of `test_doctor_quick_succeeds_against_the_real_
installed_bd` itself (`model_performance-jyg`).

That test used to be three sequential asserts with `assert result.returncode
== 0` first. A single exit-1 -- including a purely environmental one the
fixture itself creates -- took the test down before the other two assertions
ran, so a defect living AFTER that line was invisible. Measured twice:
`model_performance-wp6` (the announcement-predicate collision, invisible on
every developer machine, CI-only, blocked PR #70 for days) and
`model_performance-kxk`.

Fixing the environmental exit-1 does not fix that. The ORDERING was its own
defect: the next environmental failure, from any cause, would hide the next
real one exactly the same way. So the ordering property is pinned here,
directly and cheaply -- no bd, no subprocess, no service -- because a
guarantee that only holds while the environment happens to be healthy is not
a guarantee.

The load-bearing test is
`test_an_exit_1_does_not_hide_a_silent_failure_announcement`: it is the exact
shape of the two measured maskings, and it is RED against the old
first-assert-wins body.
"""

from __future__ import annotations

import subprocess

import pytest

from tests import _util


def _result(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["amplifier-work-tracker", "doctor", "--quick"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


_HEALTHY = "  [PASS] read.list  ok\n\nAll 38 assumptions hold. Safe to run parallel agents.\n"


def test_a_healthy_run_reports_nothing():
    assert _util.doctor_surface_failures(_result(0, _HEALTHY)) == []
    _util.assert_doctor_run_is_clean(_result(0, _HEALTHY))  # must not raise


def test_an_exit_1_does_not_hide_a_silent_failure_announcement():
    """THE regression pin. Two independent problems in one run: doctor
    exited non-zero (environmental), AND it announced an error while the
    summary line was missing. The old body reported only the first and
    stopped. Every problem must be named."""
    result = _result(
        1,
        stdout="  [FAIL] sweeps.alive  no heartbeat ever recorded\n",
        stderr='Error: unknown command "reclaim"\n',
    )

    failures = _util.doctor_surface_failures(result)

    assert any("exit code" in f for f in failures), failures
    assert any("summary line" in f for f in failures), failures
    assert len(failures) >= 2, (
        "an exit-1 must not consume the whole report -- that is precisely the masking "
        f"this exists to prevent; got {failures!r}"
    )


def test_the_aggregated_message_names_every_problem_and_carries_the_output():
    result = _result(1, stdout="  [FAIL] sweeps.alive  nope\n", stderr="Error: boom\n")

    with pytest.raises(AssertionError) as excinfo:
        _util.assert_doctor_run_is_clean(result)

    message = str(excinfo.value)
    assert "exit code" in message
    assert "summary line" in message
    assert "sweeps.alive" in message, "the doctor output itself must be in the failure message"
    assert "Error: boom" in message


def test_a_silent_failure_is_reported_even_though_the_exit_code_is_fine():
    """Exit 0 plus an error announcement is the original shipped bug. It
    must be reported on its own, with no other problem present to carry
    it."""
    result = _result(0, stdout=_HEALTHY, stderr='Error: unknown command "reclaim"\n')

    failures = _util.doctor_surface_failures(result)

    assert len(failures) == 1
    assert "silent-failure guard" in failures[0]


def test_a_missing_summary_line_is_reported_on_its_own():
    """Exit 0 with no `All N assumptions hold` line would mean doctor
    returned success without ever claiming every assumption held."""
    failures = _util.doctor_surface_failures(_result(0, stdout="  [PASS] read.list  ok\n"))

    assert len(failures) == 1
    assert "summary line" in failures[0]


def test_the_announcement_predicate_is_used_unchanged_not_reimplemented():
    """Prose that merely MENTIONS errors is still not an announcement --
    `read.unavailable_not_absent`'s own description is the exact text that
    turned a green run red before `model_performance-wp6` narrowed the
    predicate. Aggregating the checks must not have quietly widened it."""
    prose = (
        "  [PASS] read.unavailable_not_absent  reports UNAVAILABLE (not ERROR) per project\n"
        "\nAll 38 assumptions hold. Safe to run parallel agents.\n"
    )

    assert _util.doctor_surface_failures(_result(0, stdout=prose)) == []
