"""Real-concurrency contention hardening -- work_tracker item pipeline-bug.

`project_summary` (#48) and `Beads.list()`/`get()` (#49, this branch) already
moved their heavy reads off `bd list [--all]`/`bd show` and onto read-only
SQL SELECTs, which have no write set and cannot serialization-conflict at
any project size. These tests extend that proof from "functional
equivalence on quiescent data" (see `test_list_via_sql_equivalence.py` /
`test_get_via_sql_equivalence.py`) to "survives REAL concurrent write
traffic against the real (isolated test) dolt server" -- genuine threads,
genuine `bd`/dolt subprocesses, no mocking.

Covers:
  - `project_summary` (the `instances`/`status` CLI's per-project read)
    keeps succeeding with sane counts while claims/resolves are actively
    landing on the SAME project.
  - A burst of concurrent resolves, fired with zero caller-side spacing
    (relying entirely on `Beads._run`'s own internal retry/backoff, never
    an artificial `time.sleep` added by the test), all land cleanly.
  - The "reported-conflict-may-have-landed" hazard: whenever a write
    attempt genuinely raises `BeadsError` under heavier self-induced
    contention, the item's real, independently-read final state must
    NEVER show the write as having landed anyway -- a reported failure
    must never be a silent lie about what the data actually shows.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.integration


# --------------------------------------------------------------- instances


def test_project_summary_survives_concurrent_writes(shared_bd, unique_lane, workspace):
    """`project_summary` -- what `cmd_instances`/`cmd_status` call for every
    project -- must keep reporting `STATUS_OK` with sane, non-negative
    counts while OTHER writers are actively creating/claiming/resolving
    items on the exact same project, for real, concurrently, not just in
    quick succession.
    """
    project_name = shared_bd.project_name
    stop = threading.Event()
    writer_errors: list[BaseException] = []
    writes_done = [0] * 3

    def writer(n: int) -> None:
        actor = f"summary-writer-{n}-{unique_lane}"
        try:
            while not stop.is_set():
                item_id = shared_bd.create(f"summary contention {n}", tags=[unique_lane])
                shared_bd.claim_item(item_id, actor=actor)
                shared_bd.resolve(item_id, "summary contention cleanup", actor=actor)
                writes_done[n] += 1
        except BaseException as e:  # noqa: BLE001 -- captured, re-raised on the main thread
            writer_errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(3)]
    for t in threads:
        t.start()
    try:
        # Real wall-clock overlap with the writers, not just N quick calls --
        # a fixed call count could finish before the writer threads even
        # get scheduled.
        deadline = time.monotonic() + 3.0
        summaries: list[A.ProjectSummary] = []
        while time.monotonic() < deadline:
            s = A.project_summary(workspace, project_name)
            summaries.append(s)
            assert s.status == A.STATUS_OK, (
                f"project_summary reported {s.status!r} while writes were landing concurrently"
            )
            assert s.total is not None and s.total >= 0
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=30)

    assert not writer_errors, f"background writers hit unexpected errors: {writer_errors}"
    assert sum(writes_done) > 0, "no background writes actually landed -- test did not overlap"
    assert len(summaries) >= 1


# ------------------------------------------------------------- burst resolve


def test_20_concurrent_resolves_land_cleanly_with_zero_caller_spacing(shared_bd, unique_lane):
    """Fire 20 resolves at once (`ThreadPoolExecutor`, no `time.sleep`
    between submissions) -- the write path's OWN internal retry/backoff
    (`Beads._run`) is what must ride out any self-induced contention, not
    anything the caller does. All 20 must land: each `resolve()` call must
    both return successfully AND, independently re-read, actually show
    `status == \"resolved\"`.
    """
    n = 20
    ids = [shared_bd.create(f"burst resolve {i}", tags=[unique_lane]) for i in range(n)]
    actors = [f"burst-actor-{i}-{unique_lane}" for i in range(n)]
    for item_id, actor in zip(ids, actors, strict=True):
        shared_bd.claim_item(item_id, actor=actor)

    def do_resolve(item_id: str, actor: str) -> A.Item:
        return shared_bd.resolve(item_id, "burst resolve cleanup", actor=actor)

    with ThreadPoolExecutor(max_workers=n) as ex:
        futures = [
            ex.submit(do_resolve, item_id, actor)
            for item_id, actor in zip(ids, actors, strict=True)
        ]
        results = [f.result() for f in futures]  # re-raises any exception, loudly

    assert len(results) == n
    for r in results:
        assert r.status == "resolved"

    # Independent confirmation, via the (now contention-safe) SQL read path --
    # not just trusting resolve()'s own return value.
    for item_id in ids:
        assert shared_bd.get_readonly(item_id).status == "resolved"


# ------------------------------------------------ verify-before-retry hazard


def test_reported_write_failures_never_silently_land(shared_bd, unique_lane):
    """The "reported-conflict-may-have-landed" hazard: under HEAVIER
    self-induced contention (more concurrent resolvers than the burst test
    above, plus a noisy concurrent background writer on the same project)
    some resolve attempts may genuinely exhaust `Beads._run`'s retry budget
    and raise `BeadsError`. Whenever that happens, this asserts the
    strongest thing that can honestly be asserted: the item's real,
    independently-read state must NEVER show the resolve as having landed
    anyway -- a caller told "this failed" must never be lied to by the
    underlying data.

    This does not require a failure to actually occur to be a meaningful
    check (dolt/MySQL serialization-conflict semantics -- the exact error
    signatures `Beads._run` retries on -- mean a transaction reporting
    1213/1205/"serialization failure"/"try restarting transaction" was
    ABORTED, never partially committed; see `context/awareness.md`'s
    verify-before-retry contract): if every attempt here succeeds, the
    per-outcome consistency check below still holds trivially, and the
    accounting assertion (every item accounted for exactly once) still
    exercises the real concurrent path. If a failure DOES occur, this is
    the one test that would catch a false report.
    """
    n = 24
    ids = [shared_bd.create(f"hazard resolve {i}", tags=[unique_lane]) for i in range(n)]
    actors = [f"hazard-actor-{i}-{unique_lane}" for i in range(n)]
    for item_id, actor in zip(ids, actors, strict=True):
        shared_bd.claim_item(item_id, actor=actor)

    stop = threading.Event()
    noise_errors: list[BaseException] = []

    def noise() -> None:
        actor = f"hazard-noise-{unique_lane}"
        try:
            while not stop.is_set():
                nid = shared_bd.create("hazard noise", tags=[unique_lane])
                shared_bd.claim_item(nid, actor=actor)
                shared_bd.resolve(nid, "hazard noise cleanup", actor=actor)
        except BaseException as e:  # noqa: BLE001 -- captured, re-raised on the main thread
            noise_errors.append(e)

    noise_threads = [threading.Thread(target=noise) for _ in range(2)]
    for t in noise_threads:
        t.start()

    outcomes: dict[str, tuple[bool, str | None]] = {}

    def do_resolve(item_id: str, actor: str) -> None:
        try:
            shared_bd.resolve(item_id, "hazard resolve cleanup", actor=actor)
            outcomes[item_id] = (True, None)
        except A.BeadsError as e:
            outcomes[item_id] = (False, str(e))

    try:
        with ThreadPoolExecutor(max_workers=n) as ex:
            futures = [
                ex.submit(do_resolve, item_id, actor)
                for item_id, actor in zip(ids, actors, strict=True)
            ]
            for f in futures:
                f.result()  # do_resolve itself never raises -- outcomes captures it
    finally:
        stop.set()
        for t in noise_threads:
            t.join(timeout=30)

    assert not noise_errors, f"background noise writer hit unexpected errors: {noise_errors}"
    assert len(outcomes) == n, "every resolve attempt must be accounted for exactly once"

    failures = [item_id for item_id, (ok, _) in outcomes.items() if not ok]
    for item_id, (ok, _err) in outcomes.items():
        # Independent, contention-safe (SQL) re-read -- never trust the call's
        # own return value for this check.
        real_status = shared_bd.get_readonly(item_id).status
        if ok:
            assert real_status == "resolved", (
                f"{item_id}: resolve() reported success but the real state is "
                f"{real_status!r}, not 'resolved'"
            )
        else:
            assert real_status != "resolved", (
                f"{item_id}: resolve() reported failure ({outcomes[item_id][1]!r}) but "
                f"the write silently landed anyway (real state is 'resolved') -- "
                f"this is the exact hazard this test exists to catch"
            )

    # Clean up whichever items a reported failure left un-resolved, so this
    # test does not leak held items into the shared session-scoped project.
    for item_id in failures:
        actor = actors[ids.index(item_id)]
        if shared_bd.get_readonly(item_id).status != "resolved":
            shared_bd.resolve(item_id, "hazard resolve cleanup retry", actor=actor)
