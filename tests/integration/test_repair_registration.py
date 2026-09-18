"""Tier 2 -- ``Workspace.repair_registration``, against the real ``bd``
binary and a real (isolated) shared dolt server.

``repair_registration`` rewrites a stale local ``project_id`` in
``.beads/metadata.json`` to match the server's authoritative
``_project_id``.  It is operator-only, guarded by six mandatory inputs
that force the caller to demonstrate knowledge of both the stale and
correct state before any mutation.

Tests cover:
  - Dry-run diagnosis (no write, correct report).
  - Apply with post-check (metadata rewritten, backup created).
  - Every guard refusal (wrong expected ids, missing witness, endpoint
    mismatch, symlink escape, concurrent lock).
  - Rollback path (post-check failure restores original bytes).
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

import pytest

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import supervisor as SV

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repair_project(workspace):
    """A real project with one item, plus a corrupted local ``project_id``
    that diverges from the server's.

    Yields a dict with every value a test needs to call
    ``repair_registration`` or assert against its result.
    """
    name = f"repair{uuid.uuid4().hex[:12]}"
    workspace.create(name)
    bd = workspace.project(name)
    item_id = bd.create("witness item", tags=[A.LANE_WORK], description="for corroboration")

    beads_dir = workspace.path(name) / ".beads"
    meta_path = beads_dir / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    server_id = A._server_project_id(name)
    assert server_id is not None

    # Corrupt the local project_id to simulate the pre-fix drift.
    original_id = meta["project_id"]
    stale_id = str(uuid.uuid4())
    assert stale_id != server_id  # astronomically unlikely, but be safe
    meta["project_id"] = stale_id
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    host = SV.DEFAULT_DOLT_HOST
    port = SV.DEFAULT_DOLT_PORT

    yield {
        "name": name,
        "workspace": workspace,
        "beads_dir": beads_dir,
        "meta_path": meta_path,
        "original_id": original_id,
        "stale_id": stale_id,
        "server_id": server_id,
        "item_id": item_id,
        "host": host,
        "port": port,
    }

    # teardown
    try:
        A.drop_database(name)
    finally:
        shutil.rmtree(workspace.path(name), ignore_errors=True)


def _apply_repair(p):
    return p["workspace"].repair_registration(
        p["name"],
        host=p["host"],
        port=p["port"],
        expected_local_id=p["stale_id"],
        expected_server_id=p["server_id"],
        witness_item_id=p["item_id"],
        apply=True,
    )


def _assert_repair_lock_cleaned(p):
    assert not (p["workspace"].path(p["name"]) / ".repair.lock").exists()


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


def test_dry_run_diagnoses_without_writing(repair_project):
    """Dry-run (the default) returns a correct ``RepairReport`` but does NOT
    modify ``metadata.json``."""
    p = repair_project
    ws = p["workspace"]

    report = ws.repair_registration(
        p["name"],
        host=p["host"],
        port=p["port"],
        expected_local_id=p["stale_id"],
        expected_server_id=p["server_id"],
        witness_item_id=p["item_id"],
        apply=False,
    )

    assert report.dry_run is True
    assert report.applied is False
    assert report.rolled_back is False
    assert report.old_local_id == p["stale_id"]
    assert report.new_local_id == p["server_id"]
    assert report.server_id == p["server_id"]
    assert report.witness_item_id == p["item_id"]
    assert report.backup_path is None

    # Metadata must still hold the stale id -- no write happened.
    meta = json.loads(p["meta_path"].read_text(encoding="utf-8"))
    assert meta["project_id"] == p["stale_id"]


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def test_apply_rewrites_metadata_and_creates_backup(repair_project):
    """``apply=True`` replaces ``project_id`` in ``metadata.json`` with the
    server's ``_project_id`` and creates a timestamped backup of the
    original file."""
    p = repair_project
    ws = p["workspace"]

    report = ws.repair_registration(
        p["name"],
        host=p["host"],
        port=p["port"],
        expected_local_id=p["stale_id"],
        expected_server_id=p["server_id"],
        witness_item_id=p["item_id"],
        apply=True,
    )

    assert report.dry_run is False
    assert report.applied is True
    assert report.rolled_back is False
    assert report.old_local_id == p["stale_id"]
    assert report.new_local_id == p["server_id"]

    # Metadata now holds the server's identity.
    meta = json.loads(p["meta_path"].read_text(encoding="utf-8"))
    assert meta["project_id"] == p["server_id"]

    # A backup was created and contains the original (stale) metadata.
    assert report.backup_path is not None
    assert report.backup_path.is_file()
    backup = json.loads(report.backup_path.read_text(encoding="utf-8"))
    assert backup["project_id"] == p["stale_id"]


def test_apply_with_witness_title(repair_project):
    """When ``witness_title`` is provided and matches, the repair succeeds."""
    p = repair_project
    ws = p["workspace"]

    report = ws.repair_registration(
        p["name"],
        host=p["host"],
        port=p["port"],
        expected_local_id=p["stale_id"],
        expected_server_id=p["server_id"],
        witness_item_id=p["item_id"],
        witness_title="witness item",
        apply=True,
    )

    assert report.applied is True
    assert report.witness_title == "witness item"


# ---------------------------------------------------------------------------
# Guard refusals
# ---------------------------------------------------------------------------


def test_refuses_wrong_expected_local_id(repair_project):
    """If the caller's ``expected_local_id`` doesn't match what's actually
    in the metadata, the repair is refused."""
    p = repair_project
    with pytest.raises(A.BeadsError, match="local project_id mismatch"):
        p["workspace"].repair_registration(
            p["name"],
            host=p["host"],
            port=p["port"],
            expected_local_id=str(uuid.uuid4()),  # wrong
            expected_server_id=p["server_id"],
            witness_item_id=p["item_id"],
        )


def test_refuses_wrong_expected_server_id(repair_project):
    """If the caller's ``expected_server_id`` doesn't match the server's
    actual ``_project_id``, the repair is refused."""
    p = repair_project
    with pytest.raises(A.BeadsError, match="server _project_id mismatch"):
        p["workspace"].repair_registration(
            p["name"],
            host=p["host"],
            port=p["port"],
            expected_local_id=p["stale_id"],
            expected_server_id=str(uuid.uuid4()),  # wrong
            witness_item_id=p["item_id"],
        )


def test_refuses_missing_witness(repair_project):
    """If the witness item doesn't exist in the database, the repair is
    refused."""
    p = repair_project
    with pytest.raises(A.BeadsError, match="witness item.*not found"):
        p["workspace"].repair_registration(
            p["name"],
            host=p["host"],
            port=p["port"],
            expected_local_id=p["stale_id"],
            expected_server_id=p["server_id"],
            witness_item_id="nonexistent_item_id",
        )


def test_refuses_wrong_witness_title(repair_project):
    """If the witness title doesn't match the actual item, the repair is
    refused."""
    p = repair_project
    with pytest.raises(A.BeadsError, match="witness title mismatch"):
        p["workspace"].repair_registration(
            p["name"],
            host=p["host"],
            port=p["port"],
            expected_local_id=p["stale_id"],
            expected_server_id=p["server_id"],
            witness_item_id=p["item_id"],
            witness_title="completely wrong title",
        )


def test_refuses_endpoint_mismatch(repair_project):
    """If the metadata's endpoint (host:port) doesn't match the arguments,
    the repair is refused."""
    p = repair_project
    with pytest.raises(A.BeadsError, match="endpoint mismatch"):
        p["workspace"].repair_registration(
            p["name"],
            host="wrong.host.example.com",
            port=9999,
            expected_local_id=p["stale_id"],
            expected_server_id=p["server_id"],
            witness_item_id=p["item_id"],
        )


def test_refuses_invalid_uuid_for_expected_local_id(repair_project):
    """Non-UUID expected_local_id is rejected before any I/O."""
    p = repair_project
    with pytest.raises(A.BeadsError, match="not a valid UUID"):
        p["workspace"].repair_registration(
            p["name"],
            host=p["host"],
            port=p["port"],
            expected_local_id="not-a-uuid",
            expected_server_id=p["server_id"],
            witness_item_id=p["item_id"],
        )


def test_refuses_invalid_uuid_for_expected_server_id(repair_project):
    """Non-UUID expected_server_id is rejected before any I/O."""
    p = repair_project
    with pytest.raises(A.BeadsError, match="not a valid UUID"):
        p["workspace"].repair_registration(
            p["name"],
            host=p["host"],
            port=p["port"],
            expected_local_id=p["stale_id"],
            expected_server_id="not-a-uuid",
            witness_item_id=p["item_id"],
        )


def test_refuses_symlink_beads_dir(repair_project):
    """If ``.beads`` is a symlink, the repair is refused (symlink escape
    guard)."""
    p = repair_project
    beads_dir = p["beads_dir"]
    real_dir = beads_dir.parent / ".beads_real"
    beads_dir.rename(real_dir)
    beads_dir.symlink_to(real_dir)
    try:
        with pytest.raises(A.BeadsError, match="symlink"):
            p["workspace"].repair_registration(
                p["name"],
                host=p["host"],
                port=p["port"],
                expected_local_id=p["stale_id"],
                expected_server_id=p["server_id"],
                witness_item_id=p["item_id"],
            )
    finally:
        beads_dir.unlink()
        real_dir.rename(beads_dir)


def test_refuses_concurrent_repair_lock(repair_project):
    """If a ``.repair.lock`` exists (any PID), the repair is refused --
    conservative: no dead-lock healing."""
    p = repair_project
    lock_path = p["workspace"].path(p["name"]) / ".repair.lock"
    # Write our own PID -- guaranteed alive.
    lock_path.write_text(str(os.getpid()))
    try:
        with pytest.raises(A.BeadsError, match="existing repair lock"):
            p["workspace"].repair_registration(
                p["name"],
                host=p["host"],
                port=p["port"],
                expected_local_id=p["stale_id"],
                expected_server_id=p["server_id"],
                witness_item_id=p["item_id"],
                apply=True,
            )
    finally:
        lock_path.unlink(missing_ok=True)


def test_refuses_dead_repair_lock(repair_project):
    """A ``.repair.lock`` with a dead PID is also refused -- no dead-lock
    healing (conservative: operator must remove stale locks manually)."""
    p = repair_project
    lock_path = p["workspace"].path(p["name"]) / ".repair.lock"
    # PID 2^30 is almost certainly dead.
    lock_path.write_text(str(2**30))
    try:
        with pytest.raises(A.BeadsError, match="existing repair lock"):
            p["workspace"].repair_registration(
                p["name"],
                host=p["host"],
                port=p["port"],
                expected_local_id=p["stale_id"],
                expected_server_id=p["server_id"],
                witness_item_id=p["item_id"],
                apply=True,
            )
    finally:
        lock_path.unlink(missing_ok=True)


def test_lock_cleaned_up_after_apply(repair_project):
    """The ``.repair.lock`` must not survive a successful apply."""
    p = repair_project
    lock_path = p["workspace"].path(p["name"]) / ".repair.lock"

    p["workspace"].repair_registration(
        p["name"],
        host=p["host"],
        port=p["port"],
        expected_local_id=p["stale_id"],
        expected_server_id=p["server_id"],
        witness_item_id=p["item_id"],
        apply=True,
    )

    assert not lock_path.exists(), ".repair.lock must be removed after a successful apply"


# ---------------------------------------------------------------------------
# Post-check and rollback failures
# ---------------------------------------------------------------------------


def test_post_check_server_identity_change_restores_original_metadata_and_mode(
    repair_project, monkeypatch
):
    """A changed post-check identity returns a diagnostic report after restoring
    the exact original bytes and mode; the server is never changed for this test.
    """
    p = repair_project
    meta_path = p["meta_path"]
    os.chmod(meta_path, 0o640)
    original_bytes = meta_path.read_bytes()
    original_mode = meta_path.stat().st_mode & 0o7777
    original_reader = A._server_project_id
    calls = 0

    def changed_on_post_check(name):
        nonlocal calls
        calls += 1
        return str(uuid.uuid4()) if calls == 2 else original_reader(name)

    monkeypatch.setattr(A, "_server_project_id", changed_on_post_check)
    report = _apply_repair(p)

    assert report.applied is False
    assert report.rolled_back is True
    assert report.metadata_state == "original"
    assert report.verification_failure == (
        "post-check server _project_id does not match the expected identity"
    )
    assert report.rollback_failure is None
    assert report.rollback_refusal is None
    assert meta_path.read_bytes() == original_bytes
    assert meta_path.stat().st_mode & 0o7777 == original_mode
    assert report.backup_path is not None
    assert report.backup_path.read_bytes() == original_bytes
    assert report.backup_path.stat().st_mode & 0o7777 == original_mode
    _assert_repair_lock_cleaned(p)


def test_post_check_exception_is_reported_and_rolls_back(repair_project, monkeypatch):
    """An exception in the post-check follows the real rollback path and is
    retained in the returned report rather than escaping as a false success.
    """
    p = repair_project
    original_reader = A._server_project_id
    calls = 0

    def raise_on_post_check(name):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected post-check read failure")
        return original_reader(name)

    monkeypatch.setattr(A, "_server_project_id", raise_on_post_check)
    report = _apply_repair(p)

    assert report.applied is False
    assert report.rolled_back is True
    assert report.metadata_state == "original"
    assert report.verification_failure == (
        "post-check raised OSError: injected post-check read failure"
    )
    assert report.rollback_failure is None
    assert report.rollback_refusal is None
    _assert_repair_lock_cleaned(p)


def test_rollback_write_failure_reports_repaired_bytes_left_in_place(repair_project, monkeypatch):
    """If restoration fails, final readback must report the still-repaired bytes
    and retain the exact backup instead of claiming a rollback occurred.
    """
    p = repair_project
    meta_path = p["meta_path"]
    original_bytes = meta_path.read_bytes()
    original_writer = A._atomic_write_metadata
    original_reader = A._server_project_id
    calls = 0

    def changed_on_post_check(name):
        nonlocal calls
        calls += 1
        return str(uuid.uuid4()) if calls == 2 else original_reader(name)

    def fail_only_restore(path, data, *, mode):
        if path == meta_path and data == original_bytes:
            raise OSError("injected restore write failure")
        original_writer(path, data, mode=mode)

    monkeypatch.setattr(A, "_server_project_id", changed_on_post_check)
    monkeypatch.setattr(A, "_atomic_write_metadata", fail_only_restore)
    report = _apply_repair(p)

    assert report.applied is False
    assert report.rolled_back is False
    assert report.metadata_state == "repaired"
    assert report.rollback_failure == (
        "could not restore original metadata: OSError: injected restore write failure"
    )
    assert report.rollback_refusal is None
    assert json.loads(meta_path.read_text(encoding="utf-8"))["project_id"] == p["server_id"]
    assert report.backup_path is not None
    assert report.backup_path.read_bytes() == original_bytes
    _assert_repair_lock_cleaned(p)


def test_foreign_metadata_is_left_untouched_after_post_check_failure(repair_project, monkeypatch):
    """Guarded rollback refuses to overwrite bytes that appeared after this
    repair, and names them as foreign only after reading them back.
    """
    p = repair_project
    meta_path = p["meta_path"]
    foreign_bytes = b'{"project_id": "foreign-metadata"}\n'
    original_reader = A._server_project_id
    calls = 0

    def replace_with_foreign_metadata_on_post_check(name):
        nonlocal calls
        calls += 1
        if calls == 2:
            meta_path.write_bytes(foreign_bytes)
            return str(uuid.uuid4())
        return original_reader(name)

    monkeypatch.setattr(A, "_server_project_id", replace_with_foreign_metadata_on_post_check)
    report = _apply_repair(p)

    assert report.applied is False
    assert report.rolled_back is False
    assert report.metadata_state == "foreign"
    assert report.rollback_failure is None
    assert report.rollback_refusal == (
        "metadata no longer contains this repair's bytes; refusing to overwrite foreign metadata"
    )
    assert meta_path.read_bytes() == foreign_bytes
    _assert_repair_lock_cleaned(p)


def test_unreadable_final_metadata_state_is_unknown(repair_project, monkeypatch):
    """When guarded rollback cannot read the metadata, the report explicitly
    stays unknown rather than asserting original or repaired bytes.
    """
    p = repair_project
    meta_path = p["meta_path"]
    original_reader = A._server_project_id
    original_writer = A._atomic_write_metadata
    original_read_bytes = Path.read_bytes
    calls = 0
    repair_written = False

    def changed_on_post_check(name):
        nonlocal calls
        calls += 1
        return str(uuid.uuid4()) if calls == 2 else original_reader(name)

    def remember_repair_write(path, data, *, mode):
        nonlocal repair_written
        original_writer(path, data, mode=mode)
        if path == meta_path:
            repair_written = True

    def unreadable_after_repair(path):
        if path == meta_path and repair_written:
            raise OSError("injected final metadata read failure")
        return original_read_bytes(path)

    monkeypatch.setattr(A, "_server_project_id", changed_on_post_check)
    monkeypatch.setattr(A, "_atomic_write_metadata", remember_repair_write)
    monkeypatch.setattr(Path, "read_bytes", unreadable_after_repair)
    report = _apply_repair(p)

    assert report.applied is False
    assert report.rolled_back is False
    assert report.metadata_state == "unknown"
    assert report.rollback_failure == (
        "could not read metadata for guarded rollback: "
        "OSError: injected final metadata read failure"
    )
    assert report.rollback_refusal is None
    _assert_repair_lock_cleaned(p)


# ---------------------------------------------------------------------------
# Invalid project name
# ---------------------------------------------------------------------------


def test_refuses_invalid_project_name(workspace):
    """A project name that doesn't match ``NAME_RE`` is refused."""
    with pytest.raises(A.BeadsError):
        workspace.repair_registration(
            "INVALID-NAME",
            host="localhost",
            port=3306,
            expected_local_id=str(uuid.uuid4()),
            expected_server_id=str(uuid.uuid4()),
            witness_item_id="x",
        )


# ---------------------------------------------------------------------------
# Fix 1: Effective endpoint binding
# ---------------------------------------------------------------------------


def test_refuses_effective_endpoint_mismatch(repair_project):
    """Supplied host:port matches metadata but differs from the actual SQL
    endpoint (supervisor defaults) -- repair must refuse.

    Regression: without this guard, a caller could supply an endpoint that
    passes the metadata check but routes reads through a different server,
    silently writing an identity that disagrees with what future reads see.
    """
    p = repair_project
    meta = json.loads(p["meta_path"].read_text(encoding="utf-8"))

    # Corrupt metadata to point at a fake endpoint that we'll also supply.
    fake_host = "fake.endpoint.test"
    fake_port = 12345
    meta["dolt_server_host"] = fake_host
    meta["dolt_server_port"] = fake_port
    p["meta_path"].write_text(json.dumps(meta, indent=2), encoding="utf-8")

    with pytest.raises(A.BeadsError, match="does not match the actual SQL endpoint"):
        p["workspace"].repair_registration(
            p["name"],
            host=fake_host,
            port=fake_port,
            expected_local_id=p["stale_id"],
            expected_server_id=p["server_id"],
            witness_item_id=p["item_id"],
        )


# ---------------------------------------------------------------------------
# Fix 2: Database mapping guard
# ---------------------------------------------------------------------------


def test_refuses_database_mapping_mismatch(repair_project):
    """Metadata ``dolt_database`` doesn't match the project name --
    repair must refuse.

    Regression: without this guard, a corrupted dolt_database field could
    cause subsequent reads to target the wrong database on the server.
    """
    p = repair_project
    meta = json.loads(p["meta_path"].read_text(encoding="utf-8"))

    # Corrupt dolt_database to differ from the project name.
    meta["dolt_database"] = "wrong_database_name"
    p["meta_path"].write_text(json.dumps(meta, indent=2), encoding="utf-8")

    with pytest.raises(A.BeadsError, match="database mapping mismatch"):
        p["workspace"].repair_registration(
            p["name"],
            host=p["host"],
            port=p["port"],
            expected_local_id=p["stale_id"],
            expected_server_id=p["server_id"],
            witness_item_id=p["item_id"],
        )


# ---------------------------------------------------------------------------
# Fix 3: Atomic and guarded local replacement
# ---------------------------------------------------------------------------


def test_refuses_invalid_host(workspace):
    """Empty or non-string host is rejected at input validation."""
    with pytest.raises(A.BeadsError, match="host must be a non-empty string"):
        workspace.repair_registration(
            "anyproject",
            host="",
            port=3306,
            expected_local_id=str(uuid.uuid4()),
            expected_server_id=str(uuid.uuid4()),
            witness_item_id="x",
        )


def test_refuses_invalid_port(workspace):
    """Port outside 1-65535 is rejected at input validation."""
    with pytest.raises(A.BeadsError, match="port must be in range"):
        workspace.repair_registration(
            "anyproject",
            host="localhost",
            port=0,
            expected_local_id=str(uuid.uuid4()),
            expected_server_id=str(uuid.uuid4()),
            witness_item_id="x",
        )


def test_refuses_symlinked_repair_lock(repair_project):
    """A symlinked ``.repair.lock`` is refused (symlink escape guard)."""
    p = repair_project
    proj_dir = p["workspace"].path(p["name"])
    lock_path = proj_dir / ".repair.lock"
    # Create a symlink pointing at a harmless target.
    target = proj_dir / ".repair.lock.target"
    target.write_text(str(os.getpid()))
    lock_path.symlink_to(target)
    try:
        with pytest.raises(A.BeadsError, match="symlinked repair lock"):
            p["workspace"].repair_registration(
                p["name"],
                host=p["host"],
                port=p["port"],
                expected_local_id=p["stale_id"],
                expected_server_id=p["server_id"],
                witness_item_id=p["item_id"],
                apply=True,
            )
    finally:
        lock_path.unlink(missing_ok=True)
        target.unlink(missing_ok=True)


def test_refuses_any_create_lock(repair_project):
    """ANY ``.create.lock`` (even with a dead PID) causes refusal --
    conservative: operator must remove stale creation locks manually."""
    p = repair_project
    lock_path = p["workspace"].path(p["name"]) / ".create.lock"
    # Dead PID -- previously would have been ignored.
    lock_path.write_text(str(2**30))
    try:
        with pytest.raises(A.BeadsError, match="creation lock"):
            p["workspace"].repair_registration(
                p["name"],
                host=p["host"],
                port=p["port"],
                expected_local_id=p["stale_id"],
                expected_server_id=p["server_id"],
                witness_item_id=p["item_id"],
                apply=True,
            )
    finally:
        lock_path.unlink(missing_ok=True)


def test_refuses_permission_drift_before_lock(repair_project, monkeypatch):
    """A concurrent chmod must not be overwritten by the validated old mode."""
    p = repair_project
    assert p["port"] not in (3308, 13308)
    meta_path = p["meta_path"]
    os.chmod(meta_path, 0o640)
    original_bytes = meta_path.read_bytes()
    original_reader = A._server_project_id
    calls = 0

    def change_mode_after_validation(name):
        nonlocal calls
        result = original_reader(name)
        calls += 1
        if calls == 1:
            os.chmod(meta_path, 0o600)
        return result

    monkeypatch.setattr(A, "_server_project_id", change_mode_after_validation)
    with pytest.raises(A.BeadsError, match="metadata changed"):
        p["workspace"].repair_registration(
            p["name"],
            host=p["host"],
            port=p["port"],
            expected_local_id=p["stale_id"],
            expected_server_id=p["server_id"],
            witness_item_id=p["item_id"],
            apply=True,
        )
    assert meta_path.read_bytes() == original_bytes
    assert meta_path.stat().st_mode & 0o7777 == 0o600
    assert not list(p["beads_dir"].glob("metadata.json.backup-*"))
    assert not (p["workspace"].path(p["name"]) / ".repair.lock").exists()


def test_atomic_write_preserves_permissions(repair_project):
    """After a successful apply, the metadata file retains its original
    Unix permissions (mode bits)."""
    p = repair_project
    meta_path = p["meta_path"]

    # Set a distinctive mode before repair.
    os.chmod(str(meta_path), 0o644)
    mode_before = os.stat(str(meta_path)).st_mode & 0o7777

    report = p["workspace"].repair_registration(
        p["name"],
        host=p["host"],
        port=p["port"],
        expected_local_id=p["stale_id"],
        expected_server_id=p["server_id"],
        witness_item_id=p["item_id"],
        apply=True,
    )
    assert report.applied is True

    mode_after = os.stat(str(meta_path)).st_mode & 0o7777
    assert mode_after == mode_before, (
        f"file permissions changed: {oct(mode_before)} -> {oct(mode_after)}"
    )


def test_apply_preserves_all_metadata_fields(repair_project):
    """Apply must change ONLY ``project_id`` and preserve every other
    field in ``metadata.json`` byte-for-byte (modulo JSON re-serialisation)."""
    p = repair_project
    meta_before = json.loads(p["meta_path"].read_text(encoding="utf-8"))
    preserved_keys = [k for k in meta_before if k != "project_id"]

    report = p["workspace"].repair_registration(
        p["name"],
        host=p["host"],
        port=p["port"],
        expected_local_id=p["stale_id"],
        expected_server_id=p["server_id"],
        witness_item_id=p["item_id"],
        apply=True,
    )
    assert report.applied is True

    meta_after = json.loads(p["meta_path"].read_text(encoding="utf-8"))
    for key in preserved_keys:
        assert meta_after[key] == meta_before[key], (
            f"field {key!r} was mutated: {meta_before[key]!r} -> {meta_after[key]!r}"
        )
