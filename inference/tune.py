"""Tuning a strategy: an edit to its frontmatter, validated, written back
and logged with its reason. The `tune`, `add_strategy` and `infer_strategy`
tools mirror it into the database.

    tune("coverage", "weight", 3.5, "the solver kept leaving Pharah unanswered")
    tune("under-healed", "params.HEAL_MARGIN", 0.8, "two-support lines felt thin")
    tune("anti-air", "when", "enemy.flyers >= 1 and map.known == 1", "...")

    add("shut-off-heals", "Shut off a heavy heal line", "constraint", prose,
        {"when": "enemy.heal_ratio >= params.HEAL_RATIO",
         "bonus": "min(team.antiheal, 1) * 1.5", "params": {"HEAL_RATIO": 1.0}},
        "user: one anti-heal pick against a heavy heal line")
    complete("a-draft", {"metric": "team.dps_floor", "direction": "maximize",
                         "weight": 2}, "inferred from the prose")

Fields: weight, direction, soft, when, require, bonus, penalty, metric,
kind, category, params.NAME. Each of the three takes a reason and writes
in one order (_commit): the edited (or new) file is loaded through the
catalog before it is written, so a metric that does not exist or an
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

SCALARS = ("weight", "direction", "soft", "when", "require", "bonus", "penalty", "metric",
           "kind", "category")
# the string fields: the four expressions and the names a strategy carries
TEXT_FIELDS = ("when", "require", "bonus", "penalty", "metric", "direction", "category")
WEIGHT_RANGE = (0.0, 10.0)
PARAM_RE = re.compile(r"[A-Z][A-Z0-9_]*\Z")
MAX_EXPRESSION = 500       # characters in a string field
MAX_NAME = 120             # characters in a strategy's name
MAX_PROSE = 20000          # characters in a strategy's prose
MAX_SENTENCES = 3          # a strategy's prose is three sentences at most
_SENTENCE_END = re.compile(r"[.!?](?:[\"')\]`]*)(?:\s|$)")

Pairs = Sequence[tuple[str, object]]


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
    form: catalog_module.Form
    set: dict[str, str]
    line: str


class Addition(TypedDict):
    """What add() stored: the new file's form and path."""
    id: str
    form: catalog_module.Form
    path: str
    line: str


def _format(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


def _pairs(pairs: Pairs) -> str:
    return ", ".join("%s=%s" % (field, _format(value)) for field, value in pairs)


# --- the frontmatter edit -------------------------------------------------------

def _header_end(lines: list[str]) -> int:
    """Where a new header line goes: the end, before a trailing blank line."""
    return len(lines) - (1 if lines and not lines[-1].strip() else 0)


def _set_param(lines: list[str], name: str, value: object) -> str | None:
    """NAME set under params:, the block added when there is none -> the old value."""
    if not PARAM_RE.match(name):
        raise TuneError("a param is NAME: capitals, digits, underscores")
    block = next((i for i, line in enumerate(lines) if line.strip() == "params:"), None)
    if block is None:
        block = _header_end(lines)
        lines.insert(block, "params:")
    i = block + 1
    while i < len(lines) and lines[i][:1] in (" ", "\t"):
        if lines[i].strip().split(":")[0] == name:
            old = lines[i].split(":", 1)[1].strip()
            lines[i] = "  %s: %s" % (name, _format(value))
            return old
        i += 1
    lines.insert(i, "  %s: %s" % (name, _format(value)))
    return None


def _set_scalar(lines: list[str], field: str, value: object) -> str | None:
    """A flat field set in place, or added above params: -> the old value."""
    for i, line in enumerate(lines):
        if line[:1] not in (" ", "\t") and line.split(":")[0].strip() == field:
            old = line.split(":", 1)[1].strip()
            lines[i] = "%s: %s" % (field, _format(value))
            return old
    at = next((i for i, line in enumerate(lines) if line.strip() == "params:"),
              _header_end(lines))
    lines.insert(at, "%s: %s" % (field, _format(value)))
    return None


def edit_frontmatter(text: str, field: str, value: object) -> tuple[str, str | None]:
    """The file's text with one frontmatter field set -> (new text, old value)."""
    if not text.startswith("---"):
        raise TuneError("no frontmatter")
    if isinstance(value, str) and ("\n" in value or "\r" in value
                                   or value.lstrip().startswith("---")):
        raise TuneError("a value is one line")
    end = text.find("\n---", 3)
    if end < 0:                       # find() gives -1, which slices from the tail
        raise TuneError("unterminated frontmatter")
    header, rest = text[3:end], text[end:]
    lines = header.split("\n")
    if field.startswith("params."):
        old = _set_param(lines, field[7:], value)
    elif field in SCALARS:
        old = _set_scalar(lines, field, value)
    else:
        raise TuneError("field must be one of %s or params.NAME" % ", ".join(SCALARS))
    return "---" + "\n".join(lines) + rest, old


def validate(directory: str, hid: str, new_text: str) -> list[catalog_module.Strategy]:
    """Load a copy of the catalog with this one file replaced; raise on error."""
    tmp = tempfile.mkdtemp(prefix="tune-")
    try:
        for name in catalog_module.strategy_files(directory):
            shutil.copy(os.path.join(directory, name), os.path.join(tmp, name))
        with open(os.path.join(tmp, hid + ".md"), "w", encoding="utf-8") as handle:
            handle.write(new_text)
        return catalog_module.load(tmp)
    except catalog_module.CatalogError as error:
        raise TuneError(str(error)) from error
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- the values a field accepts -------------------------------------------------

def _number(value: object, message: str) -> float:
    """A number, or a TuneError saying so. A bool is an int, as float() reads it."""
    if not isinstance(value, (str, int, float)):
        raise TuneError(message)
    try:
        return float(value)
    except ValueError:
        raise TuneError(message) from None


def _coerce(field: str, value: object) -> object:
    """The value a field accepts - a number, a boolean or a string - or a
    TuneError. A field it does not know passes as it is: edit_frontmatter
    refuses it."""
    if field == "weight":
        weight = _number(value, "weight must be a number")
        if not WEIGHT_RANGE[0] <= weight <= WEIGHT_RANGE[1]:
            raise TuneError("weight must be within %g..%g" % WEIGHT_RANGE)
        return weight
    if field.startswith("params."):
        return _number(value, "a param must be a number")
    if field == "soft" and not isinstance(value, bool):
        raise TuneError("soft must be true or false")
    if field == "kind" and value not in catalog_module.KINDS:
        raise TuneError("kind must be one of %s" % "/".join(catalog_module.KINDS))
    if field in TEXT_FIELDS and not (isinstance(value, str) and len(value) <= MAX_EXPRESSION):
        raise TuneError("%s is a string under %d characters" % (field, MAX_EXPRESSION))
    return value


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


def _document(directory: str, loaded: list[catalog_module.Strategy]) -> None:
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
            what: Callable[[catalog_module.Strategy], str], reason: str,
            by: str) -> tuple[catalog_module.Strategy, str]:
    """The one write order: the catalog loaded with the new text, the file
    written, the docs regenerated, one line logged -> (the strategy as loaded,
    the line). `what` words the change from the loaded strategy; it is a
    callable because a pair's text can hold an expression's %, which a
    %-template would misread."""
    loaded = validate(directory, hid, text)
    with open(os.path.join(directory, hid + ".md"), "w", encoding="utf-8") as handle:
        handle.write(text)
    _document(directory, loaded)
    strategy = next(h for h in loaded if h.id == hid)
    line = "- %s `%s` %s (%s) [%s]" % (_stamp(), hid, what(strategy),
                                      " ".join(reason.split()), by)
    _log(_where(directory)[1], line)
    return strategy, line


# --- the three changes -------------------------------------------------------------

def tune(hid: str, field: str, value: object, reason: str, directory: str | None = None,
         by: str = "claude-code-session") -> Change:
    """Apply one change -> the field's old and new text and the log line."""
    directory = _where(directory)[0]
    _reason(reason, "a tuning change needs a reason")
    path = _existing(directory, hid)
    value = _coerce(field, value)
    with open(path, encoding="utf-8") as handle:
        text, old = edit_frontmatter(handle.read(), field, value)
    _, line = _commit(directory, hid, text, lambda _: "%s: %s -> %s" % (
        field, old if old is not None else "unset", _format(value)), reason, by)
    return {"id": hid, "field": field, "old": old, "new": _format(value), "line": line}


def complete(hid: str, fields: Mapping[str, object] | None, reason: str,
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
    return {"id": hid, "form": strategy.form, "set": {f: _format(v) for f, v in pairs},
            "line": line}


def sentences(body: str) -> int:
    """How many sentences the prose holds - the title line and code spans aside."""
    text = "\n".join(line for line in (body or "").splitlines() if not line.startswith("#"))
    text = re.sub(r"`[^`]*`", "code", text)                 # `require: a == 2.` is one token
    return len(_SENTENCE_END.findall(text.strip()))


def _check_new(hid: str, name: str, kind: str, body: str) -> None:
    """What a new strategy must be before any file exists: a kebab id, a known
    kind, a name and prose within their limits, three sentences at most."""
    if not catalog_module.ID_RE.fullmatch(hid or ""):
        raise TuneError("id must be lowercase-kebab, got %r" % hid)
    if kind not in catalog_module.KINDS:
        raise TuneError("kind must be one of %s" % "/".join(catalog_module.KINDS))
    if not (name or "").strip() or not (body or "").strip():
        raise TuneError("a strategy needs a name and its prose")
    if len(name) > MAX_NAME or len(body) > MAX_PROSE:
        raise TuneError("a strategy is a name under %d characters and prose under %d"
                        % (MAX_NAME, MAX_PROSE))
    count = sentences(body)
    if count > MAX_SENTENCES:
        raise TuneError("a strategy's prose is at most %d sentences; this has %d"
                        % (MAX_SENTENCES, count))


def add(hid: str, name: str, kind: str, body: str, fields: Mapping[str, object] | None,
        reason: str, *, directory: str | None = None, by: str = "claude-code-session",
        category: str = "general") -> Addition:
    """A new strategy file from its name, kind, prose and (inferred) fields,
    validated through the catalog before it exists and logged with its reason
    -> its form, path and log line."""
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
    text = "---\nname: %s\nkind: %s\ncategory: %s\n---\n%s\n" % (
        name.strip(), kind, (category or "general").strip(), body)
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
