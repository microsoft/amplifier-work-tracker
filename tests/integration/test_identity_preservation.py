"""Tier 2 -- identity preservation when a second client adopts an existing
database via ``bd init --database name``.

The fix under test (D1): ``adapter.Workspace.create`` now passes
``--database name`` to ``bd init``, so a second client that initializes
against an already-existing server database adopts the server's
``_project_id`` instead of minting a fresh one.  Without the fix, the two
clients would hold divergent ``project_id`` values, silently splitting the
identity.

Each test creates its own project (slow -- several seconds of ``bd init``
against the isolated dolt server) and tears down BOTH the first and
second client's directories plus the shared database.
"""

from __future__ import annotations

import json
import shutil
import uuid

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.integration


@pytest.fixture
def identity_project(workspace, tmp_path_factory):
    """A project created by the primary workspace (client A), plus a second
    workspace root (client B) pointed at the same dolt server.  Teardown
    drops the database and both directories.

    Yields ``(name, workspace_a, workspace_b)`` -- callers can create the
    same project name on workspace_b to test adoption.
    """
    name = f"ident{uuid.uuid4().hex[:12]}"
    workspace.create(name)

    root_b = tmp_path_factory.mktemp("client_b_root")
    ws_b = A.Workspace(root_b)

    yield name, workspace, ws_b

    # teardown: drop the shared database, then both local dirs
    try:
        A.drop_database(name)
    finally:
        shutil.rmtree(workspace.path(name), ignore_errors=True)
        shutil.rmtree(ws_b.path(name), ignore_errors=True)


def _local_project_id(ws: A.Workspace, name: str) -> str:
    """Read the ``project_id`` from a workspace's local ``.beads/metadata.json``."""
    meta_path = ws.path(name) / ".beads" / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return meta["project_id"]


def test_second_client_adopts_server_identity(identity_project):
    """When client B initializes a project whose database already exists on
    the server, the local ``project_id`` MUST match the server's
    ``_project_id`` -- not a freshly minted UUID.
    """
    name, ws_a, ws_b = identity_project

    # Read the authoritative server identity.
    server_id = A._server_project_id(name)
    assert server_id is not None, "server must have a _project_id after creation"

    # Client A's local id should already match the server (sanity).
    local_a = _local_project_id(ws_a, name)
    assert local_a == server_id, (
        f"client A's local id ({local_a}) should match the server ({server_id})"
    )

    # Client B adopts the same project name -- the database already exists.
    ws_b.create(name)

    # The fix: client B's local project_id must equal the server's, not a
    # fresh UUID.
    local_b = _local_project_id(ws_b, name)
    assert local_b == server_id, (
        f"client B adopted a different identity ({local_b}) instead of the "
        f"server's ({server_id}) -- --database flag may not be taking effect"
    )


def test_second_client_can_read_items_created_by_first(identity_project):
    """B can read, and A's identity-checked writes and audit history still work."""
    name, ws_a, ws_b = identity_project
    bd_a = ws_a.project(name)
    item_id = bd_a.create("cross-client witness", tags=[A.LANE_WORK])
    original_id = _local_project_id(ws_a, name)

    # Client B adopts.
    ws_b.create(name)
    bd_b = ws_b.project(name)
    assert _local_project_id(ws_b, name) == original_id
    assert _local_project_id(ws_a, name) == original_id

    items_b = [i.id for i in bd_b.list(include_resolved=True)]
    assert item_id in items_b, (
        f"client B cannot see item {item_id} created by client A -- "
        f"the two clients may not share the same database"
    )

    # SQL listing alone can hide an identity split. Exercise the guarded path.
    note = "client A remains usable after client B adopts"
    resolution = "resolution preserved across the two-client correction cycle"
    bd_a.comment(item_id, note, actor="client_a")
    closed = bd_a.resolve(item_id, resolution, actor="client_a")
    assert closed.closed_at is not None
    reopened = bd_a.reopen(item_id, "verify both clients remain usable", actor="client_a")
    assert reopened.item.status == "open" and reopened.item.holder is None
    assert reopened.previous_resolution == resolution
    assert reopened.previous_closed_at == closed.closed_at
    comments = "\n".join(e.detail or "" for e in bd_a.activity(item_id) if e.kind == "comment")
    assert note in comments and resolution in comments
    assert closed.closed_at.isoformat() in comments
