"""The reply an HTTP door gives a request that raised. A Refusal is the
caller's error: 400 with its message. Anything else is the server's fault:
500 with the error's type and message, and the traceback goes to stderr,
never to the caller. The inference service and the board answer through
here; the MCP door draws the same line in JSON-RPC's words. Stdlib only.
"""

import sys
import traceback
from typing import NamedTuple

from db import Refusal


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
