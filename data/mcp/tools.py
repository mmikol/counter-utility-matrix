"""The tools the data layer serves - and, through the same door, the board
tools of the user and inference layers.

Every pull_* tool is pull -> clean -> store for one source and domain; the
pulling and cleaning are the extract/transform code under data/, the
storing is that domain's loader. `sync_all` runs them in dependency order.
Nothing here is a static script: a session (or the orchestrator, or cron)
decides what to pull, when, and reads the summary back.
"""

import json
import os
import sys
from datetime import datetime

import psycopg

from data import common, sources
from data.common import CACHE_DIRS
from data.mcp.server import Tool, ToolError


class Context:
    """Where a tool call lands: the database and the page caches."""

    def __init__(self, dsn=None, caches=None, log=None):
        self._dsn = dsn
        self.caches = dict(CACHE_DIRS, **(caches or {}))
        self.log = log or (lambda msg: sys.stderr.write(msg + "\n"))

    @property
    def dsn(self):
        if self._dsn is None:
            self._dsn = common.default_dsn()
        return self._dsn

    def connect(self):
        return psycopg.connect(self.dsn)

    def cache(self, source):
        return common.prepare_cache(self.caches[source])


# --- the registry ----------------------------------------------------------

REGISTRY = []


def tool(name, description, properties=None, required=()):
    schema = {"type": "object", "properties": properties or {},
              "required": list(required), "additionalProperties": False}

    def decorate(fn):
        fn.tool_name = name
        REGISTRY.append((name, description, schema, fn))
        return fn
    return decorate


def build(ctx):
    """Bind every registered tool to a context -> [Tool]."""
    out = []
    for name, description, schema, fn in REGISTRY:
        def bound(fn=fn, **arguments):
            return fn(ctx, **arguments)
        out.append(Tool(name, description, schema, bound))
    return out


def run_tool(ctx, name, **arguments):
    """Call a registered tool by name, in-process (the orchestrator's path)."""
    for tool_name, _, schema, fn in REGISTRY:
        if tool_name == name:
            return fn(ctx, **arguments)
    raise KeyError(name)


REFRESH = {"refresh": {"type": "boolean",
                       "description": "fetch every page again instead of reading"
                                      " the cache; a page that fails to fetch keeps"
                                      " its cached copy"}}


def _summary(title, summary):
    lines = [title]
    for key, value in summary.items():
        if key == "tables":
            continue
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value) or "-"
        lines.append("  %-16s %s" % (key, value))
    return "\n".join(lines), dict(summary)


# --- pull, clean, store: one tool per source and domain --------------------

@tool("list_sources", "The sources the data layer pulls from, what each"
      " supplies, and how many pages its cache holds.")
def list_sources(ctx):
    from data.sources.blizzard import BLIZZARD
    from data.sources.counterpick import COUNTERPICK
    from data.sources.wiki import WIKI
    rows = []
    for code, name, url in (BLIZZARD, WIKI, COUNTERPICK):
        path = ctx.caches[code]
        cached = len(os.listdir(path)) if os.path.isdir(path) else 0
        rows.append({"code": code, "name": name, "url": url,
                     "cached_pages": cached,
                     "tools": [t for t, s in PULLS if s == code]})
    text = "\n".join("%-12s %-24s %4d cached pages  tools: %s"
                     % (r["code"], r["name"], r["cached_pages"],
                        ", ".join(r["tools"])) for r in rows)
    return text, {"sources": rows}


def _pull(ctx, source, module_path, refresh=False, **options):
    import importlib
    module = importlib.import_module(module_path)
    cache = ctx.cache(source)
    # refresh: every cached page counts as stale and is fetched again; the
    # cached copy survives a failed fetch (see data.sources.keep_stale)
    sources.set_max_age(0 if refresh else None)
    try:
        with ctx.connect() as cx:
            summary = module.run(cx, cache, log=ctx.log, **options)
    finally:
        sources.set_max_age(None)
    return summary


@tool("pull_heroes", "Blizzard's roster: heroes, roles, subroles, portraits,"
      " ability and perk text. Run first - everything links to heroes.",
      REFRESH)
def pull_heroes(ctx, refresh=False):
    return _summary("pull_heroes: roster stored", _pull(
        ctx, "blizzard", "data.load.blizzard.heroes", refresh))


@tool("pull_kits", "The wiki's Cargo ability table and hero articles: weapons"
      " and firing configs, every published number, ability kinds and"
      " keywords, hero health pools. Run after pull_heroes.",
      dict(REFRESH, supplement={"type": "boolean",
                                "description": "also read each hero article"
                                               " for the flags Cargo lacks"
                                               " (default true)"}))
def pull_kits(ctx, refresh=False, supplement=True):
    return _summary("pull_kits: kit numbers stored", _pull(
        ctx, "wiki", "data.load.wiki.heroes", refresh,
        supplement=supplement))


@tool("pull_maps", "The wiki's map pool: maps, game modes, playable"
      " combinations, and the stages of Control and Flashpoint maps.",
      REFRESH)
def pull_maps(ctx, refresh=False):
    return _summary("pull_maps: map pool stored", _pull(
        ctx, "wiki", "data.load.wiki.maps", refresh))


@tool("pull_patches", "The wiki's patch list, so every rates snapshot can say"
      " which game version it measured.", REFRESH)
def pull_patches(ctx, refresh=False):
    return _summary("pull_patches: patches stored", _pull(
        ctx, "wiki", "data.load.wiki.patches", refresh))


@tool("pull_rates", "Blizzard's win/pick/ban rates as a NEW dated snapshot,"
      " by rank tier and by map (Competitive Role Queue, console,"
      " Americas). Slow when uncached: ~40 pages at a polite pace.",
      REFRESH)
def pull_rates(ctx, refresh=False):
    return _summary("pull_rates: snapshot stored", _pull(
        ctx, "blizzard", "data.load.blizzard.meta", refresh))


@tool("pull_playstyles", "The wiki's team-composition page: which playstyle"
      " (dive, brawl, poke) each hero belongs to.", REFRESH)
def pull_playstyles(ctx, refresh=False):
    return _summary("pull_playstyles: styles stored", _pull(
        ctx, "wiki", "data.load.wiki.playstyles", refresh))


@tool("pull_counters", "counterpick.gg: who answers whom, each hero's best"
      " maps, and its own rates under a separate snapshot.", REFRESH)
def pull_counters(ctx, refresh=False):
    return _summary("pull_counters: playbook stored", _pull(
        ctx, "counterpick", "data.load.counterpick.heroes", refresh))


PULLS = [("pull_heroes", "blizzard"), ("pull_kits", "wiki"),
         ("pull_maps", "wiki"), ("pull_patches", "wiki"),
         ("pull_rates", "blizzard"), ("pull_playstyles", "wiki"),
         ("pull_counters", "counterpick")]

PLAYBOOK = ("seasons", "strategies", "synergies", "archetypes",
            "map_playstyle", "heuristics")


@tool("load_playbook", "Store the authored inputs from the repo: seasons,"
      " strategy notes, synergies, comp archetypes, map playstyles, and the"
      " mirror of the markdown heuristics catalog. Whole-truth reloads.",
      {"only": {"type": "array", "items": {"type": "string",
                                            "enum": list(PLAYBOOK)},
                "description": "a subset to reload (default: all)"}})
def load_playbook(ctx, only=None):
    import importlib
    selected = [p for p in PLAYBOOK if not only or p in only]
    summaries = {}
    with ctx.connect() as cx:
        for name in selected:
            if name == "heuristics":
                from inference import catalog
                summaries[name] = catalog.mirror(cx, catalog.load())
            else:
                module = importlib.import_module(
                    "data.load.authored." + name)
                summaries[name] = module.run(cx, log=ctx.log)
    text = "load_playbook: " + "; ".join(
        "%s %s" % (name, ", ".join("%s=%s" % (k, v) for k, v in s.items()
                                    if k != "tables"))
        for name, s in summaries.items())
    return text, summaries


@tool("sync_all", "Every pull_* tool in dependency order, then the authored"
      " playbook, then the CSV mirror: the whole database from its sources."
      " On a populated database this is an update (entities refresh in"
      " place, rates append a snapshot).", REFRESH)
def sync_all(ctx, refresh=False):
    results = {}
    for name, _ in PULLS:
        ctx.log("=== %s ===" % name)
        results[name] = run_tool(ctx, name, refresh=refresh)[1]
    ctx.log("=== load_playbook ===")
    results["load_playbook"] = run_tool(ctx, "load_playbook")[1]
    # Recorded comps come back from the mirror BEFORE the mirror is
    # rewritten - a no-op on a database that already holds them.
    from data.db import schema
    with ctx.connect() as cx:
        results["restored"] = schema.restore_recommendations(cx)
    results["export_csv"] = run_tool(ctx, "export_csv")[1]
    text = "sync_all: %d pulls + playbook + export done%s" % (
        len(PULLS), ", %d recorded rows restored" % results["restored"]
        if results["restored"] else "")
    return text, results


# --- the database's life ----------------------------------------------------

@tool("db_status", "Which database the tools are pointed at, its table and"
      " row counts, and the rates snapshots it holds.")
def db_status(ctx):
    from data.db import schema
    import re
    with ctx.connect() as cx:
        tables = schema.table_count(cx)
        counts, snaps = {}, []
        if tables:
            for t in ("heroes", "abilities", "maps", "hero_meta", "map_meta",
                      "counters", "synergies", "heuristics", "recommendations"):
                if cx.execute("select to_regclass(%s)", (t,)).fetchone()[0]:
                    counts[t] = cx.execute("select count(*) from " + t).fetchone()[0]
            if cx.execute("select to_regclass('meta_snapshots')").fetchone()[0]:
                snaps = [{"id": i, "captured": str(c), "queue": q, "source": s}
                         for i, c, q, s in cx.execute("""
                    select ms.snapshot_id, ms.captured_at::date, ms.queue,
                           src.code from meta_snapshots ms
                    join sources src using(source_id) order by 1""")]
        missing = schema.pending(cx) if tables else []
    dsn = re.sub(r"//[^@/]*@", "//", ctx.dsn)
    newest = max((s["captured"] for s in snaps), default=None)
    text = "database: %s\ntables: %d\n%s\nsnapshots: %d%s%s" % (
        dsn, tables, "\n".join("  %-16s %d" % kv for kv in counts.items()),
        len(snaps), ", newest capture %s" % newest if newest else "",
        "\nPENDING MIGRATIONS (rebuild): %s" % ", ".join(missing)
        if missing else "")
    return text, {"dsn": dsn, "tables": tables, "counts": counts,
                  "snapshots": snaps, "newest_capture": newest,
                  "pending_migrations": missing}


@tool("db_init", "Apply the migrations to an EMPTY database (schema only;"
      " sync_all fills it). Refuses a database that already has tables.")
def db_init(ctx):
    from data.db import schema
    with ctx.connect() as cx:
        if schema.table_count(cx):
            raise ToolError("the database already has tables; db_rebuild is"
                            " the tool that starts over")
        schema.apply(cx, schema.read_migrations(), quiet=True)
        n = schema.table_count(cx)
    return "db_init: %d tables, no data" % n, {"tables": n}


@tool("db_rebuild", "Drop everything, reapply the migrations, run sync_all,"
      " and restore recorded recommendations from the data/raw mirror."
      " The ground truth for structural change.", REFRESH)
def db_rebuild(ctx, refresh=False):
    from data.db import schema
    with ctx.connect() as cx:
        dropped = schema.rebuild(cx, quiet=True)
    results = run_tool(ctx, "sync_all", refresh=refresh)[1]
    text = "db_rebuild: dropped %d tables, rebuilt, restored %d recorded rows" % (
        len(dropped), results["restored"])
    return text, {"dropped": len(dropped), "restored": results["restored"],
                  "sync": results}


@tool("export_csv", "Refresh data/raw/*.csv - one CSV per table, the"
      " database's mirror and the recorded recommendations' backup.")
def export_csv(ctx):
    with ctx.connect() as cx:
        counts = common.export(cx)
    return ("export_csv: %d tables mirrored to data/raw" % len(counts),
            {"tables": dict(counts)})


@tool("db_docs", "Regenerate docs/erd.md, docs/data-dictionary.md and"
      " docs/heuristics.md from the live schema and the heuristics files.")
def db_docs(ctx):
    from data.db import schema
    from inference import catalog
    with ctx.connect() as cx:
        text = schema.generate_docs(cx)
    path = catalog.write_docs(catalog.load())
    return text + "; wrote " + os.path.relpath(path, common.ROOT), {}


READ_ONLY_STARTS = ("select", "with", "explain", "show", "table", "values")


@tool("query", "Run read-only SQL against the database (SELECT/WITH only,"
      " one statement, first 200 rows). Every table is documented in"
      " docs/data-dictionary.md.",
      {"sql": {"type": "string", "description": "the statement"}}, ["sql"])
def query(ctx, sql):
    body = sql.strip().rstrip(";").strip()
    if ";" in body or not body.lower().startswith(READ_ONLY_STARTS):
        raise ToolError("query is read-only: one SELECT/WITH statement")
    with ctx.connect() as cx:
        cx.execute("SET TRANSACTION READ ONLY")
        cursor = cx.execute(body)
        columns = [d.name for d in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(200)
        cx.rollback()
    out = [[_plain(v) for v in row] for row in rows]
    text = "\t".join(columns) + "\n" + "\n".join(
        "\t".join(str(v) for v in row) for row in out) if columns else "(no rows)"
    return text, {"columns": columns, "rows": out, "truncated": len(rows) == 200}


def _plain(value):
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return str(value)


# --- the board: user layer and inference layer through the same door -------

BOARD = {
    "map": {"type": "string", "description": "map name (any spelling)"},
    "red": {"type": "array", "items": {"type": "string"},
            "description": "the enemy team's revealed heroes"},
    "blue": {"type": "array", "items": {"type": "string"},
             "description": "your team's locked heroes"},
    "bans": {"type": "array", "items": {"type": "string"},
             "description": "the match's bans, up to five (each team's two and"
                            " the lobby's), all optional; neither team can"
                            " pick them"},
    "side": {"type": "string", "enum": ["attack", "defense", ""],
             "description": "blue's side on an Escort or Hybrid map (red gets"
                            " the other); ignored on Control, Push, Flashpoint"},
}


@tool("roster", "Every hero with role, subrole, health pool and portrait,"
      " plus the map pool with modes - the vocabulary the board tools accept.")
def roster(ctx):
    from user.facts import model
    with ctx.connect() as cx:
        world = model.load(cx)
    heroes = [{"name": h.name, "role": h.role, "subrole": h.subrole,
               "pool": h.pool, "portrait": h.portrait}
              for h in world.heroes_by_role()]
    maps = [{"name": m.name, "mode": m.mode} for m in world.maps_sorted()]
    text = "\n".join("%-9s %-14s %s" % (h["role"], h["subrole"], h["name"])
                     for h in heroes) + "\n\nmaps: " + ", ".join(
        "%s (%s)" % (m["name"], m["mode"]) for m in maps)
    return text, {"heroes": heroes, "maps": maps}


@tool("facts", "The USER LAYER: every fact the database holds about a board -"
      " independent facts per named hero and for the map, joint facts per"
      " team once it has picks (shape, effective HP, damage and healing"
      " floors, range, tempo, cohesion, coverage...), and matchup facts"
      " once both teams have picks. Numbered F1.. for citation.",
      dict(BOARD, format={"type": "string", "enum": ["lines", "json"],
                          "description": "lines (default) or json"}))
def facts_tool(ctx, map=None, red=(), blue=(), bans=(), side="", format="lines"):
    from user.facts import engine, model
    with ctx.connect() as cx:
        world = model.load(cx)
    try:
        fs = engine.generate(world, map, list(red), list(blue), list(bans), side)
    except ValueError as error:
        raise ToolError(str(error))
    payload = fs.to_dict()
    text = fs.rendered() if format == "lines" else json.dumps(payload)
    return text, payload


@tool("infer", "The INFERENCE LAYER: the optimal six for this board under"
      " the markdown heuristics in inference/heuristics/ (players assumed"
      " to play optimally). Locked blue picks are kept; the rest is"
      " searched. Returns the comp, per-pick reasons with fact citations,"
      " the heuristic score breakdown, and alternatives.",
      dict(BOARD, top={"type": "integer", "description": "alternatives to"
                                                         " return (default 5)"},
           pool={"type": "integer", "description": "candidates per role the"
                                                   " search keeps (default 6)"}))
def infer_tool(ctx, map=None, red=(), blue=(), bans=(), side="", top=5, pool=6):
    from user.facts import model
    from inference import engine
    with ctx.connect() as cx:
        world = model.load(cx)
    try:
        result = engine.infer(world, map, list(red), list(blue), top=top,
                              pool_size=pool, bans=list(bans), side=side)
    except ValueError as error:
        raise ToolError(str(error))
    return result.rendered(), result.to_dict()


@tool("evaluate", "Score a FULL blue six against the heuristics without"
      " searching: the breakdown per heuristic, constraint violations, and"
      " how it ranks against the optimum.", BOARD, ["blue"])
def evaluate_tool(ctx, map=None, red=(), blue=(), bans=(), side=""):
    from user.facts import model
    from inference import engine
    with ctx.connect() as cx:
        world = model.load(cx)
    try:
        result = engine.evaluate(world, map, list(red), list(blue), bans=list(bans),
                                 side=side)
    except ValueError as error:
        raise ToolError(str(error))
    return result.rendered(), result.to_dict()


@tool("board", "Both seats at once, on opposite sides of a sided map: blue's"
      " optimal six around the locked picks, red's optimal six around the"
      " revealed picks, and blue's current picks scored as they stand"
      " (ranked when six are locked, flagged partial otherwise).",
      dict(BOARD, pool={"type": "integer", "description": "candidates per role the"
                                                          " search keeps (default 6)"}))
def board_tool(ctx, map=None, red=(), blue=(), bans=(), side="", pool=6):
    from user.facts import model
    from inference import engine
    with ctx.connect() as cx:
        world = model.load(cx)
    try:
        b = engine.board(world, map, list(red), list(blue), list(bans), side,
                         pool_size=pool)
    except ValueError as error:
        raise ToolError(str(error))
    return engine.board_rendered(b), engine.board_dict(b)


@tool("heuristics", "The inference layer's catalog: every markdown heuristic"
      " with its kind, metric, direction, weight and expressions.")
def heuristics_tool(ctx):
    from inference import catalog
    cat = catalog.load()
    return catalog.render(cat), {"heuristics": [h.to_dict() for h in cat]}


@tool("record", "Persist a decided composition into the INFERENCE tables"
      " and a markdown transcript, under the storage gates: exactly six"
      " real heroes, each citing fact ids (F#) the board actually showed.",
      dict(BOARD, question={"type": "string"},
           model={"type": "string", "description": "who decided (default"
                                                   " claude-code-session)"},
           answer={"type": "object", "description":
                   "{playstyle, reasoning, picks: [{hero, why, evidence: [F#]}]}"}),
      ["question", "answer"])
def record_tool(ctx, question, answer, map=None, red=(), blue=(), bans=(), side="",
                model="claude-code-session"):
    from inference import record
    try:
        with ctx.connect() as cx:
            rec_id, path = record.record(cx, question, answer, map, list(red),
                                         list(blue), model, list(bans), side)
    except ValueError as error:
        raise ToolError(str(error))
    return ("recorded as recommendation %d; transcript %s"
            % (rec_id, os.path.relpath(path, common.ROOT)),
            {"rec_id": rec_id, "transcript": path})


class HeuristicResources:
    """The heuristics files, readable as MCP resources."""

    def list(self):
        from inference import catalog
        return [{"uri": "heuristic://" + h.id, "name": h.name,
                 "description": "%s (%s)" % (h.kind, h.category),
                 "mimeType": "text/markdown"} for h in catalog.load()]

    def read(self, uri):
        from inference import catalog
        hid = uri.replace("heuristic://", "", 1)
        for h in catalog.load():
            if h.id == hid:
                return {"uri": uri, "mimeType": "text/markdown", "text": h.raw}
        raise KeyError(uri)
