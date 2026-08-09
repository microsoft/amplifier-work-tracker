"""Feedback Gateway -- the only writer of user reports.

Product-level, user-facing agents run in *untrusted user context*. They must
never touch Beads directly: server mode + concurrent embedded writers proved
that path fragile, and direct DB access means a user's own session could
write into the engineering work graph. This HTTP service is the single
choke point that:

  1. Authenticates every caller to exactly one reporter identity (bearer
     token -> {reporter_id, project}), never trusting a query/body value.
  2. Redacts free-text PII *before* it reaches `bd create --metadata`,
     because Dolt/git history is effectively permanent -- there is no
     "delete it later."
  3. Is the only thing in amplifier-work-tracker that calls
     `amplifier_work_tracker.adapter` on behalf of a product agent. It never
     shells out to `bd` itself.

Endpoints: POST /reports, GET /reports, GET /reports/<id>, GET /healthz.
Stdlib only. Loopback by default.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import ParseResult, parse_qs, urlparse

from . import adapter

# ---------------------------------------------------------------------------
# Redaction -- the choke point every persisted free-text field must pass
# through. Order matters: each pattern consumes text before the next one
# runs, so a masked email's digits can't later be mistaken for a phone
# number. This is a heuristic net, not exhaustive PII detection -- it exists
# to catch the common, damaging cases before an immutable write.
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PATH_RE = re.compile(r"(?:/home/[^\s/'\"]+|/Users/[^\s/'\"]+)(?:/[^\s'\"]*)?")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD_RE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d{1,2}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)")
_SECRET_RE = re.compile(r"\b(?:[A-Za-z0-9+/]{24,}={0,2}|[A-Fa-f0-9]{32,})\b")

_PLACEHOLDERS = {
    "email": "[EMAIL]",
    "path": "[PATH]",
    "ssn": "[SSN]",
    "card": "[CARD]",
    "phone": "[PHONE]",
    "secret": "[SECRET]",
}
_REDACTION_ORDER: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", _EMAIL_RE),
    ("path", _PATH_RE),
    ("ssn", _SSN_RE),
    ("card", _CARD_RE),
    ("phone", _PHONE_RE),
    ("secret", _SECRET_RE),
)


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Mask PII-shaped substrings. Returns (redacted_text, counts_by_kind).

    Every free-text field that gets persisted must call this -- see
    `_redact_context` and `_handle_create_report` below, which are the only
    two call sites, deliberately, so redaction can never be skipped by
    accident on a new field.
    """
    if not text:
        return text, {}
    counts: dict[str, int] = {}
    out = text
    for kind, pattern in _REDACTION_ORDER:
        out, n = pattern.subn(_PLACEHOLDERS[kind], out)
        if n:
            counts[kind] = counts.get(kind, 0) + n
    return out, counts


def _accumulate(total: dict[str, int], counts: dict[str, int]) -> None:
    for k, v in counts.items():
        total[k] = total.get(k, 0) + v


def _redact_context(context: dict) -> tuple[dict, dict[str, int]]:
    """Recursively redact every string value in a free-form context blob."""
    redacted: dict = {}
    total: dict[str, int] = {}
    for key, value in context.items():
        if isinstance(value, str):
            r, c = redact(value)
            redacted[key] = r
            _accumulate(total, c)
        elif isinstance(value, dict):
            r_dict, c = _redact_context(value)
            redacted[key] = r_dict
            _accumulate(total, c)
        elif isinstance(value, list):
            new_list = []
            for v in value:
                if isinstance(v, str):
                    r, c = redact(v)
                    new_list.append(r)
                    _accumulate(total, c)
                else:
                    new_list.append(v)
            redacted[key] = new_list
        else:
            redacted[key] = value
    return redacted, total


# ---------------------------------------------------------------------------
# Auth -- tokens map to exactly one reporter identity. Fail closed always.
# ---------------------------------------------------------------------------


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_tokens_or_die(path: Path) -> dict[str, dict[str, str]]:
    """Load the tokens file, or refuse to start.

    A missing tokens file must never be silently read as "authorize
    everyone" (dev-mode bypass) or "authorize no one and pretend that's
    fine" -- both are ambiguous states an operator could ship by accident.
    Refusing to start is the only response that can't be misread.
    """
    if not path.is_file():
        print(
            f"ERROR: tokens file not found: {path}\n"
            f"Mint one first: python -m amplifier_work_tracker.gateway --tokens {path} "
            f"--make-token <reporter_id> <project>",
            file=sys.stderr,
        )
        raise SystemExit(1)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"ERROR: tokens file {path} is not valid JSON: {e}", file=sys.stderr)
        raise SystemExit(1) from e
    if not isinstance(data, dict):
        print(f"ERROR: tokens file {path} must contain a JSON object", file=sys.stderr)
        raise SystemExit(1)
    return data


def load_tokens_if_exists(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def make_token(tokens_path: Path, reporter_id: str, project: str) -> None:
    """Mint a token, print it once, persist only its hash. This is the
    admin bootstrap path -- it may create the tokens file; serving may not."""
    tokens = load_tokens_if_exists(tokens_path)
    token = secrets.token_urlsafe(32)
    tokens[_hash_token(token)] = {"reporter_id": reporter_id, "project": project}
    tokens_path.parent.mkdir(parents=True, exist_ok=True)
    tokens_path.write_text(json.dumps(tokens, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"token (shown once -- store it now): {token}")
    print(f"reporter_id={reporter_id} project={project} -> hash appended to {tokens_path}")


class HttpError(Exception):
    """Carries a real HTTP status + message. The only control-flow exception
    the handler uses -- every other exception is a genuine internal failure
    and must surface as one (constraint: no silent degradation, ever)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

_REPORT_ID_RE = re.compile(r"^/reports/([^/]+)$")


@dataclass
class _Auth:
    reporter_id: str
    project: str


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        handler_cls: type,
        *,
        tokens: dict,
        workspace: adapter.Workspace,
    ) -> None:
        super().__init__(address, handler_cls)
        self.tokens = tokens
        self.workspace = workspace


class GatewayHandler(BaseHTTPRequestHandler):
    def _srv(self) -> GatewayServer:
        return self.server  # type: ignore[return-value]

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------ identity

    def _authenticate(self) -> _Auth:
        # Identity comes from the bearer token ONLY. The previous design's
        # IDOR was `GET /reports?reporter=X` trusting a query parameter --
        # anyone could read anyone's reports. There is no query/body path
        # into reporter identity here at all; see _reject_identity_mismatch
        # for what happens if a caller tries to supply one anyway.
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise HttpError(401, "missing bearer token")
        token = header[len("Bearer ") :].strip()
        if not token:
            raise HttpError(401, "empty bearer token")
        entry = self._srv().tokens.get(_hash_token(token))
        if entry is None:
            raise HttpError(401, "invalid token")
        return _Auth(reporter_id=entry["reporter_id"], project=entry["project"])

    def _reject_identity_mismatch(self, supplied: dict[str, str], auth: _Auth) -> None:
        """If the request *also* names a reporter/project, it must agree
        with the token. Disagreeing silently in the token's favor would
        hide a client bug (or an attack) that deserves a loud 403."""
        for key in ("reporter", "reporter_id"):
            if key in supplied and supplied[key] != auth.reporter_id:
                raise HttpError(403, "reporter identity in request disagrees with bearer token")
        if "project" in supplied and supplied["project"] != auth.project:
            raise HttpError(403, "project in request disagrees with bearer token")

    def _query_dict(self, parsed: ParseResult) -> dict[str, str]:
        return {k: v[0] for k, v in parse_qs(parsed.query).items() if v}

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            raise HttpError(400, "empty request body")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise HttpError(400, f"invalid JSON body: {e}") from e
        if not isinstance(data, dict):
            raise HttpError(400, "request body must be a JSON object")
        return data

    # ------------------------------------------------------------- routes

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/healthz":
                self._send_json(200, {"status": "ok"})
                return
            auth = self._authenticate()
            if parsed.path == "/reports":
                self._reject_identity_mismatch(self._query_dict(parsed), auth)
                self._handle_list_reports(auth)
                return
            m = _REPORT_ID_RE.match(parsed.path)
            if m:
                self._handle_get_report(auth, m.group(1))
                return
            raise HttpError(404, "not found")
        except HttpError as e:
            self._send_json(e.status, {"error": e.message})
        except adapter.BeadsError as e:
            self._send_json(502, {"error": f"beads operation failed: {e}"})
        except Exception as e:  # noqa: BLE001 -- top-level guard: every failure must produce a real HTTP response, never a hang or a bare stack trace on the socket
            self._send_json(500, {"error": f"internal error: {e}"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/reports":
                auth = self._authenticate()
                body = self._read_json_body()
                self._reject_identity_mismatch(
                    {
                        k: str(v)
                        for k, v in body.items()
                        if k in ("reporter", "reporter_id", "project") and v is not None
                    },
                    auth,
                )
                self._handle_create_report(auth, body)
                return
            raise HttpError(404, "not found")
        except HttpError as e:
            self._send_json(e.status, {"error": e.message})
        except adapter.BeadsError as e:
            self._send_json(502, {"error": f"beads operation failed: {e}"})
        except Exception as e:  # noqa: BLE001 -- see do_GET
            self._send_json(500, {"error": f"internal error: {e}"})

    # ------------------------------------------------------------- domain

    def _handle_create_report(self, auth: _Auth, body: dict) -> None:
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HttpError(400, "field 'text' is required and must be non-empty")
        context = body.get("context") or {}
        if not isinstance(context, dict):
            raise HttpError(400, "field 'context' must be an object")

        redacted_text, text_counts = redact(text)
        redacted_context, context_counts = _redact_context(context)
        total_counts: dict[str, int] = {}
        _accumulate(total_counts, text_counts)
        _accumulate(total_counts, context_counts)

        meta = {
            "reporter_id": auth.reporter_id,
            "session_id": body.get("session_id"),
            "app_version": body.get("app_version"),
            "surface": body.get("surface"),
            "verbatim": redacted_text,
            "context": redacted_context,
            "captured_at": datetime.now(UTC).isoformat(),
            "redactions": total_counts,
        }
        title = redacted_text.strip().splitlines()[0][:120] or "user feedback"

        beads = self._srv().workspace.project(auth.project, actor=auth.reporter_id)
        report_id = beads.create(
            title,
            kind="chore",
            tags=[adapter.LANE_INTAKE, "src:product-agent"],
            meta=meta,
            actor=auth.reporter_id,
        )
        self._send_json(201, {"report_id": report_id, "redactions": total_counts})

    def _handle_list_reports(self, auth: _Auth) -> None:
        beads = self._srv().workspace.project(auth.project, actor=auth.reporter_id)
        items = beads.list(lane=adapter.LANE_INTAKE, include_resolved=True)
        own_ids = [it.id for it in items if it.meta.get("reporter_id") == auth.reporter_id]
        # Re-read each with links -- list() doesn't carry dependents, and we
        # need the linked issue's status/resolution for the caller's view.
        views = [self._view_from_item(beads, beads.get(rid, with_links=True)) for rid in own_ids]
        self._send_json(200, {"reports": views})

    def _handle_get_report(self, auth: _Auth, report_id: str) -> None:
        beads = self._srv().workspace.project(auth.project, actor=auth.reporter_id)
        try:
            item = beads.get(report_id, with_links=True)
        except adapter.BeadsError:
            # A nonexistent id and "exists but isn't yours" must look
            # identical to the caller -- that's the whole point of 404
            # instead of 403 here (no existence-leak). This does mean a
            # genuine Beads outage on this single id also surfaces as 404;
            # that's an accepted trade for not leaking ownership.
            raise HttpError(404, "report not found") from None
        if adapter.LANE_INTAKE not in item.tags or item.meta.get("reporter_id") != auth.reporter_id:
            raise HttpError(404, "report not found")
        self._send_json(200, self._view_from_item(beads, item))

    def _view_from_item(self, beads: adapter.Beads, item: adapter.Item) -> dict:
        work = []
        for link in item.links:
            if link.get("direction") != "to":
                # "to" = dependents = things that depend on this report, i.e. the linked issue(s)
                continue
            issue_id = link.get("id")
            if not issue_id:
                continue
            issue = beads.get(issue_id)
            work.append(
                {
                    "issue_id": issue.id,
                    "status": issue.status,
                    "resolution": issue.resolution,
                }
            )
        return {
            "report_id": item.id,
            "title": item.title,
            "status": item.status,
            "verbatim": item.meta.get("verbatim"),
            "captured_at": item.meta.get("captured_at"),
            "redactions": item.meta.get("redactions", {}),
            "work": work,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser():
    import argparse

    p = argparse.ArgumentParser(
        prog="amplifier-work-tracker-gateway",
        description="Feedback Gateway -- the only writer of user reports.",
    )
    p.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind address (default: 127.0.0.1, loopback only)",
    )
    p.add_argument("--port", type=int, default=8787, help="bind port (default: 8787)")
    p.add_argument(
        "--tokens",
        type=Path,
        required=True,
        help="path to tokens file (JSON: sha256(token) -> {reporter_id, project})",
    )
    p.add_argument(
        "--root",
        type=Path,
        default=None,
        help=(
            "amplifier-work-tracker workspace root "
            "(default: $AMPLIFIER_WORK_TRACKER_ROOT or ~/.amplifier-work-tracker)"
        ),
    )
    p.add_argument(
        "--make-token",
        nargs=2,
        metavar=("REPORTER_ID", "PROJECT"),
        help=(
            "mint a token for REPORTER_ID scoped to PROJECT, print it once, "
            "append its hash to --tokens, then exit"
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.make_token:
        reporter_id, project = args.make_token
        make_token(args.tokens, reporter_id, project)
        return 0

    tokens = load_tokens_or_die(args.tokens)
    workspace = adapter.Workspace(args.root)

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(
            "WARNING: binding to a non-loopback host. This service has no "
            "TLS and no rate limiting -- bearer tokens and report bodies "
            "travel in the clear. Do not do this off a trusted network.",
            file=sys.stderr,
        )

    server = GatewayServer(
        (args.host, args.port), GatewayHandler, tokens=tokens, workspace=workspace
    )
    print(
        f"amplifier-work-tracker gateway listening on {args.host}:{args.port} "
        f"(root={workspace.root})"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
