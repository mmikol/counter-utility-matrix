"""The stdio transport, what .mcp.json launches: JSON-RPC one message per
line on stdin, each answer one line on stdout. A batch - a JSON array - is
answered with one array, and a line that is not JSON with a parse error.
stdout is the wire, so nothing else is written to it.
"""

import json
import sys
from collections.abc import Iterable
from typing import TextIO

from db.mcp.server import PARSE_ERROR, Response, Server, error_response


def serve(mcp: Server, stdin: Iterable[str] | None = None, stdout: TextIO | None = None) -> None:
    """Answer every line of stdin until it ends."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _write(stdout, error_response(None, PARSE_ERROR, "bad JSON"))
            continue
        messages = message if isinstance(message, list) else [message]
        responses = [r for r in (mcp.handle(m) for m in messages) if r is not None]
        if isinstance(message, list):
            if responses:
                _write(stdout, responses)
        else:
            for response in responses:
                _write(stdout, response)


def _write(stdout: TextIO, payload: Response | list[Response]) -> None:
    stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    stdout.flush()
