"""Ratified eleven-tool mounted surface and its three dispatchers.

The compatibility classes remain importable for library callers, but the
runtime mount has exactly the ratified names. Real query cases use this
suite's isolated Dolt fixture; selector failures use no service install.
"""

from __future__ import annotations

import shutil
import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from amplifier_core import ToolResult
from amplifier_module_tool_work_tracker import (
    WorkItemTool,
    WorkQueryTool,
    WorkTrackerSession,
    WorkTrackerTool,
    mount,
)

import amplifier_work_tracker.adapter as A

PROJECT_PREFIX = "surfaceproj"


def _unique(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


class _Coordinator:
    def __init__(self) -> None:
        self.tools: list[Any] = []
        self.capabilities: dict[str, Any] = {}

    async def mount(self, kind: str, tool: Any, *, name: str) -> None:
        assert kind == "tools"
        assert tool.name == name
        self.tools.append(tool)

    def register_capability(self, name: str, value: Any) -> None:
        self.capabilities[name] = value


def _recording_method(calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]], name: str) -> Any:
    async def _method(*args: Any, **kwargs: Any) -> ToolResult:
        calls.append((name, args, kwargs))
        return ToolResult(success=True, output=name)

    return _method


def _assert_strict_object(schema: dict[str, Any]) -> None:
    schema_type = schema.get("type")
    types = {schema_type} if isinstance(schema_type, str) else set(schema_type or ())
    if "null" in types and "enum" in schema:
        assert None in schema["enum"], "Nullable enums must accept null placeholders"
    if "array" in types:
        _assert_strict_object(schema["items"])
    if "object" not in types:
        return
    assert schema["additionalProperties"] is False
    assert schema["required"] == list(schema["properties"])
    for property_schema in schema["properties"].values():
        _assert_strict_object(property_schema)


@pytest.mark.asyncio
async def test_mounts_exactly_the_ratified_eleven_names_and_no_legacy_aliases(tmp_path):
    coordinator = _Coordinator()
    result = await mount(coordinator, {"actor": "surface_probe", "root": str(tmp_path)})
    names = {tool.name for tool in coordinator.tools}
    assert names == {
        "work_claim",
        "work_declare",
        "work_resolve",
        "work_reopen",
        "work_erratum",
        "work_release",
        "work_query",
        "work_item",
        "work_tracker",
        "work_add",
        "work_file",
    }
    assert len(names) == 11
    assert result["provides"] == [tool.name for tool in coordinator.tools]
    assert "work_tracker.reminder_snapshot" in coordinator.capabilities
    for tool in coordinator.tools:
        _assert_strict_object(tool.input_schema)

    schemas = {tool.name: tool.input_schema for tool in coordinator.tools}
    assert schemas["work_query"]["properties"]["kind"]["type"] == "string"
    assert schemas["work_item"]["properties"]["op"]["type"] == "string"
    assert schemas["work_tracker"]["properties"]["op"]["type"] == "string"
    assert schemas["work_query"]["properties"]["project"]["type"] == ["string", "null"]
    assert schemas["work_item"]["properties"]["title"]["type"] == ["string", "null"]
    assert schemas["work_reopen"]["properties"]["claim"]["type"] == ["boolean", "null"]
    assert names.isdisjoint(
        {
            "work_status",
            "work_stats",
            "work_list",
            "work_move",
            "work_edit",
            "work_defer",
            "work_block",
            "work_dep",
            "work_tracker_status",
            "work_tracker_install",
            "work_subscribe",
            "work_unsubscribe",
            "work_subscriptions",
        }
    )


@pytest.mark.asyncio
async def test_item_dispatches_every_ratified_operation_without_reimplementing_it():
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    session = SimpleNamespace(
        move=_recording_method(calls, "move"),
        edit=_recording_method(calls, "edit"),
        defer=_recording_method(calls, "defer"),
        block=_recording_method(calls, "block"),
        dep=_recording_method(calls, "dep"),
    )
    tool = WorkItemTool(session)  # type: ignore[arg-type]
    inputs = (
        ({"op": "move", "item_id": "x", "from_project": "from", "to_project": "to"}, "move"),
        ({"op": "edit", "project": "p", "item_id": "x", "title": "new"}, "edit"),
        ({"op": "defer", "project": "p", "item_id": "x", "reason": "later"}, "defer"),
        ({"op": "block", "project": "p", "item_id": "x", "reason": "waiting"}, "block"),
        ({"op": "dep", "project": "p", "item_id": "x", "depends_on": "y"}, "dep"),
    )
    for input_, expected in inputs:
        result = await tool.execute(input_)
        assert result.success is True
        assert result.output == expected
    assert [name for name, _args, _kwargs in calls] == [expected for _input, expected in inputs]


@pytest.mark.asyncio
async def test_tracker_dispatches_status_and_explicit_install_only():
    calls: list[str] = []

    async def status(_: dict[str, Any]) -> ToolResult:
        calls.append("status")
        return ToolResult(success=True, output="status")

    async def install(_: dict[str, Any]) -> ToolResult:
        calls.append("install")
        return ToolResult(success=True, output="install")

    tracker = WorkTrackerTool(None)
    tracker._status = cast(Any, SimpleNamespace(execute=status))  # noqa: SLF001 -- dispatcher seam
    tracker._install = cast(Any, SimpleNamespace(execute=install))  # noqa: SLF001 -- dispatcher seam
    assert (await tracker.execute({"op": "status"})).output == "status"
    assert (await tracker.execute({"op": "install"})).output == "install"
    assert calls == ["status", "install"]


@pytest.mark.asyncio
async def test_item_and_tracker_selector_errors_are_actionable_and_do_not_crash(tmp_path):
    item = WorkItemTool(WorkTrackerSession({"actor": "surface_probe", "root": str(tmp_path)}))
    for input_, expected in (
        ({}, "op=move, edit, defer, block, or dep"),
        ({"op": "move", "item_id": "x"}, "from_project, to_project"),
        ({"op": "defer", "project": "p", "item_id": "x"}, "reason (unless clear=true)"),
    ):
        result = await item.execute(input_)
        assert result.success is False
        assert expected in str(result.output)

    tracker = WorkTrackerTool({"root": str(tmp_path)})
    for input_ in ({}, {"op": "restart"}):
        result = await tracker.execute(input_)
        assert result.success is False
        assert "op=status or install" in str(result.output)


@pytest.mark.asyncio
@pytest.mark.skipif(
    shutil.which("bd") is None, reason="real `bd` binary not present in this environment"
)
async def test_query_dispatches_all_four_forms_and_item_read_is_passive(project):
    adder = WorkTrackerSession({"actor": _unique("adder")})
    added = await adder.add(
        project,
        "query item",
        description="read without claiming",
        acceptance="Given an item, When queried, Then it remains open",
    )
    item_id = added.output["added"]  # type: ignore[index]
    query_session = WorkTrackerSession({"actor": _unique("query")})
    query = WorkQueryTool(query_session)

    status = await query.execute({"kind": "status"})
    stats = await query.execute({"kind": "stats", "project": project})
    listed = await query.execute({"kind": "list", "project": project, "status": "open"})
    before = A.Workspace(query_session._ws.root).project(project).get(item_id)  # noqa: SLF001
    item = await query.execute({"kind": "item", "project": project, "item_id": item_id})
    after = A.Workspace(query_session._ws.root).project(project).get(item_id)  # noqa: SLF001

    assert status.success is stats.success is listed.success is item.success is True
    assert status.output["holding"] is None  # type: ignore[index]
    assert stats.output["project"] == project  # type: ignore[index]
    assert item_id in {row["id"] for row in listed.output["items"]}  # type: ignore[index]
    assert item.output["items"][0]["description"] == "read without claiming"  # type: ignore[index]
    assert query_session._held is None  # noqa: SLF001
    assert (before.status, before.holder, before.meta) == (after.status, after.holder, after.meta)


@pytest.mark.asyncio
@pytest.mark.skipif(
    shutil.which("bd") is None, reason="real `bd` binary not present in this environment"
)
async def test_conformance1_verifies_a_resolved_item_through_work_query(project):
    adder = WorkTrackerSession({"actor": _unique("adder")})
    added = await adder.add(project, "conformance 1 query verification")
    item_id = added.output["added"]  # type: ignore[index]
    holder = WorkTrackerSession({"actor": _unique("holder")})
    assert (await holder.claim(project, item_id=item_id)).success is True
    assert (await holder.resolve(item_id, "the resolve landed")).success is True

    verifier = WorkQueryTool(WorkTrackerSession({"actor": _unique("verifier")}))
    verified = await verifier.execute({"kind": "item", "project": project, "item_id": item_id})
    assert verified.success is True
    row = verified.output["items"][0]  # type: ignore[index]
    assert row["status"] == "resolved"
    assert row["resolution"] == "the resolve landed"


@pytest.mark.asyncio
async def test_query_rejects_missing_or_unknown_kind_and_missing_selected_fields(tmp_path):
    query = WorkQueryTool(WorkTrackerSession({"actor": "surface_probe", "root": str(tmp_path)}))
    for input_, expected in (
        ({}, "kind=status, stats, list, or item"),
        ({"kind": "unknown"}, "kind=status, stats, list, or item"),
        ({"kind": "stats"}, "requires project"),
        ({"kind": "item", "project": "p"}, "requires item_id"),
    ):
        result = await query.execute(input_)
        assert result.success is False
        assert expected in str(result.output)


@pytest.mark.asyncio
async def test_strict_null_placeholders_are_omitted_before_query_and_item_dispatch():
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    query = WorkQueryTool(
        cast(
            Any,
            SimpleNamespace(
                status=_recording_method(calls, "status"),
                stats=_recording_method(calls, "stats"),
                list_items=_recording_method(calls, "list"),
            ),
        )
    )
    result = await query.execute(
        {"kind": "stats", "project": "project", "item_id": None, "status": None, "limit": None}
    )
    assert result.success is True
    assert calls == [("stats", ("project",), {})]
    missing_project = await query.execute(
        {"kind": "item", "project": None, "item_id": "item", "status": None, "limit": None}
    )
    assert missing_project.success is False
    assert "requires project" in str(missing_project.output)

    item = WorkItemTool(
        cast(
            Any,
            SimpleNamespace(
                move=_recording_method(calls, "move"),
                edit=_recording_method(calls, "edit"),
                defer=_recording_method(calls, "defer"),
                block=_recording_method(calls, "block"),
                dep=_recording_method(calls, "dep"),
            ),
        )
    )
    merge_only = await item.execute(
        {
            "op": "edit",
            "project": "project",
            "item_id": "item",
            "from_project": None,
            "to_project": None,
            "title": None,
            "description": None,
            "acceptance": None,
            "design": None,
            "merge_into": "replacement",
            "reason": None,
            "clear": None,
            "depends_on": None,
            "dep_type": None,
        }
    )
    assert merge_only.success is True
    assert calls[-1] == (
        "edit",
        ("project", "item"),
        {
            "title": None,
            "description": None,
            "acceptance": None,
            "design": None,
            "merge_into": "replacement",
        },
    )
    missing_move_project = await item.execute(
        {
            "op": "move",
            "project": None,
            "item_id": "item",
            "from_project": None,
            "to_project": "destination",
            "title": None,
            "description": None,
            "acceptance": None,
            "design": None,
            "merge_into": None,
            "reason": None,
            "clear": None,
            "depends_on": None,
            "dep_type": None,
        }
    )
    assert missing_move_project.success is False
    assert "from_project" in str(missing_move_project.output)
