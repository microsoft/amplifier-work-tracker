"""Tier 1 -- `Beads.erratum`'s preconditions and idempotency short-circuit,
plus the ERRATUM comment format's parse/format round-trip. All provable
without bd -- same stubbing style `test_reopen_preconditions.py` already
established (a `Beads` instance over a nonexistent `.beads` dir, with
`get`/`_run` monkey-assigned directly on the instance).

work_tracker item pipeline-03c: an agent resolved an item with a factually
false reason, noticed in the same run, and had no sanctioned way to correct
the record without either destroying the resolution's finality (`reopen`)
or silently discarding the correction (`resolve` on an already-closed item).
`erratum` is the append-only, no-claim-required third path.
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
    """A `Beads` instance whose `get`/`_run` are replaced so `erratum` can be
    exercised without a real `bd`/dolt. `current` is what `bd.get(item_id)`
    returns; every `_run` call is recorded (never actually invoking a
    subprocess) so a precondition failure can assert nothing was written.
    """

    def __init__(self, *, current: A.Item):
        self.bd = A.Beads(Path("/nonexistent/.beads"), actor="tester")
        self.run_calls: list[list[str]] = []

        def _get(item_id: str, *, with_links: bool = False) -> A.Item:
            return current

        def _run(args, actor=None):  # noqa: ANN001 -- matches Beads._run's signature
            self.run_calls.append(list(args))
            return _Ok()

        self.bd.get = _get  # type: ignore[method-assign]
        self.bd._run = _run  # type: ignore[method-assign]


def _item(
    status: str,
    *,
    resolution: str | None = None,
    errata: list[A.Erratum] | None = None,
) -> A.Item:
    return A.Item(
        id="p-1", title="probe", status=status, resolution=resolution, errata=errata or []
    )


# --------------------------------------------------------------- preconditions


def test_erratum_refuses_an_empty_actor_before_reading_anything():
    stub = _Stub(current=_item("resolved", resolution="stored"))
    with pytest.raises(A.BeadsError) as e:
        stub.bd.erratum("p-1", actor="   ", text="the record is wrong")
    assert "actor" in str(e.value).lower()
    assert "required" in str(e.value).lower()
    assert stub.run_calls == []


def test_erratum_refuses_a_missing_item():
    """`bd.get` raising "not found" propagates untouched -- the same
    disambiguated not-found wording every other verb here already surfaces
    (see `get_readonly`'s own wrong-project-vs-missing split)."""
    stub = A.Beads(Path("/nonexistent/.beads"), actor="tester")

    def _get(item_id: str, *, with_links: bool = False) -> A.Item:
        raise A.BeadsError(f"item {item_id!r} not found in project 'p'")

    stub.get = _get  # type: ignore[method-assign]
    with pytest.raises(A.BeadsError, match="not found"):
        stub.erratum("p-1", actor="alice", text="wrong")


@pytest.mark.parametrize("status", ["open", "held", "blocked", "deferred"])
def test_erratum_refuses_anything_that_is_not_resolved_and_names_edit(status: str):
    stub = _Stub(current=_item(status))
    with pytest.raises(A.BeadsError) as e:
        stub.bd.erratum("p-1", actor="alice", text="the record is wrong")
    msg = str(e.value)
    assert status in msg
    assert "'resolved'" in msg
    assert "edit" in msg.lower()
    assert "work_edit" in msg
    assert stub.run_calls == []  # nothing written


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_erratum_refuses_empty_text_on_a_resolved_item(text: str):
    stub = _Stub(current=_item("resolved", resolution="stored text"))
    with pytest.raises(A.BeadsError) as e:
        stub.bd.erratum("p-1", actor="alice", text=text)
    assert "text is required" in str(e.value)
    assert stub.run_calls == []


# ------------------------------------------------------------- idempotency
#
# The idempotency short-circuit reads `cur.errata` (already on the `Item`
# `bd.get` returned) directly -- it never needs a second SQL round trip, so
# this is provable purely at the stub level, with no `_errata_via_sql`
# patching required at all.


def test_erratum_is_an_idempotent_noop_when_byte_identical_text_already_recorded():
    existing = A.Erratum(at="2026-09-01T00:00:00Z", by="bob", text="the reason was wrong")
    stub = _Stub(current=_item("resolved", resolution="stored", errata=[existing]))

    outcome = stub.bd.erratum("p-1", actor="alice", text="the reason was wrong")

    assert outcome.already_recorded is True
    assert outcome.item.errata == [existing]
    assert stub.run_calls == [], "an idempotent no-op must write nothing"


def test_erratum_idempotency_normalizes_crlf_and_outer_whitespace_like_resolve_does():
    existing = A.Erratum(at="2026-09-01T00:00:00Z", by="bob", text="line one\nline two")
    stub = _Stub(current=_item("resolved", resolution="stored", errata=[existing]))

    outcome = stub.bd.erratum("p-1", actor="alice", text="  line one\r\nline two  ")

    assert outcome.already_recorded is True
    assert stub.run_calls == []


def test_erratum_idempotency_is_keyed_by_any_actor_not_just_the_original_one():
    """The design's own rule: 'a byte-identical erratum already present BY
    ANY ACTOR' is a no-op -- not scoped to the calling actor."""
    existing = A.Erratum(at="2026-09-01T00:00:00Z", by="the-original-actor", text="same text")
    stub = _Stub(current=_item("resolved", resolution="stored", errata=[existing]))

    outcome = stub.bd.erratum("p-1", actor="a-totally-different-actor", text="same text")

    assert outcome.already_recorded is True
    assert stub.run_calls == []


def test_erratum_different_text_is_not_treated_as_idempotent(monkeypatch):
    """Genuinely different text must NOT take the idempotent shortcut --
    it has to proceed to a real write attempt. The write itself (verified
    by read-back over `_errata_via_sql`, a real SQL call) is exercised
    end-to-end in `tests/integration/test_erratum.py`; here, `_errata_via_sql`
    is faked so this stays a pure, DB-free unit test of the ONE thing this
    test is about: the idempotency gate did not fire.
    """
    existing = A.Erratum(at="2026-09-01T00:00:00Z", by="bob", text="first correction")
    stub = _Stub(current=_item("resolved", resolution="stored", errata=[existing]))
    landed: list[A.Erratum] = []

    def fake_errata_via_sql(db: str, item_id: str) -> list[A.Erratum]:
        return [existing, *landed]

    monkeypatch.setattr(A, "_errata_via_sql", fake_errata_via_sql)

    real_run = stub.bd._run

    def _run(args, actor=None):  # noqa: ANN001
        p = real_run(args, actor=actor)
        # Pretend the comment call actually landed, the same way a real
        # `bd comment` would -- `_verified_write`'s own verify then sees it.
        landed.append(A.Erratum(at="now", by=actor or "alice", text=args[2].split(": ", 1)[-1]))
        return p

    stub.bd._run = _run  # type: ignore[method-assign]

    outcome = stub.bd.erratum("p-1", actor="alice", text="a completely different correction")

    assert outcome.already_recorded is False
    assert stub.run_calls, "distinct text must attempt a real write"
    assert stub.run_calls[0][0] == "comment"


def test_erratum_never_touches_status_closed_at_or_holder_on_the_stub_item():
    """The stub's `get` never receives a status/holder-mutating call --
    proving `erratum` issues no such write at all, not merely that the
    fields happen to look unchanged afterward."""
    existing = A.Erratum(at="2026-09-01T00:00:00Z", by="bob", text="same text")
    stub = _Stub(current=_item("resolved", resolution="stored", errata=[existing]))
    stub.bd.erratum("p-1", actor="alice", text="same text")
    assert stub.run_calls == []


# --------------------------------------------------------- comment wire format


def test_format_then_parse_round_trips_a_plain_erratum():
    at = "2026-09-03T12:34:56Z"
    formatted = A._format_erratum_comment(at, "alice", "the resolution text was wrong")
    assert formatted == "ERRATUM 2026-09-03T12:34:56Z alice: the resolution text was wrong"

    parsed = A._parse_erratum_comment("alice", formatted)
    assert parsed == A.Erratum(at=at, by="alice", text="the resolution text was wrong")


def test_format_then_parse_round_trips_an_actor_containing_a_colon_and_space():
    """The measured requirement: an actor whose own identity contains ':
    ' must not be mis-split from the text that follows it. The parser
    resolves the boundary from the comment's own `author` column (passed
    here as the first argument), never from the text alone."""
    at = "2026-09-03T12:34:56Z"
    actor = "team: platform-bot"
    formatted = A._format_erratum_comment(at, actor, "the reviewer said: this is fine")
    parsed = A._parse_erratum_comment(actor, formatted)
    assert parsed == A.Erratum(at=at, by=actor, text="the reviewer said: this is fine")


def test_format_then_parse_round_trips_an_actor_containing_only_a_space():
    at = "2026-09-03T12:34:56Z"
    actor = "jane doe"
    formatted = A._format_erratum_comment(at, actor, "wrong verdict")
    parsed = A._parse_erratum_comment(actor, formatted)
    assert parsed == A.Erratum(at=at, by=actor, text="wrong verdict")


def test_format_then_parse_round_trips_multi_line_text():
    at = "2026-09-03T12:34:56Z"
    text = "line one\nline two: still part of the body\nline three"
    formatted = A._format_erratum_comment(at, "alice", text)
    parsed = A._parse_erratum_comment("alice", formatted)
    assert parsed == A.Erratum(at=at, by="alice", text=text)


def test_parse_rejects_a_comment_that_is_not_an_erratum_at_all():
    assert A._parse_erratum_comment("alice", "just a normal comment") is None
    assert A._parse_erratum_comment("alice", "alice edited: description") is None


def test_parse_rejects_when_the_erratum_prefix_belongs_to_a_different_author():
    """A comment shaped `ERRATUM <at> <someone-else>: ...` must not parse
    as belonging to THIS row's `author` -- the author/text boundary is
    resolved from the real `author` column, never guessed from the text.
    """
    formatted = A._format_erratum_comment("2026-09-03T12:34:56Z", "bob", "bob's correction")
    assert A._parse_erratum_comment("alice", formatted) is None


def test_parse_rejects_a_bare_erratum_tag_with_no_timestamp_or_body():
    assert A._parse_erratum_comment("alice", "ERRATUM ") is None
    assert A._parse_erratum_comment("alice", "ERRATUM") is None


def test_erratum_tag_prefix_constant_matches_the_formatter():
    """`ERRATUM_TAG` is the public constant surfaces outside this module
    may reasonably want (e.g. a future doctor check); it must literally be
    the tag `_format_erratum_comment` writes."""
    assert A._format_erratum_comment("t", "a", "x").startswith(A.ERRATUM_TAG + " ")
