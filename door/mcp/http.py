"""The Streamable HTTP transport, the data-layer container's door: a client
POSTs JSON-RPC to /mcp and gets the response as JSON (notifications get
202). No server-initiated streams, so GET /mcp is 405; DELETE ends a
session. /health reports the database the tools are pointed at.

db.web's guard refuses a request that does not name this server before any
of it runs. The door then asks for the bearer token when one is set, caps a
body at MAX_BODY and a batch at MAX_BATCH messages, and holds each client
address to RATE_LIMIT tool calls a RATE_WINDOW. A tool call's audit line
names http and the client's address and session. A request to /mcp the
door turns away leaves a line too, under the address alone, the key the
rate limit counts by; the guard's 403 and the 404s and 405 for what the
door does not serve leave none.
"""

import hmac
import json
import os
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from urllib.parse import urlsplit

from db import web
from door.mcp.audit import audit_refusal
from door.mcp.server import PARSE_ERROR, Server, error_response

MAX_BODY = 1 << 20            # one request is a tool call, not an upload
DRAIN_CHUNK = 1 << 16         # bytes read at a time from an oversize body
MAX_BATCH = 20                # messages in one JSON-RPC batch
RATE_LIMIT = 120              # tool calls per client address per RATE_WINDOW
RATE_WINDOW = 60              # seconds
MAX_TRACKED_CLIENTS = 1000    # past this, clients unseen for a window are forgotten


class _RejectedError(Exception):
    """A request to /mcp the door turns away before any message in it is
    handled: the status, the reason its audit line records, the JSON body -
    {"error": reason} unless the reply needs its own - and any headers."""

    def __init__(
            self, code: int, reason: str, payload: Mapping[str, object] | None = None,
            headers: Mapping[str, str] | None = None) -> None:
        super().__init__(code, reason)
        self.code, self.reason = code, reason
        self.payload: Mapping[str, object] = {"error": reason} if payload is None else payload
        self.headers = dict(headers or {})


class HttpHandler(web.Handler):
    server_version = "countrix-mcp/2.1"
    server: "HttpServer"

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/health":
            return self._json(self.server.status())
        if path == "/mcp":
            return self._json(
                {"error": "this server has no server-initiated stream; POST JSON-RPC to /mcp"},
                405, {"Allow": "POST, DELETE"})
        self._json({"error": "nothing here"}, 404)

    def _check_token(self) -> None:
        """With a token configured, every /mcp request must carry it: one that
        does not is refused 401."""
        token = self.server.token
        header = self.headers.get("Authorization") or ""
        if token and not (header.startswith("Bearer ")
                          and hmac.compare_digest(header[7:].strip(), token)):
            raise _RejectedError(401, "a bearer token is required",
                                 headers={"WWW-Authenticate": "Bearer"})

    def _turn_away(self, rejected: _RejectedError) -> None:
        """Answer a request the door rejected, the one place that does: its
        audit line first - no tool, under the client address the rate limit
        counts by, refused with the status and the reason - then the reply."""
        audit_refusal("http", "http:%s" % self.client_address[0],
                      "%d %s" % (rejected.code, rejected.reason), self.server.mcp.audit_path)
        self._json(rejected.payload, rejected.code, rejected.headers)

    def do_DELETE(self) -> None:
        """Ends a session. This server keeps no session state to end, and the
        request passes the guard and the token check anyway, so every method
        on /mcp is guarded alike."""
        if urlsplit(self.path).path != "/mcp":
            return self._json({"error": "nothing here"}, 404)
        try:
            self._check_token()
        except _RejectedError as rejected:
            return self._turn_away(rejected)
        self._json(None)

    def do_POST(self) -> None:
        """One JSON-RPC message or batch: the token checked, read, admitted
        against the batch size and the client's rate, then handled."""
        if urlsplit(self.path).path != "/mcp":
            return self._json({"error": "nothing here"}, 404)
        try:
            self._check_token()
            message = self._read_message()
            messages = message if isinstance(message, list) else [message]
            self._admit(messages)
        except _RejectedError as rejected:
            return self._turn_away(rejected)
        self._dispatch(messages, batched=isinstance(message, list))

    def _read_message(self) -> object:
        """The request's JSON body, decoded - `null` included, which is a
        message the server answers. A Content-Length that is missing, not a
        number or not positive is refused, a body past MAX_BODY is drained
        and refused, and one that is not JSON is a parse error."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length <= 0:             # missing, not a number, or no body at all
            raise _RejectedError(400, "a positive Content-Length is required")
        if length > MAX_BODY:
            drained = 0
            while drained < min(length, 16 * MAX_BODY):     # let the client finish sending
                chunk = self.rfile.read(min(DRAIN_CHUNK, length - drained))
                if not chunk:
                    break
                drained += len(chunk)
            self.close_connection = True
            raise _RejectedError(413, "request too large")
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise _RejectedError(
                400, "bad JSON", error_response(None, PARSE_ERROR, "bad JSON")) from None

    def _admit(self, messages: list[object]) -> None:
        """Refuse a batch past MAX_BATCH, and tool calls past the client
        address's rate - the budget is the host's, not a claimed session's."""
        if len(messages) > MAX_BATCH:
            raise _RejectedError(413, "at most %d messages per batch" % MAX_BATCH)
        calls = sum(1 for m in messages if isinstance(m, dict) and m.get("method") == "tools/call")
        if calls and not self.server.admit(self.client_address[0], calls):
            raise _RejectedError(429, "too many calls; try again in a minute",
                                 headers={"Retry-After": str(RATE_WINDOW)})

    def _dispatch(self, messages: list[object], *, batched: bool) -> None:
        """Handle each message as this client, then reply: 202 when nothing
        needs an answer, else the answers - a list for a batch - with a new
        Mcp-Session-Id after an initialize."""
        session = (self.headers.get("Mcp-Session-Id") or "-")[:8]
        client = "http:%s/%s" % (self.client_address[0], session)
        responses = [r for r in (self.server.mcp.handle(m, client) for m in messages)
                     if r is not None]
        headers: dict[str, str] = {}
        if any(isinstance(m, dict) and m.get("method") == "initialize" for m in messages):
            headers["Mcp-Session-Id"] = uuid.uuid4().hex
        if not responses:
            return self._json(None, 202, headers)
        self._json(responses if batched else responses[0], 200, headers)


class HttpServer(web.LocalServer):
    """The MCP server over HTTP: the door's token, the rate limit per client
    address, and the status /health reports. Its audit lines name http."""

    def __init__(
            self, address: tuple[str, int], mcp: Server,
            status: Callable[[], Mapping[str, object]], allowed_hosts: Iterable[str] = (),
            token: str | None = None, rate_limit: int = RATE_LIMIT) -> None:
        super().__init__(address, HttpHandler, allowed_hosts)
        mcp.transport = "http"
        self.mcp = mcp
        self.status = status
        self.token = token if token is not None else os.environ.get("COUNTRIX_MCP_TOKEN") or None
        self.rate_limit = rate_limit
        self._calls: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def admit(self, client: str, calls: int = 1) -> bool:
        """A sliding window of RATE_WINDOW seconds per client address; False
        past the limit."""
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._calls.get(client, ()) if now - t < RATE_WINDOW]
            if len(recent) + calls > self.rate_limit:
                self._calls[client] = recent
                return False
            recent.extend([now] * calls)
            self._calls[client] = recent
            if len(self._calls) > MAX_TRACKED_CLIENTS:
                self._calls = {
                    c: ts for c, ts in self._calls.items() if ts and now - ts[-1] < RATE_WINDOW}
        return True


def serve(
        mcp: Server, host: str, port: int, status: Callable[[], Mapping[str, object]],
        allowed_hosts: Iterable[str] = ()) -> None:
    """Serve `mcp` (a Server) over HTTP until interrupted, answering to the
    local names and `allowed_hosts`."""
    httpd = HttpServer((host, port), mcp, status, allowed_hosts)
    sys.stderr.write("countrix mcp: http://%s:%d/mcp%s\n" % (
        host, port, " (bearer token required)" if httpd.token else ""))
    httpd.serve_forever()
