"""Tier 1 -- cli.cmd_unclaim's own decision logic, isolated from bd.

`_ws` is monkeypatched to a fake project (the same convention
test_cli_doctor.py uses for `S.describe_service`), so these exercise the
command's guard and reporting logic directly -- status checked BEFORE any
write, readback verification, and the JSON shape -- with no live dolt server.
The bd-backed behaviour itself is proven end-to-end by
tests/cli/test_cli_unclaim.py and the `release.reopens_unresolved` contract
assumption (tests/integration/test_contract_assumptions.py parametrizes over
`contract.CHECKS`, so the new check runs there automatically).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import cli


@dataclass
class _Item:
    status: str
    holder: str | None = None


class _FakeBeads:
    """Returns successive statuses from `get()`; `release()` advances the
    cursor so the post-release readback can differ from the pre-release read.
    """

    def __init__(self, statuses: list[str], *, get_raises: bool = False):
        self._statuses = list(statuses)
        self._i = 0
        self._get_raises = get_raises
        self.released: list[str] = []

    def get(self, item_id: str) -> _Item:
        if self._get_raises:
            raise A.BeadsError(f"show {item_id}: not found")
        st = self._statuses[min(self._i, len(self._statuses) - 1)]
        return _Item(status=st, holder=("someone" if st == "held" else None))

    def release(self, item_id: str) -> None:
        self.released.append(item_id)
        self._i += 1


class _Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _FakeWorkspace:
    def __init__(self, bd: _FakeBeads):
        self._bd = bd

    def project(self, name: str) -> _FakeBeads:
        return self._bd


@pytest.fixture(autouse=True)
def _silence_guard(monkeypatch):
    monkeypatch.setattr(cli, "_guard", lambda: None)


def _wire(monkeypatch, fake: _FakeBeads) -> None:
    monkeypatch.setattr(cli, "_ws", lambda a: _FakeWorkspace(fake))


def _args() -> _Args:
    return _Args(project="p", id="wt-1", actor="agent", root=None)


def test_happy_path_releases_and_reports_open(monkeypatch, capsys):
    fake = _FakeBeads(["held", "open"])
    _wire(monkeypatch, fake)
    rc = cli.cmd_unclaim(_args())
    assert rc in (None, 0)
    assert fake.released == ["wt-1"]
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"unclaimed": "wt-1", "status": "open", "holder": None}


def test_refuses_when_not_held_and_mutates_nothing(monkeypatch, capsys):
    fake = _FakeBeads(["open"])
    _wire(monkeypatch, fake)
    with pytest.raises(SystemExit):
        cli.cmd_unclaim(_args())
    assert fake.released == []  # never wrote -- status checked before release
    assert "not held" in capsys.readouterr().err


def test_reports_missing_item_without_mutating(monkeypatch):
    fake = _FakeBeads([], get_raises=True)
    _wire(monkeypatch, fake)
    with pytest.raises(SystemExit):
        cli.cmd_unclaim(_Args(project="p", id="nope", actor="agent", root=None))
    assert fake.released == []


def test_refuses_if_readback_still_held(monkeypatch, capsys):
    # release() "succeeds" but the item is still held on readback -- a silent
    # non-release must become a loud refusal, not a reported success.
    fake = _FakeBeads(["held", "held"])
    _wire(monkeypatch, fake)
    with pytest.raises(SystemExit):
        cli.cmd_unclaim(_args())
    assert "refusing to report success" in capsys.readouterr().err
