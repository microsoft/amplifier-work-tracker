# Work Tracker operator reference

Use this Level 3 reference after loading `claiming-work-safely` when operating
or diagnosing Work Tracker rather than claiming an item.

## Doctor and the adapter seam

Run `amplifier-work-tracker doctor` after every `bd` upgrade, in CI, and before
trusting a fresh environment with parallel agents. `doctor --quick` skips the
two adversarial atomic-claim checks and is only a fast sanity check.

A failed assumption identifies the Beads-specific adapter seam. Fix Beads
behavior in `src/amplifier_work_tracker/adapter.py`; do not teach a caller to
use raw `bd`.

## Service and sweeps

First call `work_tracker(op="status")` to diagnose prerequisites, service
state, and the concrete fix. Call `work_tracker(op="install")` only when that
status says installation is needed. Installation is explicit and verifies that
Dolt becomes reachable; never use it as a side effect of status.

The installed background service runs `reap` and `notify` sweeps. If operating
`amplifier-work-tracker serve` without that service, schedule:

```bash
amplifier-work-tracker reap --project <project>
amplifier-work-tracker notify --project <project>
```

Without `reap`, a dead holder can remain held forever. Without `notify`, a
resolved report does not reach its reporter.

## Version and topology

Require `bd >= 1.1.2`: it supplies the safe atomic queue-claim path. Run one
shared `dolt sql-server` for the named project databases; do not use concurrent
embedded mode. All Beads interaction stays behind the Work Tracker tool or CLI
seam.