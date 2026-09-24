"""The audit log: one JSON line per tool call, through either transport and
in-process - when, over which transport, from whom, which tool, the shape of
its arguments, whether it succeeded, and how long it took. The sentry reads
it. COUNTRIX_AUDIT moves it, read on every call.

Every line names its caller: stdio:<pid> (the process that launched the
stdio server), http:<address>/<session>, and in-process the board, the
refresher, the shell, or nested:<tool> for a call one tool makes to
another. An argument is recorded by name with its length (a string, a
list, an object) or its type name (anything else: int, float, bool,
NoneType) - never its value.

A line that cannot be written is noted on stderr - never stdout, the stdio
wire - and never raised: the door stays open if the log fails.
"""

import json
import os
import sys
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Literal, NotRequired, TypedDict

from db import RAW_DIR, Refusal

MS_PER_SECOND = 1000
REASON_CHARS = 200          # a refusal or a crash is recorded up to this many characters

# The door a call came through: either transport, or a call in the same process.
type Transport = Literal["stdio", "http", "in-process"]


class AuditLine(TypedDict):
    """One line of the log: when, the transport, the caller, the tool, each
    argument's size or type name, whether it succeeded and in how many
    milliseconds, and why it did not - a refusal's text or a crash's."""
    t: str
    transport: Transport
    client: str
    tool: str
    args: dict[str, int | str]
    ok: bool
    ms: int
    refused: NotRequired[str]
    crashed: NotRequired[str]


def default_audit_path() -> str:
    """The log every call is audited to: COUNTRIX_AUDIT, else db/raw/audit.jsonl."""
    return os.environ.get("COUNTRIX_AUDIT", os.path.join(RAW_DIR, "audit.jsonl"))


def audit(entry: AuditLine, path: str | None = None) -> None:
    """Append one audit line, noting on stderr a line that is not written."""
    path = path or default_audit_path()
    try:
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as error:
        sys.stderr.write("countrix mcp: the audit log %s was not written: %s\n" % (path, error))


def _sizes(arguments: Mapping[str, object]) -> dict[str, int | str]:
    """{argument name: its length, or its type name} - never the value. A
    string, a list or an object is recorded by its length; a number, a bool
    or None by its type name."""
    return {key: len(value) if isinstance(value, (list, dict, str)) else type(value).__name__
            for key, value in arguments.items()}


def audited[T](
        name: str, arguments: Mapping[str, object], call: Callable[[], T], transport: Transport,
        client: str, audit_path: str | None = None) -> T:
    """Run one tool call from `client` and leave exactly one audit line for
    it. Every path to a tool - stdio, HTTP and the in-process calls of the
    board, the refresher, the shell and one tool of another - comes through
    here, so the sentry's window covers all three. A Refusal - the tool
    refusing its input, the wrapper refusing the call - is audited as
    refused; anything else as crashed. Each carries its message, the crash
    with the error's type, as the door's reply does."""
    line = AuditLine(
        t=datetime.now(UTC).isoformat(timespec="seconds"), transport=transport, client=client,
        tool=name, args=_sizes(arguments), ok=False, ms=0)
    started = time.monotonic()

    def spent() -> int:
        return int((time.monotonic() - started) * MS_PER_SECOND)

    try:
        result = call()
    except Refusal as refused:
        line["refused"] = str(refused)[:REASON_CHARS]
        line["ms"] = spent()
        audit(line, audit_path)
        raise
    except Exception as error:
        line["crashed"] = ("%s: %s" % (type(error).__name__, error))[:REASON_CHARS]
        line["ms"] = spent()
        audit(line, audit_path)
        raise
    line["ok"] = True
    line["ms"] = spent()
    audit(line, audit_path)
    return result
