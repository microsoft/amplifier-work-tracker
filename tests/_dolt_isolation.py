"""Isolated per-test-session dolt server -- shared by BOTH the root suite
(``tests/conftest.py``) and the module suite
(``modules/tool-work-tracker/tests/conftest.py``).

Kept in exactly one place so the two suites can never drift into two
different isolation behaviors. The module suite is a genuinely separate
pytest run (its own ``pyproject.toml``, its own ``testpaths`` -- see that
suite's own ``conftest.py`` docstring) and cannot import a root-package
relative ``tests.conftest`` module, so this lives as its own tiny
standalone file both suites reach the same way they already reach
``src/``: a ``sys.path`` insert.

Why this exists
----------------
Every project this repo's tests create lives in two places: a local tmp
directory (pytest cleans that up for free), and a database on whatever
dolt server ``bd`` was pointed at. Before this file, that was *always* the
conventional shared server at ``~/.beads/shared-server:3308`` -- the SAME
server every real, permanent project also lives on.

Fixture-level teardown (``drop_project``, ``contract.Probe.__exit__``, the
module suite's ``project`` fixture) does the right thing in the ordinary
case, but it is Python code that runs *after* a test/fixture body -- and
Python code does not run at all if the process never gets to unwind: a
``kill -9``, an impatient ``timeout <n> pytest ...`` wrapper escalating to
SIGKILL, an OOM kill, a hard crash. Any of those skips every ``finally``,
every fixture finalizer, every ``atexit`` handler -- and leaves that run's
databases on the shared, PERMANENT server forever. Measured on a live box:
202 residue databases, enough on their own to make `bd init` (which is,
under the hood, a ``CREATE DATABASE``) time out at 240s server-wide --
for real projects too, not just test runs.

Teardown discipline cannot close that gap; only isolation can. So: give
every test SESSION its own throwaway ``dolt sql-server``, on its own
ephemeral port, backed by its own throwaway directory, and repoint
``supervisor.DEFAULT_DOLT_HOST`` / ``DEFAULT_DOLT_PORT`` -- and the
``AMPLIFIER_WORK_TRACKER_DOLT_HOST`` / ``_PORT`` env vars every subprocess
CLI test's freshly-imported process reads at ITS OWN import time -- at it
for the whole session. Nothing a test creates can reach the shared
production server again, structurally, independent of whether any
particular fixture remembered to clean up. A run that gets SIGKILLed mid
suite leaves, at worst, one orphaned ``dolt sql-server`` process and a
``/tmp`` directory -- never another entry on the server every real project
also lives on.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


def free_port() -> int:
    """An ephemeral TCP port nothing is bound to right now.

    Bind-then-close: the standard, unavoidable TOCTOU race (something else
    could bind it a moment later) shared by every "find a free port"
    helper -- the same technique ``tests/unit/test_supervisor_web.py``
    already uses to find a port to occupy.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class IsolatedDoltServer:
    host: str
    port: int
    data_dir: Path
    proc: subprocess.Popen


#: dolt's own bookkeeping schemas, present on any freshly-started server
#: with zero projects created. Never test residue, never dropped, never
#: counted -- see `list_test_databases`.
_SYSTEM_SCHEMAS = frozenset({"information_schema", "mysql", "dolt_cluster"})


def start(data_dir: Path, *, timeout: float = 30.0) -> IsolatedDoltServer:
    """Spawn a throwaway ``dolt sql-server`` on its own ephemeral port and
    block until it actually answers.

    Uses ``supervisor.spawn_dolt`` / ``supervisor.port_holder_responds`` --
    this repo's own production machinery, the exact functions the real
    ``serve`` supervisor uses to own and monitor its dolt child -- reused
    directly rather than reimplemented, the same principle ``contract.Probe``
    already follows for ``doctor``.
    """
    from amplifier_work_tracker import supervisor as SV  # deferred: caller sets up sys.path first

    host = "127.0.0.1"
    port = free_port()
    data_dir.mkdir(parents=True, exist_ok=True)
    proc = SV.spawn_dolt(host, port, data_dir)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        exit_code = proc.poll()
        if exit_code is not None:
            raise RuntimeError(
                f"isolated dolt sql-server exited early (code {exit_code}) on "
                f"{host}:{port}, data dir {data_dir} -- see its stdout/stderr above"
            )
        if SV.port_holder_responds(host, port):
            return IsolatedDoltServer(host=host, port=port, data_dir=data_dir, proc=proc)
        time.sleep(0.1)
    proc.kill()
    proc.wait(timeout=5)
    raise RuntimeError(
        f"isolated dolt sql-server never answered on {host}:{port} within {timeout}s"
    )


def stop(server: IsolatedDoltServer, *, term_timeout: float = 10.0) -> None:
    """Terminate the isolated server's dolt child and remove its data dir.

    Idempotent -- safe to call even if the process already exited (e.g. a
    prior call, or the child crashed on its own). SIGTERM first, SIGKILL
    only if it does not exit within `term_timeout` -- dolt needs a moment
    to flush/close cleanly.
    """
    if server.proc.poll() is None:
        server.proc.terminate()
        try:
            server.proc.wait(timeout=term_timeout)
        except subprocess.TimeoutExpired:
            server.proc.kill()
            server.proc.wait(timeout=term_timeout)
    shutil.rmtree(server.data_dir, ignore_errors=True)


def list_test_databases(host: str, port: int) -> list[str]:
    """Every non-system database currently on `host:port`.

    On an isolated, per-session server every single one of these IS test
    residue by construction -- nothing else has ever had the chance to
    create a database here. Queries `information_schema.SCHEMATA` directly
    (the same read `adapter.database_exists` / `scripts/sweep_test_residue.py`
    use) rather than parsing `show databases` table output.
    """
    from amplifier_work_tracker import adapter as A  # deferred: caller sets up sys.path first

    p = subprocess.run(
        [
            "dolt",
            "--host",
            host,
            "--port",
            str(port),
            "--no-tls",
            "sql",
            "-q",
            "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA",
            "-r",
            "csv",
        ],
        capture_output=True,
        text=True,
        env=A._bd_env(),  # noqa: SLF001 - non-interactive env; see its docstring
        check=False,
    )
    if p.returncode != 0:
        raise RuntimeError(
            f"could not list databases on isolated server {host}:{port}: "
            f"{(p.stderr or p.stdout).strip()[:500]}"
        )
    rows = [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()]
    names = rows[1:]  # drop the CSV header
    return sorted(n for n in names if n not in _SYSTEM_SCHEMAS)
