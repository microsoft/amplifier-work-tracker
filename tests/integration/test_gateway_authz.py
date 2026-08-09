"""Tier 2 -- Gateway authz and redaction, against a real running server and
a real bd project.

The redaction check here specifically reads the stored item back through
`amplifier_work_tracker.adapter.Beads.get` (the storage layer) rather than
trusting the Gateway's own API response -- an API echo could be redacted
correctly while the write underneath it was not, and that gap is exactly
what "verified at the storage layer" is checking for.
"""

from __future__ import annotations

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.integration


def test_no_token_is_401(gateway_server):
    status, body = gateway_server.request("GET", "/reports")
    assert status == 401
    assert "error" in body


def test_bad_token_is_401(gateway_server):
    status, body = gateway_server.request("GET", "/reports", token="not-a-real-token")
    assert status == 401
    assert "error" in body


def test_identity_spoof_via_query_param_is_403(gateway_server, shared_project_name, unique_actor):
    alice = f"alice-{unique_actor}"
    token = gateway_server.mint(alice, shared_project_name)
    status, body = gateway_server.request("GET", "/reports?reporter=someone-else", token=token)
    assert status == 403
    assert "error" in body


def test_identity_spoof_via_body_field_is_403(gateway_server, shared_project_name, unique_actor):
    alice = f"alice-{unique_actor}"
    token = gateway_server.mint(alice, shared_project_name)
    status, body = gateway_server.request(
        "POST",
        "/reports",
        token=token,
        body={"text": "hello", "reporter_id": "someone-else"},
    )
    assert status == 403
    assert "error" in body


def test_cross_reporter_read_is_404_not_403(gateway_server, shared_project_name, unique_actor):
    """Design decision (see gateway.py's `_handle_get_report`): a
    nonexistent id and "exists but isn't yours" must look identical to the
    caller, so there is no existence-leak. Confirm this deliberately, not
    accidentally."""
    alice = f"alice-{unique_actor}"
    bob = f"bob-{unique_actor}"
    alice_token = gateway_server.mint(alice, shared_project_name)
    bob_token = gateway_server.mint(bob, shared_project_name)

    status, body = gateway_server.request(
        "POST", "/reports", token=alice_token, body={"text": "alice's private report"}
    )
    assert status == 201
    report_id = body["report_id"]

    status, body = gateway_server.request("GET", f"/reports/{report_id}", token=bob_token)
    assert status == 404
    assert "error" in body

    status, _ = gateway_server.request("GET", "/reports/does-not-exist-at-all", token=bob_token)
    assert status == 404


def test_redaction_is_applied_at_the_storage_layer_not_just_the_api_echo(
    gateway_server, shared_project_name, shared_bd: A.Beads, unique_actor
):
    reporter_id = f"pii-{unique_actor}"
    token = gateway_server.mint(reporter_id, shared_project_name)

    raw_text = "ping me at leak@example.com or see /home/alice/secret/notes.txt"
    status, body = gateway_server.request(
        "POST",
        "/reports",
        token=token,
        body={
            "text": raw_text,
            "context": {"last_error": "contact bob@example.com for repro"},
        },
    )
    assert status == 201
    report_id = body["report_id"]
    assert body["redactions"].get("email") == 2
    assert body["redactions"].get("path") == 1

    # Storage-layer check: read the item directly through the adapter,
    # bypassing the Gateway's own API response entirely.
    stored = shared_bd.get(report_id)
    assert "leak@example.com" not in (stored.meta.get("verbatim") or "")
    assert "[EMAIL]" in (stored.meta.get("verbatim") or "")
    assert "/home/alice" not in (stored.meta.get("verbatim") or "")
    assert "[PATH]" in (stored.meta.get("verbatim") or "")
    stored_context = stored.meta.get("context") or {}
    assert "bob@example.com" not in stored_context.get("last_error", "")
    assert "[EMAIL]" in stored_context.get("last_error", "")


def test_reporter_only_sees_their_own_reports_in_the_list_view(
    gateway_server, shared_project_name, unique_actor
):
    alice = f"alice-{unique_actor}"
    bob = f"bob-{unique_actor}"
    alice_token = gateway_server.mint(alice, shared_project_name)
    bob_token = gateway_server.mint(bob, shared_project_name)

    gateway_server.request("POST", "/reports", token=alice_token, body={"text": "alice's report"})
    gateway_server.request("POST", "/reports", token=bob_token, body={"text": "bob's report"})

    status, body = gateway_server.request("GET", "/reports", token=alice_token)
    assert status == 200
    titles = [r["title"] for r in body["reports"]]
    assert any("alice" in t for t in titles)
    assert not any("bob" in t for t in titles)


def test_healthz_requires_no_auth(gateway_server):
    status, body = gateway_server.request("GET", "/healthz")
    assert status == 200
    assert body == {"status": "ok"}
