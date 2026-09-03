"""Tier 1 -- `Beads.reopen`'s refusals, and its archive-BEFORE-transition
ordering.

Both are provable without bd, and both are load-bearing:

  - reopen is deliberately NOT idempotent. Reopening an item that is not
    resolved RAISES rather than no-ops -- the mirror image of `resolve`'s
    rule. This program's recurring defect is an operation that looks like it
    worked; "reopen succeeded" on an already-open item tells the caller
    something false about what they just did.
  - the archive comment carrying the verbatim previous resolution is written
    BEFORE `bd reopen` runs. bd 1.1.2's treatment of `close_reason` across a
    reopen is undocumented upstream, so the wrapper's guarantee must not
    depend on it. Ordering is the guarantee.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amplifier_work_tracker import adapter as A


class _Ok:
    returncode = 0
    stdout = ""
    stderr = ""


class _Stub:
    def __init__(self, *, current: A.Item, after: A.Item | None = None):
        self.bd = A.Beads(Path("/nonexistent/.beads"), actor="tester")
        self.calls: list[str] = []
        self.comments: list[str] = []
        self.reads = 0

        def _get(item_id: str, *, with_links: bool = False) -> A.Item:
            self.reads += 1
            return current if self.reads == 1 or after is None else after

        def _comment(item_id: str, text: str, *, actor: str | None = None) -> None:
            self.calls.append("comment")
            self.comments.append(text)

        def _run(args, actor=None):
            self.calls.append(f"run:{args[0]}")
            return _Ok()

        self.bd.get = _get  # type: ignore[method-assign]
        self.bd.comment = _comment  # type: ignore[method-assign]
        self.bd._run = _run  # type: ignore[method-assign]


def _item(status: str, resolution: str | None = None) -> A.Item:
    return A.Item(id="p-1", title="probe", status=status, resolution=resolution)


@pytest.mark.parametrize("status", ["open", "held", "blocked", "deferred"])
def test_reopen_refuses_anything_that_is_not_resolved(status: str):
    stub = _Stub(current=_item(status))
    with pytest.raises(A.BeadsError) as e:
        stub.bd.reopen("p-1", "correcting the record")
    assert "nothing to reopen" in str(e.value)
    assert status in str(e.value)
    assert stub.calls == []  # nothing written, not even the archive comment


@pytest.mark.parametrize("reason", ["", "   ", "\n\t "])
def test_reopen_refuses_an_empty_reason_before_reading_anything(reason: str):
    stub = _Stub(current=_item("resolved", "old text"))
    with pytest.raises(A.BeadsError) as e:
        stub.bd.reopen("p-1", reason)
    assert "reason is required" in str(e.value)
    assert stub.calls == []


def test_reopen_archives_the_verbatim_previous_record_before_transitioning():
    stub = _Stub(
        current=_item("resolved", "the ORIGINAL text, wrong"),
        after=_item("open", None),
    )
    outcome = stub.bd.reopen("p-1", "2lp proved the verdict uncomputable", actor="corrector")

    # Ordering, not merely presence: the archive lands first, so the record
    # survives whatever bd does to close_reason during the transition.
    assert stub.calls == ["comment", "run:reopen"]
    archived = stub.comments[0]
    assert "the ORIGINAL text, wrong" in archived
    assert "2lp proved the verdict uncomputable" in archived
    assert "corrector reopened this item" in archived
    assert "PREVIOUS closed_at:" in archived

    # And the old text comes back in the RESULT too -- the caller is about
    # to write the replacement, usually as an edit of it.
    assert outcome.previous_resolution == "the ORIGINAL text, wrong"
    assert outcome.item.status == "open"
    assert outcome.actor == "corrector"


def test_reopen_refuses_to_report_success_if_the_item_is_still_resolved():
    stub = _Stub(current=_item("resolved", "old"), after=_item("resolved", "old"))
    with pytest.raises(A.BeadsError) as e:
        stub.bd.reopen("p-1", "why")
    assert "refusing to report success" in str(e.value)


def test_reopen_archives_a_blank_previous_resolution_explicitly():
    """An item closed with no resolution (e.g. via supersede) still gets an
    honest archive entry, never a silently empty one."""
    stub = _Stub(current=_item("resolved", None), after=_item("open", None))
    stub.bd.reopen("p-1", "why")
    assert "(none -- was blank)" in stub.comments[0]
