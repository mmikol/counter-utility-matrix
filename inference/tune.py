"""Tuning a strategy: an edit to its frontmatter, validated, written back
and logged with its reason. The `tune`, `add_strategy` and `infer_strategy`
tools mirror it into the database.

    tune("coverage", "weight", 3.5, "the solver kept leaving Pharah unanswered")
    tune("under-healed", "params.HEAL_MARGIN", 0.8, "two-support lines felt thin")
    tune("anti-air", "when", "enemy.flyers >= 1 and map.known == 1", "...")

    add("shut-off-heals", "Shut off a heavy heal line", "constraint", prose,
        {
            "when": "enemy.heal_ratio >= params.HEAL_RATIO",
            "bonus": "min(team.antiheal, 1) * 1.5", "params": {"HEAL_RATIO": 1.0}},
        "user: one anti-heal pick against a heavy heal line")
    complete("a-draft", {"metric": "team.dps_floor", "direction": "maximize",
                         "weight": 2}, "inferred from the prose")

Fields: kind, category, metric, direction, weight, confidence, when,
require, soft, bonus, penalty (strategy.TUNABLE) and params.NAME. Every
value is checked by strategy.checked_value, the rule the loader reads a
file by, before any file is touched. Each of the three takes a reason and
writes in one order (_commit): the edited (or new) file is loaded through
the catalog before it is written, so a metric that does not exist or an
expression that does not parse is refused and nothing changes. Every
accepted change is one line in inference/strategies/tuning-log.md. The log
lives beside the files: the compose stack bind-mounts that directory, so a
change made through a container lands on the host and in git with the file
it changed.
"""

import os
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import TypedDict

from db import Refusal
from inference import catalog as catalog_module
from inference.strategy import (
    FIELD_RULE,
    TUNABLE,
    CatalogError,
    Form,
    LineValue,
    Strategy,
    checked_value,
    field_text,
)

MAX_PROSE = 20000          # characters in a strategy's prose
MAX_SENTENCES = 3          # a strategy's prose is three sentences at most
_SENTENCE_END = re.compile(r"[.!?](?:[\"')\]`]*)(?:\s|$)")

type Pairs = Sequence[tuple[str, LineValue]]


class TuneError(Refusal):
    """A change the catalog or the field refuses: nothing is written."""


class Change(TypedDict):
    """What tune() changed: one field, its old and new text, the log line."""
    id: str
    field: str
    old: str | None
    new: str
    line: str


class Completion(TypedDict):
    """What complete() set: the form the strategy took and each field's text."""
    id: str
    form: Form
    set: dict[str, str]
    line: str


class Addition(TypedDict):
    """What add() stored: the new file's form and path."""
    id: str
    form: Form
    path: str
    line: str


def _pairs(pairs: Pairs) -> str:
    return ", ".join("%s=%s" % (field, field_text(value)) for field, value in pairs)


# --- the frontmatter edit -------------------------------------------------------

def _header_end(lines: list[str]) -> int:
    """Where a new header line goes: the end, before a trailing blank line."""
    return len(lines) - (1 if lines and not lines[-1].strip() else 0)


def _set_param(lines: list[str], name: str, value: LineValue) -> str | None:
    """NAME set under params:, the block added when there is none -> the old value."""
    block = next((i for i, line in enumerate(lines) if line.strip() == "params:"), None)
    if block is None:
        block = _header_end(lines)
        lines.insert(block, "params:")
    i = block + 1
    while i < len(lines) and lines[i][:1] in (" ", "\t"):
        if lines[i].strip().split(":")[0] == name:
            old = lines[i].split(":", 1)[1].strip()
            lines[i] = "  %s: %s" % (name, field_text(value))
            return old
        i += 1
    lines.insert(i, "  %s: %s" % (name, field_text(value)))
    return None


def _set_scalar(lines: list[str], field: str, value: LineValue) -> str | None:
    """A flat field set in place, or added above params: -> the old value."""
    for i, line in enumerate(lines):
        if line[:1] not in (" ", "\t") and line.split(":")[0].strip() == field:
            old = line.split(":", 1)[1].strip()
            lines[i] = "%s: %s" % (field, field_text(value))
            return old
    at = next((i for i, line in enumerate(lines) if line.strip() == "params:"), _header_end(lines))
    lines.insert(at, "%s: %s" % (field, field_text(value)))
    return None


def edit_frontmatter(text: str, field: str, value: LineValue) -> tuple[str, str | None]:
    """The file's text with one frontmatter field set -> (new text, old
    value). The value is one _coerce passed, so it is one line, and the
    field is a tunable one or a params.NAME dial."""
    if not text.startswith("---"):
        raise TuneError("no frontmatter")
    end = text.find("\n---", 3)
    if end < 0:                       # find() gives -1, which slices from the tail
        raise TuneError("unterminated frontmatter")
    header, rest = text[3:end], text[end:]
    lines = header.split("\n")
    if field.startswith("params."):
        old = _set_param(lines, field[len("params."):], value)
    elif field in TUNABLE:
        old = _set_scalar(lines, field, value)
    else:
        raise TuneError(FIELD_RULE)
    return "---" + "\n".join(lines) + rest, old


def validate(directory: str, hid: str, new_text: str) -> list[Strategy]:
    """Load a copy of the catalog with this one file replaced; raise on error."""
    tmp = tempfile.mkdtemp(prefix="tune-")
    try:
        for name in catalog_module.strategy_files(directory):
            shutil.copy(os.path.join(directory, name), os.path.join(tmp, name))
        with open(os.path.join(tmp, hid + ".md"), "w", encoding="utf-8") as handle:
            handle.write(new_text)
        return catalog_module.load(tmp)
    except CatalogError as error:
        raise TuneError(str(error)) from error
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- the values a field accepts -------------------------------------------------

def _coerce(field: str, value: object) -> LineValue:
    """The value a field accepts, by the rule the loader keeps too
    (strategy.checked_value), or a TuneError. A writer sets one line at a
    time: the params block arrives as params.NAME dials (_flatten), and a
    bare params is refused as edit_frontmatter refuses it."""
    try:
        checked = checked_value(field, value)
    except CatalogError as error:
        raise TuneError(str(error)) from error
    if isinstance(checked, dict):
        raise TuneError(FIELD_RULE)
    return checked


def _flatten(fields: Mapping[str, object] | None) -> list[tuple[str, object]]:
    """{"params": {"A": 1}, "weight": 2} -> [("params.A", 1), ("weight", 2)]."""
    out: list[tuple[str, object]] = []
    for field, value in (fields or {}).items():
        if field != "params":
            out.append((field, value))
        elif isinstance(value, Mapping):
            out += [("params." + name, v) for name, v in value.items()]
        elif value:
            raise TuneError("params is a block of NAME: number")
    return out


# --- the write order --------------------------------------------------------------

def _log(log_path: str, line: str) -> None:
    if not os.path.exists(log_path):
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write("# Tuning log\n\nEvery change to a strategy's frontmatter,"
                         " newest last: when, what, why, and who.\n\n")
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")


def _where(directory: str | None) -> tuple[str, str]:
    """The playbook in force and its log: (directory, log path)."""
    directory = directory or catalog_module.strategies_dir()
    return directory, os.path.join(directory, "tuning-log.md")


def _document(directory: str, loaded: list[Strategy]) -> None:
    """The catalog document follows the files, for the shipped playbook only."""
    if os.path.abspath(directory) == os.path.abspath(catalog_module.strategies_dir()):
        catalog_module.write_docs(loaded)


def _reason(reason: str, message: str) -> None:
    """Every change is logged with why: a blank reason is refused."""
    if not reason or not reason.strip():
        raise TuneError(message)


def _existing(directory: str, hid: str) -> str:
    """The path of the strategy file hid names, or a TuneError."""
    if not catalog_module.ID_RE.fullmatch(hid or ""):
        raise TuneError("no strategy %r" % hid)          # ids are kebab: no paths here
    path = os.path.join(directory, hid + ".md")
    if not os.path.exists(path):
        raise TuneError("no strategy %r" % hid)
    return path


def _commit(directory: str, hid: str, text: str,
            what: Callable[[Strategy], str], reason: str,
            by: str) -> tuple[Strategy, str]:
    """The one write order: the catalog loaded with the new text, the file
    written, the docs regenerated, one line logged -> (the strategy as loaded,
    the line). `what` words the change from the loaded strategy; it is a
    callable because a pair's text can hold an expression's %, which a
    %-template would misread. A file the catalog never reads, the markdown
    beside the playbook, is refused before anything is written."""
    loaded = validate(directory, hid, text)
    strategy = next((h for h in loaded if h.id == hid), None)
    if strategy is None:
        raise TuneError("%s.md lives beside the playbook and is not a strategy" % hid)
    with open(os.path.join(directory, hid + ".md"), "w", encoding="utf-8") as handle:
        handle.write(text)
    _document(directory, loaded)
    line = "- %s `%s` %s (%s) [%s]" % (_stamp(), hid, what(strategy),
                                      " ".join(reason.split()), by)
    _log(_where(directory)[1], line)
    return strategy, line


# --- the three changes -------------------------------------------------------------

def tune(
        hid: str, field: str, value: object, reason: str, directory: str | None = None,
        by: str = "claude-code-session") -> Change:
    """Apply one change -> the field's old and new text and the log line."""
    directory = _where(directory)[0]
    _reason(reason, "a tuning change needs a reason")
    path = _existing(directory, hid)
    checked = _coerce(field, value)
    new = field_text(checked)
    with open(path, encoding="utf-8") as handle:
        text, old = edit_frontmatter(handle.read(), field, checked)
    _, line = _commit(directory, hid, text, lambda _: "%s: %s -> %s" % (
        field, old if old is not None else "unset", new), reason, by)
    return {"id": hid, "field": field, "old": old, "new": new, "line": line}


def complete(
        hid: str, fields: Mapping[str, object] | None, reason: str,
        directory: str | None = None, by: str = "claude-code-session") -> Completion:
    """Set several frontmatter fields at once - what /strategy infers for a
    draft - validated as a whole, logged as one line -> the form it took and
    each field's text."""
    directory = _where(directory)[0]
    _reason(reason, "an inferred strategy needs a reason")
    path = _existing(directory, hid)
    pairs = [(f, _coerce(f, v)) for f, v in _flatten(fields)]
    if not pairs:
        raise TuneError("nothing to set")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    for field, value in pairs:
        text, _ = edit_frontmatter(text, field, value)
    strategy, line = _commit(directory, hid, text, lambda s: "inferred -> %s: %s" % (
        s.form, _pairs(pairs)), reason, by)
    return {"id": hid, "form": strategy.form, "set": {f: field_text(v) for f, v in pairs},
            "line": line}


def sentence_count(body: str) -> int:
    """How many sentences the prose holds - the title line and code spans aside."""
    text = "\n".join(line for line in (body or "").splitlines() if not line.startswith("#"))
    text = re.sub(r"`[^`]*`", "code", text)                 # `require: a == 2.` is one token
    return len(_SENTENCE_END.findall(text.strip()))


def _check_new(hid: str, name: str, kind: str, body: str) -> None:
    """What a new strategy must be before any file exists: a kebab id, a known
    kind, a name and prose, the name one line by the rule every field keeps,
    the prose within its length and three sentences at most."""
    if not catalog_module.ID_RE.fullmatch(hid or ""):
        raise TuneError("id must be lowercase-kebab, got %r" % hid)
    _coerce("kind", kind)
    if not (name or "").strip() or not (body or "").strip():
        raise TuneError("a strategy needs a name and its prose")
    _coerce("name", name)
    if len(body) > MAX_PROSE:
        raise TuneError("a strategy's prose is under %d characters" % MAX_PROSE)
    count = sentence_count(body)
    if count > MAX_SENTENCES:
        raise TuneError("a strategy's prose is at most %d sentences; this has %d"
                        % (MAX_SENTENCES, count))


def add(hid: str, name: str, kind: str, body: str, fields: Mapping[str, object] | None,
        reason: str, *, directory: str | None = None,
        by: str = "claude-code-session") -> Addition:
    """A new strategy file from its name, kind, prose and (inferred) fields,
    validated through the catalog before it exists and logged with its reason
    -> its form, path and log line. The file opens in category general; a
    category among the fields sets it in place, like any other field."""
    directory = _where(directory)[0]
    _reason(reason, "a new strategy needs a reason")
    _check_new(hid, name, kind, body)
    path = os.path.join(directory, hid + ".md")
    if os.path.exists(path):
        raise TuneError("%r exists; tune or infer_strategy changes it, deleting it is manual"
                        % hid)
    pairs = [(f, _coerce(f, v)) for f, v in _flatten(fields)]
    body = body.strip("\n")
    if not body.startswith("#"):
        body = "# %s\n\n%s" % (name.strip(), body)
    text = "---\nname: %s\nkind: %s\ncategory: general\n---\n%s\n" % (name.strip(), kind, body)
    for field, value in pairs:
        text, _ = edit_frontmatter(text, field, value)
    strategy, line = _commit(directory, hid, text, lambda s: "added as %s/%s%s" % (
        kind, s.form, ": " + _pairs(pairs) if pairs else ""), reason, by)
    return {"id": hid, "form": strategy.form, "path": path, "line": line}


def log_tail(n: int = 20, log_path: str | None = None) -> list[str]:
    """The last n lines of the log beside the playbook in force."""
    log_path = log_path or _where(None)[1]
    if not os.path.exists(log_path):
        return []
    with open(log_path, encoding="utf-8") as handle:
        lines = [line.rstrip("\n") for line in handle if line.startswith("- ")]
    return lines[-n:]
