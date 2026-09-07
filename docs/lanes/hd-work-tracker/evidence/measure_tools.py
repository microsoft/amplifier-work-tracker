import importlib
import json

m = importlib.import_module("amplifier_module_tool_work_tracker")
st = importlib.import_module("amplifier_module_tool_work_tracker.service_tools")
classes = [
    m.WorkClaimTool,
    m.WorkDeclareTool,
    m.WorkResolveTool,
    m.WorkReopenTool,
    m.WorkErratumTool,
    m.WorkReleaseTool,
    m.WorkStatusTool,
    m.WorkStatsTool,
    m.WorkFileTool,
    m.WorkAddTool,
    m.WorkMoveTool,
    m.WorkEditTool,
    m.WorkDeferTool,
    m.WorkBlockTool,
    m.WorkDepTool,
    m.WorkListTool,
    m.WorkSubscribeTool,
    m.WorkUnsubscribeTool,
    m.WorkSubscriptionsTool,
]
rows = []
total_desc = 0
total_schema = 0
for c in classes:
    t = c.__new__(c)
    t._session = None
    d = t.description
    s = json.dumps(t.input_schema)
    rows.append((t.name, len(d), len(s)))
for c in (st.WorkTrackerStatusTool, st.WorkTrackerInstallTool):
    t = c(None)
    rows.append((t.name, len(t.description), len(json.dumps(t.input_schema))))
for n, dl, sl in rows:
    total_desc += dl
    total_schema += sl
    print(f"{n:24s} desc={dl:6d} schema={sl:6d}")
print(f"{'TOTAL':24s} desc={total_desc:6d} schema={total_schema:6d}  n={len(rows)}")
