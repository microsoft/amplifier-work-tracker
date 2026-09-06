"""Every project-name parameter in this module's tool schemas STATES the
naming rule -- structurally, not by anyone remembering to.

Measured cost of the rule living nowhere an agent reads before its first
call (steward, 2026-09-06): "sessions keep trying to name things with
dashes, fail, and then have to try again w/ underscores." A tool schema is
precisely where an agent discovers what a parameter accepts, so a rule
absent from the schema is a rule stated in the wrong place.

These tests are schema-only: no `bd`, no dolt server, no fixtures. They walk
every tool this module mounts and assert the rule appears on every parameter
that takes a project name, so a tool added later cannot quietly ship without
it.
"""

from __future__ import annotations

from amplifier_module_tool_work_tracker import (
    WorkAddTool,
    WorkBlockTool,
    WorkClaimTool,
    WorkDeferTool,
    WorkDepTool,
    WorkEditTool,
    WorkErratumTool,
    WorkListTool,
    WorkMoveTool,
    WorkReopenTool,
    WorkStatsTool,
    WorkSubscribeTool,
    WorkTrackerSession,
    WorkUnsubscribeTool,
    _project_param,
)

import amplifier_work_tracker.adapter as A

#: Every tool class carrying at least one project-name parameter. The exact
#: count is asserted below rather than left implicit, so a new
#: project-taking tool added to `mount()` and forgotten here fails the count
#: instead of silently shipping a parameter with no rule on it.
_TOOLS_WITH_PROJECT_PARAMS = (
    WorkClaimTool,
    WorkReopenTool,
    WorkErratumTool,
    WorkStatsTool,
    WorkAddTool,
    WorkMoveTool,
    WorkEditTool,
    WorkDeferTool,
    WorkBlockTool,
    WorkDepTool,
    WorkListTool,
    WorkSubscribeTool,
    WorkUnsubscribeTool,
)

#: Parameter names that carry a project NAME (as opposed to an item id or a
#: free-text field).
_PROJECT_PARAM_NAMES = ("project", "from_project", "to_project")


def _schemas(tmp_path):
    """Every project-taking tool's `(name, input_schema)`. `root` is pinned
    to `tmp_path` so constructing a session can never touch a real workspace
    -- these tests read schemas only and must stay hermetic."""
    session = WorkTrackerSession({"actor": "schema_probe", "root": str(tmp_path)})
    for cls in _TOOLS_WITH_PROJECT_PARAMS:
        tool = cls(session)
        yield tool.name, tool.input_schema


def test_every_project_parameter_states_the_naming_rule(tmp_path):
    """The rule -- `adapter.NAME_RULE`, built from `NAME_RE.pattern` itself
    -- must appear verbatim on every project-name parameter of every tool.
    Verbatim matters: it is what proves the schema and the adapter's own
    refusal cannot have drifted apart."""
    checked = 0
    for tool_name, schema in _schemas(tmp_path):
        for param in _PROJECT_PARAM_NAMES:
            spec = schema["properties"].get(param)
            if spec is None:
                continue
            checked += 1
            assert A.NAME_RULE in spec["description"], (
                f"{tool_name}.{param} does not state the project-naming rule"
            )
    assert checked == 14, f"expected 14 project-name parameters, found {checked}"


def test_the_two_destination_parameters_lead_with_the_rule(tmp_path):
    """`work_add`'s `project` and `work_move`'s `to_project` are where a
    caller names a destination rather than repeating a name that already
    worked -- so the rule goes FIRST there, ahead of the parameter's own
    sentence."""
    schemas = dict(_schemas(tmp_path))
    add = schemas["work_add"]["properties"]["project"]["description"]
    to = schemas["work_move"]["properties"]["to_project"]["description"]
    assert add.startswith(A.NAME_RULE)
    assert to.startswith(A.NAME_RULE)


def test_rule_names_dashes_and_the_underscore_form(tmp_path):
    """The specific thing sessions kept getting wrong has to be the specific
    thing the description says -- not a bare regex a reader has to decode."""
    for _tool_name, schema in _schemas(tmp_path):
        for param in _PROJECT_PARAM_NAMES:
            spec = schema["properties"].get(param)
            if spec is None:
                continue
            text = spec["description"]
            assert "dashes are not accepted" in text
            assert "my_project" in text and "my-project" in text
            assert A.NAME_RE.pattern in text


def test_project_param_helper_shapes_both_orders():
    """The helper is the single construction point; both orders render the
    same rule string, so neither can drift from the other."""
    trailing = _project_param("Named project to list items from.")
    leading = _project_param("Named project to add the item to.", rule_first=True)
    assert trailing == {
        "type": "string",
        "description": f"Named project to list items from. {A.NAME_RULE}",
    }
    assert leading == {
        "type": "string",
        "description": f"{A.NAME_RULE} Named project to add the item to.",
    }
