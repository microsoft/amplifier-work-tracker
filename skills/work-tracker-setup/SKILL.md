---
name: work-tracker-setup
description: "Diagnose and fix a not-yet-running amplifier-work-tracker background service (shared dolt server + reap/notify sweeps) from a fresh machine. Symptom table + numbered decision tree covering bd_missing, bd_too_old, dolt_missing, not_installed, installed_not_running, foreign_server_on_port, and partial-install failures. Use the FIRST time work-tracker is used in a session, when work_claim/work_status/the CLI fail with a connection error, or when work_tracker_status reports anything other than running_healthy."
version: 1.1.0
---

# Work Tracker Setup

A user who installs only the work-tracker behavior bundle and then says
"use work-tracker for this task" has, on a fresh machine, no guarantee of
ANYTHING -- not the background service, not even the `bd`/`dolt` binaries
this whole package is built on top of. This skill is the decision tree for
getting from "unknown state" (possibly a TRUE zero state: no `bd`, no
`dolt`, nothing installed, nothing running) to `running_healthy` without
guessing.

## Step 0 -- always start here

Call `work_tracker_status`. It returns one of **seven** states and, for
every state except `running_healthy`, the exact fix command. Read its `fix`
field before doing anything below by hand -- it is generated from the same
live probe this skill describes, not a stale copy of it.

The first three states are checked BEFORE anything about the service at
all -- there is no point asking "is the service installed" when there is no
`bd` binary to run `bd init` with in the first place. Once one of them
fires, nothing downstream is even attempted (same dependency-ordering rule
`amplifier-work-tracker doctor` already uses for `service.installed` /
`dolt.reachable`: an upstream failure means downstream checks are skipped,
not piled on as more red for the same root cause).

## Symptom -> state table

| What you're seeing | Likely state | Go to |
|---|---|---|
| First use in a session, haven't checked yet | unknown | Step 0 |
| `work_tracker_status` says `bd_missing` | bd_missing | Decision 0a |
| `work_tracker_status` says `bd_too_old` | bd_too_old | Decision 0b |
| `work_tracker_status` says `dolt_missing` | dolt_missing | Decision 0c |
| `work_tracker_status` says `not_installed` | not_installed | Decision 1 |
| `work_claim`/`work_status`/CLI fail with a connection-refused-shaped error | installed_not_running or not_installed | Step 0, then Decision 2 |
| `work_tracker_status` says `installed_not_running` | installed_not_running | Decision 2 |
| `work_tracker_status` says `foreign_server_on_port` | foreign_server_on_port | Decision 3 |
| `work_tracker_install` reports failure | partial install | Decision 4 |
| Everything above says healthy but work still fails | something else | Decision 5 |

## Decision 0 -- prerequisite binaries missing (`bd_missing` / `bd_too_old` / `dolt_missing`)

Neither `bd` nor `dolt` is guaranteed to exist on a fresh machine -- they are
prerequisites for this package, not part of it. `work_tracker_status` probes
both, in order, before it ever asks about the service.

**Never** auto-download or install either binary yourself just because you
noticed one is missing. Same rule as `work_tracker_install` itself (see
Decision 1): report the exact state and the exact command, then let the
command actually run, deliberately, once. Both reference projects this
bundle is modeled on (muxplex, amplifier-browser-bridge) refuse ambient side
effects for exactly this class of action.

### Decision 0a -- `bd_missing`

`bd` is not on PATH at all. This is the common, expected state on a
genuinely fresh machine.

1. Read the `fix` field from `work_tracker_status` -- it is the exact
   install command (mirrors `.github/workflows/ci.yml`'s pinned "Install bd"
   step, adapted to install to `~/.local/bin` with no sudo).
2. Run it, then re-check with `work_tracker_status`.
3. If it still reports `bd_missing`, your OS/architecture may have no
   published `beads` release asset (today: `linux_amd64`, `linux_arm64`,
   `darwin_arm64` only -- notably NOT `darwin_amd64`). The fix command names
   this explicitly when it applies; if so, install from source or wait for
   a release, there is no download-based fix.

### Decision 0b -- `bd_too_old`

`bd` is on PATH, but its version is below the supported floor (or its
version string could not be read at all).

**Why the floor is not negotiable:** below it, `bd ready --claim` -- the
ONLY atomic claim path this whole package depends on -- does not exist.
The only claim path available on an older build was measured to
double-claim the same item to multiple agents in real contention. This
is not a style preference; running below the floor silently corrupts
parallel work.

1. Read the `fix` field -- the same pinned-install command as Decision 0a,
   which overwrites the old binary with the supported version.
2. Run it, then re-check with `work_tracker_status`.

### Decision 0c -- `dolt_missing`

`bd` is present and new enough, but `dolt` (the shared server `bd
--shared-server` mode runs on) is not on PATH.

1. Read the `fix` field -- mirrors ci.yml's pinned "Install dolt" step,
   same adaptation to `~/.local/bin`.
2. Run it, then re-check with `work_tracker_status`. It should now report
   `not_installed` (prerequisites clear, service not yet set up) -- proceed
   to Decision 1.

## Decision 1 -- `not_installed`

Nothing is running and nothing else is using the port. This is the clean,
common case on a fresh machine.

1. Call `work_tracker_install`. It installs the service, starts it, and
   polls until dolt actually answers before reporting success -- a partial
   install is reported as failure, never silently swallowed.
2. On success, proceed with the task (`work_claim`, etc.).
3. On failure, go to Decision 4.

**Never** call `work_tracker_install` speculatively "just in case" before
`work_tracker_status` says you need it -- it is the one tool in this bundle
that changes system state, and it must be an explicit, deliberate call, not
a side effect of checking status.

## Decision 2 -- `installed_not_running`

The service unit exists but systemd/launchd reports it inactive, or it's
active but dolt hasn't come up yet.

1. `amplifier-work-tracker service logs` -- read the actual failure. Common
   causes: the dolt binary isn't on the PATH the service unit sees, the
   configured `--root` no longer exists, or a previous crash left
   `Restart=on-failure` looping.
2. `amplifier-work-tracker service restart` -- safe to run even if it's
   already stopped.
3. Re-check with `work_tracker_status`. If it now says `running_healthy`,
   proceed. If it still says `installed_not_running`, the logs from step 1
   are the next thing to act on -- do not loop step 2 more than once without
   reading them.

## Decision 3 -- `foreign_server_on_port`

Something is already answering on the dolt port (default 127.0.0.1:3308)
that this service did not start -- most likely `bd` itself lazily
auto-starting its own shared server from an earlier, unrelated session, or a
human running `dolt sql-server` by hand.

**Do not** call `work_tracker_install` yet -- it will refuse (by design; see
`supervisor.py`'s `classify_port_holders`), and killing an unknown process on
a shared port is exactly the failure mode this bundle's port-safety logic
exists to prevent.

1. Identify it: `lsof -i :3308` (or the port `work_tracker_status` reported).
2. If it's a `bd`-managed shared server for the SAME projects you're about
   to work in, it may be fine to just use `bd`/the CLI directly without
   installing the service at all -- the service exists to make the server
   survive reboot, not to be the only valid way to run it.
3. If it's stale, unrelated, or you want the service to own it: stop that
   process, confirm the port is free (`lsof -i :3308` again), then call
   `work_tracker_install`.

## Decision 4 -- partial install failure

`work_tracker_install` returned `success: false`. Read the message --
it always names what failed:

- **"refusing to install: bd is not on PATH" / "... is below the supported
  floor" / "dolt is not on PATH"** -- this is NOT a partial install; it's
  Decision 0's refusal, reached from a stale `work_tracker_status` result
  (e.g. `bd` was installed after you last checked, but you called
  `work_tracker_install` from memory instead of re-checking). Re-run
  `work_tracker_status` and go to Decision 0.
- **"could not install"** -- a `ServiceUnsupportedError`: this platform has
  no systemd (`systemctl` not on PATH) and isn't macOS. Run
  `amplifier-work-tracker serve --root <path>` directly in a persistent
  terminal/tmux session instead; there is no background-service option here.
- **"dolt never became reachable"** -- the unit installed but the dolt child
  never bound the port within the timeout. `amplifier-work-tracker service
  logs` for the real error (permission issue on the data directory, a stale
  lock, disk full, etc.) -- this is not a case to retry blindly.

## Decision 5 -- everything reports healthy but work still fails

`work_tracker_status` says `running_healthy`, `amplifier-work-tracker
doctor` passes, but `work_claim`/`work_resolve` still fail. This is no
longer a setup problem -- load `work-tracker-operations` (the operator
skill) or `claiming-work-safely` (the agent-facing claim/custody skill)
instead of continuing here.
