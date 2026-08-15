"""Tier 2 -- nothing this repo creates on the shared dolt server outlives
the run that created it.

Why this file exists, in numbers measured on one live box: 163 databases
for 5 real projects. 157 of them were residue -- 47 `contract*` from
`doctor` runs, the rest from test fixtures that created a project and only
ever cleaned up the local half of it. dolt holds every database open, so
the pile is paid for continuously: dropping it took that server from
1.15 GB RSS / 313 MB on disk to 0.12 GB / 18 MB.

Unique naming (see conftest.py) is what keeps concurrent runs from
colliding. It is NOT cleanup, and treating it as cleanup is what let the
pile grow silently for months. These tests pin the two halves of the fix:
the production `doctor` probe, and the test suite's own teardown helper.
"""

from __future__ import annotations

import pytest

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import contract

from ..conftest import drop_project, unique_name

pytestmark = pytest.mark.integration


def test_probe_drops_its_database_on_exit():
    """The `doctor` leak, pinned directly.

    `contract.Probe.__exit__` used to remove only its temp directory, so
    every `amplifier-work-tracker doctor` run left one permanent
    `contract<ts><pid>` database behind on the shared server -- the single
    largest residue source measured (47 of 157).
    """
    with contract.Probe() as p:
        name = p.name
        assert A.database_exists(name), "sanity: the probe's database must exist inside the block"

    assert not A.database_exists(name), (
        f"probe database {name!r} outlived the probe -- every doctor run now "
        f"leaks one database, which is exactly the bug this test exists for"
    )


def test_probe_drops_databases_registered_by_a_check():
    """Checks that derive a second database from the probe's name (today:
    `check_project_removal`, whose `<name>rm` project was measured leaking
    4 times) hand it to `register_database`, and it is dropped too.

    Registration is what makes that robust: the derived database is the
    probe's responsibility from the moment the name is minted, so a check
    that raises partway through -- or whose own best-effort cleanup fails
    -- still cannot leave it behind.
    """
    with contract.Probe() as p:
        derived = f"{p.name}rm"
        p.register_database(derived)
        p.ws.create(derived)
        assert A.database_exists(derived)

    assert not A.database_exists(derived), (
        f"registered database {derived!r} outlived the probe that owned it"
    )


def test_probe_exit_is_idempotent_over_an_already_dropped_database():
    """A check may legitimately drop a registered database itself (again:
    `check_project_removal`). Probe teardown must treat "already gone" as
    done, not as an error -- otherwise the honest cleanup path becomes the
    one that fails.
    """
    with contract.Probe() as p:
        derived = f"{p.name}rm"
        p.register_database(derived)  # registered, but never created

    assert p.leaked == [], f"probe reported leaks for databases that never existed: {p.leaked}"
    assert not A.database_exists(p.name)


def test_drop_project_removes_both_halves(workspace):
    """The suite's own teardown helper, proven against a real project
    rather than trusted.

    A project lives in two independent places -- a directory under
    `AMPLIFIER_WORK_TRACKER_ROOT`, and a database on the shared server.
    Every fixture in conftest.py that creates one calls this; if it only
    removed the first half, the fixtures would look clean while the server
    kept filling up, which is precisely the failure this repo already
    shipped once.
    """
    name = unique_name("residue")
    workspace.create(name)
    assert A.database_exists(name), "sanity: create() must produce a database"
    assert workspace.path(name).exists()

    drop_project(workspace, name)

    assert not A.database_exists(name), f"database {name!r} survived drop_project"
    assert not workspace.path(name).exists(), f"directory for {name!r} survived drop_project"


def test_drop_project_is_a_no_op_for_a_project_that_was_never_created(workspace):
    """Several tests hand a name to a command that is expected to refuse it
    (`new bad.dotted.name`, `remove` of a nonexistent project). Teardown
    runs for those too, and must not turn "there was nothing to remove"
    into a failure -- while still raising for any OTHER failure, which is
    what `adapter.drop_database` guarantees.
    """
    name = unique_name("neverwas")
    assert not A.database_exists(name)

    drop_project(workspace, name)  # must not raise

    assert not A.database_exists(name)
