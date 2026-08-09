"""Tier 1 -- gateway redaction, pure logic, no bd, no network.

`gateway.redact` / `gateway._redact_context` are the choke point every
free-text field must pass through before an immutable write. This module
proves each PII class is masked, that nesting is handled, and that counts
are recorded honestly -- all without starting an HTTP server or touching
bd.
"""

from __future__ import annotations

from amplifier_work_tracker import gateway as G


def test_redact_email():
    text, counts = G.redact("ping me at alice@example.com please")
    assert "[EMAIL]" in text
    assert "alice@example.com" not in text
    assert counts == {"email": 1}


def test_redact_path_home():
    text, counts = G.redact("see /home/alice/secret-project/notes.txt for details")
    assert "[PATH]" in text
    assert "/home/alice" not in text
    assert counts.get("path") == 1


def test_redact_path_users():
    text, counts = G.redact("file at /Users/bob/Documents/file.txt")
    assert "[PATH]" in text
    assert counts.get("path") == 1


def test_redact_ssn():
    text, counts = G.redact("my ssn is 123-45-6789 for real")
    assert "[SSN]" in text
    assert "123-45-6789" not in text
    assert counts == {"ssn": 1}


def test_redact_card_number():
    text, counts = G.redact("card 4111 1111 1111 1111 declined")
    assert "[CARD]" in text
    assert counts.get("card") == 1


def test_redact_phone_number():
    text, counts = G.redact("call me at 555-123-4567 tomorrow")
    assert "[PHONE]" in text
    assert counts.get("phone") == 1


def test_redact_secret_looking_token():
    text, counts = G.redact("token: aGVsbG8gd29ybGQgdGhpc2lzYXNlY3JldA==")
    assert "[SECRET]" in text
    assert counts.get("secret") == 1


def test_redact_empty_string_is_a_noop():
    text, counts = G.redact("")
    assert text == ""
    assert counts == {}


def test_redact_clean_text_has_no_placeholders_and_no_counts():
    text, counts = G.redact("the button on the settings page does nothing")
    assert text == "the button on the settings page does nothing"
    assert counts == {}


def test_redact_multiple_pii_classes_in_one_string_all_counted():
    text, counts = G.redact("email me at bob@example.com or call 555-123-4567, ssn 123-45-6789")
    assert "[EMAIL]" in text
    assert "[PHONE]" in text
    assert "[SSN]" in text
    assert counts.get("email") == 1
    assert counts.get("phone") == 1
    assert counts.get("ssn") == 1


def test_redact_repeated_same_class_counts_all_occurrences():
    text, counts = G.redact("a@example.com and b@example.com and c@example.com")
    assert text.count("[EMAIL]") == 3
    assert counts == {"email": 3}


# --------------------------------------------------------- nested context


def test_redact_context_flat_string_field():
    redacted, counts = G._redact_context({"note": "reach me at a@example.com"})
    assert redacted["note"] == "reach me at [EMAIL]"
    assert counts == {"email": 1}


def test_redact_context_nested_dict_field_is_redacted():
    """PII buried inside a nested dict (e.g. `context.last_error.detail`)
    must be redacted too -- not just top-level string fields."""
    context = {"last_error": {"detail": "user email is x@example.com"}}
    redacted, counts = G._redact_context(context)
    assert redacted["last_error"]["detail"] == "user email is [EMAIL]"
    assert counts == {"email": 1}


def test_redact_context_list_of_strings_is_redacted():
    """PII inside a list field (e.g. `context.recent_turns`) must be
    redacted element-by-element."""
    context = {"recent_turns": ["hi", "email a@example.com", "bye"]}
    redacted, counts = G._redact_context(context)
    assert redacted["recent_turns"][1] == "email [EMAIL]"
    assert counts == {"email": 1}


def test_redact_context_non_string_values_pass_through_untouched():
    context = {"count": 3, "flag": True, "ratio": 1.5, "nothing": None}
    redacted, counts = G._redact_context(context)
    assert redacted == context
    assert counts == {}


def test_redact_context_aggregates_counts_across_nested_and_sibling_fields():
    context = {
        "top": "a@example.com",
        "nested": {"inner": "b@example.com"},
        "listed": ["c@example.com"],
    }
    _, counts = G._redact_context(context)
    assert counts == {"email": 3}


def test_redact_context_deeply_nested_dict_still_redacted():
    context = {"a": {"b": {"c": "contact d@example.com now"}}}
    redacted, counts = G._redact_context(context)
    assert redacted["a"]["b"]["c"] == "contact [EMAIL] now"
    assert counts == {"email": 1}
