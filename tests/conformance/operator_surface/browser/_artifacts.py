"""The on-disk artifact contract for the Tier-B kit (Freeze 3).

    **Freeze 3:** every Tier-B check emits artifacts the orchestrator
    re-checks itself; no check reports a rendered impression as a pass.

The rule that follows from that, and that every check in `test_tier_b.py`
obeys: **measure -> write -> read back -> assert**. A check computes numbers
in the browser, writes them to a JSON file here, and then asserts against the
file it just read back. Nothing asserts on a value that only ever lived in a
local variable, and nothing asserts on a screenshot.

Screenshots ARE saved, next to the JSON, and they are evidence only -- a
human artefact for a Freeze 8 look. No assertion anywhere in this package
opens one.

Artifact layout
---------------

    _artifacts/<run-id>/
        index.json                     every artifact written by the run
        <check>.<scenario>.json        one measurement record
        <check>.<scenario>.png         the screenshot it was measured from

`<run-id>` is `<UTC timestamp>-<pid>`, so concurrent runs never overwrite each
other and a failed run's numbers survive for inspection. The directory is
gitignored: an artifact is a RUN's evidence, not repo content, and a committed
one would be a number nobody re-measured.

Every record carries the same envelope:

    {
      "check":     "calm.zero_alarm_pixels",   # the contract's own check name
      "clause":    "Core 2",                   # what it is evidence for
      "scenario":  "calm/L0/dark",             # which fixture and render
      "recorded_at": "2026-09-04T18:11:02Z",
      "browser":   {"name": "chromium", "version": "148.0.7778.0",
                    "playwright": "1.60.0"},
      "measurement": { ... check-specific numbers ... }
    }

`browser` is not decoration: a contrast ratio or a pixel count is only
reproducible against a named engine build, which is why Freeze 2 asks for a
PINNED chromium in the first place.

The durable summary
-------------------
The per-run directory is gitignored and disappears with the checkout, so the
conformance ledger -- in-process, sub-second, browserless by design -- could
never read a number out of it. `LAST_RUN.json`, beside this module and
COMMITTED, is the bridge: every check contributes a short `headline` (the two
or three numbers its verdict actually rests on) and the summary is rewritten
at the end of every run.

That is what lets `ledger/checks/test_operator_rows.py` re-read Tier-B
numbers for itself instead of trusting the browser tier's own green
(OSV1-029 / Freeze 3). It is a RECORDED measurement, not a live one, and the
ledger treats it as such: it pins the browser build the numbers came from, so
moving the playwright pin fails the ledger until the kit is re-run.

Re-running the kit rewrites `LAST_RUN.json`; the diff IS the new measurement.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_ENVELOPE_KEYS = ("check", "clause", "scenario", "recorded_at", "browser", "measurement")

#: The committed summary the conformance ledger reads. Beside this module, not
#: under the gitignored per-run directory.
SUMMARY_PATH = Path(__file__).parent / "LAST_RUN.json"

SUMMARY_SCHEMA = "operator-surface-tier-b/1"


@dataclass
class RunArtifacts:
    """One run's artifact directory, and the index of what it wrote."""

    root: Path
    written: list[str] = field(default_factory=list)
    #: `{check: {scenario: headline}}` -- what `LAST_RUN.json` carries.
    summary: dict[str, dict[str, Any]] = field(default_factory=dict)
    browser: dict[str, str] = field(default_factory=dict)

    @classmethod
    def for_this_run(cls, base: Path) -> RunArtifacts:
        run_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{os.getpid()}"
        root = base / run_id
        root.mkdir(parents=True, exist_ok=True)
        return cls(root=root)

    def write(
        self,
        *,
        check: str,
        clause: str,
        scenario: str,
        browser: dict[str, str],
        measurement: dict[str, Any],
        headline: dict[str, Any] | None = None,
    ) -> Path:
        """Write one measurement record and return its path.

        The caller is expected to read it straight back (`read`) and assert
        against THAT -- see this module's docstring. Returning the path rather
        than the dict is deliberate: it makes the read-back the natural next
        line instead of an easily-skipped extra step.
        """
        record = {
            "check": check,
            "clause": clause,
            "scenario": scenario,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "browser": browser,
            "measurement": measurement,
        }
        path = self.root / f"{check}.{scenario.replace('/', '_')}.json"
        path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        self.written.append(path.name)
        self.browser = dict(browser)
        if headline is not None:
            self.summary.setdefault(check, {})[scenario] = headline
        return path

    def save_screenshot(self, *, check: str, scenario: str, png: bytes) -> Path:
        """Save a screenshot as EVIDENCE. Nothing asserts on the bytes here."""
        path = self.root / f"{check}.{scenario.replace('/', '_')}.png"
        path.write_bytes(png)
        self.written.append(path.name)
        return path

    def write_index(self) -> Path:
        path = self.root / "index.json"
        path.write_text(
            json.dumps(
                {"run_dir": str(self.root), "artifacts": sorted(self.written)},
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return path

    def write_summary(self) -> Path:
        """Rewrite the committed `LAST_RUN.json` the conformance ledger reads.

        Only written when the run actually produced headlines: a partial run
        (`-k something`) that measured three scenarios must not overwrite a
        full run's record with a near-empty one, because the ledger would then
        read "no such scenario" as an absence of evidence.
        """
        if not self.summary:
            return SUMMARY_PATH
        SUMMARY_PATH.write_text(
            json.dumps(
                {
                    "schema": SUMMARY_SCHEMA,
                    "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "browser": self.browser,
                    "checks": self.summary,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return SUMMARY_PATH


def read(path: Path) -> dict[str, Any]:
    """Read a record back and prove it is a well-formed artifact.

    The envelope check is not ceremony. A check that wrote `{}` and then
    asserted `record.get("measurement", {}).get("alarm_pixels", 0) == 0` would
    pass forever while measuring nothing at all -- the exact hollow green
    Freeze 3 names. Reading through this function makes that impossible.
    """
    record = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in _ENVELOPE_KEYS if k not in record]
    if missing:
        raise AssertionError(f"{path.name} is not a Tier-B artifact -- missing keys {missing}")
    if not isinstance(record["measurement"], dict) or not record["measurement"]:
        raise AssertionError(f"{path.name} carries an empty measurement -- nothing was measured")
    return record
