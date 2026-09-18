"""Real-process regression proof for SIGTERM during supervisor-owned sweeps."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

_HARNESS = r"""
import os
import sys
from pathlib import Path

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import supervisor as SV

root = Path(sys.argv[1])
port = int(sys.argv[2])
kind = sys.argv[3]
ready = Path(sys.argv[4])
child_pid = Path(sys.argv[5])
blocker = Path(sys.argv[6])

def blocking_sweep(_ws, **_kwargs):
    A._run_bounded([sys.executable, str(blocker), str(ready), str(child_pid)], timeout=60)
    return {}

if kind == "reap":
    SV.reap_sweep = blocking_sweep
else:
    SV.notify_sweep = blocking_sweep

raise SystemExit(SV.serve(
    root,
    host="127.0.0.1",
    port=port,
    reap_interval=0.01 if kind == "reap" else 300,
    notify_interval=0.01 if kind == "notify" else 300,
    dolt_restart_backoff=0.01,
))
"""

_BLOCKER = r"""
import subprocess
import sys
from pathlib import Path

ready = Path(sys.argv[1])
child_pid = Path(sys.argv[2])
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
child_pid.write_text(str(child.pid), encoding="utf-8")
ready.write_text("ready", encoding="utf-8")
child.wait()
"""


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for(path: Path, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise AssertionError(f"readiness marker did not appear: {path}")
        time.sleep(0.02)


def _pid_is_gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["reap", "notify"])
def test_sigterm_drains_real_dolt_and_blocking_sweep_descendant(tmp_path: Path, kind: str) -> None:
    """A real SIGTERM must finish the supervisor and all owned descendants in 5s."""
    harness = tmp_path / "harness.py"
    blocker = tmp_path / "blocker.py"
    ready = tmp_path / "ready"
    child_pid = tmp_path / "descendant.pid"
    harness.write_text(textwrap.dedent(_HARNESS), encoding="utf-8")
    blocker.write_text(textwrap.dedent(_BLOCKER), encoding="utf-8")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.Popen(
        [
            sys.executable,
            str(harness),
            str(tmp_path / "root"),
            str(_free_port()),
            kind,
            str(ready),
            str(child_pid),
            str(blocker),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env=env,
    )
    descendant: int | None = None
    try:
        _wait_for(ready)
        descendant = int(child_pid.read_text(encoding="utf-8"))
        started = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        stdout, stderr = proc.communicate(timeout=5)
        assert proc.returncode == 0, stderr
        assert time.monotonic() - started < 5
        assert "dolt sql-server stopped" in stderr
        assert _pid_is_gone(descendant), f"orphan descendant {descendant}"
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        if descendant is not None and not _pid_is_gone(descendant):
            os.kill(descendant, signal.SIGKILL)
