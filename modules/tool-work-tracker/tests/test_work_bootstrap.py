"""Workspace-bootstrap metadata (`repos:`/`context:`) surfaced through the
tool layer -- `work_claim`'s success dict and `work_list`'s directed
(`item_id`) read. The parsing itself is unit-tested in the root suite
(`tests/unit/test_adapter_mapping.py`); these tests prove the parsed lists
actually reach the two agent-facing tool surfaces, round-tripped through
real `bd`/dolt.
"""

from __future__ import annotations

import shutil
import uuid
from typing import Any

import pytest
from amplifier_module_tool_work_tracker import WorkTrackerSession

pytestmark = pytest.mark.skipif(
    shutil.which("bd") is None, reason="real `bd` binary not present in this environment"
)


def _unique(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


#: Consumed by the shared `project` fixture in conftest.py, which creates
#: the project AND drops its shared-server database again on teardown.
PROJECT_PREFIX = "bootproj"

_DESC_WITH_BLOCK = (
    "Bootstrap this lane.\n\n"
    "```yaml\n"
    "repos:\n"
    "  - org/frontend\n"
    "  - org/backend\n"
    "context:\n"
    "  - docs/spec.md\n"
    "```\n"
)


@pytest.mark.asyncio
async def test_work_claim_surfaces_repos_and_context(project):
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    added = await add_session.add(project, "claim bootstrap probe", description=_DESC_WITH_BLOCK)
    item_id = added.output["added"]  # type: ignore[index]

    session = WorkTrackerSession({"actor": _unique("holder")})
    result = await session.claim(project, item_id=item_id)
    assert result.success is True
    out: dict[str, Any] = result.output  # type: ignore[assignment]
    assert out["repos"] == ["org/frontend", "org/backend"]
    assert out["context"] == ["docs/spec.md"]

    await session.resolve(item_id, "test cleanup")


@pytest.mark.asyncio
async def test_work_claim_empty_lists_for_item_without_a_block(project):
    """Backward compatibility at the tool surface: an item with no yaml
    block claims exactly as before, with repos/context as empty lists."""
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    added = await add_session.add(
        project, "plain claim probe", description="just a normal description"
    )
    item_id = added.output["added"]  # type: ignore[index]

    session = WorkTrackerSession({"actor": _unique("holder")})
    result = await session.claim(project, item_id=item_id)
    assert result.success is True
    out: dict[str, Any] = result.output  # type: ignore[assignment]
    assert out["repos"] == []
    assert out["context"] == []

    await session.resolve(item_id, "test cleanup")


@pytest.mark.asyncio
async def test_work_list_directed_read_surfaces_repos_and_context(project):
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    added = await add_session.add(project, "list bootstrap probe", description=_DESC_WITH_BLOCK)
    item_id = added.output["added"]  # type: ignore[index]

    list_session = WorkTrackerSession({"actor": _unique("lister")})
    result = await list_session.list_items(project, item_id=item_id)
    assert result.success is True
    out: dict[str, Any] = result.output  # type: ignore[assignment]
    row = out["items"][0]
    assert row["repos"] == ["org/frontend", "org/backend"]
    assert row["context"] == ["docs/spec.md"]
    # Read-only: never claimed by the directed read.
    assert list_session._held is None  # noqa: SLF001
