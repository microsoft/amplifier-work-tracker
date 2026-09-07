# Work Tracker

Several agents pull from one shared queue at the same time, so every rule for
claiming, holding and closing an item — and every way those fail silently —
lives in the description of the `work_*` tool that enforces it, where it fires
at the moment it bites. First use in a session, or any `work_*` call that fails
to connect → `work_tracker_status`; claiming, working or resolving an
engineering-lane item → delegate to `work-tracker:work-executor`, or
`load_skill(skill_name="claiming-work-safely")` for the full claim/custody
procedure and what to do after a reap; `doctor` output, the `bd` seam, or
scheduling `reap`/`notify` → `load_skill(skill_name="work-tracker-operations")`.
