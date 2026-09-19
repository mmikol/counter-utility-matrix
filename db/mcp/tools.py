"""The tools the data layer serves, and - through the same door - the board
tools of the UI and inference layers.

Every pull_* tool is pull -> clean -> store for one source and domain: that
domain's run() in its source package under db/data/. `sync_all` runs them in
dependency order. A session, the refresher or a shell (`python -m db.mcp
call`) decides what to pull and when, and reads the summary back.
"""

import json
import os
import re
import sys

import psycopg

from db import CACHE_DIRS, ROOT, psql
from db.data import fetch
from db.mcp.server import Tool, ToolError


class Context:
    """Where a tool call lands: the database and the page caches."""

    def __init__(self, dsn=None, caches=None, log=None):
        self._dsn = dsn
        self.caches = dict(CACHE_DIRS, **(caches or {}))
        self.log = log or (lambda msg: sys.stderr.write(msg + "\n"))

    @property
    def dsn(self):
        if self._dsn is None:
            self._dsn = psql.default_dsn()
        return self._dsn

    def connect(self):
        return psycopg.connect(self.dsn)

    def cache(self, source):
        return fetch.prepare_cache(self.caches[source])


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


def run_tool(ctx, name, /, **arguments):
    """Call a registered tool by name, in-process (the refresher's and the shell's
    path). The tool's name is positional only, so a tool argument called `name`
    (add_strategy has one) reaches the tool instead of colliding here."""
    for tool_name, _, _schema, fn in REGISTRY:
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
    from db.data.blizzard import BLIZZARD
    from db.data.counterpick import COUNTERPICK
    from db.data.wiki import WIKI
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
    # cached copy survives a failed fetch (see db.data.fetch.keep_stale)
    fetch.set_max_age(0 if refresh else None)
    try:
        with ctx.connect() as cx:
            summary = module.run(cx, cache, log=ctx.log, **options)
    finally:
        fetch.set_max_age(None)
    return summary


@tool("pull_heroes", "Blizzard's roster: heroes, roles, subroles, portraits,"
      " ability and perk text. Run first - everything links to heroes.",
      REFRESH)
def pull_heroes(ctx, refresh=False):
    return _summary("pull_heroes: roster stored", _pull(
        ctx, "blizzard", "db.data.blizzard.heroes", refresh))


@tool("pull_kits", "The wiki's Cargo ability table and hero articles: weapons"
      " and firing configs, every published number, ability kinds and"
      " keywords, hero health pools. Run after pull_heroes.",
      dict(REFRESH, supplement={"type": "boolean",
                                "description": "also read each hero article"
                                               " for the flags Cargo lacks"
                                               " (default true)"}))
def pull_kits(ctx, refresh=False, supplement=True):
    return _summary("pull_kits: kit numbers stored", _pull(
        ctx, "wiki", "db.data.wiki.heroes", refresh,
        supplement=supplement))


@tool("pull_maps", "The wiki's map pool: maps, game modes, playable"
      " combinations, and the stages of Control and Flashpoint maps.",
      REFRESH)
def pull_maps(ctx, refresh=False):
    return _summary("pull_maps: map pool stored", _pull(
        ctx, "wiki", "db.data.wiki.maps", refresh))


@tool("pull_patches", "The wiki's patch list, so every rates snapshot can say"
      " which game version it measured.", REFRESH)
def pull_patches(ctx, refresh=False):
    return _summary("pull_patches: patches stored", _pull(
        ctx, "wiki", "db.data.wiki.patches", refresh))


@tool("pull_rates", "Blizzard's win/pick/ban rates as a NEW dated snapshot,"
      " by rank tier and by map (Competitive Role Queue - the page offers no"
      " Open Queue - console, Americas). Slow when uncached: ~40 pages, 5s apart.",
      REFRESH)
def pull_rates(ctx, refresh=False):
    return _summary("pull_rates: snapshot stored", _pull(
        ctx, "blizzard", "db.data.blizzard.meta", refresh))


@tool("pull_playstyles", "The wiki's team-composition page: which playstyle"
      " (dive, brawl, poke) each hero belongs to.", REFRESH)
def pull_playstyles(ctx, refresh=False):
    return _summary("pull_playstyles: styles stored", _pull(
        ctx, "wiki", "db.data.wiki.playstyles", refresh))


@tool("pull_counters", "counterpick.gg: who answers whom, each hero's best"
      " maps, and its own rates under a separate snapshot.", REFRESH)
def pull_counters(ctx, refresh=False):
    return _summary("pull_counters: counters stored", _pull(
        ctx, "counterpick", "db.data.counterpick.heroes", refresh))


PULLS = [("pull_heroes", "blizzard"), ("pull_kits", "wiki"),
         ("pull_maps", "wiki"), ("pull_patches", "wiki"),
         ("pull_rates", "blizzard"), ("pull_playstyles", "wiki"),
         ("pull_counters", "counterpick")]

AUTHORED_INPUTS = ("seasons", "synergies", "archetypes", "map_playstyle", "strategies")


@tool("load_authored", "Store the inputs we write instead of fetch: seasons,"
      " synergies, comp archetypes, map playstyles, and the mirror of the"
      " strategies catalog. Whole-truth reloads.",
      {"only": {"type": "array", "items": {"type": "string",
                                            "enum": list(AUTHORED_INPUTS)},
                "description": "a subset to reload (default: all)"}})
def load_authored(ctx, only=None):
    from db.data import authored
    selected = [p for p in AUTHORED_INPUTS if not only or p in only]
    summaries = {}
    with ctx.connect() as cx:
        for name in selected:
            if name == "strategies":
                from inference import catalog, derive
                cat = catalog.load()
                if any(h.pending for h in cat) and derive.available():
                    # drafts on a host with the CLI: the engine derives them now
                    ctx.log(derive.rendered(derive.derive(log=ctx.log)))
                    cat = catalog.load()
                summaries[name] = catalog.mirror(cx, cat)
                pending = [h.id for h in cat if h.pending]
                if pending:
                    summaries[name]["pending"] = len(pending)
            else:
                summaries[name] = authored.LOADERS[name](cx, log=ctx.log)
    text = "load_authored: " + "; ".join(
        "%s %s" % (name, ", ".join("%s=%s" % (k, v) for k, v in s.items()
                                    if k != "tables"))
        for name, s in summaries.items())
    return text, summaries


@tool("sync_all", "Every pull_* tool in dependency order, then the authored"
      " inputs, then the CSV mirror. On a populated database this is an"
      " update: entities refresh in place, rates append a snapshot.", REFRESH)
def sync_all(ctx, refresh=False):
    results = {}
    for name, _ in PULLS:
        ctx.log("=== %s ===" % name)
        results[name] = run_tool(ctx, name, refresh=refresh)[1]
    ctx.log("=== load_authored ===")
    results["load_authored"] = run_tool(ctx, "load_authored")[1]
    results["export_csv"] = run_tool(ctx, "export_csv")[1]
    return "sync_all: %d pulls + authored inputs + export done" % len(PULLS), results


# --- the database's life ----------------------------------------------------

@tool("db_status", "Which database the tools are pointed at, its table and"
      " row counts, and the rates snapshots it holds.")
def db_status(ctx):
    from db.psql import schema
    with ctx.connect() as cx:
        tables = schema.table_count(cx)
        counts, snaps = {}, []
        if tables:
            for t in ("heroes", "abilities", "maps", "hero_meta", "map_meta",
                      "counters", "synergies", "strategies"):
                if cx.execute("select to_regclass(%s)", (t,)).fetchone()[0]:
                    counts[t] = cx.execute("select count(*) from " + t).fetchone()[0]
            if "heroes" in counts:
                counts["announced"] = cx.execute(
                    "select count(*) from heroes where status = 'announced'").fetchone()[0]
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
    from db.psql import schema
    with ctx.connect() as cx:
        if schema.table_count(cx):
            raise ToolError("the database already has tables; db_rebuild"
                            " starts over")
        schema.apply(cx, schema.read_migrations(), quiet=True)
        n = schema.table_count(cx)
    return "db_init: %d tables, no data" % n, {"tables": n}


@tool("db_migrate", "Apply the migrations the ledger has not recorded, in"
      " place: a populated database catching up with the files without a"
      " rebuild. Nothing pending is not an error.")
def db_migrate(ctx):
    from db.psql import schema
    with ctx.connect() as cx:
        names = schema.pending(cx)
        todo = [(p, sql) for p, sql in schema.read_migrations()
                if os.path.basename(p) in names]
        schema.apply(cx, todo, quiet=True)
    return ("db_migrate: applied %d migration(s)%s"
            % (len(names), ": " + ", ".join(names) if names else ""), {"applied": names})


@tool("db_rebuild", "Drop everything, reapply the migrations and run"
      " sync_all.", REFRESH)
def db_rebuild(ctx, refresh=False):
    from db.psql import schema
    with ctx.connect() as cx:
        dropped = schema.rebuild(cx, quiet=True)
    results = run_tool(ctx, "sync_all", refresh=refresh)[1]
    return ("db_rebuild: dropped %d tables, rebuilt" % len(dropped),
            {"dropped": len(dropped), "sync": results})


@tool("export_csv", "Refresh db/raw/*.csv: one CSV per table.")
def export_csv(ctx):
    with ctx.connect() as cx:
        counts = psql.export(cx)
    return ("export_csv: %d tables mirrored to db/raw" % len(counts),
            {"tables": dict(counts)})


def write_tool_docs(path=None):
    """The tool reference - every registered tool, its description and its
    arguments - generated into docs/mcp.md between its markers."""
    from db.psql.schema import embed
    path = path or os.path.join(ROOT, "docs", "mcp.md")
    out = ["%d tools, in the order the server lists them. Regenerated by"
           " `python -m db.mcp call db_docs`." % len(REGISTRY), "",
           "| tool | does | arguments |", "| --- | --- | --- |"]
    for name, description, schema, _ in REGISTRY:
        required = set(schema.get("required", ()))
        args = []
        for arg, spec in schema.get("properties", {}).items():
            kind = spec.get("type") or "any"
            if "enum" in spec:
                kind = " \\| ".join(str(v) for v in spec["enum"])
            args.append("`%s`%s (%s)%s" % (arg, " *required*" if arg in required else "",
                                            kind, ": " + spec["description"].replace("|", "\\|")
                                            if spec.get("description") else ""))
        out.append("| `%s` | %s | %s |" % (name, description.replace("|", "\\|"),
                                          "<br>".join(args) if args else "none"))
    embed(path, "tools", "\n".join(out))
    return path


@tool("db_docs", "Regenerate the generated sections of the docs: the ERD and data"
      " dictionary in docs/db.md from the live schema, the catalog and vocabulary in"
      " docs/inference.md from the strategies files, the tool reference in docs/mcp.md.")
def db_docs(ctx):
    from db.psql import schema
    from inference import catalog
    with ctx.connect() as cx:
        text = schema.generate_docs(cx)
    paths = [p for p in (catalog.write_docs(catalog.load()), write_tool_docs()) if p]
    if catalog.STRATEGIES_DIR != catalog.SHIPPED_DIR:
        ctx.log("db_docs: another playbook folder is in force (%s); the catalog section"
                " of docs/inference.md was left as the shipped playbook" % catalog.STRATEGIES_DIR)
    return text + "; wrote " + ", ".join(os.path.relpath(p, ROOT) for p in paths), {}


READ_ONLY_STARTS = ("select", "with", "explain", "show", "table", "values")
# Names that reach the file system or the network from inside SQL, refused
# before the database sees them. The reader role below is the second guard.
SQL_DENIED = re.compile(r"\b(pg_read_file|pg_read_binary_file|pg_ls_dir|pg_stat_file|"
                        r"lo_import|lo_export|lo_get|lo_put|pg_execute_server_program|"
                        r"dblink|pg_sleep|pg_terminate_backend|pg_cancel_backend|"
                        r"set_config|query_to_xml|query_to_xmlschema|query_to_xml_and_xmlschema|"
                        r"cursor_to_xml|cursor_to_xmlschema|pg_reload_conf)\b", re.I)
READER_ROLE = "matrix_reader"          # a login of its own (migration 012): SELECT, nothing else
MAX_QUERY_BYTES = 1 << 20              # what one query may return
MAX_CELL = 2000                        # characters per cell


def reader_dsn(dsn):
    """The same database, connected as the reader: a non-superuser session
    cannot SET ROLE back up."""
    parts = psycopg.conninfo.conninfo_to_dict(dsn)
    parts["user"] = READER_ROLE
    parts["password"] = READER_ROLE
    return psycopg.conninfo.make_conninfo(**parts)


@tool("query", "Run read-only SQL against the database (SELECT/WITH only,"
      " one statement, first 200 rows). Every table is documented in"
      " the data dictionary in docs/db.md.",
      {"sql": {"type": "string", "description": "the statement"}}, ["sql"])
def query(ctx, sql):
    body = sql.strip().rstrip(";").strip()
    if ";" in body or not body.lower().startswith(READ_ONLY_STARTS):
        raise ToolError("query is read-only: one SELECT/WITH statement")
    if len(body) > 20000:
        raise ToolError("query too long")
    denied = SQL_DENIED.search(body)
    if denied:
        raise ToolError("query refuses %r: SQL here reads tables, not files or servers"
                        % denied.group(1))
    with psycopg.connect(reader_dsn(ctx.dsn)) as cx:
        cx.execute("SET TRANSACTION READ ONLY")
        cx.execute("SET LOCAL statement_timeout = '10s'")
        cursor = cx.execute(body)
        columns = [d.name for d in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(200)
        cx.rollback()
    out, size = [], 0
    for row in rows:
        cells = []
        for v in row:
            v = _plain(v)
            if isinstance(v, str) and len(v) > MAX_CELL:
                v = v[:MAX_CELL] + "…"
            cells.append(v)
            size += len(str(v))
        if size > MAX_QUERY_BYTES:
            break
        out.append(cells)
    text = "\t".join(columns) + "\n" + "\n".join(
        "\t".join(str(v) for v in row) for row in out) if columns else "(no rows)"
    return text, {"columns": columns, "rows": out, "truncated": len(rows) == 200}


def _plain(value):
    """A cell as JSON carries it: dates and times as ISO text, the rest as is."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return str(value)


# --- the board: UI layer and inference layer through the same door -------

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


@tool("roster", "Every hero with role, subrole, health pool, portrait and status"
      " (released, or announced with its release day - shown, never picked), plus"
      " the map pool with modes - the vocabulary the board tools accept.")
def roster(ctx):
    from ui.facts import model
    with ctx.connect() as cx:
        world = model.load(cx)
    heroes = [{"name": h.name, "role": h.role, "subrole": h.subrole,
               "pool": h.pool, "portrait": h.portrait, "status": h.status,
               "release_date": str(h.release_date) if h.release_date else None}
              for h in world.heroes_by_role()]
    maps = [{"name": m.name, "mode": m.mode} for m in world.maps_sorted()]
    text = "\n".join("%-9s %-14s %s%s" % (h["role"], h["subrole"], h["name"],
                                          "" if h["status"] == "released" else
                                          "  (announced%s)" % (", releases " + h["release_date"]
                                                               if h["release_date"] else ""))
                     for h in heroes) + "\n\nmaps: " + ", ".join(
        "%s (%s)" % (m["name"], m["mode"]) for m in maps)
    return text, {"heroes": heroes, "maps": maps}


@tool("facts", "The UI LAYER: every fact the database holds about a board -"
      " independent facts per named hero and for the map, joint facts per"
      " team once it has picks (shape, effective HP, damage and healing"
      " floors, range, tempo, cohesion, coverage...), and matchup facts"
      " once both teams have picks. Numbered F1.. for citation.",
      dict(BOARD, format={"type": "string", "enum": ["lines", "json"],
                          "description": "lines (default) or json"}))
def facts_tool(ctx, map=None, red=(), blue=(), bans=(), side="", format="lines"):
    from ui.facts import engine, model
    with ctx.connect() as cx:
        world = model.load(cx)
    try:
        fs = engine.generate(world, map, list(red), list(blue), list(bans), side)
    except ValueError as error:
        raise ToolError(str(error)) from error
    payload = fs.to_dict()
    text = fs.rendered() if format == "lines" else json.dumps(payload)
    return text, payload


def _clamp(pool, top=5):
    """Bounds on the search: pool 2..12 per role, top 1..20."""
    return max(2, min(int(pool or 6), 12)), max(1, min(int(top or 5), 20))


@tool("infer", "The INFERENCE LAYER: the optimal six for this board under"
      " the markdown strategies in inference/strategies/ (players assumed"
      " to play optimally). Locked blue picks are kept; the rest is"
      " searched. Returns the comp, per-pick reasons with fact citations,"
      " the strategy score breakdown, and alternatives.",
      dict(BOARD, top={"type": "integer", "description": "alternatives to"
                                                         " return (default 5)"},
           pool={"type": "integer", "description": "candidates per role the"
                                                   " search keeps (default 6)"},
           compact={"type": "boolean", "description": "true: the comp, the silent"
                                                      " heuristics (applying, metric"
                                                      " not varying on this board) and"
                                                      " the largest terms only"}))
def infer_tool(ctx, map=None, red=(), blue=(), bans=(), side="", top=5, pool=6,
               compact=False):
    pool, top = _clamp(pool, top)
    from inference import engine
    from ui.facts import model
    with ctx.connect() as cx:
        world = model.load(cx)
    try:
        result = engine.infer(world, map, list(red), list(blue), top=top,
                              pool_size=pool, bans=list(bans), side=side)
    except ValueError as error:
        raise ToolError(str(error)) from error
    if compact:
        return _compact(result)
    return result.rendered(), result.to_dict()


COMPACT_TERMS = 15


def _compact(result):
    """A result small enough for a tool reply under a playbook of hundreds:
    the comp, the heuristics that apply but whose metric does not vary on this
    board, and the largest terms."""
    full = result.to_dict()
    terms = full["contributions"]
    silent = sorted(c["id"] for c in terms
                    if c["kind"] == "heuristic" and c["applies"] and not c["spread"])
    idle = sum(1 for c in terms if not c["applies"])
    largest = sorted((c for c in terms if c["weighted"]),
                     key=lambda c: (-abs(c["weighted"]), c["id"]))[:COMPACT_TERMS]
    payload = {"map": result.map_name, "side": result.side, "red": list(result.red),
               "blue": list(result.blue), "score": full["score"],
               "strategies": len(terms), "idle": idle, "silent": silent,
               "largest": [{"id": c["id"], "weighted": round(c["weighted"], 4)}
                           for c in largest]}
    lines = result.rendered().split("\n")[:2]
    lines.append("  %d strategies, %d not applying here" % (len(terms), idle))
    lines.append("  silent (applies, metric does not vary here): %s"
                 % (", ".join(silent) or "none"))
    lines += ["  %+.2f  %s" % (c["weighted"], c["id"]) for c in largest]
    return "\n".join(lines), payload


@tool("evaluate", "Score a FULL blue six against the strategies without"
      " searching: the breakdown per strategy, constraint violations, and"
      " how it ranks against the optimum.", BOARD, ["blue"])
def evaluate_tool(ctx, map=None, red=(), blue=(), bans=(), side=""):
    from inference import engine
    from ui.facts import model
    with ctx.connect() as cx:
        world = model.load(cx)
    try:
        result = engine.evaluate(world, map, list(red), list(blue), bans=list(bans),
                                 side=side)
    except ValueError as error:
        raise ToolError(str(error)) from error
    return result.rendered(), result.to_dict()


@tool("board", "The whole board at any stage of the draft (no map, a map, a side,"
      " bans, red's picks as they reveal): blue's optimal six as the best counter"
      " to red's selection - to their likely six until they reveal a pick"
      " (blue's own picks never constrain it), red's best"
      " counter to yours, both current comps scored on those scales, your picks"
      " against red's best counter, your locked picks with the empty slots filled,"
      " the fight odds (each seat's share of its own optimal, and the two against"
      " each other), the game plan in prose, the shapes the playbook's limits"
      " allow, and red's likely six"
      " from the data alone (a two-two-two from the map's pick rates and the"
      " authored synergies, past the bans; static for the board, no strategy read).",
      dict(BOARD, pool={"type": "integer", "description": "candidates per role the"
                                                          " search keeps (default 6)"},
           weights={"type": "object",
                    "description": "{heuristic id: 0..10} - weights to score this board"
                                   " under instead of the files' (the playbook tab's"
                                   " sliders); the files are untouched"}))
def board_tool(ctx, map=None, red=(), blue=(), bans=(), side="", pool=6, weights=None):
    pool, _ = _clamp(pool)
    from inference import catalog, engine
    from ui.facts import model
    with ctx.connect() as cx:
        world = model.load(cx)
    try:
        b = engine.board(world, map, list(red), list(blue), list(bans), side,
                         pool_size=pool, weights=catalog.parse_weights(weights or {}))
    except ValueError as error:
        raise ToolError(str(error)) from error
    return engine.board_rendered(b), engine.board_dict(b)


@tool("strategies", "The inference layer's catalog - STRATEGIES = CONSTRAINTS ∪ HEURISTICS"
      " ∪ ASSUMPTIONS: every markdown strategy with its kind (constraint, heuristic or"
      " assumption), a constraint's form (limit, scored, draft), metric, direction, weight"
      " and expressions.")
def strategies_tool(ctx):
    from inference import catalog
    cat = catalog.load()
    pending = [h.id for h in cat if h.pending]
    text = catalog.render(cat)
    if catalog.STRATEGIES_DIR != catalog.SHIPPED_DIR:
        text = "playbook in force: %s (the shipped one is %s)\n\n%s" % (
            os.path.relpath(catalog.STRATEGIES_DIR, ROOT),
            os.path.relpath(catalog.SHIPPED_DIR, ROOT), text)
    if pending:
        text += "\n\n%d draft(s) awaiting /strategy: %s" % (len(pending), ", ".join(pending))
    return text, {"strategies": [h.to_dict() for h in cat], "pending": pending}


@tool("tune", "Change one strategy's frontmatter - its weight, a params dial, or"
      " a when/require/bonus/penalty expression - validated through the"
      " catalog before it is written, mirrored into the database, and logged"
      " with the reason in inference/strategies/tuning-log.md.",
      {"id": {"type": "string", "description": "the strategy's id (its filename)"},
       "field": {"type": "string", "description": "weight | direction | soft | when |"
                                                  " require | bonus | penalty | metric |"
                                                  " params.NAME"},
       "value": {"description": "the new value: a number, a boolean, or an expression"},
       "reason": {"type": "string", "description": "why, in a sentence"},
       "by": {"type": "string", "description": "who asked, for the log line (default"
                                              " claude-code-session; the board says so)"}},
      ["id", "field", "value", "reason"])
def tune_tool(ctx, id, field, value, reason, by="claude-code-session"):
    from inference import catalog, tune
    try:
        change = tune.tune(id, field, value, reason, by=str(by or "claude-code-session")[:40])
        with ctx.connect() as cx:
            catalog.mirror(cx, catalog.load())
    except (tune.TuneError, ValueError) as error:
        raise ToolError(str(error)) from error
    return "tuned %s: %s %s -> %s\n%s" % (change["id"], change["field"], change["old"],
                                         change["new"], change["line"]), change


@tool("metrics", "The vocabulary a strategy may reference: every metric key with its"
      " meaning - team.*, enemy.* (the same for the red side), matchup.*, map.*,"
      " world.* - and which are text. What /strategy reads to infer a heuristic's"
      " metric or a constraint's expression from prose.")
def metrics_tool(ctx):
    from ui.facts import compute
    reg = compute.registry()
    numeric = {k: v for k, v in reg.items() if k not in compute.TEXT_METRICS}
    lines = ["%-32s %s%s" % (k, v, "  (text)" if k in compute.TEXT_METRICS else "")
             for k, v in reg.items() if not k.startswith("enemy.")]
    return "\n".join(lines), {"metrics": reg, "numeric": sorted(numeric),
                              "text": sorted(compute.TEXT_METRICS)}


STRATEGY_FIELDS = {
    "metric": {"type": "string", "description": "heuristics: a numeric key from `metrics`"},
    "direction": {"type": "string", "enum": ["maximize", "minimize"]},
    "weight": {"type": "number", "description": "0..10; 1-4 is the working range"},
    "when": {"type": "string", "description": "a guard expression; optional"},
    "require": {"type": "string", "description": "constraints: a limit expression"},
    "soft": {"type": "boolean",
             "description": "with require: charge `penalty` instead of discarding"},
    "bonus": {"type": "string",
              "description": "constraints: an expression added while `when` holds"},
    "penalty": {"type": "string",
                "description": "constraints: an expression (or a number with soft) subtracted"},
    "params": {"type": "object",
               "description": "NAME: number dials the expressions read as params.NAME"},
    "category": {"type": "string"},
}


@tool("add_strategy", "Store a new strategy in inference/strategies/ from its name,"
      " kind and prose plus the frontmatter /strategy inferred - a heuristic's"
      " metric/direction/weight, or a constraint's require or when/bonus/penalty"
      " and params; an assumption is prose and needs nothing. The prose is three"
      " sentences at most. Validated through the"
      " catalog before the file exists, mirrored into the database, logged."
      " Left with nothing inferred it lands as a draft the solver ignores.",
      dict({"id": {"type": "string", "description": "lowercase-kebab, becomes the filename"},
            "name": {"type": "string"},
            "kind": {"type": "string", "enum": ["constraint", "heuristic", "assumption"]},
            "body": {"type": "string", "description": "the prose: what it means and why"},
            "reason": {"type": "string", "description": "why it was added, in a sentence"}},
           **STRATEGY_FIELDS),
      ["id", "name", "kind", "body"])
def add_strategy(ctx, id, name, kind, body, reason="", **fields):
    from inference import catalog, tune
    try:
        category = fields.pop("category", "general")
        fields.pop("kind", None)
        added = tune.add(id, name, kind, body, fields, reason, category=category)
        with ctx.connect() as cx:
            catalog.mirror(cx, catalog.load())
    except (tune.TuneError, ValueError) as error:
        raise ToolError(str(error)) from error
    note = ("\nstored as a DRAFT: the solver ignores it until /strategy infers its frontmatter"
            if added["form"] == "draft" else "")
    return "added %s as %s/%s -> %s\n%s%s" % (
        id, kind, added["form"], os.path.relpath(added["path"], ROOT), added["line"], note), added


@tool("infer_strategy", "Complete a draft (or rewrite a strategy's scoring): set several"
      " frontmatter fields at once - metric/direction/weight, when/require/bonus/"
      "penalty, params - validated as a whole, mirrored, logged as one line.",
      dict({"id": {"type": "string"},
            "reason": {"type": "string", "description": "how the fields follow from the prose"}},
           **STRATEGY_FIELDS),
      ["id", "reason"])
def infer_strategy(ctx, id, reason, **fields):
    from inference import catalog, tune
    try:
        done = tune.complete(id, fields, reason)
        with ctx.connect() as cx:
            catalog.mirror(cx, catalog.load())
    except (tune.TuneError, ValueError) as error:
        raise ToolError(str(error)) from error
    return "%s is now %s: %s\n%s" % (id, done["form"], ", ".join(
        "%s=%s" % kv for kv in done["set"].items()), done["line"]), done


@tool("derive_strategies", "Complete every draft (a strategy with only a name, a kind"
      " and prose) by asking Claude Code in print mode - the subscription, no key -"
      " for the frontmatter, validated through the catalog and logged. Runs where"
      " the claude CLI is signed in (the host); elsewhere drafts stay pending.",
      {"ids": {"type": "array", "items": {"type": "string"},
               "description": "which drafts (default: all)"}})
def derive_strategies(ctx, ids=None):
    from inference import catalog, derive
    result = derive.derive(ids, log=ctx.log)
    if result["derived"]:
        with ctx.connect() as cx:
            catalog.mirror(cx, catalog.load())
    return derive.rendered(result), result


@tool("tuning_log", "The audit trail of every change to the strategies'"
      " frontmatter, newest last.",
      {"lines": {"type": "integer", "description": "how many (default 20)"}})
def tuning_log_tool(ctx, lines=20):
    from inference import tune
    tail = tune.log_tail(lines)
    return "\n".join(tail) or "no tuning yet", {"lines": tail}


class StrategyResources:
    """The strategies files (and the tuning log), readable as MCP resources."""

    def list(self):
        from inference import catalog
        out = [{"uri": "strategy://" + h.id, "name": h.name,
                "description": "%s (%s)" % (h.kind, h.category),
                "mimeType": "text/markdown"} for h in catalog.load()]
        out.append({"uri": "strategy://tuning-log", "name": "tuning log",
                    "description": "every change to the strategies, with reasons",
                    "mimeType": "text/markdown"})
        return out

    def read(self, uri):
        from inference import catalog, tune
        hid = uri.replace("strategy://", "", 1)
        if hid == "tuning-log":
            return {"uri": uri, "mimeType": "text/markdown",
                    "text": "\n".join(tune.log_tail(1000)) or "no tuning yet"}
        for h in catalog.load():
            if h.id == hid:
                return {"uri": uri, "mimeType": "text/markdown", "text": h.raw}
        raise KeyError(uri)
