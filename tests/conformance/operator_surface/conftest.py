"""Fixtures for the Tier-A operator-surface conformance kit.

Three datasets, three workspaces
--------------------------------
`contracts/operator-surface.v1.md` defines its Tier-A fixtures against whole
RENDERED PAGES, and two of its clauses (Core 2's calm half, Core 8's
empty-vs-populated comparison) are only meaningful if the page under test
shows *exactly* the dataset the fixture names. L0 Mission Control aggregates
EVERY project in a workspace, so three datasets sharing one workspace root
would each contaminate the others' L0 -- an ALARM project would make the CALM
render alarming, and neither would ever be empty.

So each dataset gets its OWN workspace root (a session-scoped tmp directory)
and its own `webapp.create_app` client:

    CALM   -- ready + resolved items and one FRESH hold. Nothing past custody
              TTL, nothing blocked: the state Core 2 says must paint no alarm.
    ALARM  -- one hold backdated past `custody.CUSTODY_TTL_SECONDS`, plus one
              blocked item: Conformance 2's scenario.
    EMPTY  -- a project with zero items: Conformance 7's all-empty fixture.

Isolation
---------
The dolt SERVER is still the root suite's session-scoped isolated one (see
`tests/conftest.py::isolated_dolt_server`, autouse for the whole session), so
nothing here can reach the shared production server. Only the workspace
DIRECTORY is private to each dataset. Every database created here is dropped
at session end -- `assert_isolated_server_clean` fails the run otherwise, and
that backstop is the reason this file may not skip its own teardown.

Skipping
--------
The static checks in `test_tier_a.py` (Core 4, 5, 9, 10, 11 and the token
halves of 2 and 7) need neither `bd` nor the `web` extra and always run. The
RENDERED checks (Core 1, 3, 8) depend on the fixtures below, which skip
loudly if `bd` or fastapi is missing rather than failing a check about the
operator surface for a reason that has nothing to do with it.
"""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import custody as C

#: Rendered-page fixtures need a real `bd` and the `web` extra. Named once.
_NEEDS_BD = "the `bd` binary is not on PATH -- rendered Tier-A fixtures need real data"


def _unique(prefix: str) -> str:
    """A project name matching `adapter.NAME_RE`, unique per run."""
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _backdate_custody(bd: A.Beads, item_id: str, *, holder: str, seconds_stale: int) -> None:
    """Write a custody record whose `last_seen` is already past the TTL.

    `take_custody`/`renew_custody` always stamp "now", so a stale-custody
    fixture cannot be produced through the public seam. This mirrors the exact
    `bd update --metadata` mechanism those methods themselves use -- the same
    approach `tests/integration/test_observatory_aggregates.py::_set_custody`
    takes, and for the same reason.
    """
    seen = (datetime.now(UTC) - timedelta(seconds=seconds_stale)).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {
        "holder": holder,
        "pid": 1234,
        "host": "conformance-fixture",
        "started_at": seen,
        "last_seen": seen,
        "declared_state": C.STATE_WORKING,
        "declared_since": seen,
        "generation": 1,
    }
    p = bd._run(  # noqa: SLF001 -- fixture setup only, see this function's docstring
        ["update", item_id, "--metadata", json.dumps({C.CUSTODY_KEY: record})],
        actor=holder,
    )
    assert p.returncode == 0, p.stderr


@dataclass(frozen=True)
class Dataset:
    """One rendered-fixture dataset: its own workspace, project and client."""

    label: str
    project: str
    workspace: A.Workspace
    client: object  # starlette.testclient.TestClient -- imported lazily
    item_ids: tuple[str, ...]

    def html(self, path: str) -> str:
        resp = self.client.get(path)  # type: ignore[attr-defined]
        assert resp.status_code == 200, f"{self.label} GET {path} -> {resp.status_code}"
        return resp.text

    @property
    def l0(self) -> str:
        """L0 Mission Control, rendered against this dataset alone."""
        return self.html("/")

    @property
    def l1(self) -> str:
        """L1 Project Observatory for this dataset's project."""
        return self.html(f"/projects/{self.project}")

    def l2(self, item_id: str) -> str:
        """L2 Item Detail."""
        return self.html(f"/projects/{self.project}/items/{item_id}")


def _make_dataset(
    root: Path,
    label: str,
    prefix: str,
    populate: Callable[[A.Beads], tuple[str, ...]],
) -> Iterator[Dataset]:
    """Stand a dataset up in its OWN workspace root, yield it, then drop it."""
    pytest.importorskip("fastapi", reason="the 'web' extra is not installed")
    if shutil.which("bd") is None:
        pytest.skip(_NEEDS_BD)

    from starlette.testclient import TestClient

    from amplifier_work_tracker import webapp
    from amplifier_work_tracker import webauth as WA

    workspace = A.Workspace(root)
    name = _unique(prefix)
    try:
        workspace.create(name)
        item_ids = populate(workspace.project(name))

        auth = WA.AuthConfig(
            mode="password",
            secret="conformance-kit-secret",  # noqa: S106 - test fixture
            ttl_seconds=3600,
            password="conformance-kit-password",  # noqa: S106 - test fixture
        )
        app = webapp.create_app(workspace, auth)
        with TestClient(app, follow_redirects=False) as client:
            resp = client.post(
                "/login",
                data={
                    "username": "operator",
                    "password": "conformance-kit-password",
                    "next": "/",
                },
            )
            assert resp.status_code == 303, resp.text
            yield Dataset(
                label=label,
                project=name,
                workspace=workspace,
                client=client,
                item_ids=item_ids,
            )
    finally:
        # Unconditional: `assert_isolated_server_clean` fails the session for
        # any database that outlives its fixture, and a kit that leaks one is
        # a kit that stops being runnable.
        try:
            A.drop_database(name)
        finally:
            shutil.rmtree(workspace.path(name), ignore_errors=True)


@pytest.fixture(scope="session")
def calm_dataset(tmp_path_factory) -> Iterator[Dataset]:
    """Nothing held past TTL, nothing blocked -- Core 2's calm screen."""

    def populate(bd: A.Beads) -> tuple[str, str, str]:
        ready = bd.create("Calm ready item", tags=[A.LANE_WORK], description="waiting, quietly")
        held = bd.create("Calm held item", tags=[A.LANE_WORK])
        bd.claim_item(held, actor="agent_calm")
        bd.take_custody(held, holder="agent_calm", pid=4321, host="conformance-fixture")
        done = bd.create("Calm resolved item", tags=[A.LANE_WORK])
        bd.resolve(done, "done, and nothing is on fire", actor="agent_calm")
        return (ready, held, done)

    yield from _make_dataset(tmp_path_factory.mktemp("calm_ws"), "CALM", "calm", populate)


@pytest.fixture(scope="session")
def alarm_dataset(tmp_path_factory) -> Iterator[Dataset]:
    """One hold past custody TTL and one blocked item -- Conformance 2."""

    def populate(bd: A.Beads) -> tuple[str, str, str]:
        stale = bd.create("Alarm stale-custody item", tags=[A.LANE_WORK])
        bd.claim_item(stale, actor="agent_stale")
        _backdate_custody(
            bd, stale, holder="agent_stale", seconds_stale=C.CUSTODY_TTL_SECONDS + 1000
        )
        blocked = bd.create("Alarm blocked item", tags=[A.LANE_WORK])
        bd.block(blocked, "waiting on an upstream decision", actor="agent_stale")
        ready = bd.create("Alarm ready item", tags=[A.LANE_WORK])
        return (stale, blocked, ready)

    yield from _make_dataset(tmp_path_factory.mktemp("alarm_ws"), "ALARM", "alarm", populate)


@pytest.fixture(scope="session")
def empty_dataset(tmp_path_factory) -> Iterator[Dataset]:
    """A project with zero items -- Conformance 7's all-empty fixture."""

    def populate(bd: A.Beads) -> tuple[str, ...]:  # noqa: ARG001 - deliberately creates nothing
        return ()

    yield from _make_dataset(tmp_path_factory.mktemp("empty_ws"), "EMPTY", "empty", populate)
