"""ntfy phone-push ALARM channel -- send-with-retry + LOUD fail.

This adopts the wire shape proven by Amplifier's notify bundle
(`hooks-notify-push`): a plain `POST {server}/{topic}`, the message as raw
UTF-8 body bytes, and all metadata carried in HTTP headers (`Title`,
`Priority`, `Tags`, `Click`). It deliberately ADDS the three things that
bundle lacks and that a real *alarm* channel cannot do without:

  1. **Auth for a self-hosted ntfy** -- `Authorization: Bearer <token>`. This
     deployment sits behind Tailscale; a private self-hosted ntfy plus an
     access token removes the "the topic name IS the password" fragility of
     public ntfy.sh.
  2. **`Priority: urgent`** -- the priority level that bypasses a phone's
     Do-Not-Disturb, which is exactly what turns a notification into an alarm.
  3. **Bounded retry + a LOUD failure** -- a small number of retries on
     transient failure, and on exhaustion (or a non-transient response) a
     `logger.error` (NOT debug-only, the way `hooks-notify-push` logs) *and* a
     raised `AlarmDeliveryError`. An alarm that fails silently is worse than no
     alarm at all -- it tells you nothing is wrong when something is.

Everything is configured from the environment, and the secret (the topic, and
the self-hosted token) lives ONLY in the environment -- never in a settings
file that could be committed:

  NTFY_SERVER            default https://ntfy.sh
  NTFY_TOPIC             the topic; a credential on public ntfy.sh -- env only
  NTFY_TOKEN             self-hosted access token -- env only (optional)
  NTFY_ALARM_ENABLED     enable flag (truthy: 1/true/yes/on) -- opt-in
  NTFY_MAX_ATTEMPTS      retry budget (default 4)
  NTFY_BACKOFF_BASE_SECONDS   backoff base for exponential retry (default 0.5)
  NTFY_CLICK_BASE        optional dashboard base URL for a `Click:` deep-link

Dead-man's-switch heartbeat (noted, not fully wired): the same `send_alarm`
path can carry a periodic "sweeps still alive" heartbeat so that the ABSENCE of
a heartbeat -- not just the presence of a failure -- can raise the phone. The
supervisor already proves sweep liveness on disk (see
`amplifier_work_tracker.heartbeat`); wiring that liveness signal to a
heartbeat push is the natural extension and is left as a follow-up.

This module is import-light and knows nothing about Beads. It takes plain
values (an item id, a holder, a reason string) and speaks HTTP. The reap/notify
loops that would call it live in `supervisor.py` (not owned by this change);
`fire_reclaim_alarm` is the sync, never-raises entry point built for that
caller, and the exact wiring is recorded as a residual.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# --- environment variable names (secrets are env-only, never a settings file) -
ENV_SERVER = "NTFY_SERVER"
ENV_TOPIC = "NTFY_TOPIC"
ENV_TOKEN = "NTFY_TOKEN"
ENV_ENABLED = "NTFY_ALARM_ENABLED"
ENV_MAX_ATTEMPTS = "NTFY_MAX_ATTEMPTS"
ENV_BACKOFF_BASE = "NTFY_BACKOFF_BASE_SECONDS"
ENV_CLICK_BASE = "NTFY_CLICK_BASE"

DEFAULT_SERVER = "https://ntfy.sh"
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_BACKOFF_BASE = 0.5
DEFAULT_TIMEOUT_SECONDS = 10.0

# ntfy's DND-bypassing priority -- this is what makes the channel an *alarm*.
PRIORITY_ALARM = "urgent"

_TRUTHY = {"1", "true", "yes", "on"}


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUTHY


# --------------------------------------------------------------------------- #
# Errors -- both loud by design.                                              #
# --------------------------------------------------------------------------- #


class AlarmConfigError(RuntimeError):
    """The channel was asked to fire while enabled but misconfigured (e.g. no
    topic). Raised loudly rather than swallowed -- a misconfigured alarm is a
    silent alarm, which is the failure this whole module exists to prevent."""


class AlarmDeliveryError(RuntimeError):
    """Delivery failed after exhausting the retry budget, or hit a
    non-transient response (a 4xx other than 429). Carries the diagnostic
    detail and is always accompanied by a `logger.error` at the raise site."""

    def __init__(
        self,
        message: str,
        *,
        attempts: int,
        last_status: int | None,
        last_error: str | None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_status = last_status
        self.last_error = last_error


# --------------------------------------------------------------------------- #
# Config -- resolved from the environment, secrets env-only.                   #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class NtfyConfig:
    server: str
    topic: str
    token: str | None
    enabled: bool
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    backoff_base: float = DEFAULT_BACKOFF_BASE
    click_base: str | None = None

    @property
    def url(self) -> str:
        """The POST target: `{server}/{topic}` with a single joining slash."""
        return f"{self.server.rstrip('/')}/{self.topic}"


def _int_env(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning("%s=%r is not an integer -- using default %d", name, raw, default)
        return default


def _float_env(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        logger.warning("%s=%r is not a number -- using default %s", name, raw, default)
        return default


def resolve_config(env: Mapping[str, str] | None = None) -> NtfyConfig:
    """Build an `NtfyConfig` from the environment (defaults to `os.environ`).

    Passing an explicit mapping keeps this pure and unit-testable without
    touching the real process environment.
    """
    e = env if env is not None else os.environ
    server = (e.get(ENV_SERVER) or "").strip() or DEFAULT_SERVER
    topic = (e.get(ENV_TOPIC) or "").strip()
    token = (e.get(ENV_TOKEN) or "").strip() or None
    click_base = (e.get(ENV_CLICK_BASE) or "").strip() or None
    return NtfyConfig(
        server=server,
        topic=topic,
        token=token,
        enabled=_truthy(e.get(ENV_ENABLED)),
        max_attempts=_int_env(e, ENV_MAX_ATTEMPTS, DEFAULT_MAX_ATTEMPTS),
        backoff_base=_float_env(e, ENV_BACKOFF_BASE, DEFAULT_BACKOFF_BASE),
        click_base=click_base,
    )


# --------------------------------------------------------------------------- #
# Result.                                                                      #
# --------------------------------------------------------------------------- #


@dataclass
class AlarmResult:
    delivered: bool
    attempts: int
    status: int | None = None
    disabled: bool = False
    url: str = ""
    error: str | None = None


# --------------------------------------------------------------------------- #
# Transient classification -- what is worth a retry.                           #
# --------------------------------------------------------------------------- #


def is_transient_status(status: int) -> bool:
    """HTTP status codes worth retrying: 429 (rate limited) and any 5xx.

    A 4xx other than 429 is a client/config error -- retrying it just wastes
    the budget and delays the loud failure, so it is treated as terminal.
    """
    return status == 429 or 500 <= status < 600


def _headers(
    config: NtfyConfig,
    *,
    title: str,
    priority: str,
    tags: Sequence[str] | None,
    click: str | None,
) -> dict[str, str]:
    headers: dict[str, str] = {"Title": title, "Priority": priority}
    if tags:
        headers["Tags"] = ",".join(tags)
    if click:
        headers["Click"] = click
    if config.token:
        headers["Authorization"] = f"Bearer {config.token}"
    return headers


async def send_alarm(
    title: str,
    message: str,
    *,
    priority: str = PRIORITY_ALARM,
    tags: Sequence[str] | None = None,
    click: str | None = None,
    config: NtfyConfig | None = None,
    client: httpx.AsyncClient | None = None,
    max_attempts: int | None = None,
    backoff_base: float | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> AlarmResult:
    """POST an alarm to `{NTFY_SERVER}/{NTFY_TOPIC}`, retrying transient
    failures and failing LOUDLY on exhaustion.

    Wire shape (matching `hooks-notify-push`): the message is the raw UTF-8
    request body; `title`, `priority`, `tags`, and `click` ride in headers; a
    self-hosted token, if configured, is sent as `Authorization: Bearer`.

    Behaviour:
      - Channel disabled (`NTFY_ALARM_ENABLED` not truthy) -> a no-op result
        with `disabled=True`. This makes the call site safe to invoke
        unconditionally when the operator has not opted in.
      - Enabled but no topic -> `AlarmConfigError` (loud): a configured-on but
        unusable alarm is itself an alarm-worthy condition.
      - 2xx -> `AlarmResult(delivered=True, ...)`.
      - Transient failure (network/timeout error, 429, or 5xx) -> retried up to
        `max_attempts` with exponential backoff.
      - Exhausted retries, or a non-transient 4xx -> `logger.error(...)` AND
        `AlarmDeliveryError`. Never a silent swallow.

    `client` and `sleep` are injectable so the whole retry/fail machine is
    unit-testable against a mock transport with no real network and no real
    waiting.
    """
    config = config or resolve_config()
    if not config.enabled:
        logger.debug("ntfy alarm channel disabled (%s not set) -- skipping %r", ENV_ENABLED, title)
        return AlarmResult(delivered=False, attempts=0, disabled=True)
    if not config.topic:
        raise AlarmConfigError(
            f"ntfy alarm is enabled ({ENV_ENABLED}) but {ENV_TOPIC} is unset -- "
            "cannot send; set the topic in the environment"
        )

    attempts = max_attempts if max_attempts is not None else config.max_attempts
    attempts = max(1, attempts)
    base = backoff_base if backoff_base is not None else config.backoff_base
    do_sleep = sleep if sleep is not None else asyncio.sleep

    url = config.url
    body = message.encode("utf-8")
    headers = _headers(config, title=title, priority=priority, tags=tags, click=click)

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS)

    last_status: int | None = None
    last_error: str | None = None
    attempt = 0
    try:
        for attempt in range(1, attempts + 1):
            try:
                resp = await client.post(url, content=body, headers=headers)
            except httpx.RequestError as exc:  # connect/read/write/timeout -- transient
                last_error = f"{type(exc).__name__}: {exc}"
                last_status = None
                if attempt < attempts:
                    await do_sleep(base * (2 ** (attempt - 1)))
                    continue
                break

            last_status = resp.status_code
            last_error = None
            if 200 <= resp.status_code < 300:
                return AlarmResult(
                    delivered=True, attempts=attempt, status=resp.status_code, url=url
                )
            if is_transient_status(resp.status_code) and attempt < attempts:
                await do_sleep(base * (2 ** (attempt - 1)))
                continue
            # Either a transient status on the final attempt, or a non-transient
            # 4xx -- both terminal. Stop and fail loudly below.
            break
    finally:
        if owns_client:
            await client.aclose()

    # LOUD failure -- error level, not debug. This is the line that must appear
    # in the journal when the phone did not ring.
    logger.error(
        "ntfy alarm delivery FAILED after %d attempt(s): url=%s last_status=%s last_error=%s "
        "title=%r",
        attempt,
        url,
        last_status,
        last_error,
        title,
    )
    raise AlarmDeliveryError(
        f"ntfy alarm not delivered after {attempt} attempt(s) "
        f"(last_status={last_status}, last_error={last_error})",
        attempts=attempt,
        last_status=last_status,
        last_error=last_error,
    )


# --------------------------------------------------------------------------- #
# Trigger: turn a reclaim-eligible (custody-breached) item into an alarm.      #
#                                                                              #
# The custody-TTL breach is the already-trusted signal --                     #
# `amplifier_work_tracker.custody.reclaim_eligible(record)` -> (eligible,      #
# reason). These helpers format that verdict into an alarm and send it. They   #
# do NOT re-decide eligibility; the caller (the reap loop) has already done    #
# that. That keeps the alarm bound to the trusted signal and off any new,      #
# unproven ranking logic.                                                      #
# --------------------------------------------------------------------------- #

RECLAIM_TAGS: tuple[str, ...] = ("rotating_light", "warning")


def dashboard_link(item_id: str, *, click_base: str | None) -> str | None:
    """Optional `Click:` deep-link back into the dashboard for `item_id`.

    Returns None when no base URL is configured, so the header is simply
    omitted rather than pointing nowhere.
    """
    if not click_base:
        return None
    return f"{click_base.rstrip('/')}/item/{item_id}"


def reclaim_alarm_payload(
    item_id: str,
    holder: str | None,
    reason: str,
    *,
    click_base: str | None = None,
) -> tuple[str, str, tuple[str, ...], str | None]:
    """Pure formatting: `(title, message, tags, click)` for a custody breach.

    Kept pure and separate so the wording is unit-testable without any HTTP.
    """
    who = holder or "unknown"
    title = f"work-tracker: custody reclaimed {item_id}"
    message = f"{item_id} reclaimed from {who} -- {reason}"
    click = dashboard_link(item_id, click_base=click_base)
    return title, message, RECLAIM_TAGS, click


async def alarm_for_reclaimed_item(
    item_id: str,
    holder: str | None,
    reason: str,
    *,
    config: NtfyConfig | None = None,
    client: httpx.AsyncClient | None = None,
    max_attempts: int | None = None,
    backoff_base: float | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> AlarmResult:
    """Format a custody-breach alarm and send it via `send_alarm` (urgent)."""
    config = config or resolve_config()
    title, message, tags, click = reclaim_alarm_payload(
        item_id, holder, reason, click_base=config.click_base
    )
    return await send_alarm(
        title,
        message,
        priority=PRIORITY_ALARM,
        tags=tags,
        click=click,
        config=config,
        client=client,
        max_attempts=max_attempts,
        backoff_base=backoff_base,
        sleep=sleep,
    )


def fire_reclaim_alarm(
    item_id: str,
    holder: str | None,
    reason: str,
    *,
    config: NtfyConfig | None = None,
) -> AlarmResult:
    """Sync, NEVER-raises entry point for the reap loop's worker thread.

    The reap sweep runs via `asyncio.to_thread(...)`, i.e. in a thread with no
    running event loop, so `asyncio.run` is safe here. A push failure must
    never prevent (or undo) the reclaim that already happened, so every failure
    is caught and returned as a non-delivered result -- the loud `logger.error`
    inside `send_alarm` (and the ones here) is what surfaces the problem, not a
    propagated exception that could abort the sweep.
    """
    try:
        return asyncio.run(alarm_for_reclaimed_item(item_id, holder, reason, config=config))
    except AlarmConfigError as exc:
        logger.error("ntfy alarm misconfigured for reclaimed %s: %s", item_id, exc)
        return AlarmResult(delivered=False, attempts=0, error=str(exc))
    except AlarmDeliveryError as exc:
        # send_alarm already logged this at error level; do not double-log the body.
        return AlarmResult(
            delivered=False, attempts=exc.attempts, status=exc.last_status, error=str(exc)
        )
    except Exception as exc:  # noqa: BLE001 -- a push must never break the reap sweep
        logger.error("ntfy alarm unexpected failure for reclaimed %s: %s", item_id, exc)
        return AlarmResult(delivered=False, attempts=0, error=str(exc))


__all__ = [
    "AlarmConfigError",
    "AlarmDeliveryError",
    "AlarmResult",
    "NtfyConfig",
    "PRIORITY_ALARM",
    "RECLAIM_TAGS",
    "alarm_for_reclaimed_item",
    "dashboard_link",
    "fire_reclaim_alarm",
    "is_transient_status",
    "reclaim_alarm_payload",
    "resolve_config",
    "send_alarm",
]
