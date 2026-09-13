"""A minimal, dependency-free MCP server over stdio.

MCP is JSON-RPC 2.0, one message per line on stdin/stdout, and this server
speaks the parts a tool host needs: `initialize`, `ping`, `tools/list`,
`tools/call`, `resources/list`, `resources/read`, and empty `prompts/list`.
Logs go to stderr - stdout is the wire.
"""

import json
import sys
import traceback

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "overwatch-db", "version": "2.0.0"}

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL = (
    -32700, -32600, -32601, -32602, -32603)


class ToolError(Exception):
    """A tool refusing its input: reported as isError, not as a crash."""


class Server:
    def __init__(self, tools, resources=None, log=None):
        """tools: [Tool]; resources: object with list() and read(uri)."""
        self.tools = {t.name: t for t in tools}
        self.resources = resources
        self.log = log or (lambda msg: sys.stderr.write(msg + "\n"))
        self.initialized = False

    # --- dispatch ------------------------------------------------------

    def handle(self, message):
        """One decoded message -> a response dict, or None for notifications."""
        if not isinstance(message, dict):
            return self._error(None, INVALID_REQUEST, "expected an object")
        msg_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}
        if method is None:
            return None            # a response to something we never sent
        try:
            if method.startswith("notifications/"):
                if method == "notifications/initialized":
                    self.initialized = True
                return None
            handler = {
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
        except KeyError as missing:
            return self._error(msg_id, INVALID_PARAMS,
                               "missing parameter %s" % missing)
        except Exception as error:      # never let one request kill the wire
            self.log(traceback.format_exc())
            return self._error(msg_id, INTERNAL, "%s: %s"
                               % (type(error).__name__, error))

    def _error(self, msg_id, code, text):
        return {"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": code, "message": text}}

    # --- methods -------------------------------------------------------

    def _initialize(self, params):
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
                "overwatch-db: the data layer (pull_* tools scrape, clean and"
                " store each source; sync_all does them all in order), the"
                " user layer (facts: every fact the database holds about a"
                " board of map + red + blue picks) and the inference layer"
                " (infer: the optimal composition under the markdown"
                " heuristics; evaluate: score a full six). Read-only SQL"
                " via query."),
        }

    def _tools_list(self, params):
        return {"tools": [t.describe() for t in self.tools.values()]}

    def _tools_call(self, params):
        name = params["name"]
        tool = self.tools.get(name)
        if tool is None:
            raise KeyError("tool %r" % name)
        arguments = params.get("arguments") or {}
        try:
            text, structured = tool(arguments)
        except ToolError as refused:
            return {"content": [{"type": "text", "text": str(refused)}],
                    "isError": True}
        result = {"content": [{"type": "text", "text": text}],
                  "isError": False}
        if structured is not None:
            result["structuredContent"] = structured
        return result

    def _resources_list(self, params):
        if self.resources is None:
            return {"resources": []}
        return {"resources": self.resources.list()}

    def _resources_read(self, params):
        if self.resources is None:
            raise KeyError("uri")
        return {"contents": [self.resources.read(params["uri"])]}

    # --- the wire ------------------------------------------------------

    def serve(self, stdin=None, stdout=None):
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
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
    def _write(stdout, payload):
        stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        stdout.flush()


class Tool:
    """A callable with the description and JSON schema the host needs."""

    def __init__(self, name, description, schema, fn):
        self.name, self.description, self.schema, self.fn = (
            name, description, schema, fn)

    def describe(self):
        return {"name": self.name, "description": self.description,
                "inputSchema": self.schema}

    def __call__(self, arguments):
        allowed = set(self.schema.get("properties", {}))
        unknown = set(arguments) - allowed
        if unknown:
            raise ToolError("%s: unknown argument(s) %s" % (
                self.name, ", ".join(sorted(unknown))))
        for required in self.schema.get("required", ()):
            if required not in arguments:
                raise ToolError("%s: missing %r" % (self.name, required))
        return self.fn(**arguments)


# --- the Streamable HTTP transport ------------------------------------------
#
# The same server over HTTP, for the data-layer container: a client POSTs
# JSON-RPC to /mcp and gets the response as JSON (notifications get 202).
# No server-initiated streams, so GET /mcp is 405; DELETE ends a session.
# /health reports the database the tools are pointed at.

import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


class HttpHandler(BaseHTTPRequestHandler):
    server_version = "overwatch-db-mcp/2.0"

    def log_message(self, fmt, *args):
        pass

    def _reply(self, code, payload=None, headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") \
            if payload is not None else b""
        self.send_response(code)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        if body:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _origin_allowed(self):
        """DNS-rebinding guard: browsers send Origin; only local ones pass."""
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = urlparse(origin).hostname
        return host in LOCAL_HOSTS or host in self.server.allowed_hosts

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._reply(200, self.server.status())
        if path == "/mcp":
            return self._reply(405, {"error": "this server has no server-initiated"
                                          " stream; POST JSON-RPC to /mcp"},
                               {"Allow": "POST, DELETE"})
        self._reply(404, {"error": "nothing here"})

    def do_DELETE(self):
        self._reply(200 if urlparse(self.path).path == "/mcp" else 404)

    def do_POST(self):
        if urlparse(self.path).path != "/mcp":
            return self._reply(404, {"error": "nothing here"})
        if not self._origin_allowed():
            return self._reply(403, {"error": "origin not allowed"})
        length = int(self.headers.get("Content-Length") or 0)
        try:
            message = json.loads(self.rfile.read(length) or b"")
        except ValueError:
            return self._reply(400, {"jsonrpc": "2.0", "id": None,
                                     "error": {"code": PARSE_ERROR,
                                               "message": "bad JSON"}})
        messages = message if isinstance(message, list) else [message]
        responses = [r for r in (self.server.mcp.handle(m) for m in messages)
                     if r is not None]
        headers = {}
        if any(isinstance(m, dict) and m.get("method") == "initialize"
               for m in messages):
            headers["Mcp-Session-Id"] = uuid.uuid4().hex
        if not responses:
            return self._reply(202, None, headers)
        self._reply(200, responses if isinstance(message, list) else responses[0],
                    headers)


class HttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, mcp, status, allowed_hosts=()):
        super().__init__(address, HttpHandler)
        self.mcp = mcp
        self.status = status
        self.allowed_hosts = set(allowed_hosts)


def serve_http(mcp, host, port, status, allowed_hosts=()):
    """Serve `mcp` (a Server) over HTTP until interrupted."""
    httpd = HttpServer((host, port), mcp, status, allowed_hosts)
    sys.stderr.write("overwatch-db mcp: http://%s:%d/mcp\n" % (host, port))
    httpd.serve_forever()
