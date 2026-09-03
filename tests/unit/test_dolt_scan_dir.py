"""Tier 1 -- the pinned dolt scan directory and the direct-SQL retry.

THE root-cause half of lane `model_performance-8zv`. Diagnosed by lane
`model_performance-rpz` (harness `probes/rpz-dolt-error-misreport/repro.sh`):
the `dolt` CLI enumerates its data directory and `lstat()`s every entry on
EVERY invocation -- including pure client mode against an already-running
shared server -- and with no `--data-dir` given, that directory is whatever
the CALLING AGENT's working directory happened to be. If an entry vanishes
between `readdir` and `lstat`, dolt aborts the whole query.

Measured, identical load, 25 attempts each:

    cwd = churning dir (the behaviour these tests fence out) ... 6/25 FAIL
    cwd pinned to a stable dir ................................. 0/25
    dolt --data-dir <stable>, cwd left churning ................ 0/25

Both remedies are applied and both are pinned here, because they are
independent: a future refactor that drops one must not silently reopen the
defect via the other.

Everything here is a pure function of `_run_bounded`'s recorded arguments --
no `bd`, no dolt server, no network, no real subprocess.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from amplifier_work_tracker import adapter as A

TRANSPORT_FAILURE = (
    "failed to load database names: lstat /tmp/churn_7473.sig: no such file or directory"
)


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["dolt"], returncode, stdout, stderr)


def _record(monkeypatch, results):
    """Replace `_run_bounded` with one that returns `results` in order and
    records every call. Returns the call list."""
    calls: list[dict] = []
    seq = list(results)

    def fake(args, *, env=None, cwd=None, timeout=None):
        calls.append({"args": list(args), "env": env, "cwd": cwd})
        return seq.pop(0) if seq else _proc()

    monkeypatch.setattr(A, "_run_bounded", fake)
    return calls


# ------------------------------------------------------- the pin itself


def test_scan_dir_exists_and_is_reused(monkeypatch, tmp_path):
    """The pinned directory is real (dolt is handed a path that exists, not
    one it will fail to open) and stable across calls -- a fresh directory
    per query would reintroduce the per-call cost the pin exists to remove."""
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_DOLT_SCAN_DIR", str(tmp_path / "scan"))
    first = A._dolt_scan_dir()
    second = A._dolt_scan_dir()
    assert first == second
    assert first.is_dir()


def test_scan_dir_is_not_the_process_cwd(monkeypatch, tmp_path):
    """The whole defect in one assertion: the directory dolt scans must not
    be the caller's own working directory, whatever that happens to be."""
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_DOLT_SCAN_DIR", str(tmp_path / "scan"))
    assert A._dolt_scan_dir().resolve() != Path.cwd().resolve()


def test_conn_args_pin_the_data_dir(monkeypatch, tmp_path):
    """`--data-dir` is on EVERY dolt invocation (it lives in
    `_dolt_conn_args`, not on the two hot helpers), which is what makes
    `DROP DATABASE`/`SHOW CREATE`/the copy script benefit by construction
    rather than by remembering. This is measured fix B: 0/25 with the cwd
    left churning."""
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_DOLT_SCAN_DIR", str(tmp_path / "scan"))
    args = A._dolt_conn_args()
    assert "--data-dir" in args
    assert args[args.index("--data-dir") + 1] == str(tmp_path / "scan")


def test_dolt_sql_pins_cwd(monkeypatch, tmp_path):
    """Measured fix A: `cwd=` is passed to `_run_bounded`, so the child
    `dolt` never inherits the caller's directory. Before this change both
    helpers passed no `cwd` at all (`_run_bounded`'s `cwd=None` default ->
    `Popen` inherits the parent's)."""
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_DOLT_SCAN_DIR", str(tmp_path / "scan"))
    calls = _record(monkeypatch, [_proc(0, "ok\n")])
    A._dolt_sql("SELECT 1")
    assert calls[0]["cwd"] is not None
    assert Path(calls[0]["cwd"]) == tmp_path / "scan"


def test_dolt_sql_json_pins_cwd(monkeypatch, tmp_path):
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_DOLT_SCAN_DIR", str(tmp_path / "scan"))
    calls = _record(monkeypatch, [_proc(0, '{"rows": []}')])
    A._dolt_sql_json("SELECT 1")
    assert Path(calls[0]["cwd"]) == tmp_path / "scan"


# ------------------------------------------------- the transport retry


def test_lstat_race_is_classified_transient():
    """dolt's own wording for the race. Before this change it appeared in no
    retry table at all, and `_RETRYABLE_CONNECTION` was consulted only by
    `Beads._run` (which wraps `bd`), never by the direct-SQL path."""
    assert A._connection_retryable(TRANSPORT_FAILURE)
    assert A._sql_failure("boom", _proc(1, "", TRANSPORT_FAILURE)).__class__ is (
        A.BeadsUnavailableError
    )


def test_a_real_domain_failure_is_not_classified_transient():
    """The other half of the classifier, and the reason it is conservative:
    a genuine bd/SQL failure must stay a plain `BeadsError`, or the fix
    would soften every real error into 'maybe transient'."""
    p = _proc(1, "", "Error 1064: syntax error near 'SELCT'")
    assert not A._connection_retryable((p.stdout or "") + (p.stderr or ""))
    err = A._sql_failure("boom", p)
    assert isinstance(err, A.BeadsError)
    assert not isinstance(err, A.BeadsUnavailableError)


def test_direct_sql_retries_a_transient_failure_and_then_succeeds(monkeypatch, tmp_path):
    """The 19 direct-SQL call sites had NO retry of any kind. One blip now
    rides through instead of surfacing as a read failure."""
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_DOLT_SCAN_DIR", str(tmp_path / "scan"))
    monkeypatch.setattr(A, "time", _NoSleep(A.time))
    calls = _record(
        monkeypatch,
        [
            _proc(1, "", TRANSPORT_FAILURE),
            _proc(1, "", TRANSPORT_FAILURE),
            _proc(0, '{"rows": []}'),
        ],
    )
    p = A._dolt_sql_json("SELECT 1")
    assert p.returncode == 0
    assert len(calls) == 3


def test_direct_sql_retry_is_BOUNDED_and_surfaces_the_failure(monkeypatch, tmp_path):
    """A persistent outage must fail FAST and surface the SAME non-zero
    process every existing call site already handles -- never a new
    exception type, and never an unbounded hammer."""
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_DOLT_SCAN_DIR", str(tmp_path / "scan"))
    monkeypatch.setattr(A, "time", _NoSleep(A.time))
    calls = _record(monkeypatch, [_proc(1, "", TRANSPORT_FAILURE)] * 50)
    p = A._dolt_sql("SELECT 1")
    assert p.returncode == 1
    assert TRANSPORT_FAILURE in p.stderr
    assert len(calls) == A._MAX_CONNECTION_RETRIES + 1


def test_direct_sql_does_not_retry_a_real_domain_failure(monkeypatch, tmp_path):
    """A syntax error is not a blip. Retrying it would burn seconds and
    change nothing."""
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_DOLT_SCAN_DIR", str(tmp_path / "scan"))
    calls = _record(monkeypatch, [_proc(1, "", "Error 1064: syntax error")] * 10)
    p = A._dolt_sql("SELCT 1")
    assert p.returncode == 1
    assert len(calls) == 1


class _NoSleep:
    """`A.time` with `sleep` neutered -- the retry budget is asserted by call
    count, so the test must not actually wait out the backoff."""

    def __init__(self, real):
        self._real = real

    def sleep(self, _seconds):
        return None

    def __getattr__(self, name):
        return getattr(self._real, name)
