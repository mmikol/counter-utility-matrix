"""Deriving a draft's frontmatter from its prose - the engine's own call to
the model, on the subscription, with no key.

A draft is a strategy file with only a name, a kind and prose. The solver
cannot score it; a model can say how it should be scored. This module asks
Claude Code in print mode (`claude -p`) - the same model the /strategy
skill is, but headless, on the subscription, so the free-only rule holds -
for a JSON answer, then stores it through tune.complete, which validates
the fields against the catalog before anything is written. A refused
answer is sent back once with the catalog's objection; a second refusal
leaves the draft as it was.

    derive()                 every draft in inference/strategies/
    derive(["heal-line"])    one
    available()              whether the claude CLI is on this machine

Runs where the claude CLI is signed in - the host. `load_authored` and
`orchestrator.py up` call it when drafts exist; inside the compose stack the CLI
is absent, so drafts stay pending until the host runs.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile

from ui.facts import compute
from inference import catalog as catalog_module
from inference import tune

CLI_ENV = "OVERWATCH_DB_CLAUDE"
CLI_CANDIDATES = ("claude", os.path.expanduser("~/.local/bin/claude"))
TIMEOUT = 300
STYLE = ("anti-heal-answer", "coverage", "squish-limit", "open-queue-tanks")


class CliUnavailable(RuntimeError):
    """No usable CLI: absent, or not signed in. Drafts stay pending."""


def cli():
    """The claude CLI to run, or None."""
    explicit = os.environ.get(CLI_ENV)
    if explicit:
        return explicit if os.path.exists(explicit) else shutil.which(explicit)
    for candidate in CLI_CANDIDATES:
        found = shutil.which(candidate) or (candidate if os.path.isfile(candidate) else None)
        if found:
            return found
    return None


def available():
    return cli() is not None


def vocabulary():
    reg = compute.registry()
    lines = []
    for key, meaning in reg.items():
        if key.startswith("enemy."):
            continue
        lines.append("%s - %s%s" % (key, meaning, " (text)" if key in compute.TEXT_METRICS else ""))
    return "\n".join(lines)


def prompt(draft, catalog, objection=None):
    """What the model is asked. Three inputs from the person; the rest inferred."""
    anchors = "\n\n".join(h.raw.split("\n---")[0] + "\n---" for h in catalog if h.id in STYLE)
    fields = ('{"metric": "<numeric key>", "direction": "maximize|minimize", "weight": <1-4>}'
              if draft.kind == "heuristic" else
              '{"require": "<expr>"} or {"require": "<expr>", "soft": true, "penalty": <number>}'
              ' or {"when": "<expr>", "bonus": "<expr>", "penalty": "<expr>", "params": {"NAME": <number>}}'
              ' (when/bonus/penalty/params each optional) or {"prose": true}')
    text = """You complete a strategy file for overwatch-db, a deterministic Overwatch 2 6v6 composition solver. A person wrote the file's name, its kind and its prose; you write the frontmatter that makes the solver act on it. Answer with ONE JSON object and nothing else:

{"fields": %s, "reason": "<one sentence quoting the prose each field follows from>"}

Rules:
- A heuristic names ONE numeric metric to maximize or minimize, weighted 1-4 (3 is strong).
- A constraint is a limit (require: an expression that must hold; soft: true with a numeric penalty to charge instead of forbid), or scored (when: a guard; bonus and/or penalty: expressions; params: NAME: number for any threshold, read as params.NAME), or {"prose": true} when nothing measurable captures it.
- Expressions use the vocabulary below (team.* is our side, enemy.* the same keys for the red side, matchup.*, map.*, world.*), arithmetic, comparisons, and/or/not, x if c else y, min, max, abs, round. Text keys may appear in a when, never as a metric. Cap rewards with min(x, n); 0.5-2 per unit is the house scale for bonus and penalty.
- Never invent a key. If no key captures the prose, answer {"fields": {"prose": true}, "reason": "..."}.

The catalog's own files, for style:

%s

Vocabulary:

%s

The draft:

name: %s
kind: %s
prose:
%s
""" % (fields, anchors, vocabulary(), draft.name, draft.kind, draft.body)
    if objection:
        text += "\nYour previous answer was refused by the catalog: %s\nFix it and answer with the JSON object again.\n" % objection
    return text


def parse(output):
    """The JSON object in the model's answer -> (fields, reason)."""
    m = re.search(r"\{.*\}", output, re.S)
    if not m:
        raise ValueError("no JSON object in the answer: %r" % output[:200])
    data = json.loads(m.group(0))
    fields = data.get("fields") if isinstance(data, dict) else None
    if not isinstance(fields, dict) or not fields:
        raise ValueError("the answer has no fields: %r" % output[:200])
    return fields, str(data.get("reason") or "derived from the prose")


def run_cli(text, timeout=TIMEOUT):
    """Ask claude -p from a neutral directory (no project settings, no MCP
    servers) with no session inherited -> the answer text."""
    binary = cli()
    if not binary:
        raise RuntimeError("no claude CLI on this machine (set %s)" % CLI_ENV)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    done = subprocess.run([binary, "-p", text, "--output-format", "text",
                           "--no-session-persistence", "--strict-mcp-config"],
                          capture_output=True, text=True, timeout=timeout, env=env,
                          cwd=tempfile.gettempdir())
    if done.returncode != 0:
        said = (done.stdout.strip() + " " + done.stderr.strip()).strip()[-300:]
        if "Not logged in" in said or "/login" in said:
            raise CliUnavailable("the claude CLI is not signed in: run `%s login` once on"
                                 " this machine" % binary)
        raise RuntimeError("claude -p failed (%d): %s" % (done.returncode, said))
    return done.stdout


def derive(ids=None, directory=None, runner=run_cli, log=print, by="claude -p (derive)"):
    """Complete every draft (or the named ones) -> {"derived": [...], "failed": {...},
    "skipped": reason|None}."""
    directory = directory or catalog_module.STRATEGIES_DIR
    catalog = catalog_module.load(directory)
    drafts = [h for h in catalog if h.pending and (not ids or h.id in ids)]
    out = {"derived": [], "failed": {}, "skipped": None}
    if not drafts:
        out["skipped"] = "nothing pending"
        return out
    if runner is run_cli and not available():
        out["skipped"] = "no claude CLI here; drafts stay pending (run /strategy, or derive on the host)"
        return out
    for draft in drafts:
        objection = None
        for attempt in (1, 2):
            try:
                fields, reason = parse(runner(prompt(draft, catalog, objection)))
                done = tune.complete(draft.id, fields, reason, directory=directory, by=by)
                log("derive: %s -> %s (%s)" % (draft.id, done["form"], ", ".join(
                    "%s=%s" % kv for kv in done["set"].items())))
                out["derived"].append({"id": draft.id, "form": done["form"], "set": done["set"]})
                break
            except (tune.TuneError, ValueError) as error:
                objection = str(error)
                log("derive: %s attempt %d refused: %s" % (draft.id, attempt, objection))
            except CliUnavailable as error:
                out["skipped"] = str(error)
                log("derive: " + out["skipped"])
                return out
            except (RuntimeError, subprocess.TimeoutExpired) as error:
                objection = str(error)
                log("derive: %s: %s" % (draft.id, objection))
                break
        if draft.id not in [d["id"] for d in out["derived"]]:
            out["failed"][draft.id] = objection
    return out


def rendered(result):
    parts = ["derive: %d completed" % len(result["derived"])] if result["derived"] else []
    if result["skipped"]:
        parts.append("derive: " + result["skipped"])
    parts += ["  %s -> %s" % (d["id"], d["form"]) for d in result["derived"]]
    parts += ["  %s FAILED: %s" % kv for kv in result["failed"].items()]
    return "\n".join(parts)
