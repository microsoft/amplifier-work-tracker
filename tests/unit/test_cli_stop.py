"""The CLI must not turn a failed systemd readback into a success message."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from amplifier_work_tracker import cli
from amplifier_work_tracker import service as S


def test_service_stop_exits_nonzero_with_observed_state(monkeypatch, capsys):
    error = S.ServiceStopError(
        "systemctl stop returned zero, but amplifier-work-tracker is not cleanly stopped "
        "(observed: {'ActiveState': 'failed', 'MainPID': '0'})"
    )
    monkeypatch.setattr(S, "service_stop", lambda: (_ for _ in ()).throw(error))
    with pytest.raises(SystemExit) as excinfo:
        cli.cmd_service_stop(SimpleNamespace())
    assert excinfo.value.code == 1
    assert "observed" in capsys.readouterr().err
