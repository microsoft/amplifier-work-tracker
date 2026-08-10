---
name: work-tracker-setup
description: "Diagnose and fix a not-yet-running amplifier-work-tracker background service (shared dolt server + reap/notify sweeps) from a fresh machine. Symptom table + numbered decision tree covering bd_missing, bd_too_old, dolt_missing, not_installed, installed_not_running, running_unmanaged, and partial-install failures, plus a copy-pasteable OS/arch-detecting install snippet for bd/dolt. Use the FIRST time work-tracker is used in a session, when work_claim/work_status/the CLI fail with a connection error, or when work_tracker_status reports anything other than running_healthy."
version: 1.2.0
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
| `work_tracker_status` says `running_unmanaged` | running_unmanaged | Decision 3 |
| `work_tracker_install` reports failure | partial install | Decision 4 |
| Everything above says healthy but work still fails | something else | Decision 5 |
| Nothing in the queue yet -- need to file the FIRST item | (no state; a task) | Decision 6 |

## Decision 0 -- prerequisite binaries missing (`bd_missing` / `bd_too_old` / `dolt_missing`)

Neither `bd` nor `dolt` is guaranteed to exist on a fresh machine -- they are
prerequisites for this package, not part of it. `work_tracker_status` AND
`work_tracker_install` both probe both binaries, in order, BEFORE either one
ever asks about the service or touches systemd/launchd -- a missing binary
is refused loudly, never discovered halfway through a confusing systemd
error (see `prereqs.py` and `service_tools.classify_state`).

**Never** auto-download or install either binary yourself just because you
noticed one is missing. Same rule as `work_tracker_install` itself (see
Decision 1): report the exact state and the exact command, then let the
command actually run, deliberately, once. Both reference projects this
bundle is modeled on (muxplex, amplifier-browser-bridge) refuse ambient side
effects for exactly this class of action.

**Do not `web_search` for install instructions.** They are already here --
see "Copy-pasteable install snippet" immediately below -- and in
`docs/FOR_AGENT_SESSIONS.md`. If both binaries are missing, `work_tracker_status`'s
`fix` field already gives you the exact command for THIS machine's
OS/architecture; the snippet below is the same logic written as a portable,
auto-detecting one-liner for when you want to install both at once, or
don't have the tool available yet to read the `fix` field from.

### Copy-pasteable install snippet (auto-detects OS/arch, never hardcodes one)

Mirrors `.github/workflows/ci.yml`'s pinned "Install bd (pinned)" / "Install
dolt (pinned)" steps exactly (same release repos, same asset-name patterns),
adapted to install to `~/.local/bin` with no `sudo` (this runs on someone's
machine, not a CI runner CI owns). Safe to run even if one binary is already
present -- it just reinstalls to the same pinned version.

```bash
set -euo pipefail
BD_VERSION="1.1.2"      # keep in sync with adapter.py's MIN_VERSION
DOLT_VERSION="2.2.3"    # keep in sync with prereqs.py's DOLT_INSTALL_VERSION

case "$(uname -s)" in
  Linux)  OS=linux ;;
  Darwin) OS=darwin ;;
  *) echo "no known bd/dolt release asset for OS $(uname -s)" >&2; exit 1 ;;
esac
case "$(uname -m)" in
  x86_64|amd64)   ARCH=amd64 ;;
  arm64|aarch64)  ARCH=arm64 ;;
  *) echo "no known bd/dolt release asset for arch $(uname -m)" >&2; exit 1 ;;
esac
if [ "$OS" = "darwin" ] && [ "$ARCH" = "amd64" ]; then
  echo "beads does not publish a darwin_amd64 release -- only linux_amd64, " \
       "linux_arm64, and darwin_arm64 today. Install from source or wait " \
       "for a release: https://github.com/gastownhall/beads/releases" >&2
  exit 1
fi

mkdir -p ~/.local/bin

# bd
BD_ASSET="beads_${BD_VERSION}_${OS}_${ARCH}.tar.gz"
curl -fsSL -o "/tmp/${BD_ASSET}" \
  "https://github.com/gastownhall/beads/releases/download/v${BD_VERSION}/${BD_ASSET}"
mkdir -p "/tmp/bd-${BD_VERSION}"
tar -xzf "/tmp/${BD_ASSET}" -C "/tmp/bd-${BD_VERSION}"
install -m 0755 "/tmp/bd-${BD_VERSION}/bd" ~/.local/bin/bd
rm -rf "/tmp/${BD_ASSET}" "/tmp/bd-${BD_VERSION}"
bd --version

# dolt (tarball nests one level -- --strip-components=1)
DOLT_ASSET="dolt-${OS}-${ARCH}.tar.gz"
curl -fsSL -o "/tmp/${DOLT_ASSET}" \
  "https://github.com/dolthub/dolt/releases/download/v${DOLT_VERSION}/${DOLT_ASSET}"
mkdir -p "/tmp/dolt-${DOLT_VERSION}"
tar -xzf "/tmp/${DOLT_ASSET}" -C "/tmp/dolt-${DOLT_VERSION}" --strip-components=1
install -m 0755 "/tmp/dolt-${DOLT_VERSION}/bin/dolt" ~/.local/bin/dolt
rm -rf "/tmp/${DOLT_ASSET}" "/tmp/dolt-${DOLT_VERSION}"
dolt version

export PATH="$HOME/.local/bin:$PATH"   # this shell only -- add to your rc file to persist
```

After running it, re-check with `work_tracker_status` -- it should now
report `not_installed` (both prerequisites clear, service not yet set up).

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

## Decision 3 -- `running_unmanaged`

Something is already answering on the dolt port (default 127.0.0.1:3308)
that this service did not start -- most likely `bd` itself lazily
auto-starting its own shared server from an earlier, unrelated session, or a
human running `dolt sql-server` by hand.

**This is a WORKING server, not a problem.** bd's shared-server topology is
one server per host:port, regardless of who started it -- so this is
already usable. **Do not stop it.** It may be holding live claims from
other sessions right now; killing it on a guess is exactly the failure mode
this classification exists to prevent (an earlier version of this state was
named `foreign_server_on_port` and advised "stop it if it's safe to" --
that advice was itself the bug: a real session followed it against a
server it had just started, mid-task).

1. **Just use it.** `work_claim`/`work_status`/the CLI all work against it
   right now with no further action -- there is nothing to fix.
2. Only if you specifically want it to survive reboot and get the
   reap/notify sweeps: identify what's running it (`lsof -i :3308`), decide
   whether stopping it is actually safe (no one else depends on it), stop it
   yourself if so, confirm the port is free (`lsof -i :3308` again), THEN
   call `work_tracker_install`. Do not do this by default.
3. `work_tracker_install` will still refuse while something is bound to the
   port (installing on top of it would only crash-loop, not adopt it) -- its
   refusal message says so plainly and is not itself a problem to solve.

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

## Decision 6 -- nothing in the queue yet (filing the FIRST item)

A brand-new project has no work in it, and there is no held item to file
`work_file` against (it requires one). Use `work_add(project=<name>,
title=..., description=..., acceptance=...)` -- or the CLI's
`amplifier-work-tracker add --project <name> <title>` -- instead. It needs
no held item and applies the engineering lane label itself; you never need
to know a label like `lane:eng` exists, and you must never `bd create` +
guess a label by hand to work around this (that is exactly the raw-`bd`
escape `docs/FOR_AGENT_SESSIONS.md` rule #4 forbids).

```bash
amplifier-work-tracker add --project demo "Add health check endpoint" \
  --description "Implement a /health endpoint that returns 200 OK" \
  --acceptance "GET /health returns 200 with a JSON body"
```

The item lands immediately claimable via `work_claim`/`amplifier-work-tracker claim`.

## Decision 5 -- everything reports healthy but work still fails

`work_tracker_status` says `running_healthy`, `amplifier-work-tracker
doctor` passes, but `work_claim`/`work_resolve` still fail. This is no
longer a setup problem -- load `work-tracker-operations` (the operator
skill) or `claiming-work-safely` (the agent-facing claim/custody skill)
instead of continuing here.
