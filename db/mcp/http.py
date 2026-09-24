"""The Streamable HTTP transport, the data-layer container's door: a client
POSTs JSON-RPC to /mcp and gets the response as JSON (notifications get
202). No server-initiated streams, so GET /mcp is 405; DELETE ends a
session. /health reports the database the tools are pointed at.

db.web's guard refuses a request that does not name this server before any
of it runs. The door then asks for the bearer token when one is set, caps a
body at MAX_BODY and a batch at MAX_BATCH messages, and holds each client
address to RATE_LIMIT tool calls a RATE_WINDOW. Its audit lines name http
and the client's address and session.
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
from db.mcp.server import PARSE_ERROR, Server, error_response

MAX_BODY = 1 << 20            # one request is a tool call, not an upload
DRAIN_CHUNK = 1 << 16         # bytes read at a time from an oversize body
MAX_BATCH = 20                # messages in one JSON-RPC batch
RATE_LIMIT = 120              # tool calls per client address per RATE_WINDOW
RATE_WINDOW = 60              # seconds
MAX_TRACKED_CLIENTS = 1000    # past this, clients unseen for a window are forgotten


class _RejectedError(Exception):
    """A POST the door turns away before any message in it is handled: the
    status, the JSON body and any headers the reply carries."""

    def __init__(
            self, code: int, payload: Mapping[str, object],
            headers: Mapping[str, str] | None = None) -> None:
        super().__init__(code)
        self.code, self.payload, self.headers = code, payload, dict(headers or {})


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

    def _authorized(self) -> bool:
        """With a token configured, every /mcp request must carry it."""
        token = self.server.token
        if not token:
            return True
        header = self.headers.get("Authorization") or ""
        return header.startswith("Bearer ") and hmac.compare_digest(header[7:].strip(), token)

    def _refuse_unauthorized(self) -> None:
        self._json({"error": "a bearer token is required"}, 401, {"WWW-Authenticate": "Bearer"})

    def do_DELETE(self) -> None:
        """Ends a session. This server keeps no session state to end, and the
        request passes the guard and the token check anyway, so every method
        on /mcp is guarded alike."""
        if urlsplit(self.path).path != "/mcp":
            return self._json({"error": "nothing here"}, 404)
        if not self._authorized():
            return self._refuse_unauthorized()
        self._json(None)

    def do_POST(self) -> None:
        """One JSON-RPC message or batch: read, admitted against the batch
        size and the client's rate, then handled."""
        if urlsplit(self.path).path != "/mcp":
            return self._json({"error": "nothing here"}, 404)
        if not self._authorized():
            return self._refuse_unauthorized()
        try:
            message = self._read_message()
            messages = message if isinstance(message, list) else [message]
            self._admit(messages)
        except _RejectedError as rejected:
            return self._json(rejected.payload, rejected.code, rejected.headers)
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
            raise _RejectedError(400, {"error": "a positive Content-Length is required"})
        if length > MAX_BODY:
            drained = 0
            while drained < min(length, 16 * MAX_BODY):     # let the client finish sending
                chunk = self.rfile.read(min(DRAIN_CHUNK, length - drained))
                if not chunk:
                    break
                drained += len(chunk)
            self.close_connection = True
            raise _RejectedError(413, {"error": "request too large"})
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise _RejectedError(400, error_response(None, PARSE_ERROR, "bad JSON")) from None

    def _admit(self, messages: list[object]) -> None:
        """Refuse a batch past MAX_BATCH, and tool calls past the client
        address's rate - the budget is the host's, not a claimed session's."""
        if len(messages) > MAX_BATCH:
            raise _RejectedError(413, {"error": "at most %d messages per batch" % MAX_BATCH})
        calls = sum(1 for m in messages if isinstance(m, dict) and m.get("method") == "tools/call")
        if calls and not self.server.admit(self.client_address[0], calls):
            raise _RejectedError(
                429, {"error": "too many calls; try again in a minute"},
                {"Retry-After": str(RATE_WINDOW)})

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
