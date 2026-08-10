"""Tier 1 -- amplifier_work_tracker.adapter's pure field/status mapping and
name validation.

`Item.from_beads` and `Workspace.create`'s name check are pure functions of
their inputs; none of this needs bd installed or a real project. The
project-name-validation tests specifically prove the dotted-name guard
fires *before* any subprocess/filesystem work happens (see bug #7 in the
design doc: `bd init` used to report success on a dotted name and then
break every later command).
"""

from __future__ import annotations

from amplifier_work_tracker import adapter as A

# -------------------------------------------------------------- field names


def test_field_mapping_renames_every_declared_field():
    d = {
        "id": "proj-a1b2",
        "title": "fix the thing",
        "status": "open",
        "assignee": "alice",
        "issue_type": "bug",
        "close_reason": "shipped in 2.4.0",
        "acceptance_criteria": "Given/When/Then",
        "description": "it breaks",
        "design": "suspect the cache",
        "labels": ["lane:eng"],
        "metadata": {"reporter_id": "alice"},
        "priority": 1,
    }
    item = A.Item.from_beads(d)
    assert item.id == "proj-a1b2"
    assert item.title == "fix the thing"
    assert item.holder == "alice"  # assignee -> holder
    assert item.kind == "bug"  # issue_type -> kind
    assert item.resolution == "shipped in 2.4.0"  # close_reason -> resolution
    assert item.acceptance == "Given/When/Then"  # acceptance_criteria -> acceptance
    assert item.description == "it breaks"
    assert item.design == "suspect the cache"
    assert item.tags == ["lane:eng"]  # labels -> tags
    assert item.meta == {"reporter_id": "alice"}  # metadata -> meta
    assert item.priority == 1


def test_raw_dict_is_preserved_verbatim():
    d = {"id": "x-1", "status": "open", "some_unmapped_field": 42}
    item = A.Item.from_beads(d)
    assert item.raw == d


# ----------------------------------------------------------------- statuses


def test_known_statuses_are_mapped():
    assert A.Item.from_beads({"id": "x", "status": "open"}).status == "open"
    assert A.Item.from_beads({"id": "x", "status": "in_progress"}).status == "held"
    assert A.Item.from_beads({"id": "x", "status": "closed"}).status == "resolved"
    assert A.Item.from_beads({"id": "x", "status": "blocked"}).status == "blocked"
    assert A.Item.from_beads({"id": "x", "status": "deferred"}).status == "deferred"


def test_unknown_status_passes_through_unchanged():
    """A status Beads introduces tomorrow that we've never seen must show
    up as itself, not be silently coerced into one of our known statuses
    (which would misrepresent it) or collapsed to a generic 'unknown'
    (which would hide what actually happened)."""
    item = A.Item.from_beads({"id": "x", "status": "archived"})
    assert item.status == "archived"


def test_missing_status_defaults_to_unknown():
    item = A.Item.from_beads({"id": "x"})
    assert item.status == "unknown"


# ------------------------------------------------------- defaults & nulls


def test_tags_and_meta_default_to_empty_containers_when_absent():
    item = A.Item.from_beads({"id": "x", "status": "open"})
    assert item.tags == []
    assert item.meta == {}


def test_tags_and_meta_default_to_empty_containers_when_explicitly_null():
    """Beads may send `labels: null` / `metadata: null` rather than
    omitting the key entirely -- both must normalize to safe empty
    containers, never `None` (which would break every `in`/`.get()` call
    downstream)."""
    item = A.Item.from_beads({"id": "x", "status": "open", "labels": None, "metadata": None})
    assert item.tags == []
    assert item.meta == {}


def test_missing_id_defaults_to_empty_string():
    item = A.Item.from_beads({"status": "open"})
    assert item.id == ""


# -------------------------------------------------------------- _retryable


def test_retryable_detects_dolt_conflict_codes():
    assert A._retryable("Error 1213: serialization failure") is True
    assert A._retryable("Error 1205: lock wait timeout") is True
    assert A._retryable("please try restarting transaction") is True


def test_retryable_is_case_insensitive():
    assert A._retryable("SERIALIZATION FAILURE") is True


def test_retryable_false_for_unrelated_errors():
    assert A._retryable("no ready work in lane") is False
    assert A._retryable("") is False


# ------------------------------------------------------------ project names


def test_name_re_accepts_simple_lowercase_name():
    assert A.NAME_RE.match("demoapp")


def test_name_re_rejects_dotted_name():
    """The documented `bd init` landmine: a dotted name reports successful
    creation and then fails every later command. Reject it before any I/O
    happens at all."""
    assert not A.NAME_RE.match("demo.app")


def test_name_re_rejects_uppercase():
    assert not A.NAME_RE.match("DemoApp")


def test_name_re_rejects_single_character():
    assert not A.NAME_RE.match("a")


def test_name_re_accepts_underscores_and_digits():
    assert A.NAME_RE.match("demo_app_2")


def test_workspace_create_rejects_dotted_name_before_touching_disk(tmp_path):
    """The dotted-name guard must fire before `Workspace.create` does any
    filesystem work at all -- not just before it calls `bd`. If the guard
    were only a warning after `mkdir`, we'd be back to bug #7's
    reports-success-then-breaks-forever shape."""
    ws = A.Workspace(tmp_path)
    try:
        ws.create("bad.name")
        raise AssertionError("expected BeadsError for a dotted project name")
    except A.BeadsError as e:
        assert "invalid project name" in str(e)
    assert not (tmp_path / "projects" / "bad.name").exists()


def test_workspace_create_rejects_uppercase_name_before_touching_disk(tmp_path):
    ws = A.Workspace(tmp_path)
    try:
        ws.create("BadName")
        raise AssertionError("expected BeadsError for an uppercase project name")
    except A.BeadsError:
        pass
    assert not (tmp_path / "projects" / "BadName").exists()


# ------------------------------------------------- non-interactive `bd` env


def test_env_always_disables_bd_telemetry_prompt(tmp_path):
    """An agent session has no tty -- `bd`'s telemetry-consent prompt on
    first use would hang forever waiting for input that never comes. Every
    `bd` subprocess this module launches must be non-interactive by
    construction, not by hoping the caller already exported the var."""
    bd = A.Beads(tmp_path / ".beads")
    assert bd._env()["BD_TELEMETRY_DISABLE"] == "1"  # noqa: SLF001


def test_env_disables_bd_telemetry_even_when_absent_from_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("BD_TELEMETRY_DISABLE", raising=False)
    bd = A.Beads(tmp_path / ".beads")
    assert bd._env()["BD_TELEMETRY_DISABLE"] == "1"  # noqa: SLF001


def test_env_overrides_a_falsy_ambient_value(tmp_path, monkeypatch):
    """Even if something in the ambient environment set this to a falsy-
    looking value, the subprocess env this module builds must still
    unconditionally disable telemetry -- never merely inherit."""
    monkeypatch.setenv("BD_TELEMETRY_DISABLE", "0")
    bd = A.Beads(tmp_path / ".beads")
    assert bd._env()["BD_TELEMETRY_DISABLE"] == "1"  # noqa: SLF001
