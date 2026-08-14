"""Tier 1 -- pure-function tests for `webapp._humanize_identity`/`_identity_html`.

No bd, no dolt, no network: these are plain string transforms. See
`tests/integration/test_web.py`'s cycle-2 identity-display tests for the
end-to-end check against a real installation's actual `owner` value --
this file covers the passthrough/no-op guarantee for every OTHER shape of
identity string, which does not depend on what any particular bd install
happens to set `owner` to.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="the 'web' extra is not installed")

from amplifier_work_tracker.webapp import _humanize_identity, _identity_html  # noqa: E402

# ------------------------------------------------------- _humanize_identity


def test_humanize_identity_reduces_a_github_noreply_address_to_the_username():
    raw = "240397093+microsoft-amplifier@users.noreply.github.com"
    assert _humanize_identity(raw) == "microsoft-amplifier"


def test_humanize_identity_handles_a_hyphenated_username():
    raw = "12345+some-org-bot@users.noreply.github.com"
    assert _humanize_identity(raw) == "some-org-bot"


def test_humanize_identity_leaves_an_ordinary_actor_name_unchanged():
    assert _humanize_identity("agent-spark-1-106784") == "agent-spark-1-106784"
    assert _humanize_identity("alice") == "alice"


def test_humanize_identity_leaves_a_non_noreply_email_unchanged():
    """Only the specific GitHub noreply SHAPE is reduced -- an ordinary
    email address is a real, meaningful identity, not something to hide."""
    assert _humanize_identity("alice@example.com") == "alice@example.com"


def test_humanize_identity_handles_empty_and_none():
    assert _humanize_identity(None) == ""
    assert _humanize_identity("") == ""
    assert _humanize_identity("   ") == ""


def test_humanize_identity_strips_surrounding_whitespace():
    raw = "  240397093+microsoft-amplifier@users.noreply.github.com  "
    assert _humanize_identity(raw) == "microsoft-amplifier"


# ----------------------------------------------------------- _identity_html


def test_identity_html_wraps_a_humanized_noreply_identity_with_a_raw_tooltip():
    raw = "240397093+microsoft-amplifier@users.noreply.github.com"
    html = _identity_html(raw)
    assert html == f'<span title="{raw}">microsoft-amplifier</span>'


def test_identity_html_renders_an_ordinary_identity_as_plain_escaped_text_only():
    """No pointless `<span title="X">X</span>` wrapper when there is
    nothing to humanize -- the raw value IS the display value."""
    html = _identity_html("agent-spark-1-106784")
    assert html == "agent-spark-1-106784"
    assert "<span" not in html


def test_identity_html_escapes_html_special_characters():
    html = _identity_html("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_identity_html_returns_empty_string_for_missing_identity():
    assert _identity_html(None) == ""
    assert _identity_html("") == ""
