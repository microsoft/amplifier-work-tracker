"""FAIL-BEFORE / PASS-AFTER probe for model_performance-oy4.

Reproduces the measured h6v shape with the SAME API on both trees, so the
before/after difference is behaviour, not a missing function signature:
a hold whose holder process is genuinely dead, last renewed 400s ago,
against the documented 900s CUSTODY_TTL_SECONDS.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time

import pytest

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import custody as C
from amplifier_work_tracker import supervisor as SV

pytestmark = pytest.mark.integration
SILENCE = 400


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])  # noqa: S603
    p.wait()
    return p.pid


def test_probe(workspace, project_factory):
    name, bd = project_factory("failbefore")
    item_id = bd.create("dead holder probe", priority=1)
    bd.claim_item(item_id, actor="dead-agent")
    pid = _dead_pid()
    bd.take_custody(item_id, holder="dead-agent", pid=pid, host=socket.gethostname())
    rec = dict(bd.get(item_id).meta[C.CUSTODY_KEY])
    rec["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - SILENCE))
    bd._run(["update", item_id, "--metadata", json.dumps({C.CUSTODY_KEY: rec})], actor="dead-agent")

    out = []
    out.append(f"holder pid {pid} running? {os.path.exists(f'/proc/{pid}')}")
    out.append(f"custody last_seen {SILENCE}s ago; CUSTODY_TTL_SECONDS={C.CUSTODY_TTL_SECONDS}")
    s = A.project_summary(workspace, name)
    out.append(
        f"work_stats view:  held={s.held}  held_stale={s.held_stale}  "
        f"held_stale_oldest_age_seconds={s.held_stale_oldest_age_seconds}"
    )
    r = SV.reap_project(bd)  # default TTL, exactly what the service runs
    out.append(
        f"reap_project(default ttl): reclaimed_count={r['reclaimed_count']} "
        f"reasons={[x['reason'] for x in r['reclaimed']]}"
    )
    after = bd.get(item_id)
    out.append(f"after sweep: status={after.status} holder={after.holder!r}")
    try:
        bd.claim_item(item_id, actor="successor-agent")
        out.append("successor work_claim: SUCCESS")
    except Exception as e:
        out.append(f"successor work_claim: REFUSED -- {str(e)[:150]}")
    print("\n".join("    " + line for line in out))
