"""Tier 1 -- `resolve` compares the resolution TEXT, not merely the status,
at BOTH places it decides "did my write land?".

The defect these pin (work_tracker item model_performance-uma, spec
`w3-uma-work-tracker-reopen/SPEC.md`): a `resolve` against an ALREADY-closed
item exited 0 and echoed the OLD stored text back as if it were the text just
written. Seven wrong resolutions shipped that way and could not be corrected.

`resolve` decides that question in two places, and a fix that patches only
the obvious one leaves the other silently wrong:

  - the normal post-write readback (`bd close` returned 0), and
  - the CONTENDED path, where `_run` exhausted its serialization-retry
    budget and raised, so the wrapper reads the item back and decides from
    what it finds.

The contended path is where a caller is LEAST able to reason about what
happened, so both are exercised here -- with no bd and no dolt, by driving a
`Beads` instance whose `_run`/`get` are stubbed. That is deliberate: these
are the wrapper's own decisions, and they must be provable without needing a
contention race to occur for real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amplifier_work_tracker import adapter as A

# ---------------------------------------------------------------- normalization


def test_norm_resolution_unifies_line_endings_and_strips_outer_whitespace():
    assert A._norm_resolution("fixed the thing\r\n") == "fixed the thing"
    assert A._norm_resolution("  fixed the thing  ") == "fixed the thing"
    assert A._norm_resolution("a\r\nb") == A._norm_resolution("a\nb")
    assert A._norm_resolution(None) == ""


def test_norm_resolution_keeps_case_and_internal_whitespace_significant():
    """Both are REAL edits to what a human will read -- a normalization that
    swallowed them would re-open the silent-discard hole from the inside."""
    assert not A._resolution_landed("Fixed", "fixed")
    assert not A._resolution_landed("a b", "a  b")
    assert not A._resolution_landed("line one\nline two", "line one line two")


def test_resolution_landed_is_true_only_for_the_same_text():
    assert A._resolution_landed("done\n", "done")
    assert A._resolution_landed(None, "   ")
    assert not A._resolution_landed("done", "done, actually not")


def test_echo_resolution_truncates_loudly_never_silently():
    long = "x" * 900
    out = A._echo_resolution(long)
    assert out.startswith("x" * A.RESOLUTION_ECHO_LIMIT)
    assert "[truncated, 900 chars]" in out
    assert A._echo_resolution("") == "(none -- blank)"
    assert A._echo_resolution("short") == "short"


def test_divergent_error_message_carries_everything_a_caller_needs():
    err = A._divergent_resolution_error(
        "proj-abc",
        project="proj",
        stored="VERDICT: retention PASSES",
        sent="2lp proved this UNCOMPUTABLE",
    )
    msg = str(err)
    # 1. the item, 2. both texts side by side, 3. the words that stop a
    # blind retry, 4. the remedy as a runnable command on BOTH surfaces.
    assert "proj-abc" in msg
    assert "VERDICT: retention PASSES" in msg
    assert "2lp proved this UNCOMPUTABLE" in msg
    assert "NOTHING WAS WRITTEN" in msg
    assert "amplifier-work-tracker reopen --project proj --id proj-abc" in msg
    assert "work_reopen(" in msg


# ------------------------------------------------------------------- the wrapper


class _Stub:
    """A `Beads` with its two bd-touching primitives replaced.

    Only `_run` and `get` are stubbed -- every decision under test is made
    by the real `resolve_outcome` code path, including `_read_back_or_none`,
    which routes through the stubbed `get` exactly as it would route through
    the real one.
    """

    def __init__(self, *, current: A.Item | None, after: A.Item | None, run):
        self.bd = A.Beads(Path("/nonexistent/.beads"), actor="tester")
        self.reads = 0
        self.run_calls: list[list[str]] = []

        def _get(item_id: str, *, with_links: bool = False) -> A.Item:
            self.reads += 1
            item = current if self.reads == 1 else after
            if item is None:
                raise A.BeadsError(f"item {item_id!r} not found")
            return item

        def _run_stub(args, actor=None):
            self.run_calls.append(list(args))
            return run(args)

        self.bd.get = _get  # type: ignore[method-assign]
        self.bd._run = _run_stub  # type: ignore[method-assign]


def _item(item_id: str, *, status: str, resolution: str | None) -> A.Item:
    return A.Item(id=item_id, title="probe", status=status, resolution=resolution)


class _Ok:
    returncode = 0
    stdout = ""
    stderr = ""


def _ok(_args):
    return _Ok()


def _raises(_args):
    raise A.BeadsError("still conflicting after 8 retries")


# --- precondition (checked BEFORE any write, so "NOTHING WAS WRITTEN" is true)


def test_divergent_text_on_a_closed_item_refuses_and_writes_nothing():
    stub = _Stub(
        current=_item("p-1", status="resolved", resolution="the ORIGINAL, wrong text"),
        after=None,
        run=_ok,
    )
    with pytest.raises(A.BeadsError) as e:
        stub.bd.resolve_outcome("p-1", "the CORRECTED text")
    assert "NOTHING WAS WRITTEN" in str(e.value)
    assert "the ORIGINAL, wrong text" in str(e.value)
    assert "the CORRECTED text" in str(e.value)
    # The whole promise: no bd write was even attempted.
    assert stub.run_calls == []


def test_identical_text_on_a_closed_item_is_an_idempotent_success_with_no_write():
    """The retry case the contention contract promises is safe: a retry
    re-sends the identical string, and must not be turned into a failure."""
    stub = _Stub(
        current=_item("p-2", status="resolved", resolution="done: fixed the parser\n"),
        after=None,
        run=_ok,
    )
    outcome = stub.bd.resolve_outcome("p-2", "done: fixed the parser")
    assert outcome.idempotent is True
    assert outcome.item.id == "p-2"
    assert stub.run_calls == []


def test_resolving_an_open_item_is_unchanged():
    stub = _Stub(
        current=_item("p-3", status="open", resolution=None),
        after=_item("p-3", status="resolved", resolution="closed it"),
        run=_ok,
    )
    outcome = stub.bd.resolve_outcome("p-3", "closed it")
    assert outcome.idempotent is False
    assert outcome.item.status == "resolved"
    assert stub.run_calls and stub.run_calls[0][0] == "close"


# --- decision point 1: the normal post-write readback


def test_post_write_readback_refuses_when_the_stored_text_is_not_ours():
    """`bd close` exited 0, the item is resolved -- and the resolution on it
    is somebody else's text. Status alone would call that success."""
    stub = _Stub(
        current=_item("p-4", status="open", resolution=None),
        after=_item("p-4", status="resolved", resolution="someone else's text"),
        run=_ok,
    )
    with pytest.raises(A.BeadsError) as e:
        stub.bd.resolve_outcome("p-4", "my text")
    assert "someone else's text" in str(e.value)
    assert "my text" in str(e.value)
    assert "reopen" in str(e.value)


# --- decision point 2: the CONTENDED path (_run raised; wrapper reads back)


def test_contended_path_reports_success_only_when_our_own_text_landed():
    stub = _Stub(
        current=_item("p-5", status="open", resolution=None),
        after=_item("p-5", status="resolved", resolution="my text"),
        run=_raises,
    )
    outcome = stub.bd.resolve_outcome("p-5", "my text")
    assert outcome.item.status == "resolved"
    # Not idempotent: the precondition read proved it was open when we
    # started, so the write that landed was OURS, inside this call.
    assert outcome.idempotent is False


def test_contended_path_raises_when_the_readback_text_is_not_ours():
    """THE EASY ONE TO MISS. `_run` gave up; the readback shows the item
    resolved -- but with text that is not what we sent. Returning that item
    as success (status-only check) is a lie, and it is the exact site a
    half-done fix leaves wrong."""
    stub = _Stub(
        current=_item("p-6", status="open", resolution=None),
        after=_item("p-6", status="resolved", resolution="a DIFFERENT resolution"),
        run=_raises,
    )
    with pytest.raises(A.BeadsError) as e:
        stub.bd.resolve_outcome("p-6", "the text I actually sent")
    msg = str(e.value)
    assert "a DIFFERENT resolution" in msg
    assert "the text I actually sent" in msg
    assert "NOT WRITTEN" in msg
    assert "reopen" in msg


def test_contended_path_still_reraises_when_the_item_never_closed():
    """Unchanged behaviour: the wrapper gave up and the item is NOT
    resolved, so the original conflict error is what the caller gets."""
    stub = _Stub(
        current=_item("p-7", status="open", resolution=None),
        after=_item("p-7", status="open", resolution=None),
        run=_raises,
    )
    with pytest.raises(A.BeadsError) as e:
        stub.bd.resolve_outcome("p-7", "my text")
    assert "still conflicting after 8 retries" in str(e.value)


def test_resolve_returns_an_item_for_every_existing_caller():
    """`resolve()` keeps its `Item` return type -- `resolve_outcome` is the
    additive entry point, not a breaking rename."""
    stub = _Stub(
        current=_item("p-8", status="open", resolution=None),
        after=_item("p-8", status="resolved", resolution="closed"),
        run=_ok,
    )
    back = stub.bd.resolve("p-8", "closed")
    assert isinstance(back, A.Item)
    assert back.status == "resolved"
