"""Tier 1 -- `tests._util.assert_no_silent_failure`'s own predicate: the
difference between a command that ANNOUNCES an error and one that merely
MENTIONS the word.

Both directions live in this one file on purpose. The failure mode being
fenced is not "the check is too strict" or "the check is too loose" --
it is the two collapsing into each other. A fix that only proved the
innocent case passes would have retired the guarantee; a check that only
proved the guilty case fails is what shipped and blocked PR #70. Split
across two files, one half can be deleted without the other noticing.

The assertions below are written against `looks_like_error_text` and
`assert_no_silent_failure` -- the API that existed BEFORE this change --
so that running this file against the parent commit reports the real
diagnosis (prose classified as an error) rather than an AttributeError on
a helper that did not exist yet. `error_announcement`, which additionally
names WHICH shape fired, is exercised in one dedicated test at the end.

Why this is tier 1 and not tier 3: the CLI-tier test that actually
surfaced this (`test_doctor_quick_succeeds_against_the_real_installed_bd`)
is invisible on any machine whose sweep heartbeats live outside the test
root -- there `doctor` exits 1 and the test dies at the EARLIER
`assert result.returncode == 0`, never reaching the silent-failure check
(`model_performance-jyg`). A tier-1 test of the predicate itself needs no
bd, no dolt, and no healthy sweeps, so it cannot be masked that way.
"""

from __future__ import annotations

import subprocess

import pytest

from .. import _util

# --------------------------------------------------------------------------
# The innocent case, verbatim.
#
# This is not a synthetic sentence: it is the actual `detail` string of the
# `read.unavailable_not_absent` contract check added by PR #70
# (microsoft/amplifier-work-tracker, branch `lane/8zv-dolt-scan-dir`, head
# 20557bc, src/amplifier_work_tracker/contract.py:1372-1374). The old
# `\berror\b` predicate matched `ERROR` inside "(not ERROR)" at offset 125
# and failed the doctor test on a completely healthy system.
# --------------------------------------------------------------------------

PR70_DETAIL = (
    "an infrastructure read failure raises BeadsUnavailableError with its cause "
    "intact on read/claim and reports UNAVAILABLE (not ERROR) per project, while "
    "genuine absence on a healthy database still reports plain 'not found'"
)


def _doctor_line(check_id: str, detail: str, *, mark: str = "PASS", width: int = 41) -> str:
    """One rendered `doctor` row, in cli.cmd_doctor's own format:

        print(f"  [{r.mark}] {r.id:<{width}}  {r.detail}")

    `width` is the longest check id in the run; 41 is the observed width of
    a real `doctor --quick` run on this branch. The exact padding does not
    matter to the assertions -- what matters is that the description is
    surrounded by real row furniture, not tested as a bare sentence.
    """
    return f"  [{mark}] {check_id:<{width}}  {detail}"


HEALTHY_DOCTOR_TAIL = "\nAll 35 assumptions hold. Safe to run parallel agents.\n"


# --------------------------------------------------------- prose is not an error


def test_pr70_description_is_prose_not_an_announcement():
    """The sentence that actually blocked a PR."""
    assert _util.looks_like_error_text(PR70_DETAIL) is False


def test_healthy_doctor_run_carrying_pr70s_description_is_not_a_silent_failure():
    """The end-to-end shape: a `doctor --quick` run that passes every
    assumption, including PR #70's, and exits 0."""
    stdout = (
        _doctor_line("version", "bd 1.1.2")
        + "\n"
        + _doctor_line(
            "conflict.retryable",
            "Write conflicts surface as retryable serialization errors",
        )
        + "\n"
        + _doctor_line("read.unavailable_not_absent", PR70_DETAIL)
        + "\n"
        + HEALTHY_DOCTOR_TAIL
    )
    result = subprocess.CompletedProcess(
        args=["doctor", "--quick"], returncode=0, stdout=stdout, stderr=""
    )
    _util.assert_no_silent_failure(result)  # must not raise


@pytest.mark.parametrize(
    "text",
    [
        # A real assumption description from src/amplifier_work_tracker/adapter.py.
        "Write conflicts surface as retryable serialization errors",
        # The shape of the sentence that blocked #70, isolated.
        "reports UNAVAILABLE (not ERROR) per project",
        # Prose about the guard itself.
        "an infrastructure read failure raises BeadsUnavailableError",
        "this command never reports an error it did not observe",
        "ERROR and UNAVAILABLE are different readings of the same field",
        # A JSON field explicitly saying there was NO error.
        '{"ok": true, "error": null}',
        '{"ok": true, "error": ""}',
    ],
)
def test_mentioning_errors_is_not_announcing_one(text):
    assert _util.looks_like_error_text(text) is False, (
        f"{text!r} was classified as an error announcement -- the check is back to "
        f"failing commands for talking about errors while succeeding"
    )


# ------------------------------------------- the guarantee, still standing


@pytest.mark.parametrize(
    "text",
    [
        # THE bug. `amplifier-work-tracker reap` printed this to stderr and
        # exited 0. If this row ever stops failing, the guard is gone.
        'Error: unknown command "reclaim"',
        # ...preceded by other output, which is how it actually appeared.
        'reaping stale holds...\nError: unknown command "reclaim"\n',
        # adapter.py's own status for a project whose database cannot be read,
        # as `instances` renders it -- indented, in a table column.
        "  brokenqueue  TOTAL - READY - HELD -  ERROR: database unreachable",
        # gateway.py.
        "ERROR: tokens file not found: /etc/awt/tokens.json",
        # argparse / cobra.
        "amplifier-work-tracker: error: unrecognized arguments: --nope",
        "internal error: connection reset by peer",
        # supervisor.py writes {"error": str(e)} into printed payloads.
        '{"custody": {"error": "dolt: connection refused"}}',
        "error running bd list --json",
        # The two rows below are NEW coverage: neither contains the word
        # "error" at all, so the parent commit's `\berror\b` predicate missed
        # both. A Go CLI that renames its announcement prefix, and a Python
        # crash, are the same silent failure wearing different clothes.
        'unknown command "reclaim" for "bd"',
        'Traceback (most recent call last):\n  File "cli.py", line 1\n',
    ],
)
def test_real_error_announcements_are_still_caught(text):
    assert _util.looks_like_error_text(text) is True, (
        f"{text!r} is a real error announcement and was NOT detected -- the "
        f"silent-failure guarantee has been retired, not repaired"
    )


def test_the_shipped_reap_bug_still_fails_the_assertion():
    """The whole point, stated as the assertion callers actually make:
    `Error: unknown command "reclaim"` on stderr with exit 0 must raise."""
    result = subprocess.CompletedProcess(
        args=["reap"],
        returncode=0,
        stdout="",
        stderr='Error: unknown command "reclaim"\n',
    )
    with pytest.raises(AssertionError, match="exited 0"):
        _util.assert_no_silent_failure(result)


def test_an_announced_error_with_a_nonzero_exit_is_fine():
    """The guard is about the COMBINATION. A command that announces an error
    and exits non-zero is behaving correctly and must not be flagged."""
    result = subprocess.CompletedProcess(
        args=["reap"],
        returncode=1,
        stdout="",
        stderr='Error: unknown command "reclaim"\n',
    )
    _util.assert_no_silent_failure(result)  # must not raise


def test_announcements_are_found_across_the_stdout_stderr_seam():
    """`assert_no_silent_failure` concatenates the two streams; an
    announcement on stderr must be caught even when stdout is chatty."""
    result = subprocess.CompletedProcess(
        args=["reap"],
        returncode=0,
        stdout="reclaimed 0 holds\n",
        stderr="ERROR: database unreachable\n",
    )
    with pytest.raises(AssertionError):
        _util.assert_no_silent_failure(result)


def test_the_failure_message_names_which_shape_fired():
    """A CI reader must be able to tell a real announcement from a false
    positive without re-deriving the regex. `error_announcement` returns the
    shape name and the matched text; `assert_no_silent_failure` puts both in
    the assertion message."""
    assert _util.error_announcement(PR70_DETAIL) is None
    assert _util.error_announcement('Error: unknown command "reclaim"') == (
        "error-colon",
        "Error:",
    )
    result = subprocess.CompletedProcess(
        args=["reap"], returncode=0, stdout="", stderr='Error: unknown command "reclaim"\n'
    )
    with pytest.raises(AssertionError, match=r"shape=error-colon"):
        _util.assert_no_silent_failure(result)
