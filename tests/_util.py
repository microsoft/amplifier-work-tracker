"""Small, dependency-free helpers shared by the CLI-surface tests.

Kept out of conftest.py because these are plain functions, not fixtures.
"""

from __future__ import annotations

import re
import subprocess

# --------------------------------------------------------------------------
# What counts as "this command printed an error".
#
# The check below used to be a bare `\berror\b`. That is not a test for an
# error being EMITTED -- it is a test for the word "error" appearing, and a
# command is allowed to *talk about* errors while succeeding. `doctor` prints
# every assumption's own DESCRIPTION on a healthy run, so in a catalogue whose
# subject matter is error handling, one honest sentence turned a green run
# red: `read.unavailable_not_absent`'s description ("... reports UNAVAILABLE
# (not ERROR) per project ...") matched at offset 125 and failed
# `test_doctor_quick_succeeds_against_the_real_installed_bd` on a completely
# healthy system. That blocked PR #70, which was correct in every other
# respect. Rewording the description would only move the trap to the next
# assumption.
#
# So the predicate is now a list of ANNOUNCEMENT shapes -- the shapes a
# program uses when it is reporting its own failure, rather than describing
# one. Each entry below is justified by output this project actually emits;
# none of them is a guess:
#
#   1. `error:`      -- the colon announcement. `Error: unknown command
#                       "reclaim"` (the shipped `reap` bug this whole tier is
#                       named for), `ERROR: <cause>` (adapter.py's own status
#                       for an unreadable project), `ERROR: tokens file not
#                       found` (gateway.py), and the argparse/cobra
#                       `<prog>: error: <msg>` shape all land here. Deliberately
#                       NOT anchored to the start of a line: a real
#                       announcement is routinely preceded by a program name,
#                       a log prefix, or a table column.
#   2. `"error": ..` -- the JSON shape, with a non-empty value. `supervisor.py`
#                       writes `{"error": str(e)}` into payloads the CLI
#                       prints, and `{"error": "boom"}` alongside exit 0 is
#                       exactly the silent failure this tier exists to catch.
#                       A null/empty value is the "no error" reading of the
#                       same field and is deliberately not matched.
#   3. `error running`-- announcement without a colon; named in the item.
#   4. `unknown command` -- the shipped bug's own words, kept as a shape in
#                       its own right so the guard survives the announcement
#                       prefix changing.
#   5. `Traceback`   -- a Python crash printed while exiting 0 is the same
#                       silent-failure shape wearing different clothes.
#
# The line this must NOT match is ordinary prose that happens to contain the
# word: "(not ERROR)", "retryable serialization errors", "an error is
# reported". Those describe; they do not announce.
#
# Widening this list is cheap and safe. NARROWING it retires a guarantee --
# see tests/unit/test_error_announcement_detection.py, which pins both
# directions in one file so the distinction cannot silently collapse again.
# --------------------------------------------------------------------------

_ERROR_ANNOUNCEMENT_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("error-colon", re.compile(r"\berror\s*:", re.IGNORECASE)),
    ("json-error-field", re.compile(r'"error"\s*:\s*(?!null\b|""|\[\]|\{\})\S')),
    ("error-running", re.compile(r"\berror\s+running\b", re.IGNORECASE)),
    ("unknown-command", re.compile(r"\bunknown command\b", re.IGNORECASE)),
    ("python-traceback", re.compile(r"^Traceback \(most recent call last\):", re.MULTILINE)),
)


def error_announcement(text: str) -> tuple[str, str] | None:
    """Return `(shape_name, matched_text)` for the first error ANNOUNCEMENT
    in `text`, or None if the text merely mentions errors.

    Naming the shape is not decoration: it is what tells a reader of a CI
    failure whether the guard fired on a real announcement or on prose.
    """
    for name, pattern in _ERROR_ANNOUNCEMENT_RES:
        m = pattern.search(text or "")
        if m:
            return name, m.group(0)
    return None


def looks_like_error_text(text: str) -> bool:
    return error_announcement(text) is not None


def assert_no_silent_failure(result: subprocess.CompletedProcess) -> None:
    """The invariant this whole tier exists to enforce: a command that
    ANNOUNCES an error must never also report success (exit 0).

    This is precisely the shape of the two shipped bugs this suite is
    named to prevent from recurring: `amplifier-work-tracker reap` printed
    `Error: unknown command "reclaim"` to stderr and still exited 0.

    "Announces" and "mentions" are different things, and keeping them
    different is the whole job -- see the shape list above.
    """
    combined = (result.stdout or "") + (result.stderr or "")
    hit = error_announcement(combined)
    if hit:
        shape, matched = hit
        assert result.returncode != 0, (
            "command printed an error announcement but exited 0 (this is "
            "exactly the silent-failure shape amplifier-work-tracker shipped before): "
            f"shape={shape} matched={matched!r} in {combined[:500]!r}"
        )


# --------------------------------------------------------------------------
# Reporting EVERY problem a `doctor` run has, not just the first one.
#
# `test_doctor_quick_succeeds_against_the_real_installed_bd` used to be three
# sequential asserts with `assert result.returncode == 0` first. Any exit-1
# -- including a purely environmental one the fixture itself creates -- took
# the test down before the two assertions after it ever ran. That is not a
# style nit; it MASKED real defects, twice measurably:
#
#   - `model_performance-wp6`: the `\berror\b` collision in the announcement
#     predicate lived AFTER the returncode assertion, so it was invisible on
#     every developer machine and only ever appeared in CI. It blocked PR #70
#     for days.
#   - `model_performance-kxk`: same test, same masking, different defect.
#
# The environmental FAIL is fixed at the source (`model_performance-jyg` --
# `sweeps.alive` no longer fails against a root the service does not serve),
# but the masking is a SEPARATE defect: the next environmental exit-1, from
# any cause, would hide the next real one exactly the same way. So the checks
# are collected independently and reported together, and the collection is a
# named function so it can be unit-tested directly -- see
# tests/unit/test_doctor_surface_failures.py.
#
# This ADDS a report; it removes no guarantee. `assert_no_silent_failure` and
# its announcement predicate are called unchanged.
# --------------------------------------------------------------------------


def doctor_surface_failures(result: subprocess.CompletedProcess) -> list[str]:
    """Every independent way a `doctor` run can be wrong, as a list.

    Empty list means a healthy run. Each entry is one self-contained
    problem, phrased so a CI reader knows which property broke without
    re-running anything.
    """
    failures: list[str] = []
    if result.returncode != 0:
        failures.append(
            f"exit code: expected 0, got {result.returncode} -- doctor reports a violated "
            f"assumption (see the [FAIL] line(s) in its output below)"
        )
    if "All" not in (result.stdout or ""):
        failures.append(
            "summary line: expected doctor to print `All N assumptions hold`, which it only "
            "prints when every assumption passed"
        )
    try:
        assert_no_silent_failure(result)
    except AssertionError as e:
        failures.append(f"silent-failure guard: {e}")
    return failures


def assert_doctor_run_is_clean(result: subprocess.CompletedProcess) -> None:
    """Assert a `doctor` run had NO problems, naming every one it did have.

    One assert, many reported problems -- deliberately not a chain of
    asserts, so the first failure can never hide the ones after it.
    """
    failures = doctor_surface_failures(result)
    if not failures:
        return
    numbered = "\n".join(f"  {i}. {f}" for i, f in enumerate(failures, 1))
    raise AssertionError(
        f"`doctor --quick` failed {len(failures)} independent check(s) "
        f"(all of them reported, none masked by the first):\n"
        f"{numbered}\n\n--- doctor stdout ---\n{result.stdout}"
        f"\n--- doctor stderr ---\n{result.stderr}"
    )
