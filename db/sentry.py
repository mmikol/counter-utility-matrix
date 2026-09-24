"""The sentry: the guard over the playbook and the door.

Every COUNTRIX_SENTRY_EVERY seconds (30):

    the playbook   every file in inference/strategies/ must load through the
                   catalog; one that does not is quarantined (renamed to
                   .md.quarantined, which the catalog ignores) and named in
                   the report, so a malformed or hostile file dropped in
                   through the bind mount never reaches the solver or a
                   session. A file whose prose carries instruction-like text
                   ("ignore previous instructions", a shell command, a
                   credential, a script tag, a base64 blob) is quarantined
                   the same way.
    the database   the same scan over the free text in the database
                   (descriptions, the wiki's notes, strategy bodies); those
                   are flagged, not removed - a person decides
    the door       the audit log every tool call writes (db/raw/audit.jsonl):
                   calls in the last minute, refusals, crashes, any client
                   past the rate limit, and any line that is not an audit
                   entry
    the report     db/raw/sentry.json - ok or not, what was quarantined, the
                   flags, the counts - which `orchestrator.py status` prints

    python -m db.sentry            the loop (the sentry container)
    python -m db.sentry --once     one pass, exit 0 when nothing is wrong and
                                   1 when something is; any other argument
                                   prints this text and exits 2
"""

import json
import os
import re
import sys
import time
import traceback
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import NoReturn, TypedDict

import psycopg
from psycopg.sql import SQL

from db import RAW_DIR, psql
from db.mcp import server  # one definition: the door's own
from inference import catalog as catalog_module

EVERY = float(os.environ.get("COUNTRIX_SENTRY_EVERY", "30"))

Log = Callable[[str], object]

REPORT_PATH = os.path.join(RAW_DIR, "sentry.json")
AUDIT_TAIL_BYTES = 262144  # 256 KiB: the last minute's lines with room to spare
QUARANTINE = ".quarantined"


@dataclass(frozen=True)
class Watch:
    """Where one pass looks and reports. No directory is the playbook in force,
    no audit path the door's own log (server.default_audit_path()) and no DSN
    default_dsn(), each resolved on every pass."""
    directory: str | None = None
    audit_path: str | None = None
    dsn: str | None = None
    report_path: str = REPORT_PATH
    scan_database: bool = True
    log: Log = print


class Report(TypedDict):
    """One pass, as db/raw/sentry.json holds it and `orchestrator.py status` reads it."""
    checked_at: str
    ok: bool
    playbook: int | None
    quarantined: list[str]
    flags: list[str]
    calls_last_minute: int
    refused_last_minute: int
    audit_offset: int


# What a strategy, a note or a description never legitimately says.
TOOLS = r"(db_rebuild|db_init|db_migrate|sync_all|pull_\w+|load_authored|tune|infer_strategy|" \
        r"add_strategy|derive_strategies|query|export_csv)"
INJECTION = [re.compile(p, re.I | re.S) for p in (
    r"\b(ignore|disregard|forget|override)\b[^.\n]{0,60}\b(instructions?|rules?|messages?|prompts?|guidelines?)\b",
    r"\b(instructions?|rules?|prompts?)\b[^.\n]{0,30}\b(above|before|previous|prior|earlier)\b[^.\n]{0,40}\b(ignore|disregard|forget|override|no longer)\b",  # noqa: E501
    r"\byou are now (a|an|the|my|our)\b", r"\bnew (instructions|persona|identity)\b",
    r"\bsystem prompt\b", r"\bdeveloper message\b", r"\bas an ai\b",
    r"\b(run|execute|call|invoke|use)\b[^.\n]{0,40}\b" + TOOLS + r"\b",
    r"\b(run|execute)\b[^.\n]{0,20}\b(the following|this) (command|script|code)\b",
    r"(^|[\s`])(curl|wget|bash -c|sh -c|rm -rf|sudo|chmod|powershell|nc -e)\b",
    r"\b(pg_read_file|pg_ls_dir|set_config|query_to_xml|lo_export|lo_import|dblink)\b",
    r"\b(api[_ -]?key|password|secret|token|credential)s?\b[^.\n]{0,60}\b(reveal|print|send|leak|exfiltrat|paste)\b",  # noqa: E501
    r"\b(reveal|print|send|leak|exfiltrat|paste)\b[^.\n]{0,60}\b(api[_ -]?key|password|secret|token|credential)s?\b",  # noqa: E501
    r"<script\b", r"[A-Za-z0-9+/]{240,}={0,2}",
)]
INVISIBLE = re.compile("[\u200b-\u200f\u2060\ufeff\u00ad]")


def normalised(text: str | None) -> str:
    """One shape for the scan: compatibility-folded, no zero-width characters."""
    return INVISIBLE.sub("", unicodedata.normalize("NFKC", text or ""))

# Free text in the database worth scanning: (table, columns).
TEXT_COLUMNS = (("abilities", ("description",)), ("perks", ("description",)),
                ("subroles", ("passive_description",)), ("synergies", ("note",)),
                ("seasons", ("name", "note")), ("strategies", ("body",)))


def injection_in(text: str) -> str | None:
    """The first instruction-like pattern in `text`, or None."""
    text = normalised(text)
    for pattern in INJECTION:
        m = pattern.search(text)
        if m:
            return m.group(0).strip()[:60]
    return None


def _quarantine(directory: str, name: str, why: str, log: Log) -> bool:
    src = os.path.join(directory, name)
    dst = src + QUARANTINE
    try:
        os.replace(src, dst)
    except OSError as error:
        log("sentry: could not quarantine %s: %s" % (name, error))
        return False
    log("sentry: QUARANTINED %s - %s" % (name, why))
    return True


def check_playbook(
        directory: str | None = None,
        log: Log = print) -> tuple[list[str], list[catalog_module.Strategy] | None]:
    """Load the catalog; quarantine what will not load or reads like an
    instruction -> (quarantined names, catalog or None)."""
    directory = directory or catalog_module.strategies_dir()
    quarantined: list[str] = []
    for _ in range(100):
        try:
            cat = catalog_module.load(directory)
        except catalog_module.CatalogError as error:
            text = str(error)
            name = error.file
            if not name or not os.path.exists(os.path.join(directory, name)):
                log("sentry: the playbook will not load and the file is unclear: %s" % text)
                return quarantined, None
            if not _quarantine(directory, name, "will not load: " + text[:120], log):
                return quarantined, None
            quarantined.append(name)
            continue
        hit = None
        for h in cat:
            why = injection_in(h.name + "\n" + h.body)
            if why:
                hit = (os.path.basename(h.path), why)
                break
        if not hit:
            return quarantined, cat
        if not _quarantine(directory, hit[0], "reads like an instruction: %r" % hit[1], log):
            return quarantined, None
        quarantined.append(hit[0])
    return quarantined, None


def scan(cx: psycopg.Connection) -> list[str]:
    """Instruction-like text in TEXT_COLUMNS over one connection -> flags, one
    per column at most. A table or column the database lacks is skipped; any
    other failure is a flag of its own, so the guard never reports clean about
    text it could not read."""
    flags: list[str] = []
    for table, columns in TEXT_COLUMNS:
        for column in columns:
            try:
                rows = cx.execute(
                    SQL("SELECT {col} FROM {table} WHERE {col} IS NOT NULL").format(
                        col=psql.identifier(column), table=psql.identifier(table))).fetchall()
            except (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedColumn):
                cx.rollback()        # a schema this build does not have: nothing to read
                continue
            except psycopg.Error as error:
                cx.rollback()
                flags.append("%s.%s not scanned: %s: %s"
                             % (table, column, type(error).__name__, error))
                continue
            for (value,) in rows:
                why = injection_in(value)
                if why:
                    flags.append("%s.%s reads like an instruction: %r"
                                 % (table, column, why))
                    break
    return flags


def check_database(dsn: str | None = None) -> list[str]:
    """Instruction-like free text in the database -> flags. A database out of
    reach is a flag carrying its reason."""
    try:
        with psycopg.connect(dsn or psql.default_dsn()) as cx:
            return scan(cx)
    except psql.UNREACHABLE as error:       # a scan failure is a flag, not a crash
        return ["database not scanned: %s: %s" % (type(error).__name__, error)]


@dataclass(frozen=True)
class DoorTally:
    """What one read of the audit log found: the last minute's calls,
    refusals and crashes, the clients past the rate limit, the lines that are
    not audit entries, and the offset the next read starts from."""
    offset: int = 0
    recent: int = 0
    refused: int = 0
    crashed: int = 0
    hot: list[str | None] = field(default_factory=list)
    malformed: int = 0


def check_door(audit_path: str | None = None, offset: int = 0) -> DoorTally:
    """Read the audit log from `offset` -> the tally. A line that is not an
    audit entry counts once, in the read that first passes it; a last line
    without its newline is still being written and waits for the next read."""
    audit_path = audit_path or server.default_audit_path()
    if not os.path.exists(audit_path):
        return DoorTally()
    now = time.time()
    recent = refused = crashed = malformed = 0
    per_client: dict[str | None, int] = {}
    size = os.path.getsize(audit_path)
    # bytes: the door writes UTF-8 unescaped, and a seek can land inside a character
    with open(audit_path, "rb") as handle:
        # re-read the last minute's worth even when the offset is ahead: the
        # window is time, the offset only spares re-reading the whole file
        tail = max(0, min(offset, size) - AUDIT_TAIL_BYTES)
        if tail:
            handle.seek(tail - 1)
            handle.readline()       # the rest of the line the seek lands in
        end = handle.tell()
        for raw in handle:
            start, end = end, end + len(raw)
            if not raw.endswith(b"\n"):
                end = start         # still being written: the next read takes it whole
                break
            try:
                entry = json.loads(raw)
                when = datetime.fromisoformat(entry["t"]).timestamp()
            except (ValueError, KeyError, TypeError):
                malformed += start >= offset
                continue
            if now - when > 60:
                continue
            recent += 1
            per_client[entry.get("client")] = per_client.get(entry.get("client"), 0) + 1
            refused += bool(entry.get("refused"))
            crashed += bool(entry.get("crashed"))
    hot = [c for c, n in per_client.items() if n >= server.RATE_LIMIT]
    return DoorTally(offset=end, recent=recent, refused=refused, crashed=crashed, hot=hot,
                     malformed=malformed)


def _report(
        quarantined: list[str], cat: list[catalog_module.Strategy] | None, flags: list[str],
        door: DoorTally) -> Report:
    """The report of one pass: ok when the playbook loads whole, nothing was
    quarantined and nothing is flagged."""
    return Report(checked_at=datetime.now(UTC).isoformat(timespec="seconds"),
                  ok=not quarantined and not flags and cat is not None,
                  playbook=None if cat is None else len(cat),
                  quarantined=quarantined, flags=flags,
                  calls_last_minute=door.recent, refused_last_minute=door.refused,
                  audit_offset=door.offset)


def _write_report(report: Report, watch: Watch) -> None:
    """Leave the report where the watch keeps it; a failed write is logged."""
    try:
        os.makedirs(os.path.dirname(watch.report_path), exist_ok=True)
        with open(watch.report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=1)
    except OSError as error:
        watch.log("sentry: could not write the report: %s" % error)


def run_once(watch: Watch | None = None, offset: int = 0) -> Report:
    """One pass, reading the audit log from `offset` -> the report, also
    written to the watch's report path."""
    watch = watch or Watch()
    quarantined, cat = check_playbook(watch.directory, watch.log)
    flags = check_database(watch.dsn) if watch.scan_database else []
    door = check_door(watch.audit_path, offset)
    if door.crashed:
        flags.append("%d tool call(s) crashed in the last minute" % door.crashed)
    if door.hot:
        flags.append("client(s) past the rate limit: %s" % ", ".join(str(c) for c in door.hot))
    if door.malformed:
        flags.append("%d malformed line(s) in the audit log" % door.malformed)
    report = _report(quarantined, cat, flags, door)
    _write_report(report, watch)
    watch.log("sentry: %s - playbook %s, %d call(s)/min, %d flag(s)%s" % (
        "ok" if report["ok"] else "NOT OK", report["playbook"], door.recent, len(flags),
        ", quarantined " + ", ".join(quarantined) if quarantined else ""))
    for flag in flags:
        watch.log("sentry: flag - " + flag)
    return report


def run_forever(
        every: float = EVERY, watch: Watch | None = None,
        sleep: Callable[[float], object] = time.sleep) -> NoReturn:
    """A pass every `every` seconds, each reading the audit log on from where
    the last one stopped. A pass that fails leaves a report that is not ok."""
    watch = watch or Watch()
    watch.log("sentry: watching the playbook, the database and the door every %gs" % every)
    offset = 0
    while True:
        try:
            offset = run_once(watch, offset)["audit_offset"]
        except Exception as error:  # noqa: BLE001  # a failed pass must not stop the daemon
            watch.log(traceback.format_exc().rstrip())
            failure = "pass failed: %s: %s" % (type(error).__name__, error)
            watch.log("sentry: " + failure)
            # said in the report, or status prints the last pass's verdict as current
            _write_report(_report([], None, [failure], DoorTally(offset=offset)), watch)
        sleep(every)


def main(argv: list[str] | None = None) -> int:
    """The command line -> its exit code; the loop never returns."""
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--once"]:
        return 0 if run_once()["ok"] else 1
    if argv:
        print(__doc__, file=sys.stderr)
        return 2
    run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
