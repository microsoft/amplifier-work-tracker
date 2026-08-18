"""Tier 1 -- ntfy alarm channel (webpush), pure logic + mock transport.

No real network and no real waiting: every request is served by an
``httpx.MockTransport`` handler, and the retry backoff is driven through an
injected ``sleep`` that merely records the durations it was asked to wait. The
custody-breach trigger is exercised against the SAME trusted signal the reaper
uses -- ``custody.reclaim_eligible`` -- with a forged stale timestamp, so the
"fire on a real alarm condition" wiring is proven without a live queue.

Test/function names all contain ``push`` so ``pytest -k push`` selects them.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx
import pytest

from amplifier_work_tracker import custody as C
from amplifier_work_tracker import webpush as W

# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #


def _enabled_config(**overrides) -> W.NtfyConfig:
    base = {
        "server": "https://ntfy.example",
        "topic": "secret-topic",
        "token": "tok-abc",
        "enabled": True,
        "max_attempts": 4,
        "backoff_base": 0.5,
        "click_base": None,
    }
    base.update(overrides)
    return W.NtfyConfig(**base)


class _Recorder:
    """Serves a scripted list of responses (int status codes, or an Exception
    to raise) and records every request it received."""

    def __init__(self, script):
        self._script = list(script)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        outcome = self._script.pop(0) if self._script else 200
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome)

    @property
    def count(self) -> int:
        return len(self.requests)


def _client(recorder: _Recorder) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(recorder))


class _SleepSpy:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# request shape                                                                #
# --------------------------------------------------------------------------- #


def test_push_send_alarm_request_shape_and_headers():
    rec = _Recorder([200])
    client = _client(rec)
    result = _run(
        W.send_alarm(
            "Alarm title",
            "the body message",
            tags=["rotating_light", "warning"],
            click="https://dash.example/item/wt-1",
            config=_enabled_config(),
            client=client,
        )
    )

    assert result.delivered is True
    assert result.attempts == 1
    assert result.status == 200
    assert rec.count == 1

    req = rec.requests[0]
    assert req.method == "POST"
    assert str(req.url) == "https://ntfy.example/secret-topic"
    # message is the RAW UTF-8 body, exactly like hooks-notify-push.
    assert req.content == b"the body message"
    assert req.headers["Title"] == "Alarm title"
    assert req.headers["Priority"] == "urgent"
    assert req.headers["Tags"] == "rotating_light,warning"
    assert req.headers["Click"] == "https://dash.example/item/wt-1"
    assert req.headers["Authorization"] == "Bearer tok-abc"


def test_push_default_priority_is_urgent():
    rec = _Recorder([200])
    _run(W.send_alarm("t", "m", config=_enabled_config(), client=_client(rec)))
    assert rec.requests[0].headers["Priority"] == W.PRIORITY_ALARM == "urgent"


def test_push_bearer_absent_when_no_token():
    rec = _Recorder([200])
    _run(W.send_alarm("t", "m", config=_enabled_config(token=None), client=_client(rec)))
    assert "Authorization" not in rec.requests[0].headers


def test_push_utf8_body_is_encoded():
    rec = _Recorder([200])
    _run(W.send_alarm("t", "café — déjà", config=_enabled_config(), client=_client(rec)))
    assert rec.requests[0].content == "café — déjà".encode()


def test_push_omits_tags_and_click_when_absent():
    rec = _Recorder([200])
    _run(W.send_alarm("t", "m", config=_enabled_config(), client=_client(rec)))
    headers = rec.requests[0].headers
    assert "Tags" not in headers
    assert "Click" not in headers


# --------------------------------------------------------------------------- #
# enable flag / config guards                                                  #
# --------------------------------------------------------------------------- #


def test_push_disabled_channel_is_noop():
    rec = _Recorder([200])
    result = _run(
        W.send_alarm("t", "m", config=_enabled_config(enabled=False), client=_client(rec))
    )
    assert result.disabled is True
    assert result.delivered is False
    assert rec.count == 0  # nothing sent


def test_push_enabled_without_topic_raises_config_error():
    rec = _Recorder([200])
    with pytest.raises(W.AlarmConfigError):
        _run(W.send_alarm("t", "m", config=_enabled_config(topic=""), client=_client(rec)))
    assert rec.count == 0


# --------------------------------------------------------------------------- #
# retry on transient failure                                                   #
# --------------------------------------------------------------------------- #


def test_push_retries_on_5xx_then_succeeds():
    rec = _Recorder([500, 503, 200])
    sleep = _SleepSpy()
    result = _run(
        W.send_alarm("t", "m", config=_enabled_config(), client=_client(rec), sleep=sleep)
    )
    assert result.delivered is True
    assert result.attempts == 3
    assert rec.count == 3
    # exponential backoff: 0.5 * 2**0, then 0.5 * 2**1
    assert sleep.calls == [0.5, 1.0]


def test_push_retries_on_429_then_succeeds():
    rec = _Recorder([429, 200])
    sleep = _SleepSpy()
    result = _run(
        W.send_alarm("t", "m", config=_enabled_config(), client=_client(rec), sleep=sleep)
    )
    assert result.delivered is True
    assert result.attempts == 2
    assert sleep.calls == [0.5]


def test_push_retries_on_network_error_then_succeeds():
    boom = httpx.ConnectError("simulated connect failure")
    rec = _Recorder([boom, 200])
    sleep = _SleepSpy()
    result = _run(
        W.send_alarm("t", "m", config=_enabled_config(), client=_client(rec), sleep=sleep)
    )
    assert result.delivered is True
    assert result.attempts == 2
    assert sleep.calls == [0.5]


# --------------------------------------------------------------------------- #
# LOUD fail                                                                    #
# --------------------------------------------------------------------------- #


def test_push_loud_fail_after_exhausting_retries(caplog):
    rec = _Recorder([503, 503, 503])
    sleep = _SleepSpy()
    with caplog.at_level(logging.ERROR, logger="amplifier_work_tracker.webpush"):
        with pytest.raises(W.AlarmDeliveryError) as ei:
            _run(
                W.send_alarm(
                    "urgent thing",
                    "m",
                    config=_enabled_config(),
                    client=_client(rec),
                    max_attempts=3,
                    sleep=sleep,
                )
            )
    assert ei.value.attempts == 3
    assert ei.value.last_status == 503
    assert rec.count == 3
    assert sleep.calls == [0.5, 1.0]  # slept between the 3 attempts, not after the last
    # LOUD: an ERROR-level record naming the failure, not a debug whisper.
    assert any(r.levelno == logging.ERROR for r in caplog.records)
    assert "delivery FAILED" in caplog.text


def test_push_non_transient_4xx_fails_immediately_without_retry(caplog):
    rec = _Recorder([403, 200])  # 200 must never be reached
    sleep = _SleepSpy()
    with caplog.at_level(logging.ERROR, logger="amplifier_work_tracker.webpush"):
        with pytest.raises(W.AlarmDeliveryError) as ei:
            _run(W.send_alarm("t", "m", config=_enabled_config(), client=_client(rec), sleep=sleep))
    assert ei.value.attempts == 1
    assert ei.value.last_status == 403
    assert rec.count == 1  # no retry on a client error
    assert sleep.calls == []
    assert "delivery FAILED" in caplog.text


def test_push_loud_fail_on_persistent_network_error(caplog):
    boom = httpx.ConnectError("down")
    rec = _Recorder([boom, boom])
    sleep = _SleepSpy()
    with caplog.at_level(logging.ERROR, logger="amplifier_work_tracker.webpush"):
        with pytest.raises(W.AlarmDeliveryError) as ei:
            _run(
                W.send_alarm(
                    "t",
                    "m",
                    config=_enabled_config(),
                    client=_client(rec),
                    max_attempts=2,
                    sleep=sleep,
                )
            )
    assert ei.value.attempts == 2
    assert ei.value.last_status is None
    assert "ConnectError" in (ei.value.last_error or "")
    assert "delivery FAILED" in caplog.text


def test_push_max_attempts_one_does_not_retry():
    rec = _Recorder([500])
    sleep = _SleepSpy()
    with pytest.raises(W.AlarmDeliveryError):
        _run(
            W.send_alarm(
                "t",
                "m",
                config=_enabled_config(),
                client=_client(rec),
                max_attempts=1,
                sleep=sleep,
            )
        )
    assert rec.count == 1
    assert sleep.calls == []


# --------------------------------------------------------------------------- #
# config resolution from env                                                   #
# --------------------------------------------------------------------------- #


def test_push_resolve_config_defaults_and_secrets_env_only():
    cfg = W.resolve_config({"NTFY_TOPIC": "top", "NTFY_ALARM_ENABLED": "1"})
    assert cfg.server == "https://ntfy.sh"  # default
    assert cfg.topic == "top"
    assert cfg.token is None  # unset -> None, never blank string
    assert cfg.enabled is True
    assert cfg.url == "https://ntfy.sh/top"
    assert cfg.max_attempts == W.DEFAULT_MAX_ATTEMPTS


def test_push_resolve_config_overrides_and_url_join():
    cfg = W.resolve_config(
        {
            "NTFY_SERVER": "https://ntfy.example/",  # trailing slash trimmed
            "NTFY_TOPIC": "t",
            "NTFY_TOKEN": "sekret",
            "NTFY_ALARM_ENABLED": "yes",
            "NTFY_MAX_ATTEMPTS": "7",
            "NTFY_BACKOFF_BASE_SECONDS": "0.1",
        }
    )
    assert cfg.url == "https://ntfy.example/t"
    assert cfg.token == "sekret"
    assert cfg.max_attempts == 7
    assert cfg.backoff_base == 0.1


def test_push_resolve_config_disabled_when_flag_absent_or_falsey():
    assert W.resolve_config({"NTFY_TOPIC": "t"}).enabled is False
    assert W.resolve_config({"NTFY_TOPIC": "t", "NTFY_ALARM_ENABLED": "0"}).enabled is False
    assert W.resolve_config({"NTFY_TOPIC": "t", "NTFY_ALARM_ENABLED": "false"}).enabled is False


def test_push_resolve_config_bad_numbers_fall_back_to_defaults():
    cfg = W.resolve_config(
        {"NTFY_TOPIC": "t", "NTFY_MAX_ATTEMPTS": "notanint", "NTFY_BACKOFF_BASE_SECONDS": "x"}
    )
    assert cfg.max_attempts == W.DEFAULT_MAX_ATTEMPTS
    assert cfg.backoff_base == W.DEFAULT_BACKOFF_BASE


def test_push_dashboard_link_none_without_base():
    assert W.dashboard_link("wt-1", click_base=None) is None
    assert (
        W.dashboard_link("wt-1", click_base="https://d.example/") == "https://d.example/item/wt-1"
    )


# --------------------------------------------------------------------------- #
# the trigger: custody breach -> alarm (the already-trusted signal)            #
# --------------------------------------------------------------------------- #


def _stale_custody_record(*, last_seen_ago: float) -> dict:
    """A custody record whose last renewal is `last_seen_ago` seconds in the
    past -- forged, never slept, exactly as tests/unit/test_custody.py does."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - last_seen_ago))
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time()))
    return {
        "holder": "agent-7",
        "pid": 4242,
        "host": "worker-a",
        "generation": 1,
        "started_at": now,
        "declared_since": now,
        "last_seen": ts,
        "declared_state": C.STATE_WORKING,
    }


def test_push_reclaim_alarm_payload_carries_id_reason_and_urgent_tags():
    title, message, tags, click = W.reclaim_alarm_payload(
        "wt-42",
        "agent-7",
        "custody stale -- last seen 3600s ago (ttl 900s)",
        click_base="https://dash.example",
    )
    assert "wt-42" in title
    assert "wt-42" in message
    assert "agent-7" in message
    assert "stale" in message
    assert "rotating_light" in tags
    assert click == "https://dash.example/item/wt-42"


def test_push_fires_on_custody_ttl_breach_simulated_item():
    """End-to-end trigger proof: the TRUSTED custody signal says reclaim, and
    that verdict flows through the send path as an urgent alarm."""
    rec = _record = _stale_custody_record(last_seen_ago=3600)
    eligible, reason = C.reclaim_eligible(_record, ttl=900)
    assert eligible is True
    assert "stale" in reason  # this is the alarm condition we key on

    http = _Recorder([200])
    client = _client(http)
    result = _run(
        W.alarm_for_reclaimed_item(
            "wt-99", rec["holder"], reason, config=_enabled_config(), client=client
        )
    )

    assert result.delivered is True
    assert http.count == 1
    req = http.requests[0]
    assert req.headers["Priority"] == "urgent"
    body = req.content.decode()
    assert "wt-99" in body
    assert "agent-7" in body
    assert reason in body
    assert "rotating_light" in req.headers["Tags"]


def test_push_does_not_fire_when_custody_is_fresh():
    """The negative half of the trigger: a freshly-renewed hold is NOT reclaim
    eligible, so nothing should be sent. We assert on the signal directly -- the
    reaper only calls the send path when `reclaim_eligible` is True."""
    fresh = _stale_custody_record(last_seen_ago=10)
    eligible, _ = C.reclaim_eligible(fresh, ttl=900)
    assert eligible is False


# --------------------------------------------------------------------------- #
# sync wiring entry point never raises (safe inside the reap sweep thread)     #
# --------------------------------------------------------------------------- #


def test_push_fire_reclaim_alarm_disabled_is_noop():
    result = W.fire_reclaim_alarm(
        "wt-1", "agent-7", "custody stale", config=_enabled_config(enabled=False)
    )
    assert result.disabled is True
    assert result.delivered is False


def test_push_fire_reclaim_alarm_swallows_config_error():
    # enabled but no topic -> AlarmConfigError inside; the sync wrapper must not
    # let it escape and abort the reap sweep.
    result = W.fire_reclaim_alarm(
        "wt-1", "agent-7", "custody stale", config=_enabled_config(topic="")
    )
    assert result.delivered is False
    assert result.error is not None


def test_push_fire_reclaim_alarm_swallows_delivery_error(monkeypatch):
    async def _boom(*_a, **_k):
        raise W.AlarmDeliveryError("nope", attempts=3, last_status=503, last_error=None)

    monkeypatch.setattr(W, "alarm_for_reclaimed_item", _boom)
    result = W.fire_reclaim_alarm("wt-1", "agent-7", "custody stale", config=_enabled_config())
    assert result.delivered is False
    assert result.attempts == 3
    assert result.status == 503
