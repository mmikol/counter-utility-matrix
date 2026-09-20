"""The sentry: the guard over the playbook and the door.

Every COUNTER_MATRIX_SENTRY_EVERY seconds (30):

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
    the door       the audit log the MCP server writes (db/raw/audit.jsonl):
                   calls in the last minute, refusals, crashes, and any
                   client past the rate limit
    the report     db/raw/sentry.json - ok or not, what was quarantined, the
                   flags, the counts - which `orchestrator.py status` prints

    python -m db.sentry            the loop (the sentry container)
    python -m db.sentry --once     one pass, exit 0 when nothing is wrong
"""

import json
import os
import re
import sys
import time
import unicodedata
from datetime import UTC, datetime

from db import RAW_DIR
from db.mcp.server import AUDIT_PATH, RATE_LIMIT  # one definition: the door's own
from inference import catalog as catalog_module

EVERY = float(os.environ.get("COUNTER_MATRIX_SENTRY_EVERY", "30"))

REPORT_PATH = os.path.join(RAW_DIR, "sentry.json")
QUARANTINE = ".quarantined"

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


def normalised(text):
    """One shape for the scan: compatibility-folded, no zero-width characters."""
    return INVISIBLE.sub("", unicodedata.normalize("NFKC", text or ""))

# Free text in the database worth scanning: (table, columns).
TEXT_COLUMNS = (("abilities", ("description",)), ("perks", ("description",)),
                ("subroles", ("passive_description",)), ("synergies", ("note",)),
                ("seasons", ("name", "note")), ("strategies", ("body",)))


def injected(text):
    """The first instruction-like pattern in `text`, or None."""
    text = normalised(text)
    for pattern in INJECTION:
        m = pattern.search(text)
        if m:
            return m.group(0).strip()[:60]
    return None


def _quarantine(directory, name, why, log):
    src = os.path.join(directory, name)
    dst = src + QUARANTINE
    try:
        os.replace(src, dst)
    except OSError as error:
        log("sentry: could not quarantine %s: %s" % (name, error))
        return False
    log("sentry: QUARANTINED %s - %s" % (name, why))
    return True


def check_playbook(directory=None, log=print):
    """Load the catalog; quarantine what will not load or reads like an
    instruction -> (quarantined names, catalog or None)."""
    directory = directory or catalog_module.STRATEGIES_DIR
    quarantined = []
    for _ in range(100):
        try:
            cat = catalog_module.load(directory)
        except catalog_module.CatalogError as error:
            text = str(error)
            name = getattr(error, "file", None)
            if not name or not os.path.exists(os.path.join(directory, name)):
                log("sentry: the playbook will not load and the file is unclear: %s" % text)
                return quarantined, None
            if not _quarantine(directory, name, "will not load: " + text[:120], log):
                return quarantined, None
            quarantined.append(name)
            continue
        hit = None
        for h in cat:
            why = injected(h.name + "\n" + h.body)
            if why:
                hit = (os.path.basename(h.path), why)
                break
        if not hit:
            return quarantined, cat
        if not _quarantine(directory, hit[0], "reads like an instruction: %r" % hit[1], log):
            return quarantined, None
        quarantined.append(hit[0])
    return quarantined, None


def scan(cx):
    """Instruction-like text in TEXT_COLUMNS over one connection -> flags, one
    per column at most. A table or column the database lacks is skipped."""
    import psycopg
    flags = []
    for table, columns in TEXT_COLUMNS:
        for column in columns:
            try:
                rows = cx.execute("SELECT %s FROM %s WHERE %s IS NOT NULL"
                                  % (column, table, column)).fetchall()
            except psycopg.Error:
                cx.rollback()
                continue
            for (value,) in rows:
                why = injected(value)
                if why:
                    flags.append("%s.%s reads like an instruction: %r"
                                 % (table, column, why))
                    break
    return flags


def check_database(dsn=None):
    """Instruction-like free text in the database -> flags."""
    try:
        import psycopg

        from db import psql
        with psycopg.connect(dsn or psql.default_dsn()) as cx:
            return scan(cx)
    except Exception as error:      # a scan failure is a flag, not a crash
        return ["database not scanned: %s" % type(error).__name__]


def check_door(audit_path=None, offset=0):
    """Read the audit log from `offset` -> (new offset, calls in the last minute,
    refusals, crashes, clients past the limit)."""
    audit_path = audit_path or AUDIT_PATH
    now = time.time()
    recent, refused, crashed, per_client = 0, 0, 0, {}
    if not os.path.exists(audit_path):
        return 0, 0, 0, 0, []
    size = os.path.getsize(audit_path)
    with open(audit_path, encoding="utf-8") as handle:
        # re-read the last minute's worth even when the offset is ahead: the
        # window is time, the offset only spares re-reading the whole file
        handle.seek(max(0, min(offset, size) - 262144))
        for line in handle:
            try:
                entry = json.loads(line)
                when = datetime.fromisoformat(entry["t"]).timestamp()
            except (ValueError, KeyError):
                continue
            if now - when > 60:
                continue
            recent += 1
            per_client[entry.get("client")] = per_client.get(entry.get("client"), 0) + 1
            refused += 1 if entry.get("refused") else 0
            crashed += 1 if entry.get("crashed") else 0
        offset = handle.tell()
    hot = [c for c, n in per_client.items() if n >= RATE_LIMIT]
    return offset, recent, refused, crashed, hot


def run_once(directory=None, audit_path=None, dsn=None, log=print,
             report_path=None, scan_database=True, offset=0):
    """One pass -> the report dict, also written to db/raw/sentry.json."""
    quarantined, cat = check_playbook(directory, log)
    flags = check_database(dsn) if scan_database else []
    offset, recent, refused, crashed, hot = check_door(audit_path, offset)
    if crashed:
        flags.append("%d tool call(s) crashed in the last minute" % crashed)
    if hot:
        flags.append("client(s) past the rate limit: %s" % ", ".join(str(c) for c in hot))
    report = {"checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
              "ok": not quarantined and not flags and cat is not None,
              "playbook": None if cat is None else len(cat),
              "quarantined": quarantined, "flags": flags,
              "calls_last_minute": recent, "refused_last_minute": refused,
              "audit_offset": offset}
    report_path = report_path or REPORT_PATH
    try:
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=1)
    except OSError as error:
        log("sentry: could not write the report: %s" % error)
    log("sentry: %s - playbook %s, %d call(s)/min, %d flag(s)%s" % (
        "ok" if report["ok"] else "NOT OK", report["playbook"], recent, len(flags),
        ", quarantined " + ", ".join(quarantined) if quarantined else ""))
    for flag in flags:
        log("sentry: flag - " + flag)
    return report


def run_forever(every=EVERY, log=print, sleep=time.sleep):
    log("sentry: watching the playbook, the database and the door every %gs" % every)
    offset = 0
    while True:
        try:
            offset = run_once(log=log, offset=offset).get("audit_offset", 0)
        except Exception as error:      # a failed pass is logged, the loop goes on
            log("sentry: pass failed: %s: %s" % (type(error).__name__, error))
        sleep(every)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--once"]:
        return 0 if run_once()["ok"] else 1
    if argv:
        sys.exit(__doc__)
    run_forever()


if __name__ == "__main__":
    sys.exit(main())
