"""The data layer's own tools: pull, clean, store, one tool per source and
domain, then the strategies mirror and the whole sync.

Every pull_* tool is pull -> clean -> store for one source and domain: that
domain's run() in its source package under db/data/, handed a PullContext
over the source's page cache. The pulls are registered in dependency order,
and sync_all runs them in it. A session, the refresher or a shell
(`.venv/bin/python -m door.mcp call`) decides what to pull and when, and reads
the summary back.
"""

import functools
import os
import time
from collections.abc import Callable, Mapping
from typing import TypedDict

import psycopg

from db.data import PullSummary, fetch
from db.data.blizzard import BLIZZARD
from db.data.blizzard import heroes as blizzard_heroes
from db.data.blizzard import meta as blizzard_meta
from db.data.wiki import WIKI
from db.data.wiki import heroes as wiki_heroes
from db.data.wiki import maps as wiki_maps
from db.data.wiki import matchups as wiki_matchups
from db.data.wiki import patches as wiki_patches
from db.data.wiki import playstyles as wiki_playstyles
from db.data.wiki import seasons as wiki_seasons
from db.data.wiki import synergies as wiki_synergies
from db.data.wiki import terrain as wiki_terrain
from door.mcp.registry import REFRESH, Context, tool
from door.mcp.schema import Properties, ToolReply
from inference import catalog, derive

# A pull's own function: the source module's run(connection, pull, **options).
type PullFn = Callable[..., PullSummary]


def _summary(name: str, stored: str, summary: PullSummary) -> ToolReply:
    """A pull's reply: its headline - "<name>: <stored>", or "<name>: nothing
    stored" when it wrote no table, ending in the count of pages read from
    the stale cache when there are any - over one line per count (the tables
    it wrote left out), and the summary itself as the payload."""
    stale = summary.get("stale")
    headline = "%s: %s" % (name, stored if summary["tables"] else "nothing stored")
    lines = [headline + ("; stale: %d" % len(stale) if stale else "")]
    for key, value in summary.items():
        if key == "tables":
            continue
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value) or "-"
        lines.append("  %-16s %s" % (key, value))
    return ToolReply("\n".join(lines), dict(summary))


class SourceRow(TypedDict):
    """A source as list_sources reports it: its code, name and address, the
    pages its cache holds and the pulls that read it."""
    code: str
    name: str
    url: str
    cached_pages: int
    tools: list[str]


@tool(
    "list_sources", "The sources the data layer pulls from, what each"
    " supplies, and how many pages its cache holds.")
def list_sources(ctx: Context) -> ToolReply:
    rows: list[SourceRow] = []
    for source in (BLIZZARD, WIKI):
        path = ctx.caches[source.code]
        cached = len(os.listdir(path)) if os.path.isdir(path) else 0
        rows.append(SourceRow(
            code=source.code, name=source.name, url=source.url, cached_pages=cached,
            tools=[s.name for s in ctx.tools.pulls() if s.source == source.code]))
    text = "\n".join("%-12s %-24s %4d cached pages  tools: %s" % (
        r["code"], r["name"], r["cached_pages"], ", ".join(r["tools"])) for r in rows)
    return ToolReply(text, {"sources": rows})


def _pull(ctx: Context, source: str, fn: PullFn, refresh: bool, **options: bool) -> PullSummary:
    """One pull against the database, reading through the source's page cache
    and logging to the context's log -> the summary its run() returns, with
    the pages it read from the stale cache under stale."""
    # refresh: every page cached before the refresh began is fetched again -
    # before sync_all's start under it (ctx.cutoff), else before this pull's
    # - and a page written since is read. The cached copy survives a failed
    # fetch and is listed (see fetch.cached)
    cutoff = (time.time() if ctx.cutoff is None else ctx.cutoff) if refresh else None
    pull = fetch.PullContext(ctx.cache(source), log=ctx.log, cutoff=cutoff)
    with ctx.connect() as cx:
        summary = fn(cx, pull, **options)
    summary["stale"] = pull.stale
    return summary


def _pull_call(
        name: str, stored: str, source: str, fn: PullFn, ctx: Context, /,
        refresh: bool = False, **options: bool) -> ToolReply:
    """A pull tool's call: the pull, and its summary under its headline."""
    return _summary(name, stored, _pull(ctx, source, fn, refresh, **options))


def pull_tool(
        name: str, description: str, *, source: str, stored: str,
        properties: Properties = REFRESH) -> Callable[[PullFn], PullFn]:
    """The decorator that registers a pull as a tool: the tool runs the
    function against `source`'s page cache, refreshing every page when asked,
    and replies under the headline "<name>: <stored>", or "<name>: nothing
    stored" when the pull wrote no table. The call wears the function's name
    and module, which is its family; the function is returned as it is."""
    def decorate(fn: PullFn) -> PullFn:
        call = functools.partial(_pull_call, name, stored, source, fn)
        tool(name, description, properties, source=source)(functools.update_wrapper(call, fn))
        return fn
    return decorate


# Registration order is dependency order, and sync_all runs the pulls in it:
# heroes before what links to them, maps and their stages before the terrain
# counted for them, seasons and patches before the pull that stamps a
# snapshot (rates). Each body looks its module's run up when it is called, so
# a test that replaces the run replaces the pull's.

@pull_tool(
    "pull_heroes", "Blizzard's roster: heroes, roles, subroles, portraits,"
    " ability and perk text. Run first - everything links to heroes.",
    source="blizzard", stored="roster stored")
def pull_heroes(connection: psycopg.Connection, pull: fetch.PullContext) -> PullSummary:
    return blizzard_heroes.run(connection, pull)


@pull_tool(
    "pull_kits", "The wiki's Cargo ability table and hero articles: weapons"
    " and firing configs, every published number, ability kinds and"
    " keywords, hero health pools. Run after pull_heroes.",
    source="wiki", stored="kit numbers stored",
    properties=dict(REFRESH, supplement={
        "type": "boolean",
        "description": "also read each hero article for the flags Cargo lacks"
                       " (default true)"}))
def pull_kits(
        connection: psycopg.Connection, pull: fetch.PullContext,
        supplement: bool = True) -> PullSummary:
    return wiki_heroes.run(connection, pull, supplement=supplement)


@pull_tool(
    "pull_maps", "The wiki's map pool: maps, game modes, playable"
    " combinations, and each map's stages: a Control map's three, a Flashpoint"
    " map's five points, a Hybrid map's two phases, an Escort map's stretches"
    " where its article names them. Push maps have none.",
    source="wiki", stored="map pool stored")
def pull_maps(connection: psycopg.Connection, pull: fetch.PullContext) -> PullSummary:
    return wiki_maps.run(connection, pull)


@pull_tool(
    "pull_terrain", "The wiki's map articles: per map, the mentions of each"
    " terrain feature (chokes, interiors, high_ground, flanks, sightlines,"
    " open_ground, hazards, cover) and the mentions per thousand words; the"
    " same per stage, where the article has text about the stage. Reloads"
    " map_terrain and stage_terrain whole. Run after pull_maps: a stage must"
    " exist before its terrain.", source="wiki", stored="terrain stored")
def pull_terrain(connection: psycopg.Connection, pull: fetch.PullContext) -> PullSummary:
    return wiki_terrain.run(connection, pull)


@pull_tool(
    "pull_patches", "The wiki's patch list, so every rates snapshot can say"
    " which game version it measured.", source="wiki", stored="patches stored")
def pull_patches(connection: psycopg.Connection, pull: fetch.PullContext) -> PullSummary:
    return wiki_patches.run(connection, pull)


@pull_tool(
    "pull_seasons", "The wiki's Season pages: every season that has started,"
    " with its start date. Restamps every rates snapshot with its season. Run"
    " before pull_rates.", source="wiki", stored="seasons stored")
def pull_seasons(connection: psycopg.Connection, pull: fetch.PullContext) -> PullSummary:
    return wiki_seasons.run(connection, pull)


@pull_tool(
    "pull_rates", "Blizzard's win/pick/ban rates as a NEW dated snapshot,"
    " by rank tier and by map (Competitive Role Queue - the page offers no"
    " Open Queue - console, Americas). Slow when uncached: ~40 pages, 5s apart.",
    source="blizzard", stored="snapshot stored")
def pull_rates(connection: psycopg.Connection, pull: fetch.PullContext) -> PullSummary:
    return blizzard_meta.run(connection, pull)


@pull_tool(
    "pull_playstyles", "The wiki's team-composition page: which playstyle"
    " (dive, brawl, poke) each hero belongs to.", source="wiki", stored="styles stored")
def pull_playstyles(connection: psycopg.Connection, pull: fetch.PullContext) -> PullSummary:
    return wiki_playstyles.run(connection, pull)


@pull_tool(
    "pull_synergies", "The Synergy section of every hero's wiki article: one"
    " row per pair, score 2 when both articles name each other, 1 when one"
    " does, the wiki's advice as the note. Run after pull_heroes.",
    source="wiki", stored="pairs stored")
def pull_synergies(connection: psycopg.Connection, pull: fetch.PullContext) -> PullSummary:
    return wiki_synergies.run(connection, pull)


@pull_tool(
    "pull_counters", "The Match-Up column of every hero's wiki article: each"
    " written cell read as a verdict and stored as a directed edge, one row ="
    " countered_by answers hero. Reloads the table whole. Run after"
    " pull_heroes.", source="wiki", stored="counters stored")
def pull_counters(connection: psycopg.Connection, pull: fetch.PullContext) -> PullSummary:
    return wiki_matchups.run(connection, pull)


@tool(
    "load_authored", "Store the one input a user writes: the mirror of the"
    " strategies in inference/strategies/. A whole-truth reload; where the"
    " claude CLI is present, it first completes pending drafts as"
    " derive_strategies does, writing their files and the tuning log.")
def load_authored(ctx: Context) -> ToolReply:
    with ctx.connect() as cx:
        cat = catalog.load()
        if any(h.pending for h in cat) and derive.available():
            # drafts on a host with the CLI: the engine derives them now
            ctx.log(derive.derive_rendered(derive.derive(log=ctx.log)))
            cat = catalog.load()
        summary = catalog.mirror(cx, cat)
        pending = [h.id for h in cat if h.pending]
        if pending:
            summary["pending"] = len(pending)
    text = "load_authored: strategies " + ", ".join(
        "%s=%s" % (k, v) for k, v in summary.items() if k != "tables")
    # the payload still names what was loaded, so a caller reads it the same way
    return ToolReply(text, {"strategies": summary})


@tool(
    "sync_all", "Every pull_* tool in dependency order, then the strategies"
    " mirror, then the CSV mirror. On a populated database this is an"
    " update: entities refresh in place, rates append a snapshot.", REFRESH)
def sync_all(ctx: Context, refresh: bool = False) -> ToolReply:
    results: dict[str, Mapping[str, object]] = {}
    pulls = ctx.tools.pulls()
    # one cutoff for every pull: the hero articles pull_kits, pull_synergies
    # and pull_counters read, and the map articles pull_maps and pull_terrain
    # read, are fetched by the first and read from the cache by the rest
    run = ctx.refreshing() if refresh else ctx
    for spec in pulls:
        ctx.log("=== %s ===" % spec.name)
        results[spec.name] = run.call(spec.name, refresh=refresh).data
    ctx.log("=== load_authored ===")
    results["load_authored"] = ctx.call("load_authored").data
    results["export_csv"] = ctx.call("export_csv").data
    stale = [spec.name for spec in pulls if results[spec.name].get("stale")]
    text = "sync_all: %d pulls + strategies mirror + export done" % len(pulls)
    if stale:
        text += "; stale: %s" % ", ".join(stale)
    return ToolReply(text, results)
