"""What the three HTTP servers share - the MCP door, the inference service and
the board - and the one client that calls the door.

A server here answers only requests that name it: LocalServer holds the host
names it answers to, and Handler checks each request's Host and Origin
against them before any route is dispatched, so every method is guarded
alike. Handler also sends the replies - JSON, or bytes of a content type -
and logs one line on stderr for a request that failed or took a timed route.
A request that raised is answered by failure(): a Refusal is the caller's
error, 400 with its message; anything else is the server's fault, 500 with
the error's type and message, and the traceback goes to stderr, never to the
caller. call_tool() is a tools/call over the MCP door's HTTP transport.

Stdlib only, besides db.Refusal, so the MCP door's HTTP transport that
stands on it (db/mcp/http.py) stays dependency-free.
"""

import json
import sys
import time
import traceback
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import NamedTuple
from urllib.parse import urlsplit

from db import Refusal

# the names a request may call a local server by: an allowlisted Host, not a bind
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})  # nosec B104


class Reply(NamedTuple):
    """A JSON reply: its body and its HTTP status."""
    body: dict[str, str]
    status: int


def failure(error: BaseException) -> Reply:
    """The reply to a request that raised `error`."""
    if isinstance(error, Refusal):
        return Reply({"error": str(error)}, 400)
    traceback.print_exception(error, file=sys.stderr)
    return Reply({"error": "%s: %s" % (type(error).__name__, error)}, 500)


# --- the guard ---------------------------------------------------------------

def _hostname(url: str) -> str | None:
    """A URL's host name, lowercased, without its port or brackets; None when
    it has none or does not parse."""
    try:
        return urlsplit(url).hostname
    except ValueError:
        return None


def request_allowed(headers: Message, allowed: frozenset[str]) -> bool:
    """Whether a request names a server that answers to `allowed`: its Host
    header's host name is one of them, and so is its Origin's when it sends
    one. A missing or unparsable Host is refused, and so is `Origin: null`.
    The Host check stops DNS rebinding: a page rebound to this address
    sends a same-origin GET with no Origin, but under its own host name."""
    host = headers.get("Host")
    if not host or _hostname("//" + host) not in allowed:
        return False
    origin = headers.get("Origin")
    return origin is None or _hostname(origin) in allowed


class LocalServer(ThreadingHTTPServer):
    """A threading HTTP server that answers to the local names and to any
    `allowed_hosts` it is published under - the compose service name another
    container calls it by, or a public host name."""

    def __init__(
            self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler],
            allowed_hosts: Iterable[str] = ()) -> None:
        super().__init__(address, handler)
        self.allowed_hosts = LOCAL_HOSTS | frozenset(h.lower() for h in allowed_hosts)


class Handler(BaseHTTPRequestHandler):
    """A request to a LocalServer: refused with 403 before dispatch unless its
    Host and Origin name the server, then answered through _send and _json.
    `timed` names the routes whose every request is logged with how long it
    took - the solves; any other request is logged only when it fails."""
    server: LocalServer
    timed: frozenset[str] = frozenset()
    started: float | None = None

    def parse_request(self) -> bool:
        """The request line and headers, parsed, then the guard: a request
        that does not name this server is answered 403 and its connection
        closed, since an unread body must not be parsed as the next request."""
        self.started = time.monotonic()
        if not super().parse_request():
            return False
        if request_allowed(self.headers, self.server.allowed_hosts):
            return True
        self.close_connection = True
        self._json({"error": "host or origin not allowed"}, 403)
        return False

    def _send(
            self, data: bytes, ctype: str | None, code: int = 200,
            headers: Mapping[str, str] | None = None) -> None:
        """One reply: the status, the extra headers, the content type (none
        for an empty body) and length, and the body."""
        self.send_response(code)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        if ctype is not None:
            self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _json(
            self, payload: object, code: int = 200,
            headers: Mapping[str, str] | None = None) -> None:
        """A JSON reply; a payload of None is an empty body with no content
        type - the MCP door's 202, and its DELETE."""
        if payload is None:
            return self._send(b"", None, code, headers)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(data, "application/json", code, headers)

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        """One line on stderr for a request that failed - a status of 400 or
        more - or took a timed route: the request line, the status and the
        seconds since the request was read. Nothing for the rest, and nothing
        on stdout, which over stdio is the MCP wire."""
        status = code if isinstance(code, int) else 0        # an HTTPStatus is an int
        if status < 400 and urlsplit(self.path).path not in self.timed:
            return
        spent = time.monotonic() - self.started if self.started is not None else 0.0
        self.log_message('"%s" %s %.2fs', self.requestline, status or code, spent)


# --- the client --------------------------------------------------------------

@dataclass(frozen=True)
class CallReply:
    """What a tools/call over HTTP came back with: the tool's text (or why
    there is none), its structured payload, and whether it is an error - the
    tool's refusal, the door turning the call away, or no server answering."""
    text: str
    structured: dict[str, object] | None
    is_error: bool


def _refused_by_door(error: urllib.error.HTTPError) -> CallReply:
    """The door's error status, in its own words where its body gives them."""
    try:
        body = json.loads(error.read().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return CallReply("the MCP server answered %d" % error.code, None, True)
    said = body.get("error") if isinstance(body, dict) else None
    if isinstance(said, dict):                       # a JSON-RPC error object
        said = said.get("message")
    reason = said or error.msg
    return CallReply("the MCP server answered %d: %s" % (error.code, reason), None, True)


def _answer(reply: object) -> CallReply:
    """A JSON-RPC response to tools/call, read: its error's message, or its
    result."""
    if not isinstance(reply, dict):
        return CallReply("the MCP server answered with no JSON-RPC response", None, True)
    if "error" in reply:
        error = reply["error"]
        said = error.get("message", error) if isinstance(error, dict) else error
        return CallReply(str(said), None, True)
    return _tool_result(reply.get("result"))


def _tool_result(result: object) -> CallReply:
    """A tools/call result as the door sends it (db.mcp.server.ToolResult),
    read off the wire into the record a caller gets: the text items of its
    content joined by newlines, its structured payload, and whether it is an
    error. A result that is not an object says nothing and is no error, and
    content or a payload that is not what the door sends reads as none."""
    if not isinstance(result, dict):
        return CallReply("", None, False)
    content = result.get("content")
    items = content if isinstance(content, list) else []
    text = "\n".join(
        str(c.get("text", "")) for c in items if isinstance(c, dict) and c.get("type") == "text")
    structured = result.get("structuredContent")
    payload = structured if isinstance(structured, dict) else None
    return CallReply(text, payload, bool(result.get("isError")))


def call_tool(
        url: str, name: str, arguments: Mapping[str, object], token: str | None = None,
        timeout: float = 60) -> CallReply:
    """One tools/call on the MCP server at `url`, with the bearer token when
    one is given. A URL that is not http or https is a ValueError: urlopen
    would read a file: URL as a path."""
    if urlsplit(url).scheme not in ("http", "https"):
        raise ValueError("the MCP server's URL must be http or https, got %r" % url)
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": dict(arguments)}})
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, data=body.encode("utf-8"), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310  # scheme checked above
            return _answer(json.loads(response.read().decode("utf-8")))
    except urllib.error.HTTPError as error:          # a URLError, so caught first
        return _refused_by_door(error)
    except (urllib.error.URLError, OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        return CallReply("the MCP server is unreachable: %s" % error, None, True)
