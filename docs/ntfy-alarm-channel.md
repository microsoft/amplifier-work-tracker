# ntfy phone-push alarm channel

A self-contained ALARM channel that raises a phone when a real alarm condition
fires in amplifier-work-tracker. Lives in
`src/amplifier_work_tracker/webpush.py`. It adopts the wire shape proven by
Amplifier's notify bundle (`hooks-notify-push`) and adds the three things an
*alarm* channel needs and that bundle lacks: **Bearer auth** for a self-hosted
ntfy, **`Priority: urgent`** (bypasses phone Do-Not-Disturb), and a **bounded
retry + LOUD fail** (never a silent swallow).

## Wire shape

```
POST {NTFY_SERVER}/{NTFY_TOPIC}
Title: <title>
Priority: urgent
Tags: rotating_light,warning
Click: <optional dashboard deep-link>
Authorization: Bearer <NTFY_TOKEN>     # only when a token is configured

<message as raw UTF-8 body bytes>
```

## Configuration (env only — secrets never in a settings file)

| Variable | Default | Meaning |
|---|---|---|
| `NTFY_SERVER` | `https://ntfy.sh` | ntfy base URL. Point at your self-hosted instance. |
| `NTFY_TOPIC` | *(unset)* | Topic. On public ntfy.sh the topic name **is** the password — keep it in the env, never a file. |
| `NTFY_TOKEN` | *(unset)* | Self-hosted access token, sent as `Authorization: Bearer`. Optional. |
| `NTFY_ALARM_ENABLED` | *(unset)* | Enable flag (`1`/`true`/`yes`/`on`). Opt-in: while unset, `send_alarm` is a safe no-op. |
| `NTFY_MAX_ATTEMPTS` | `4` | Retry budget (attempts, not retries). |
| `NTFY_BACKOFF_BASE_SECONDS` | `0.5` | Base for exponential backoff between attempts. |
| `NTFY_CLICK_BASE` | *(unset)* | Optional dashboard base URL for a `Click:` deep-link back to the item. |

### Why self-hosted + token (recommended for this deployment)

This deployment runs behind Tailscale. A private self-hosted ntfy plus an
access token removes the "topic name == password" fragility of public ntfy.sh:
the topic can no longer be guessed off the wire, and delivery is authenticated.

## Retry + LOUD fail semantics

- **2xx** → delivered.
- **Transient** (network/timeout error, HTTP `429`, or any `5xx`) → retried up
  to `NTFY_MAX_ATTEMPTS` with exponential backoff.
- **Exhausted retries, or a non-transient `4xx`** → `logger.error(...)` **and**
  `AlarmDeliveryError`. The `logger.error` is deliberately NOT debug-only (the
  way `hooks-notify-push` logs) — it is the line that must appear in the journal
  when the phone did not ring.
- **Disabled** (`NTFY_ALARM_ENABLED` not truthy) → no-op result, so call sites
  can invoke it unconditionally.

## The trigger — bound to the already-trusted signal

The alarm keys off the **custody-TTL breach**, i.e. the exact signal the reaper
already trusts: `custody.reclaim_eligible(record) -> (eligible, reason)`. It
does **not** re-decide eligibility and is **not** wired to any new/unproven
ranking logic. Helpers in `webpush.py`:

- `reclaim_alarm_payload(item_id, holder, reason)` — pure `(title, message, tags, click)` formatting.
- `alarm_for_reclaimed_item(item_id, holder, reason, ...)` — async, formats + sends (urgent).
- `fire_reclaim_alarm(item_id, holder, reason, config=None)` — **sync, never-raises** entry point for the reap-sweep worker thread.

## RESIDUAL — exact `supervisor.py` wiring (applied at merge by the orchestrator)

`supervisor.py` is not owned by this change; the reap/notify loops live there.
Apply these two edits to wire the alarm to the custody-breach path. Both are
additive.

**1. Import** — alongside the sibling imports near the top of `supervisor.py`
(currently around lines 56–58: `from . import adapter as A` / `custody as C` /
`heartbeat as HB`). Add:

```python
from . import webpush as WP
```

**2. Fire on reclaim** — in `reap_project(...)`, inside the `if eligible:` branch,
immediately after the existing `reclaimed.append({...})` (currently lines
123–125):

```python
        if eligible:
            bd.release(item.id)
            reclaimed.append({"id": item.id, "was_holder": item.holder, "reason": reason})
            # ALARM: custody-TTL breach is a real alarm condition. Sync, never
            # raises — a push failure must never prevent/undo the reclaim above,
            # and any failure is LOUD-logged inside webpush, not swallowed.
            WP.fire_reclaim_alarm(item.id, item.holder, reason)
```

Rationale for placement/order: the alarm fires **after** `bd.release(...)` so the
reclaim (the source of truth) is never gated on a push; `fire_reclaim_alarm` is
sync and swallow-and-loud-log, which is correct inside the `asyncio.to_thread`
reap-sweep worker (no running event loop there) and keeps one bad push from
aborting the sweep for other projects.

Dependency note: `httpx` is currently declared only under the `dev` extra in
`pyproject.toml`. When this wiring ships, add `httpx>=0.27` to the runtime
dependencies (either the base `dependencies` or the `web` extra, since the
alarm is a service concern) so a non-dev install can import `webpush`.

## Confirming on a REAL phone (PENDING-HUMAN)

Reaching an actual device needs the device, so it is a human step. In-repo the
plumbing is proven end-to-end against a local stub (real localhost POST, urgent
priority, bearer token, correct body — see the E2E check). To confirm on your
own phone:

1. Install the ntfy app and subscribe to your topic (self-hosted server + token,
   or a private topic on ntfy.sh).
2. Export the same env the service will use, then send a test alarm:

```bash
export NTFY_SERVER="https://ntfy.your-tailnet.ts.net"   # or https://ntfy.sh
export NTFY_TOPIC="your-secret-topic"
export NTFY_TOKEN="tk_your_selfhosted_token"            # omit for public ntfy.sh

# (a) directly with curl — exactly the shape webpush sends:
curl -sS -X POST "$NTFY_SERVER/$NTFY_TOPIC" \
  -H "Title: work-tracker: custody reclaimed wt-123" \
  -H "Priority: urgent" \
  -H "Tags: rotating_light,warning" \
  ${NTFY_TOKEN:+-H "Authorization: Bearer $NTFY_TOKEN"} \
  -d "wt-123 reclaimed from agent-7 -- custody stale (ttl 900s)"

# (b) or through the module itself (proves config resolution + retry path too):
NTFY_ALARM_ENABLED=1 .venv/bin/python -c "
import asyncio; from amplifier_work_tracker import webpush as W
print(asyncio.run(W.alarm_for_reclaimed_item('wt-123','agent-7','custody stale (ttl 900s)')))
"
```

The phone should buzz through Do-Not-Disturb (that is what `Priority: urgent`
buys). If it does not ring, the LOUD `logger.error` from `send_alarm` names the
`url`, `last_status`, and `last_error` to act on.
