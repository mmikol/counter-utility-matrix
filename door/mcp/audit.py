"""The audit log: one JSON line per tool call, through either transport and
in-process, where the refresher and the shell call one directly - when, over
which transport, from whom, which tool, the shape of its arguments (names and
sizes, never the values), whether it succeeded, and how long it took. The
sentry reads it. COUNTRIX_AUDIT moves it, read on every call.

A line that cannot be written is noted on stderr - never stdout, the stdio
wire - and never raised: the door stays open if the log fails.
"""

import json
import os
import sys
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from db import RAW_DIR, Refusal

MS_PER_SECOND = 1000


def default_audit_path() -> str:
    """The log every call is audited to: COUNTRIX_AUDIT, else db/raw/audit.jsonl."""
    return os.environ.get("COUNTRIX_AUDIT", os.path.join(RAW_DIR, "audit.jsonl"))


def audit(entry: Mapping[str, object], path: str | None = None) -> None:
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


def _sizes(arguments: Mapping[str, object] | None) -> dict[str, object]:
    """{argument name: size} - never the value."""
    out: dict[str, object] = {}
    for key, value in (arguments or {}).items():
        if isinstance(value, (list, dict, str)):
            out[key] = len(value)
        else:
            out[key] = value if isinstance(value, (bool, int, float)) else str(type(value).__name__)
    return out


def audited[T](
        name: str, arguments: Mapping[str, object], call: Callable[[], T], transport: str,
        client: str | None = None, audit_path: str | None = None) -> T:
    """Run one tool call and leave exactly one audit line for it. Every path to
    a tool - stdio, HTTP and the in-process calls the refresher and the shell
    make - comes through here, so the sentry's window covers all three. A
    Refusal - the tool refusing its input, the wrapper refusing the call - is
    audited as refused; anything else as crashed. Each carries its message, the
    crash with the error's type, as the door's reply does."""
    entry: dict[str, object] = {
        "t": datetime.now(UTC).isoformat(timespec="seconds"), "transport": transport,
        "client": client, "tool": name, "args": _sizes(arguments)}
    started = time.monotonic()

    def spent() -> int:
        return int((time.monotonic() - started) * MS_PER_SECOND)

    try:
        result = call()
    except Refusal as refused:
        audit(dict(entry, ok=False, refused=str(refused)[:200], ms=spent()), audit_path)
        raise
    except Exception as error:
        crashed = "%s: %s" % (type(error).__name__, error)
        audit(dict(entry, ok=False, crashed=crashed[:200], ms=spent()), audit_path)
        raise
    audit(dict(entry, ok=True, ms=spent()), audit_path)
    return result
