"""Real-process regression proof for SIGTERM during supervisor-owned sweeps."""

from __future__ import annotations

import os
import signal
import socket
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
blocker_pid = Path(sys.argv[7])
dolt_dir = Path(sys.argv[8])

def blocking_sweep(_ws, **_kwargs):
    A._run_bounded(
        [sys.executable, str(blocker), str(ready), str(child_pid), str(blocker_pid)], timeout=60
    )
    return {}

if kind == "reap":
    SV.reap_sweep = blocking_sweep
else:
    SV.notify_sweep = blocking_sweep
SV.default_dolt_dir = lambda: dolt_dir

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
blocker_pid = Path(sys.argv[3])
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
child_pid.write_text(str(child.pid), encoding="utf-8")
blocker_pid.write_text(str(__import__("os").getpid()), encoding="utf-8")
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
        state = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2]
    except FileNotFoundError:
        return True
    return state == "Z"


def _dolt_responds(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2) as sock:
            sock.settimeout(0.2)
            return bool(sock.recv(4))
    except OSError:
        return False


def _wait_until(predicate, description: str, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError(f"readiness condition did not appear: {description}")
        time.sleep(0.02)


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["reap", "notify"])
def test_sigterm_drains_real_dolt_and_blocking_sweep_descendant(tmp_path: Path, kind: str) -> None:
    """A real SIGTERM must finish the supervisor and all owned descendants in 5s."""
    harness = tmp_path / "harness.py"
    blocker = tmp_path / "blocker.py"
    ready = tmp_path / "ready"
    child_pid = tmp_path / "descendant.pid"
    blocker_pid_path = tmp_path / "blocker.pid"
    root = tmp_path / "root"
    dolt_dir = tmp_path / "private-dolt"
    port = _free_port()
    harness.write_text(textwrap.dedent(_HARNESS), encoding="utf-8")
    blocker.write_text(textwrap.dedent(_BLOCKER), encoding="utf-8")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.Popen(
        [
            sys.executable,
            str(harness),
            str(root),
            str(port),
            kind,
            str(ready),
            str(child_pid),
            str(blocker),
            str(blocker_pid_path),
            str(dolt_dir),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env=env,
    )
    descendant: int | None = None
    blocker_parent: int | None = None
    dolt_pid: int | None = None
    try:
        _wait_until(
            lambda: (
                ready.exists() and (root / ".dolt-server.pid").exists() and _dolt_responds(port)
            ),
            "blocking sweep, private Dolt pid, and Dolt listener",
        )
        descendant = int(child_pid.read_text(encoding="utf-8"))
        blocker_parent = int(blocker_pid_path.read_text(encoding="utf-8"))
        dolt_pid = int((root / ".dolt-server.pid").read_text(encoding="utf-8"))
        assert dolt_dir.is_dir()
        assert Path(os.readlink(f"/proc/{dolt_pid}/cwd")).resolve() == dolt_dir.resolve()
        started = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        stdout, stderr = proc.communicate(timeout=5)
        assert proc.returncode == 0, stderr
        assert time.monotonic() - started < 5
        assert "dolt sql-server stopped (exit 0)" in stderr
        assert _pid_is_gone(dolt_pid), f"Dolt child survived: {dolt_pid}"
        assert _pid_is_gone(blocker_parent), f"blocker parent survived: {blocker_parent}"
        assert _pid_is_gone(descendant), f"orphan descendant {descendant}"
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        if blocker_parent is not None and not _pid_is_gone(blocker_parent):
            try:
                os.killpg(blocker_parent, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if descendant is not None and not _pid_is_gone(descendant):
            os.kill(descendant, signal.SIGKILL)
