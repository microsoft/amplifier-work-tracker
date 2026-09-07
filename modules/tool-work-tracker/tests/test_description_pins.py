"""The 21 tool descriptions are the head cost this bundle bills every turn.

A tool description is paid for on EVERY request of EVERY session that mounts
this module, whether or not the tool is ever called. The bodies behind them
(the skills, the agent) are pay-per-use; a description is pay-per-turn. That
distinction is the whole reason this file exists.

Measured before this pin (model_performance-b1tw, 2026-09-07): 21
descriptions totalling 12,758 chars, 9 of them over 600, none trigger-first,
none naming when NOT to use the tool -- plus a 7,529-byte always-on
`context/awareness.md` restating seven hazards that the tools themselves
never mentioned. The hazards MOVED into the descriptions of the tools they
are about (and into the claiming-work-safely skill for the full procedure),
which is where they fire at the moment they bite.

These tests are schema/description-only: no `bd`, no dolt server, no
network, no subprocess. They walk every tool this module mounts, so a tool
added later cannot quietly ship an untriggered, unbudgeted description -- and
a later edit cannot silently regrow one, or silently drop a hazard that has
nowhere else to live.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from amplifier_module_tool_work_tracker import (
    WorkAddTool,
    WorkBlockTool,
    WorkClaimTool,
    WorkDeclareTool,
    WorkDeferTool,
    WorkDepTool,
    WorkEditTool,
    WorkErratumTool,
    WorkFileTool,
    WorkListTool,
    WorkMoveTool,
    WorkReleaseTool,
    WorkReopenTool,
    WorkResolveTool,
    WorkStatsTool,
    WorkStatusTool,
    WorkSubscribeTool,
    WorkSubscriptionsTool,
    WorkTrackerSession,
    WorkUnsubscribeTool,
)
from amplifier_module_tool_work_tracker.service_tools import (
    WorkTrackerInstallTool,
    WorkTrackerStatusTool,
)

#: Every tool `mount()` registers. The count is asserted below rather than
#: left implicit: a tool added to `mount()` and forgotten here would ship an
#: unmeasured description, which is exactly the state this file replaced.
_SESSION_TOOLS = (
    WorkClaimTool,
    WorkDeclareTool,
    WorkResolveTool,
    WorkReopenTool,
    WorkErratumTool,
    WorkReleaseTool,
    WorkStatusTool,
    WorkStatsTool,
    WorkFileTool,
    WorkAddTool,
    WorkMoveTool,
    WorkEditTool,
    WorkDeferTool,
    WorkBlockTool,
    WorkDepTool,
    WorkListTool,
    WorkSubscribeTool,
    WorkUnsubscribeTool,
    WorkSubscriptionsTool,
)
_CONFIG_TOOLS = (WorkTrackerStatusTool, WorkTrackerInstallTool)

#: Per-description ceiling. The standard is "~600 chars"; 610 is that with a
#: few characters of tolerance so a one-word clarification is not a red
#: build. Measured max on this branch: 606 (`work_tracker_status`, whose
#: three no-fix running states are named in full on purpose -- an agent that
#: reads only two of them stops a healthy server).
MAX_DESCRIPTION_CHARS = 610

#: Whole-surface ceiling. Measured on this branch: 11,206, down from 12,758
#: while ABSORBING seven hazards from the deleted awareness prose. The
#: headroom is deliberately small: a new tool is expected to be lean, and a
#: real need to raise this is a decision someone should have to make on
#: purpose.
MAX_TOTAL_DESCRIPTION_CHARS = 11_600

#: `context/awareness.md` is injected into every session's head on every
#: turn. It is a concept, a trigger and a pointer -- nothing that belongs in
#: a tool description or a skill. It was 7,529 bytes; it is now ~700.
REPO_ROOT = Path(__file__).resolve().parents[3]
AWARENESS = REPO_ROOT / "context" / "awareness.md"
MAX_AWARENESS_BYTES = 1_200

#: The seven silent-failure hazards `context/awareness.md` used to carry,
#: each pinned to the tool whose call is the moment it bites. Format:
#: (hazard, tool name, phrase that must appear in that tool's description).
#: A hazard deleted in a byte-reduction is a bug report from a confused user
#: three weeks later, so each one is asserted by name.
_HAZARDS_AT_THE_TOOL = (
    ("1 never list-then-pick", "work_claim", "Never list-then-pick"),
    ("1 double-claims silently", "work_claim", "double-claims SILENTLY"),
    ("2 renewal is one-strike", "work_status", "there is no retry on the next tick"),
    ("2 the passive signal", "work_status", "holding.custody_lost"),
    ("2 the TTL does not enforce itself", "work_stats", "The TTL does not enforce itself"),
    ("2 no sweep, no reclaim", "work_stats", "persists indefinitely where no sweep runs"),
    ("2 awaiting_human is not exempt", "work_declare", "ZERO exemption from the custody clock"),
    ("3 an empty queue is terminal", "work_claim", "a normal terminal outcome"),
    ("4 never speak to bd directly", "work_add", "never fall back to a raw storage-layer CLI"),
    ("4 never speak to bd directly", "work_list", "never use a raw storage-layer CLI"),
    ("5 stop after a reclaimed refusal", "work_resolve", "then STOP, do not retry"),
    ("5 stop after a reclaimed refusal", "work_declare", "STOP -- do not retry it"),
    ("6 a reported success IS confirmed", "work_resolve", "a reported success here is confirmed"),
    ("6 a reported success IS confirmed", "work_release", "a reported success here is confirmed"),
    ("6 unverified write, re-read first", "work_add", "does NOT prove the write failed"),
    ("6 unverified write, re-read first", "work_file", "does NOT prove nothing was written"),
    ("7 resolve cannot overwrite", "work_resolve", "different text fails and writes nothing"),
    ("7 the record is wrong", "work_erratum", "APPEND-ONLY"),
    ("7 the work is wrong", "work_reopen", "CLEARS closed_at"),
)


@pytest.fixture
def descriptions(tmp_path) -> dict[str, str]:
    """Every mounted tool's `(name, description)`. `root` is pinned to
    `tmp_path` so constructing a session can never touch a real workspace --
    these tests read strings only and must stay hermetic."""
    session = WorkTrackerSession({"actor": "description_probe", "root": str(tmp_path)})
    out = {}
    for cls in _SESSION_TOOLS:
        tool = cls(session)
        out[tool.name] = tool.description
    for cfg_cls in _CONFIG_TOOLS:
        tool = cfg_cls(None)
        out[tool.name] = tool.description
    return out


def test_every_mounted_tool_is_measured(descriptions: dict[str, str]) -> None:
    """21 tools, all present. A tool added to `mount()` but not here would
    escape every budget and shape check below."""
    assert len(descriptions) == 21, f"expected 21 tools, measured {sorted(descriptions)}"


def test_every_description_is_trigger_first(descriptions: dict[str, str]) -> None:
    """A description's first words decide whether a model reaches for the
    tool at all. It opens with the trigger -- when to use it -- not with what
    the tool is."""
    wrong = {
        n: d[:40] for n, d in descriptions.items() if not d.startswith(("USE WHEN", "USE FIRST"))
    }
    assert not wrong, f"descriptions that do not open with a trigger: {wrong}"


def test_every_description_names_when_not_to_use_it(descriptions: dict[str, str]) -> None:
    """These 21 verbs have deliberately adjacent jobs (defer/block/dep,
    erratum/reopen, file/add, status/stats). Without an explicit DO NOT USE
    the catalog routes on vibes."""
    missing = sorted(n for n, d in descriptions.items() if "DO NOT USE" not in d)
    assert not missing, f"descriptions with no DO NOT USE clause: {missing}"


def test_no_description_exceeds_its_budget(descriptions: dict[str, str]) -> None:
    over = {n: len(d) for n, d in descriptions.items() if len(d) > MAX_DESCRIPTION_CHARS}
    assert not over, (
        f"descriptions over the {MAX_DESCRIPTION_CHARS}-char budget: {over}. "
        f"Every char here is billed on every request of every session."
    )


def test_the_whole_tool_surface_stays_lean(descriptions: dict[str, str]) -> None:
    total = sum(len(d) for d in descriptions.values())
    assert total <= MAX_TOTAL_DESCRIPTION_CHARS, (
        f"tool descriptions total {total} chars, over the "
        f"{MAX_TOTAL_DESCRIPTION_CHARS} ceiling (was 12,758 before "
        f"model_performance-b1tw, 11,206 after)"
    )


@pytest.mark.parametrize(("hazard", "tool", "phrase"), _HAZARDS_AT_THE_TOOL)
def test_each_moved_hazard_lives_where_it_acts(
    descriptions: dict[str, str], hazard: str, tool: str, phrase: str
) -> None:
    """Every hazard the always-on awareness file used to carry is asserted
    in the description of the tool it is about. Deleting one is now a red
    build, not a discovery three weeks later."""
    assert tool in descriptions, f"{tool} is not mounted -- this pin is out of date"
    assert phrase in descriptions[tool], (
        f"hazard {hazard!r} is no longer stated in {tool}'s description (looked for {phrase!r})"
    )


def test_the_awareness_file_stays_a_pointer() -> None:
    """`context/awareness.md` is always-on. It carries a concept, a trigger
    and a pointer -- and must not regrow the operating rules that now live
    in the tools and the skill."""
    text = AWARENESS.read_text(encoding="utf-8")
    size = len(text.encode("utf-8"))
    assert size <= MAX_AWARENESS_BYTES, (
        f"context/awareness.md is {size} bytes, over the {MAX_AWARENESS_BYTES} "
        f"ceiling (it was 7,529 before model_performance-b1tw). Operating rules "
        f"belong in the description of the tool that enforces them."
    )
    for regrown in (
        "double-claim",
        "custody_lost",
        "reclaim-eligible",
        "still conflicting after 8 retries",
        "already_recorded",
    ):
        assert regrown not in text, (
            f"context/awareness.md has regrown an operating rule ({regrown!r}) that "
            f"now lives in a tool description or the claiming-work-safely skill"
        )
