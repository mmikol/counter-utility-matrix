"""The protocol: JSON-RPC 2.0 messages answered from a server's tools and
resources, whichever transport carries them - stdio.py one message per line,
http.py a POST each.

A Server speaks the parts a tool host needs: `initialize`, `ping`,
`tools/list`, `tools/call`, `resources/list`, `resources/read`,
`resources/templates/list` and an empty `prompts/list`. A tools/call is
checked against the tool's schema (schema.Tool) and audited (audit.py).
Logs go to stderr unless the server is told otherwise - over stdio, stdout
is the wire.
"""

import traceback
from collections.abc import Callable, Iterable, Mapping
from typing import NotRequired, Protocol, TypedDict

from db import Log, Refusal, to_stderr
from door.mcp.audit import Transport, audited
from door.mcp.schema import Tool

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "countrix", "version": "2.1.0"}

# A JSON object: a request's params as json.loads reads them, or a method's
# result. Arbitrary JSON, so a value read from one is narrowed before use.
type Message = dict[str, object]

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL = (
    -32700, -32600, -32601, -32602, -32603)


class ErrorDetail(TypedDict):
    """A JSON-RPC error: its code and what went wrong."""
    code: int
    message: str


class ErrorResponse(TypedDict):
    """The answer to a request that failed. Its id is the request's, or None
    when the request could not be read."""
    jsonrpc: str
    id: object
    error: ErrorDetail


class ResultResponse(TypedDict):
    """The answer to a request that succeeded: the method's result."""
    jsonrpc: str
    id: object
    result: Mapping[str, object]


type Response = ResultResponse | ErrorResponse


def error_response(msg_id: object, code: int, text: str) -> ErrorResponse:
    """A JSON-RPC error response, for the server and both transports."""
    return ErrorResponse(jsonrpc="2.0", id=msg_id, error=ErrorDetail(code=code, message=text))


class TextContent(TypedDict):
    """One item of a tool's content: its text."""
    type: str
    text: str


class ToolResult(TypedDict):
    """A tools/call result: the tool's text, whether it is an error - the
    tool's refusal - and, for an answer, the same as a JSON object."""
    content: list[TextContent]
    isError: bool
    structuredContent: NotRequired[Mapping[str, object]]


class InvalidParamsError(Exception):
    """The request left out a field this method needs, sent one of the wrong
    type, or named something the server does not serve: the wire's
    INVALID_PARAMS. Raised only where that is what went wrong, so anything
    else escaping a handler is the server's own fault and reaches the branch
    that logs a traceback."""


class Resource(TypedDict):
    """A resource as resources/list lists it."""
    uri: str
    name: str
    description: str
    mimeType: str


class ResourceText(TypedDict):
    """A resource as resources/read returns it: its uri, its type and its text."""
    uri: str
    mimeType: str
    text: str


class NoSuchResourceError(KeyError):
    """No resource at the uri a caller asked for - told apart from a KeyError
    raised while reading one, which is the server's fault."""

    def __str__(self) -> str:
        return "no resource at %s" % self.args[0]


class Resources(Protocol):
    """What a server serves as MCP resources: a listing, and one resource by
    uri, a NoSuchResourceError when nothing is at it."""

    def list(self) -> list[Resource]: ...

    def read(self, uri: str) -> ResourceText: ...


# One method's handler: the request's params -> the result.
type Method = Callable[[Message], Mapping[str, object]]


class Server:
    """The protocol over any transport: its tools by name, the resources it
    serves, where it logs (stderr unless told), the transport its audit lines
    name - stdio until an HttpServer serves it - and the audit log's path."""

    def __init__(
            self, tools: Iterable[Tool], resources: Resources | None = None, *,
            log: Log | None = None, audit_path: str | None = None) -> None:
        self.tools = {t.name: t for t in tools}
        self.resources = resources
        self.log: Log = log or to_stderr
        self.transport: Transport = "stdio"
        self.audit_path = audit_path

    def handle(self, message: object, client: str) -> Response | None:
        """One decoded message from `client` (as the audit line names the
        caller) -> a response, or None for a notification. A message that is
        not an object or names no string method is INVALID_REQUEST, and a
        request the wire cannot serve - its params not an object, a field
        missing or of the wrong type - INVALID_PARAMS; anything else that
        escapes a method is the server's fault, INTERNAL with its type and
        message, and its traceback goes to the log, never to the caller."""
        if not isinstance(message, dict):
            return error_response(None, INVALID_REQUEST, "expected an object")
        msg_id: object = message.get("id")
        method: object = message.get("method")
        params: object = message.get("params") or {}
        if method is None:
            return None            # a response to something we never sent
        if not isinstance(method, str):
            return error_response(msg_id, INVALID_REQUEST, "method must be a string")
        try:
            if method.startswith("notifications/"):
                return None                # a notification gets no response
            handler = self._methods(client).get(method)
            if handler is None:
                return error_response(msg_id, METHOD_NOT_FOUND, "unknown method %r" % method)
            if not isinstance(params, dict):
                raise InvalidParamsError("params must be an object")
            return ResultResponse(jsonrpc="2.0", id=msg_id, result=handler(params))
        except InvalidParamsError as bad:
            return error_response(msg_id, INVALID_PARAMS, str(bad))
        except Exception as error:  # noqa: BLE001  # never let one request kill the wire
            self.log(traceback.format_exc())
            return error_response(msg_id, INTERNAL, "%s: %s" % (type(error).__name__, error))

    def _methods(self, client: str) -> dict[str, Method]:
        """The methods this server answers, a tools/call audited as `client`'s."""
        return {
            "initialize": self._initialize,
            "ping": lambda p: {},
            "tools/list": self._tools_list,
            "tools/call": lambda p: self._tools_call(p, client),
            "resources/list": self._resources_list,
            "resources/read": self._resources_read,
            "resources/templates/list": lambda p: {"resourceTemplates": []},
            "prompts/list": lambda p: {"prompts": []},
        }

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
                " facts layer (facts: every fact the database holds about a"
                " board of map + red + blue picks) and the inference layer"
                " (infer: the optimal composition under the markdown"
                " strategies; evaluate: score a full six). Read-only SQL"
                " via query."),
        }

    def _tools_list(self, params: Message) -> Message:
        return {"tools": [t.describe() for t in self.tools.values()]}

    def _tools_call(self, params: Message, client: str) -> ToolResult:
        if "name" not in params:
            raise InvalidParamsError("missing parameter 'name'")
        name = params["name"]
        tool = self.tools.get(name) if isinstance(name, str) else None
        if tool is None:
            raise InvalidParamsError("no tool named %r" % (name,))
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise InvalidParamsError("arguments must be an object")
        try:
            text, structured = audited(tool.name, arguments, lambda: tool(arguments),
                                       self.transport, client, self.audit_path)
        except Refusal as refused:
            return ToolResult(content=[TextContent(type="text", text=str(refused))],
                              isError=True)
        return ToolResult(content=[TextContent(type="text", text=text)], isError=False,
                          structuredContent=structured)

    def _resources_list(self, params: Message) -> Message:
        if self.resources is None:
            return {"resources": []}
        return {"resources": self.resources.list()}

    def _resources_read(self, params: Message) -> Message:
        if "uri" not in params:
            raise InvalidParamsError("missing parameter 'uri'")
        if self.resources is None:
            raise InvalidParamsError("this server serves no resources")
        uri = params["uri"]
        if not isinstance(uri, str):
            raise InvalidParamsError("uri must be a string")
        try:
            return {"contents": [self.resources.read(uri)]}
        except NoSuchResourceError as unknown:
            raise InvalidParamsError(str(unknown)) from unknown
