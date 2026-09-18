"""Tier 1 -- repair-registration CLI JSON and exit contract.

These tests drive ``cli.main`` through its real parser and command dispatch.
The workspace is a fake because adapter rollback mechanics are exercised by
the isolated-server integration tests.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass

import pytest

from amplifier_work_tracker import cli


@dataclass
class _Report:
    name: str = "repair_project"
    dry_run: bool = False
    applied: bool = False
    rolled_back: bool = False
    old_local_id: str = "11111111-1111-1111-1111-111111111111"
    new_local_id: str = "22222222-2222-2222-2222-222222222222"
    server_id: str = "22222222-2222-2222-2222-222222222222"
    witness_item_id: str = "witness-1"
    witness_title: str | None = "known witness"
    backup_path: object | None = None
    metadata_state: str = "not_applied"
    verification_failure: str | None = None
    rollback_failure: str | None = None
    rollback_refusal: str | None = None


class _Workspace:
    def __init__(self, report: _Report):
        self.report = report
        self.calls: list[dict[str, object]] = []

    def repair_registration(self, name, **kwargs):
        self.calls.append({"name": name, **kwargs})
        return self.report


@pytest.fixture(autouse=True)
def _silence_guard(monkeypatch):
    monkeypatch.setattr(cli, "_guard", lambda: None)


def _run_cli(monkeypatch, capsys, report: _Report, *, apply: bool):
    workspace = _Workspace(report)
    monkeypatch.setattr(cli, "_ws", lambda _args: workspace)
    argv = [
        "amplifier-work-tracker",
        "repair-registration",
        "repair_project",
        "--host",
        "example.test",
        "--port",
        "3306",
        "--expected-local-id",
        report.old_local_id,
        "--expected-server-id",
        report.new_local_id,
        "--witness-item",
        report.witness_item_id,
    ]
    if apply:
        argv.append("--apply")
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exited:
        cli.main()
    return exited.value.code, json.loads(capsys.readouterr().out), workspace


def test_dry_run_keeps_zero_exit_and_prints_structured_json(monkeypatch, capsys):
    report = _Report(dry_run=True)

    code, payload, workspace = _run_cli(monkeypatch, capsys, report, apply=False)

    assert code == 0
    assert workspace.calls == [
        {
            "name": "repair_project",
            "host": "example.test",
            "port": 3306,
            "expected_local_id": report.old_local_id,
            "expected_server_id": report.new_local_id,
            "witness_item_id": "witness-1",
            "witness_title": None,
            "apply": False,
        }
    ]
    assert payload["dry_run"] is True
    assert payload["applied"] is False
    assert payload["metadata_state"] == "not_applied"
    assert payload["verification_failure"] is None


def test_successful_apply_keeps_zero_exit(monkeypatch, capsys):
    report = _Report(applied=True, metadata_state="repaired")

    code, payload, _ = _run_cli(monkeypatch, capsys, report, apply=True)

    assert code == 0
    assert payload["applied"] is True
    assert payload["metadata_state"] == "repaired"
    assert payload["rollback_failure"] is None


@pytest.mark.parametrize(
    ("metadata_state", "rolled_back", "rollback_failure", "rollback_refusal"),
    [
        ("original", True, None, None),
        ("repaired", False, "restore write failed", None),
        ("foreign", False, None, "foreign metadata was not overwritten"),
        ("unknown", False, "final readback failed", None),
    ],
)
def test_failed_apply_prints_diagnostic_json_and_exits_nonzero(
    monkeypatch, capsys, metadata_state, rolled_back, rollback_failure, rollback_refusal
):
    report = _Report(
        metadata_state=metadata_state,
        rolled_back=rolled_back,
        verification_failure="post-check server identity changed",
        rollback_failure=rollback_failure,
        rollback_refusal=rollback_refusal,
    )

    code, payload, _ = _run_cli(monkeypatch, capsys, report, apply=True)

    assert code == 1
    assert payload["applied"] is False
    assert payload["dry_run"] is False
    assert payload["metadata_state"] == metadata_state
    assert payload["verification_failure"] == "post-check server identity changed"
    assert payload["rollback_failure"] == rollback_failure
    assert payload["rollback_refusal"] == rollback_refusal
