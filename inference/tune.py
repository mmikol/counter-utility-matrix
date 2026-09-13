"""Tuning a heuristic: an edit to its frontmatter, validated, written back,
mirrored, and logged with its reason.

    tune("coverage", "weight", 3.5, "the solver kept leaving Pharah unanswered")
    tune("under-healed", "params.HEAL_MARGIN", 0.8, "two-support lines felt thin")
    tune("anti-air", "when", "enemy.flyers >= 1 and map.known == 1", "...")

Fields: weight, direction, soft, when, require, bonus, penalty, params.NAME.
The edited file is loaded through the catalog before it is written, so a
metric that does not exist or an expression that does not parse is refused
and nothing changes. Every accepted change is one line in
inference/tuning-log.md - the audit trail of how the brain came to be.
"""

import os
import shutil
import tempfile
from datetime import datetime, timezone

from inference import catalog as catalog_module

LOG_PATH = os.path.join(os.path.dirname(catalog_module.HEURISTICS_DIR), "tuning-log.md")
SCALARS = ("weight", "direction", "soft", "when", "require", "bonus", "penalty", "metric")
WEIGHT_RANGE = (0.0, 10.0)


class TuneError(ValueError):
    pass


def _format(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


def edit_frontmatter(text, field, value):
    """The file's text with one frontmatter field set -> (new text, old value)."""
    if not text.startswith("---"):
        raise TuneError("no frontmatter")
    end = text.find("\n---", 3)
    header, rest = text[3:end], text[end:]
    lines = header.split("\n")
    old = None
    if field.startswith("params."):
        name = field[7:]
        block = next((i for i, l in enumerate(lines) if l.strip() == "params:"), None)
        if block is None:
            lines.insert(len(lines) - (1 if lines and not lines[-1].strip() else 0),
                         "params:")
            block = len(lines) - 1 if lines[-1].strip() == "params:" else len(lines) - 2
        i = block + 1
        while i < len(lines) and lines[i][:1] in (" ", "\t"):
            key = lines[i].strip().split(":")[0]
            if key == name:
                old = lines[i].split(":", 1)[1].strip()
                lines[i] = "  %s: %s" % (name, _format(value))
                break
            i += 1
        else:
            lines.insert(i, "  %s: %s" % (name, _format(value)))
    elif field in SCALARS:
        for i, line in enumerate(lines):
            if line[:1] not in (" ", "\t") and line.split(":")[0].strip() == field:
                old = line.split(":", 1)[1].strip()
                lines[i] = "%s: %s" % (field, _format(value))
                break
        else:
            insert_at = next((i for i, l in enumerate(lines) if l.strip() == "params:"),
                             len(lines) - (1 if lines and not lines[-1].strip() else 0))
            lines.insert(insert_at, "%s: %s" % (field, _format(value)))
    else:
        raise TuneError("field must be one of %s or params.NAME" % ", ".join(SCALARS))
    return "---" + "\n".join(lines) + rest, old


def validate(directory, hid, new_text):
    """Load a copy of the catalog with this one file replaced; raise on error."""
    tmp = tempfile.mkdtemp(prefix="tune-")
    try:
        for name in os.listdir(directory):
            if name.endswith(".md") and name not in catalog_module.NOT_HEURISTICS:
                shutil.copy(os.path.join(directory, name), os.path.join(tmp, name))
        with open(os.path.join(tmp, hid + ".md"), "w", encoding="utf-8") as handle:
            handle.write(new_text)
        return catalog_module.load(tmp)
    except catalog_module.CatalogError as error:
        raise TuneError(str(error))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def tune(hid, field, value, reason, directory=None, by="claude-code-session",
         log_path=None):
    """Apply one change -> {"id", "field", "old", "new", "line"}."""
    directory = directory or catalog_module.HEURISTICS_DIR
    log_path = log_path or (LOG_PATH if directory == catalog_module.HEURISTICS_DIR
                            else os.path.join(directory, "tuning-log.md"))
    if not reason or not reason.strip():
        raise TuneError("a tuning change needs a reason")
    path = os.path.join(directory, hid + ".md")
    if not os.path.exists(path):
        raise TuneError("no heuristic %r" % hid)
    if field == "weight":
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise TuneError("weight must be a number")
        if not WEIGHT_RANGE[0] <= value <= WEIGHT_RANGE[1]:
            raise TuneError("weight must be within %g..%g" % WEIGHT_RANGE)
    if field.startswith("params."):
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise TuneError("a param must be a number")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    new_text, old = edit_frontmatter(text, field, value)
    validate(directory, hid, new_text)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(new_text)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    line = "- %s `%s` %s: %s -> %s (%s) [%s]" % (
        stamp, hid, field, old if old is not None else "unset", _format(value),
        " ".join(reason.split()), by)
    if not os.path.exists(log_path):
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write("# Tuning log\n\nEvery change to a heuristic's frontmatter,"
                         " newest last: when, what, why, and who.\n\n")
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return {"id": hid, "field": field, "old": old, "new": _format(value), "line": line}


def log_tail(n=20, log_path=LOG_PATH):
    if not os.path.exists(log_path):
        return []
    with open(log_path, encoding="utf-8") as handle:
        lines = [l.rstrip("\n") for l in handle if l.startswith("- ")]
    return lines[-n:]
