"""Tier 1 -- a HANDLED condition must never republish another program's
error ANNOUNCEMENT onto a stderr that will accompany exit 0.

The observed leak (`model_performance-kxk`), verbatim from
`docs/lanes/wp6-error-regex-scope/evidence/pr70-doctor-quick.run1-transient.stderr.txt`
on main:

    project 'contract1788423815748rm': bd init hit a dirty schema migration
      -- dropping and retrying once: [mysql] ... busy buffer
    Error: failed to open Dolt store: failed to initialize schema: schema
      migration: pending schema migrations alter pre-existing dirty tables:
      comments, ...; run 'bd dolt commit' to

`doctor --quick` printed `All 35 assumptions hold` and exited 0 underneath
that. From outside, an error announcement alongside exit 0 IS the
silent-failure shape `tests/_util.assert_no_silent_failure` exists to
forbid -- so a run that recovered correctly could fail a CLI-tier test.

The root cause is not bd's stderr escaping around us. The `Error:` line is
INSIDE our own `logger.warning`: the old call interpolated
`blob.strip()[:300]`, and `blob` is multi-line. Proof, from the committed
evidence rather than from reasoning: the quoted text spanning those two
lines is exactly 300 characters and stops mid-sentence at
"run 'bd dolt commit' to" -- the slice boundary, not bd's own line ending.

WHY THIS FILE IS TIER 1. The condition was observed ONCE and did not
reproduce on the immediately following run: a real dirty dolt store is not
something a test can conjure on demand. But the leak never needed a real
dirty store -- it needed bd to hand `Workspace.create` that blob once. That
IS reproducible, deterministically, with no bd, no dolt, and no network, by
scripting the single `bd init` call the heal path branches on. So this file
pins the actual product path (`Workspace.create`'s dirty-schema self-heal),
not a re-implementation of it.

BOTH DIRECTIONS LIVE HERE ON PURPOSE, for the reason
`test_error_announcement_detection.py` gives for the same choice: the
failure mode is not "too quiet" or "too loud", it is the two collapsing.
A fix that only proved the healed run is quiet could have been achieved by
swallowing everything, which would retire the guarantee that a genuine
failure still announces.
"""

from __future__ import annotations

import logging
import subprocess

import pytest

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import cli

from .. import _util

# --------------------------------------------------------------------------
# The blob bd actually emitted, reconstructed from the committed evidence.
#
# Two lines, because that is what made the second one read as OUR
# announcement once it was interpolated into a log message.
# --------------------------------------------------------------------------

OBSERVED_BD_BLOB = (
    "[mysql] 2026/09/03 01:25:03 connection.go:214 busy buffer\n"
    "Error: failed to open Dolt store: failed to initialize schema: schema migration: "
    "pending schema migrations alter pre-existing dirty tables: comments, "
    "compaction_snapshots, dependencies, events, issue_snapshots, labels; "
    "run 'bd dolt commit' to commit the working set\n"
)

# The same failure signature WITHOUT any of `_LEAKING_BD_INTERNALS_PATTERNS`
# (no `bd dolt commit`, no `run 'bd `). Used for the genuine-failure half:
# `_clean_bd_error` passes this through verbatim, so the announcement bd made
# is still visible in the CLI's own failure message. That is what proves the
# defusal is confined to the handled path.
GENUINE_FAILURE_BLOB = (
    "Error: failed to initialize schema: schema migration: pending schema migrations "
    "alter pre-existing dirty tables: comments, events\n"
)

PROJECT = "kxkheal"


class _ScriptedRun:
    """Stands in for `adapter._run_bounded`, the single call site every
    `bd`/`dolt`/`git` subprocess in the module goes through.

    Only `bd init` is scripted; everything else (the `git init`/`git commit`
    bootstrap, `bd metrics off`) succeeds silently, which is what they do on
    a healthy box.
    """

    def __init__(self, *init_results: tuple[int, str]):
        self.init_results = list(init_results)
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        if list(args[:2]) == ["bd", "init"]:
            rc, err = self.init_results.pop(0) if self.init_results else (0, "")
            return subprocess.CompletedProcess(list(args), rc, "", err)
        return subprocess.CompletedProcess(list(args), 0, "", "")

    @property
    def init_calls(self) -> int:
        return sum(1 for c in self.calls if c[:2] == ["bd", "init"])


class _AnsweringProject:
    """`Workspace.create` finishes by proving the project actually answers.
    Nothing in this file is about that step."""

    def list(self, *a, **kw):
        return []


@pytest.fixture
def scripted(monkeypatch, tmp_path):
    """A `Workspace` rooted in `tmp_path` whose bd calls are scripted.

    Returns a factory: `scripted(*init_results) -> (workspace, run)`.
    """

    def _make(*init_results: tuple[int, str]):
        run = _ScriptedRun(*init_results)
        monkeypatch.setattr(A, "_run_bounded", run)
        monkeypatch.setattr(A, "drop_database", lambda name: True)
        monkeypatch.setattr(
            A.Workspace, "project", lambda self, name, actor=None: _AnsweringProject()
        )
        # `bd metrics off` is once-per-process; reset so the call is scripted
        # rather than skipped depending on test ordering.
        monkeypatch.setattr(A, "_TELEMETRY_OFF_ATTEMPTED", False, raising=False)
        return A.Workspace(tmp_path), run

    return _make


def _stderr_of(caplog) -> str:
    """Reconstruct what a plain CLI invocation would put on stderr.

    `logger.warning` and above reach stderr through Python's handler of last
    resort, which has NO formatter -- it writes `record.getMessage()`, the
    fully-interpolated message and nothing else. That is exactly what the
    recorded evidence file contains (bare messages, no level prefix), so
    joining `getMessage()` reproduces those bytes rather than approximating
    them. `caplog` is used only to reach the records; the reconstruction, not
    pytest's own formatting, is what gets asserted on.
    """
    return "\n".join(r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------
# The healed run: quiet about failure, still loud about the recovery.
# --------------------------------------------------------------------------


def test_a_healed_dirty_migration_leaves_no_error_announcement(scripted, caplog):
    """The reproduction, and the fix, in one test.

    Against the parent commit this FAILS at the `error_announcement`
    assertion with `shape=error-colon matched='Error:'` -- the recorded leak,
    on demand.
    """
    caplog.set_level(logging.WARNING, logger="amplifier_work_tracker.adapter")
    ws, run = scripted((1, OBSERVED_BD_BLOB), (0, ""))

    path = ws.create(PROJECT)

    # The heal actually happened -- otherwise this test proves nothing about
    # the heal path.
    assert run.init_calls == 2, f"expected a retry after the dirty migration, got {run.calls}"
    assert path.name == PROJECT

    stderr = _stderr_of(caplog)

    # 1. The recovery stays VISIBLE. Going quiet would also pass the check
    #    below, and would be the wrong fix.
    assert "dropping and retrying once" in stderr
    assert "dirty schema migration" in stderr

    # 2. bd's detail survives, so the line is still diagnostic.
    assert "busy buffer" in stderr
    assert "failed to open Dolt store" in stderr

    # 3. ... but it no longer ANNOUNCES. This is the whole item.
    assert _util.error_announcement(stderr) is None, (
        "a handled, recovered condition republished an error announcement: "
        f"{_util.error_announcement(stderr)!r} in {stderr!r}"
    )

    # 4. And the tier-3 invariant itself, run against exactly this stderr
    #    beside the exit code a healed run really produces.
    _util.assert_no_silent_failure(
        subprocess.CompletedProcess(["doctor", "--quick"], 0, "All 35 assumptions hold\n", stderr)
    )


def test_the_healed_warning_is_a_single_line(scripted, caplog):
    """A quoted multi-line blob is half the illusion: it puts bd's `Error:`
    at the START of a line of our stderr, which is where a reader (and a
    log scraper) reads it as ours. One record, one line."""
    caplog.set_level(logging.WARNING, logger="amplifier_work_tracker.adapter")
    ws, _ = scripted((1, OBSERVED_BD_BLOB), (0, ""))
    ws.create(PROJECT)

    heal_lines = [
        r.getMessage() for r in caplog.records if "dirty schema migration" in r.getMessage()
    ]
    assert len(heal_lines) == 1
    assert "\n" not in heal_lines[0]


# --------------------------------------------------------------------------
# The genuine failure: still loud, still non-zero. This is the half that a
# too-eager fix would silently retire.
# --------------------------------------------------------------------------


def test_a_migration_that_really_fails_still_raises(scripted):
    """Both attempts fail -> `create` refuses, it does not return a path.
    Nothing about the defusal reaches this path."""
    ws, run = scripted((1, GENUINE_FAILURE_BLOB), (1, GENUINE_FAILURE_BLOB))

    with pytest.raises(A.BeadsError) as excinfo:
        ws.create(PROJECT)

    assert run.init_calls == 2, "the retry must still be attempted before giving up"
    message = str(excinfo.value)
    assert "bd init failed" in message
    # The failure path goes through `_clean_bd_error`, never
    # `_quote_handled_output`: bd's own announcement is preserved verbatim.
    assert _util.error_announcement(message) is not None
    assert "[bd " not in message


def test_a_migration_that_really_fails_exits_non_zero_and_announces(scripted, monkeypatch, capsys):
    """The same failure at the CLI surface: `cmd_new` -> `die` -> exit 1,
    with the announcement on stderr.

    Asserted together with `assert_no_silent_failure`, which must NOT fire
    here: an announcement beside a non-zero exit is a program reporting its
    failure correctly. That is the guarantee `model_performance-wp6` shipped,
    and this test is where this change proves it did not weaken it.
    """
    ws, _ = scripted((1, GENUINE_FAILURE_BLOB), (1, GENUINE_FAILURE_BLOB))
    monkeypatch.setattr(cli, "_guard", lambda: None)
    monkeypatch.setattr(cli, "_ws", lambda a: ws)
    monkeypatch.setattr(A, "database_exists", lambda name: False)

    args = type("A", (), {"name": PROJECT, "root": str(ws.root)})()
    with pytest.raises(SystemExit) as excinfo:
        cli.cmd_new(args)

    exit_code = excinfo.value.code
    assert isinstance(exit_code, int) and exit_code != 0
    captured = capsys.readouterr()
    assert "bd init failed" in captured.err

    result = subprocess.CompletedProcess(["new", PROJECT], exit_code, captured.out, captured.err)
    assert _util.error_announcement(captured.err) is not None, (
        "a genuine failure must still announce -- if this goes None, the "
        "defusal has leaked onto the failure path"
    )
    _util.assert_no_silent_failure(result)  # announcement + non-zero exit is correct


# --------------------------------------------------------------------------
# The coupling. Product code cannot import a test helper, so the guarantee
# is closed from this side instead: every shape the tier-3 predicate knows
# about must be defused by `_quote_handled_output`.
# --------------------------------------------------------------------------

# One representative blob per shape in `_util._ERROR_ANNOUNCEMENT_RES`.
SHAPE_SAMPLES: dict[str, str] = {
    "error-colon": "Error: failed to open Dolt store",
    "json-error-field": '{"error": "connection refused", "code": 2}',
    "error-running": "error running migration step 4",
    "unknown-command": 'unknown command "reclaim" for "bd"',
    "python-traceback": "Traceback (most recent call last):\n  File x\nValueError: nope",
}


def test_every_known_announcement_shape_has_a_sample():
    """If a shape is added to the predicate without a sample here, this goes
    red -- which is the point. A coupling test that silently covers only the
    old shapes is not a coupling test."""
    known = {name for name, _ in _util._ERROR_ANNOUNCEMENT_RES}
    assert known == set(SHAPE_SAMPLES), (
        "shapes without a defusal sample: "
        f"{sorted(known - set(SHAPE_SAMPLES))}; stale samples: "
        f"{sorted(set(SHAPE_SAMPLES) - known)}"
    )


@pytest.mark.parametrize("shape", sorted(SHAPE_SAMPLES))
def test_quote_handled_output_defuses_every_shape(shape):
    sample = SHAPE_SAMPLES[shape]
    # The sample really is an announcement before the treatment -- otherwise
    # this test could pass against a function that does nothing at all.
    assert _util.error_announcement(sample) is not None, shape
    quoted = A._quote_handled_output(sample)
    assert _util.error_announcement(quoted) is None, f"{shape} survived: {quoted!r}"


def test_quote_handled_output_keeps_the_detail_readable():
    """Defusing is not redacting. The words a human would grep for survive."""
    quoted = A._quote_handled_output(OBSERVED_BD_BLOB)
    assert "busy buffer" in quoted
    assert "failed to open Dolt store" in quoted
    assert "dirty tables" in quoted
    assert "error" in quoted.lower(), "the word itself must survive -- people grep for it"
    assert "\n" not in quoted


def test_quote_handled_output_reports_emptiness_rather_than_nothing():
    assert A._quote_handled_output("") == "(bd reported no detail)"
    assert A._quote_handled_output(None) == "(bd reported no detail)"
    assert A._quote_handled_output("   \n\t ") == "(bd reported no detail)"


def test_quote_handled_output_truncates_at_a_word_boundary():
    """The old `[:300]` slice cut mid-sentence ("run 'bd dolt commit' to"),
    which is exactly the fragment problem `truncate_status` already solved."""
    quoted = A._quote_handled_output("word " * 200)
    assert quoted.endswith("...[truncated]")
    assert len(quoted) <= A.STATUS_ERROR_MAX + len(" ...[truncated]")
