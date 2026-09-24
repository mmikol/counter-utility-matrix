"""A minimal, dependency-free MCP server: JSON-RPC 2.0 over stdio, and the
same surface over Streamable HTTP (serve_http, below).

Over stdio it is one message per line on stdin/stdout, and this server
speaks the parts a tool host needs: `initialize`, `ping`, `tools/list`,
`tools/call`, `resources/list`, `resources/read`, and empty `prompts/list`.
Logs go to stderr - stdout is the wire.
"""

import hmac
import json
import os
import sys
import threading
import time
import traceback
import uuid
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, TextIO
from urllib.parse import urlsplit

from db import RAW_DIR, Refusal, web

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "countrix", "version": "2.1.0"}

_client = threading.local()

# A JSON-RPC message, request or response, as json.loads reads it: arbitrary JSON.
Message = dict[str, Any]
# What a tool answers: its text, and the same as a JSON object for a
# structured reply, or None.
Answer = tuple[str, Mapping[str, Any] | None]


# Every tool call is one JSON line here - through either transport, and
# in-process where the refresher and the shell call one directly: when, over
# which transport, from whom, which tool, the shape of its arguments (names and
# sizes, never the values), whether it succeeded, and how long it took. The
# sentry reads it. COUNTRIX_AUDIT moves it, read on every call.
def default_audit_path() -> str:
    return os.environ.get("COUNTRIX_AUDIT", os.path.join(RAW_DIR, "audit.jsonl"))


def audit(entry: Mapping[str, object], path: str | None = None) -> None:
    """Append one audit line. A line that cannot be written is noted on
    stderr - never stdout, the stdio wire - and never raised: the door stays
    open if the log fails."""
    path = path or default_audit_path()
    try:
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as error:
        sys.stderr.write("countrix mcp: the audit log %s was not written: %s\n" % (path, error))


def _shape(arguments: Mapping[str, object] | None) -> dict[str, object]:
    """{argument name: size} - never the value."""
    out: dict[str, object] = {}
    for key, value in (arguments or {}).items():
        if isinstance(value, (list, dict, str)):
            out[key] = len(value)
        else:
            out[key] = value if isinstance(value, (bool, int, float)) else str(type(value).__name__)
    return out


PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL = (
    -32700, -32600, -32601, -32602, -32603)
MS_PER_SECOND = 1000


def audited[T](name: str, arguments: Mapping[str, object], call: Callable[[], T],
                transport: str, client: str | None = None, audit_path: str | None = None) -> T:
    """Run one tool call and leave exactly one audit line for it. Every path to
    a tool - stdio, HTTP and the in-process calls the refresher and the shell
    make - comes through here, so the sentry's window covers all three. A
    Refusal - the tool refusing its input, the wrapper refusing the call - is
    audited as refused; anything else as crashed."""
    entry: dict[str, object] = {
        "t": datetime.now(UTC).isoformat(timespec="seconds"), "transport": transport,
        "client": client, "tool": name, "args": _shape(arguments)}
    started = time.monotonic()

    def spent() -> int:
        return int((time.monotonic() - started) * MS_PER_SECOND)

    try:
        result = call()
    except Refusal as refused:
        audit(dict(entry, ok=False, refused=str(refused)[:200], ms=spent()), audit_path)
        raise
    except Exception:
        audit(dict(entry, ok=False, crashed=True, ms=spent()), audit_path)
        raise
    audit(dict(entry, ok=True, ms=spent()), audit_path)
    return result


class InvalidParamsError(Exception):
    """The request left out a field this method needs, or named something the
    server does not serve: the wire's INVALID_PARAMS. Raised only where that is
    what went wrong, so anything else escaping a handler is the server's own
    fault and reaches the branch that logs a traceback."""


class Resources(Protocol):
    """What a server serves as MCP resources: a listing, and one resource by
    uri, a KeyError when nothing is at it."""

    def list(self) -> list[dict[str, str]]: ...

    def read(self, uri: str) -> dict[str, str]: ...


class Server:
    """The protocol over any transport: its tools by name, the resources it
    serves, where it logs (stderr unless told), the transport its audit lines
    name - stdio until an HttpServer serves it - and the audit log's path."""

    def __init__(
            self, tools: Iterable["Tool"], resources: Resources | None = None, *,
            log: Callable[[str], object] | None = None, audit_path: str | None = None) -> None:
        self.tools = {t.name: t for t in tools}
        self.resources = resources
        self.log = log or (lambda msg: sys.stderr.write(msg + "\n"))
        self.transport = "stdio"
        self.audit_path = audit_path

    # --- dispatch ------------------------------------------------------

    def handle(self, message: object) -> Message | None:
        """One decoded message -> a response, or None for a notification. A
        request the wire cannot serve is INVALID_PARAMS; anything else that
        escapes a method is the server's fault, INTERNAL with its type and
        message, and its traceback goes to the log, never to the caller."""
        if not isinstance(message, dict):
            return self._error(None, INVALID_REQUEST, "expected an object")
        msg_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}
        if method is None:
            return None            # a response to something we never sent
        try:
            if method.startswith("notifications/"):
                return None                # a notification gets no response
            handler: Callable[[Message], Message] | None = {
                "initialize": self._initialize,
                "ping": lambda p: {},
                "tools/list": self._tools_list,
                "tools/call": self._tools_call,
                "resources/list": self._resources_list,
                "resources/read": self._resources_read,
                "resources/templates/list": lambda p: {"resourceTemplates": []},
                "prompts/list": lambda p: {"prompts": []},
            }.get(method)
            if handler is None:
                return self._error(msg_id, METHOD_NOT_FOUND,
                                   "unknown method %r" % method)
            return {"jsonrpc": "2.0", "id": msg_id, "result": handler(params)}
        except InvalidParamsError as bad:
            return self._error(msg_id, INVALID_PARAMS, str(bad))
        except Exception as error:  # noqa: BLE001  # never let one request kill the wire
            self.log(traceback.format_exc())
            return self._error(msg_id, INTERNAL, "%s: %s"
                               % (type(error).__name__, error))

    def _error(self, msg_id: object, code: int, text: str) -> Message:
        return {"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": code, "message": text}}

    # --- methods -------------------------------------------------------

    def _initialize(self, params: Message) -> Message:
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False},
                             "resources": {"subscribe": False,
                                           "listChanged": False},
                             "prompts": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": (
                "Countrix: the data layer (pull_* tools scrape, clean and"
                " store each source; sync_all does them all in order), the"
                " UI layer (facts: every fact the database holds about a"
                " board of map + red + blue picks) and the inference layer"
                " (infer: the optimal composition under the markdown"
                " strategies; evaluate: score a full six). Read-only SQL"
                " via query."),
        }

    def _tools_list(self, params: Message) -> Message:
        return {"tools": [t.describe() for t in self.tools.values()]}

    def _tools_call(self, params: Message) -> Message:
        if "name" not in params:
            raise InvalidParamsError("missing parameter 'name'")
        name = params["name"]
        tool = self.tools.get(name)
        if tool is None:
            raise InvalidParamsError("no tool named %r" % name)
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise InvalidParamsError("arguments must be an object")
        try:
            text, structured = audited(name, arguments, lambda: tool(arguments),
                                       self.transport, getattr(_client, "id", None),
                                       self.audit_path)
        except Refusal as refused:
            return {"content": [{"type": "text", "text": str(refused)}],
                    "isError": True}
        result: Message = {"content": [{"type": "text", "text": text}],
                  "isError": False}
        if structured is not None:
            result["structuredContent"] = structured
        return result

    def _resources_list(self, params: Message) -> Message:
        if self.resources is None:
            return {"resources": []}
        return {"resources": self.resources.list()}

    def _resources_read(self, params: Message) -> Message:
        if "uri" not in params:
            raise InvalidParamsError("missing parameter 'uri'")
        if self.resources is None:
            raise InvalidParamsError("this server serves no resources")
        try:
            return {"contents": [self.resources.read(params["uri"])]}
        except KeyError as unknown:
            raise InvalidParamsError("no resource at %s" % unknown) from unknown

    # --- the wire ------------------------------------------------------

    def serve(self, stdin: Iterable[str] | None = None, stdout: TextIO | None = None) -> None:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self._write(stdout, self._error(None, PARSE_ERROR, "bad JSON"))
                continue
            messages = message if isinstance(message, list) else [message]
            responses = [r for r in (self.handle(m) for m in messages)
                         if r is not None]
            if isinstance(message, list):
                if responses:
                    self._write(stdout, responses)
            else:
                for response in responses:
                    self._write(stdout, response)

    @staticmethod
    def _write(stdout: TextIO, payload: object) -> None:
        stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        stdout.flush()


# The Python values each JSON schema type admits. A bool is an int to Python
# and neither an integer nor a number here; None is no type at all.
JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,), "integer": (int,), "number": (int, float), "boolean": (bool,),
    "array": (list, tuple), "object": (dict,)}


def _is_a(value: object, kind: str) -> bool:
    """Whether a value is of a JSON schema type."""
    if isinstance(value, bool):
        return kind == "boolean"
    return isinstance(value, JSON_TYPES[kind])


def _misfit(spec: Mapping[str, Any], value: object) -> str | None:
    """What a value must be to fit the property that declares it, or None when
    it fits: its type (an array's items too, where they declare one) and its
    enum. A property that declares neither admits anything."""
    kind, items = spec.get("type"), spec.get("items", {}).get("type")
    wanted = "%s of %s" % (kind, items) if items else kind
    if kind is not None and not _is_a(value, kind):
        return wanted
    if items and isinstance(value, (list, tuple)) and not all(_is_a(v, items) for v in value):
        return wanted
    if "enum" in spec and value not in spec["enum"]:
        return "one of %s" % ", ".join(repr(v) for v in spec["enum"])
    return None


class Tool:
    """A callable with the description and JSON schema the host needs. Every
    call is checked against the schema before the function runs, so a call
    the schema refuses never reaches the tool, whichever door it came in by."""

    def __init__(self, name: str, description: str, schema: Message,
                 fn: Callable[..., Answer]) -> None:
        self.name, self.description, self.schema, self.fn = (
            name, description, schema, fn)

    def describe(self) -> Message:
        return {"name": self.name, "description": self.description,
                "inputSchema": self.schema}

    def __call__(self, arguments: Mapping[str, object]) -> Answer:
        """Call the tool once its schema allows the call. An argument it does
        not declare, one it requires left out, and a value that is not the
        declared type or not one of the declared values are each a Refusal."""
        properties = self.schema.get("properties", {})
        unknown = set(arguments) - set(properties)
        if unknown:
            raise Refusal("%s: unknown argument(s) %s" % (
                self.name, ", ".join(sorted(unknown))))
        for required in self.schema.get("required", ()):
            if required not in arguments:
                raise Refusal("%s: missing %r" % (self.name, required))
        for argument, value in arguments.items():
            wanted = _misfit(properties[argument], value)
            if wanted is not None:
                raise Refusal("%s: %r must be %s" % (self.name, argument, wanted))
        return self.fn(**arguments)


# --- the Streamable HTTP transport ------------------------------------------
#
# The same server over HTTP, for the data-layer container: a client POSTs
# JSON-RPC to /mcp and gets the response as JSON (notifications get 202).
# No server-initiated streams, so GET /mcp is 405; DELETE ends a session.
# /health reports the database the tools are pointed at. db.web's guard
# refuses a request that does not name this server before any of it runs.

MAX_BODY = 1 << 20            # one request is a tool call, not an upload
DRAIN_CHUNK = 1 << 16         # bytes read at a time from an oversize body
MAX_BATCH = 20                # messages in one JSON-RPC batch
RATE_LIMIT = 120              # tool calls per client address per RATE_WINDOW
RATE_WINDOW = 60              # seconds
MAX_TRACKED_CLIENTS = 1000    # past this, clients unseen for a window are forgotten


class _RejectedError(Exception):
    """A POST the door turns away before any message in it is handled: the
    status, the JSON body and any headers the reply carries."""

    def __init__(self, code: int, payload: dict[str, object],
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
            return self._json({"error": "this server has no server-initiated"
                                        " stream; POST JSON-RPC to /mcp"},
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
            raise _RejectedError(400, {"jsonrpc": "2.0", "id": None, "error": {
                "code": PARSE_ERROR, "message": "bad JSON"}}) from None

    def _admit(self, messages: list[object]) -> None:
        """Refuse a batch past MAX_BATCH, and tool calls past the client
        address's rate - the budget is the host's, not a claimed session's."""
        if len(messages) > MAX_BATCH:
            raise _RejectedError(413, {"error": "at most %d messages per batch" % MAX_BATCH})
        calls = sum(1 for m in messages if isinstance(m, dict) and m.get("method") == "tools/call")
        if calls and not self.server.admit(self.client_address[0], calls):
            raise _RejectedError(429, {"error": "too many calls; try again in a minute"},
                                 {"Retry-After": str(RATE_WINDOW)})

    def _dispatch(self, messages: list[object], *, batched: bool) -> None:
        """Handle each message as this client, then reply: 202 when nothing
        needs an answer, else the answers - a list for a batch - with a new
        Mcp-Session-Id after an initialize."""
        _client.id = "http:%s/%s" % (self.client_address[0],
                                     (self.headers.get("Mcp-Session-Id") or "-")[:8])
        responses = [r for r in (self.server.mcp.handle(m) for m in messages) if r is not None]
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
                self._calls = {c: ts for c, ts in self._calls.items()
                               if ts and now - ts[-1] < RATE_WINDOW}
        return True


def serve_http(mcp: Server, host: str, port: int, status: Callable[[], Mapping[str, object]],
               allowed_hosts: Iterable[str] = ()) -> None:
    """Serve `mcp` (a Server) over HTTP until interrupted, answering to the
    local names and `allowed_hosts`."""
    httpd = HttpServer((host, port), mcp, status, allowed_hosts)
    sys.stderr.write("countrix mcp: http://%s:%d/mcp%s\n" % (
        host, port, " (bearer token required)" if httpd.token else ""))
    httpd.serve_forever()
