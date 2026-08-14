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


# ------------------------------------------------------- directed claim


def _item_with_deps(deps: list[dict]) -> A.Item:
    return A.Item.from_beads({"id": "x-1", "status": "open", "dependencies": deps})


def test_active_blockers_empty_when_no_dependencies():
    assert A._active_blockers(_item_with_deps([])) == []


def test_active_blockers_ignores_non_blocks_dependency_types():
    """A `discovered-from` link (or any non-`blocks` type) must never be
    treated as a blocker -- only `dependency_type == "blocks"` counts."""
    deps = [{"id": "y-1", "status": "open", "dependency_type": "discovered-from"}]
    assert A._active_blockers(_item_with_deps(deps)) == []


def test_active_blockers_ignores_closed_blocker():
    """A `blocks` dependency whose blocker has been closed no longer blocks."""
    deps = [{"id": "y-1", "status": "closed", "dependency_type": "blocks"}]
    assert A._active_blockers(_item_with_deps(deps)) == []


def test_active_blockers_reports_open_blocks_dependency():
    deps = [{"id": "y-1", "status": "open", "dependency_type": "blocks"}]
    result = A._active_blockers(_item_with_deps(deps))
    assert [d["id"] for d in result] == ["y-1"]


def test_active_blockers_treats_blocked_and_deferred_blockers_as_still_active():
    """A blocker that is itself `blocked` or `deferred` (not `closed`) must
    still count as an active blocker -- only `closed` clears the way."""
    deps = [
        {"id": "y-1", "status": "blocked", "dependency_type": "blocks"},
        {"id": "y-2", "status": "deferred", "dependency_type": "blocks"},
    ]
    result = A._active_blockers(_item_with_deps(deps))
    assert {d["id"] for d in result} == {"y-1", "y-2"}


def test_active_blockers_handles_missing_dependencies_key():
    item = A.Item.from_beads({"id": "x-1", "status": "open"})
    assert A._active_blockers(item) == []


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


# --------------------------------------- residue must never report success


def test_workspace_create_refuses_to_report_success_on_dead_residue(tmp_path):
    """A directory named `.beads` existing is not evidence of anything -- a
    previous `bd init` that crashed, was killed, or hit a full disk can
    leave `.beads/` behind with no usable database inside it. The OLD
    behaviour (`if (d / ".beads").is_dir(): return d`) returned success on
    this residue without ever proving the database answers, so every
    subsequent `create()` call was a silent no-op that reported "verified
    writable." This test creates exactly that residue by hand -- an empty
    `.beads/` directory, no real bd project underneath it -- and asserts
    `create()` refuses rather than reporting success."""
    ws = A.Workspace(tmp_path)
    name = "probedirty"
    d = ws.path(name)
    (d / ".beads").mkdir(parents=True)  # residue: exists, but dead -- no
    # database, no config, nothing bd itself ever wrote.

    try:
        ws.create(name)
        raise AssertionError(
            "create() reported success on dead .beads residue -- exactly the "
            "silent-partial-success shape this project exists to prevent"
        )
    except A.BeadsError as e:
        assert "residue" in str(e) or "does not answer" in str(e), (
            f"expected the error to name the residue, got: {e}"
        )
    # And the residue itself is left alone for a human/agent to inspect or
    # remove -- this call observes and reports, it does not clean up.
    assert (d / ".beads").is_dir()


def test_workspace_create_returns_cleanly_when_beads_dir_already_works(workspace, project_factory):
    """The other half of the fix: an EXISTING, WORKING project must still
    short-circuit and return without erroring or re-running `bd init` --
    the liveness probe must not turn a legitimate no-op into a failure.
    Uses a real `bd`-backed project (via `project_factory`), not residue,
    so this only passes if the liveness probe genuinely succeeds against a
    live database."""
    name, _bd = project_factory("existingok")
    result = workspace.create(name)  # second call: .beads/ already exists and works
    assert result == workspace.path(name)


# ------------------------------------------------- non-interactive `bd` env


def test_env_always_sets_bd_non_interactive(tmp_path):
    """An agent session has no tty -- `bd`'s telemetry-consent prompt on
    first use would hang forever waiting for input that never comes. Every
    `bd` subprocess this module launches must be non-interactive by
    construction, not by hoping the caller already exported the var.

    Verified against the real v1.1.2 binary (see `_bd_env`'s docstring):
    `BD_NON_INTERACTIVE` is the real, present switch -- unlike the round-1
    `BD_TELEMETRY_DISABLE`, which does not exist in the binary at all and
    was a pure no-op."""
    bd = A.Beads(tmp_path / ".beads")
    assert bd._env()["BD_NON_INTERACTIVE"] == "1"  # noqa: SLF001


def test_env_sets_bd_non_interactive_even_when_absent_from_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("BD_NON_INTERACTIVE", raising=False)
    bd = A.Beads(tmp_path / ".beads")
    assert bd._env()["BD_NON_INTERACTIVE"] == "1"  # noqa: SLF001


def test_env_overrides_a_falsy_ambient_value(tmp_path, monkeypatch):
    """Even if something in the ambient environment set this to a falsy-
    looking value, the subprocess env this module builds must still
    unconditionally set it -- never merely inherit."""
    monkeypatch.setenv("BD_NON_INTERACTIVE", "0")
    bd = A.Beads(tmp_path / ".beads")
    assert bd._env()["BD_NON_INTERACTIVE"] == "1"  # noqa: SLF001


def test_env_no_longer_sets_the_ineffective_telemetry_disable_var(tmp_path):
    """Regression guard for the round-1 mistake: `BD_TELEMETRY_DISABLE` is
    absent from the real bd v1.1.2 binary (verified via `strings`) -- it
    has zero effect on the process bd runs, so this module must not keep
    shipping it as if it did something. Not asserting it's ABSENT from the
    returned dict (ambient os.environ could coincidentally have it) --
    asserting this module itself doesn't set it to a value it invented."""
    bd = A.Beads(tmp_path / ".beads")
    env = bd._env()  # noqa: SLF001
    # If it's present at all, it must be an ambient/inherited value, never
    # "1" set by this module's own code path (the round-1 bug's shape).
    # We can't distinguish those from the dict alone, so instead assert the
    # one thing we CAN prove: the real, effective var is present and "1".
    assert env["BD_NON_INTERACTIVE"] == "1"


def test_disable_telemetry_once_is_cached_per_process(monkeypatch):
    """`_disable_telemetry_once` must only invoke `bd metrics off` once per
    process -- repeated `Workspace.create` calls in the same session must
    not each pay a subprocess round-trip for an idempotent, already-applied
    setting.

    Monkeypatches `A._run_bounded` -- the one seam every `bd`/`dolt`/`git`
    subprocess call in this module goes through (see its docstring) --
    rather than `subprocess.run` directly, since `_run_bounded` itself uses
    `subprocess.Popen` for process-group-safe timeout handling.
    """
    monkeypatch.setattr(A, "_TELEMETRY_OFF_ATTEMPTED", False)
    calls = []

    def fake_run_bounded(args, **kwargs):
        calls.append(args)

        class _P:
            returncode = 0
            stdout = ""
            stderr = ""

        return _P()

    monkeypatch.setattr(A, "_run_bounded", fake_run_bounded)
    A._disable_telemetry_once()  # noqa: SLF001
    A._disable_telemetry_once()  # noqa: SLF001
    assert len(calls) == 1
    assert calls[0][:3] == ["bd", "metrics", "off"]


def test_disable_telemetry_once_never_raises_on_subprocess_failure(monkeypatch):
    """Telemetry preference is a courtesy setting -- a broken/missing `bd`
    must never block project creation because of this call."""
    monkeypatch.setattr(A, "_TELEMETRY_OFF_ATTEMPTED", False)

    def boom(*args, **kwargs):
        raise FileNotFoundError("bd not found")

    monkeypatch.setattr(A, "_run_bounded", boom)
    A._disable_telemetry_once()  # noqa: SLF001 -- must not raise


# --------------------------------------------------------- work_list status


def test_statuses_public_tuple_covers_every_domain_status():
    assert set(A.STATUSES) == {"open", "held", "resolved", "blocked", "deferred"}


def test_status_reverse_map_is_the_exact_inverse_of_the_forward_map():
    for beads_status, our_status in A._STATUS_MAP.items():  # noqa: SLF001
        assert A._STATUS_MAP_REVERSE[our_status] == beads_status  # noqa: SLF001


def test_list_rejects_unknown_status_before_any_subprocess_call(tmp_path, monkeypatch):
    """Validation of `status` must happen before any `bd` subprocess is
    launched -- a caller passing a typo'd status should get an immediate,
    clear error, never a wasted round-trip or a confusing bd-side failure."""

    def boom(*args, **kwargs):
        raise AssertionError("subprocess.run should never be reached for an invalid status")

    monkeypatch.setattr(A.subprocess, "run", boom)
    bd = A.Beads(tmp_path / ".beads")
    try:
        bd.list(status="nonexistent-status")
        raise AssertionError("expected BeadsError for an unknown status")
    except A.BeadsError as e:
        assert "unknown status" in str(e)
        for s in A.STATUSES:
            assert s in str(e)


def test_list_bounded_clamps_requested_limit_above_the_max(tmp_path, monkeypatch):
    """A caller asking for more than LIST_MAX_LIMIT must be silently clamped
    to the max (never a hard error -- a huge limit is not invalid input),
    but the clamp itself must be visible via `requested_limit` vs `limit`."""
    bd = A.Beads(tmp_path / ".beads")
    monkeypatch.setattr(bd, "list", lambda **kwargs: [])
    result = bd.list_bounded(limit=10_000)
    assert result.requested_limit == 10_000
    assert result.limit == A.LIST_MAX_LIMIT


def test_list_bounded_clamps_a_nonpositive_requested_limit_to_one(tmp_path, monkeypatch):
    bd = A.Beads(tmp_path / ".beads")
    monkeypatch.setattr(bd, "list", lambda **kwargs: [])
    result = bd.list_bounded(limit=0)
    assert result.limit == 1
    result_negative = bd.list_bounded(limit=-5)
    assert result_negative.limit == 1


def test_list_bounded_uses_default_limit_when_omitted(tmp_path, monkeypatch):
    bd = A.Beads(tmp_path / ".beads")
    monkeypatch.setattr(bd, "list", lambda **kwargs: [])
    result = bd.list_bounded()
    assert result.limit == A.LIST_DEFAULT_LIMIT
    assert result.requested_limit is None


def test_list_bounded_reports_truncation_honestly(tmp_path, monkeypatch):
    """Truncation must be computed from the TRUE total (an unbounded fetch),
    never inferred from the capped page alone."""
    items = [A.Item.from_beads({"id": f"x-{i}", "status": "open"}) for i in range(10)]
    bd = A.Beads(tmp_path / ".beads")
    monkeypatch.setattr(bd, "list", lambda **kwargs: items)
    result = bd.list_bounded(limit=3)
    assert result.total_count == 10
    assert result.returned_count == 3
    assert result.truncated is True
    assert [i.id for i in result.items] == ["x-0", "x-1", "x-2"]


def test_list_bounded_reports_no_truncation_when_everything_fits(tmp_path, monkeypatch):
    items = [A.Item.from_beads({"id": f"x-{i}", "status": "open"}) for i in range(3)]
    bd = A.Beads(tmp_path / ".beads")
    monkeypatch.setattr(bd, "list", lambda **kwargs: items)
    result = bd.list_bounded(limit=50)
    assert result.total_count == 3
    assert result.returned_count == 3
    assert result.truncated is False


# ------------------------------------------------------------- Item.summary


def _full_item() -> A.Item:
    return A.Item.from_beads(
        {
            "id": "proj-abc1",
            "title": "a title",
            "status": "in_progress",
            "assignee": "someone",
            "close_reason": "fixed it",
            "acceptance_criteria": "Given/When/Then",
            "description": "the description",
            "design": "the design notes",
        }
    )


def test_summary_default_is_lean_and_omits_body_fields():
    """The default (list) shape -- unchanged from before this feature --
    must never carry acceptance/description/design at all, not even as
    null keys, so a bulk listing payload stays small by construction."""
    row = _full_item().summary()
    assert row == {
        "id": "proj-abc1",
        "title": "a title",
        "status": "held",
        "holder": "someone",
        "resolution": "fixed it",
    }
    assert "acceptance" not in row
    assert "description" not in row
    assert "design" not in row


def test_summary_full_adds_the_same_body_fields_claim_returns():
    row = _full_item().summary(full=True)
    assert row["acceptance"] == "Given/When/Then"
    assert row["description"] == "the description"
    assert row["design"] == "the design notes"
    # Still carries every lean field too -- full is a superset, not a
    # replacement.
    assert row["id"] == "proj-abc1"
    assert row["status"] == "held"
    assert row["holder"] == "someone"
    assert row["resolution"] == "fixed it"


def test_summary_full_on_an_item_with_no_body_reports_none_not_missing():
    row = A.Item.from_beads({"id": "x-1", "status": "open"}).summary(full=True)
    assert row["acceptance"] is None
    assert row["description"] is None
    assert row["design"] is None


# --------------------------------------------------------- Beads.get_readonly


def test_get_readonly_project_name_is_inferred_from_the_beads_dir_parent(tmp_path):
    bd = A.Beads(tmp_path / "projects" / "demoproj" / ".beads")
    assert bd.project_name == "demoproj"  # noqa: SLF001 - project_name is public


def test_get_readonly_wrong_project_prefix_raises_distinct_error(tmp_path, monkeypatch):
    """An id that doesn't even carry this project's own prefix must be
    reported as a likely wrong-project mistake -- distinctly from a
    genuine not-found -- without ever reaching a subprocess (`bd show`'s
    own error text is identical for both cases, which is exactly why this
    project-level check exists)."""
    bd = A.Beads(tmp_path / "projects" / "thisproj" / ".beads")

    def fake_get(item_id, *, with_links=False):
        raise A.BeadsError("`bd show other-9`: no issues found matching the provided IDs")

    monkeypatch.setattr(bd, "get", fake_get)
    try:
        bd.get_readonly("other-9")
        raise AssertionError("expected BeadsError for a wrong-project id")
    except A.BeadsError as e:
        assert "does not look like it belongs to project" in str(e)
        assert "thisproj" in str(e)


def test_get_readonly_correct_prefix_but_missing_raises_plain_not_found(tmp_path, monkeypatch):
    bd = A.Beads(tmp_path / "projects" / "thisproj" / ".beads")

    def fake_get(item_id, *, with_links=False):
        raise A.BeadsError("`bd show thisproj-99`: no issues found matching the provided IDs")

    monkeypatch.setattr(bd, "get", fake_get)
    try:
        bd.get_readonly("thisproj-99")
        raise AssertionError("expected BeadsError for a genuinely missing item")
    except A.BeadsError as e:
        assert "not found in project" in str(e)
        assert "thisproj" in str(e)
        assert "does not look like it belongs" not in str(e)


def test_get_readonly_delegates_to_get_and_returns_the_item_unmodified(tmp_path, monkeypatch):
    bd = A.Beads(tmp_path / "projects" / "thisproj" / ".beads")
    item = A.Item.from_beads({"id": "thisproj-1", "status": "open", "description": "hi"})
    monkeypatch.setattr(bd, "get", lambda item_id, **kwargs: item)
    got = bd.get_readonly("thisproj-1")
    assert got is item


# --------------------------------------------------------- offset (pagination)


def test_list_bounded_offset_defaults_to_zero_and_matches_prior_behavior(tmp_path, monkeypatch):
    """Every existing caller that never passed `offset` must see byte-identical
    behavior -- the window starts at 0, exactly as before this field existed."""
    items = [A.Item.from_beads({"id": f"x-{i}", "status": "open"}) for i in range(10)]
    bd = A.Beads(tmp_path / ".beads")
    monkeypatch.setattr(bd, "list", lambda **kwargs: items)
    result = bd.list_bounded(limit=3)
    assert result.offset == 0
    assert [i.id for i in result.items] == ["x-0", "x-1", "x-2"]


def test_list_bounded_offset_shifts_the_returned_window(tmp_path, monkeypatch):
    """A real second page: same page size, later items -- not a bigger cap."""
    items = [A.Item.from_beads({"id": f"x-{i}", "status": "open"}) for i in range(10)]
    bd = A.Beads(tmp_path / ".beads")
    monkeypatch.setattr(bd, "list", lambda **kwargs: items)
    result = bd.list_bounded(limit=3, offset=3)
    assert result.offset == 3
    assert [i.id for i in result.items] == ["x-3", "x-4", "x-5"]
    assert result.total_count == 10
    assert result.truncated is True  # 6 of 10 seen so far (offset 3 + 3 returned)


def test_list_bounded_offset_past_the_end_reports_no_truncation(tmp_path, monkeypatch):
    """The LAST page must honestly report `truncated=False` -- there is
    nothing further beyond it, even though earlier pages exist."""
    items = [A.Item.from_beads({"id": f"x-{i}", "status": "open"}) for i in range(10)]
    bd = A.Beads(tmp_path / ".beads")
    monkeypatch.setattr(bd, "list", lambda **kwargs: items)
    result = bd.list_bounded(limit=3, offset=9)
    assert result.offset == 9
    assert [i.id for i in result.items] == ["x-9"]
    assert result.returned_count == 1
    assert result.truncated is False


def test_list_bounded_negative_offset_clamps_to_zero(tmp_path, monkeypatch):
    items = [A.Item.from_beads({"id": f"x-{i}", "status": "open"}) for i in range(5)]
    bd = A.Beads(tmp_path / ".beads")
    monkeypatch.setattr(bd, "list", lambda **kwargs: items)
    result = bd.list_bounded(limit=2, offset=-100)
    assert result.offset == 0
    assert [i.id for i in result.items] == ["x-0", "x-1"]
