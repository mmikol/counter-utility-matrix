"""Tuning a strategy: an edit to its frontmatter, validated, written back,
mirrored, and logged with its reason.

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
prose, category, params.NAME. The edited (or new) file is loaded through
the catalog before it is written, so a metric that does not exist or an
expression that does not parse is refused and nothing changes. Every
accepted change is one line in inference/strategies/tuning-log.md - the
audit trail of how the brain came to be. The log lives beside the files on
purpose: the compose stack bind-mounts that directory, so a change made
through a container lands on the host and in git like the file it changed.
"""

import os
import re
import shutil
import tempfile
from datetime import UTC, datetime

from inference import catalog as catalog_module

LOG_PATH = os.path.join(catalog_module.STRATEGIES_DIR, "tuning-log.md")
SCALARS = ("weight", "direction", "soft", "when", "require", "bonus", "penalty", "metric",
           "kind", "category")
WEIGHT_RANGE = (0.0, 10.0)
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
PARAM_RE = re.compile(r"[A-Z][A-Z0-9_]*\Z")


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
    if isinstance(value, str) and ("\n" in value or "\r" in value
                                   or value.lstrip().startswith("---")):
        raise TuneError("a value is one line")
    end = text.find("\n---", 3)
    header, rest = text[3:end], text[end:]
    lines = header.split("\n")
    old = None
    if field.startswith("params."):
        name = field[7:]
        if not PARAM_RE.match(name):
            raise TuneError("a param is NAME: capitals, digits, underscores")
        block = next((i for i, line in enumerate(lines) if line.strip() == "params:"), None)
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
            insert_at = next((i for i, line in enumerate(lines) if line.strip() == "params:"),
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
        raise TuneError(str(error)) from error
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _coerce(field, value):
    """The value a field accepts, or a TuneError."""
    if field == "weight":
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise TuneError("weight must be a number") from None
        if not WEIGHT_RANGE[0] <= value <= WEIGHT_RANGE[1]:
            raise TuneError("weight must be within %g..%g" % WEIGHT_RANGE)
    elif field.startswith("params."):
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise TuneError("a param must be a number") from None
    elif field == "soft":
        if not isinstance(value, bool):
            raise TuneError("soft must be true or false")
    elif field == "kind":
        if value not in catalog_module.KINDS:
            raise TuneError("kind must be one of %s" % "/".join(catalog_module.KINDS))
    elif field in ("when", "require", "bonus", "penalty", "metric", "direction", "category"):
        if not isinstance(value, str) or len(value) > 500:
            raise TuneError("%s is a string under 500 characters" % field)
    return value


def _flatten(fields):
    """{"params": {"A": 1}, "weight": 2} -> [("params.A", 1), ("weight", 2)]."""
    out = []
    for field, value in (fields or {}).items():
        if field == "params":
            for name, v in (value or {}).items():
                out.append(("params." + name, v))
        else:
            out.append((field, value))
    return out


def _log(log_path, line):
    if not os.path.exists(log_path):
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write("# Tuning log\n\nEvery change to a strategy's frontmatter,"
                         " newest last: when, what, why, and who.\n\n")
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _stamp():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")


def _where(directory, log_path):
    directory = directory or catalog_module.STRATEGIES_DIR
    return directory, log_path or os.path.join(directory, "tuning-log.md")


def _document(directory, loaded):
    """The catalog document follows the files - for the real playbook only,
    never for a test's copy."""
    if os.path.abspath(directory) == os.path.abspath(catalog_module.STRATEGIES_DIR):
        catalog_module.write_docs(loaded)


def tune(hid, field, value, reason, directory=None, by="claude-code-session",
         log_path=None):
    """Apply one change -> {"id", "field", "old", "new", "line"}."""
    directory, log_path = _where(directory, log_path)
    if not reason or not reason.strip():
        raise TuneError("a tuning change needs a reason")
    if not ID_RE.fullmatch(hid or ""):
        raise TuneError("no strategy %r" % hid)          # ids are kebab: no paths here
    path = os.path.join(directory, hid + ".md")
    if not os.path.exists(path):
        raise TuneError("no strategy %r" % hid)
    value = _coerce(field, value)
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    new_text, old = edit_frontmatter(text, field, value)
    loaded = validate(directory, hid, new_text)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(new_text)
    _document(directory, loaded)
    line = "- %s `%s` %s: %s -> %s (%s) [%s]" % (
        _stamp(), hid, field, old if old is not None else "unset", _format(value),
        " ".join(reason.split()), by)
    _log(log_path, line)
    return {"id": hid, "field": field, "old": old, "new": _format(value), "line": line}


def complete(hid, fields, reason, directory=None, by="claude-code-session", log_path=None):
    """Set several frontmatter fields at once - what /strategy infers for a
    draft - validated as a whole, logged as one line -> {"id", "form", "set", "line"}."""
    directory, log_path = _where(directory, log_path)
    if not reason or not reason.strip():
        raise TuneError("an inferred strategy needs a reason")
    if not ID_RE.fullmatch(hid or ""):
        raise TuneError("no strategy %r" % hid)
    path = os.path.join(directory, hid + ".md")
    if not os.path.exists(path):
        raise TuneError("no strategy %r" % hid)
    pairs = [(f, _coerce(f, v)) for f, v in _flatten(fields)]
    if not pairs:
        raise TuneError("nothing to set")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    for field, value in pairs:
        text, _ = edit_frontmatter(text, field, value)
    loaded = validate(directory, hid, text)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    _document(directory, loaded)
    form = next(h.form for h in loaded if h.id == hid)
    line = "- %s `%s` inferred -> %s: %s (%s) [%s]" % (
        _stamp(), hid, form, ", ".join("%s=%s" % (f, _format(v)) for f, v in pairs),
        " ".join(reason.split()), by)
    _log(log_path, line)
    return {"id": hid, "form": form, "set": {f: _format(v) for f, v in pairs},
            "line": line}


def add(hid, name, kind, body, fields=None, reason="", directory=None,
        by="claude-code-session", log_path=None, category="general"):
    """A new strategy file from its name, kind, prose and (inferred) fields,
    validated through the catalog before it exists -> {"id", "form", "path", "line"}."""
    directory, log_path = _where(directory, log_path)
    if not ID_RE.fullmatch(hid or ""):
        raise TuneError("id must be lowercase-kebab, got %r" % hid)
    if kind not in catalog_module.KINDS:
        raise TuneError("kind must be one of %s" % "/".join(catalog_module.KINDS))
    if not (name or "").strip() or not (body or "").strip():
        raise TuneError("a strategy needs a name and its prose")
    if len(name) > 120 or len(body) > 20000:
        raise TuneError("a strategy is a name under 120 characters and prose under 20,000")
    path = os.path.join(directory, hid + ".md")
    if os.path.exists(path):
        raise TuneError("%r exists; tune or infer_strategy changes it, delete is a human's" % hid)
    pairs = [(f, _coerce(f, v)) for f, v in _flatten(fields)]
    body = body.strip("\n")
    if not body.startswith("#"):
        body = "# %s\n\n%s" % (name.strip(), body)
    text = "---\nname: %s\nkind: %s\ncategory: %s\n---\n%s\n" % (
        name.strip(), kind, (category or "general").strip(), body)
    for field, value in pairs:
        text, _ = edit_frontmatter(text, field, value)
    loaded = validate(directory, hid, text)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    _document(directory, loaded)
    form = next(h.form for h in loaded if h.id == hid)
    line = "- %s `%s` added as %s/%s%s (%s) [%s]" % (
        _stamp(), hid, kind, form,
        ": " + ", ".join("%s=%s" % (f, _format(v)) for f, v in pairs) if pairs else "",
        " ".join((reason or "added").split()), by)
    _log(log_path, line)
    return {"id": hid, "form": form, "path": path, "line": line}


def log_tail(n=20, log_path=LOG_PATH):
    if not os.path.exists(log_path):
        return []
    with open(log_path, encoding="utf-8") as handle:
        lines = [line.rstrip("\n") for line in handle if line.startswith("- ")]
    return lines[-n:]
