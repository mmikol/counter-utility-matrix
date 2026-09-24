"""The sources: one package per source, each owning the whole path from
page to table, plus what they share.

    blizzard/     the official site: heroes (roster, roles, portraits,
                  text), meta (rates as dated snapshots)
    wiki/         the MediaWiki endpoint: heroes (kits, numbers, keywords),
                  maps, terrain, patches, seasons, playstyles, synergies,
                  matchups (counters) - the markup reader they share, and
                  kits/, the heroes pull's kit pipeline
    authored/     the source row of the one input a user writes, the
                  strategies in inference/strategies/
    fetch         the page cache, its freshness and the request loop
    names         matching hero, map and ability names across sources

Each fetched source's domain module ends in a run(connection, pull) - pull
a fetch.PullContext: the page cache, the session, the log and how old a
cached page may be - that returns a PullSummary: the tables it wrote, and
for a pull that reads one article or page per entity, the ones that would
not fetch (ArticlePullSummary).
authored/ has no run - the strategies mirror is inference.catalog.mirror.
The MCP pull tools (door/mcp) import and call them. Nothing here is an entry
point of its own.
"""

from typing import TypedDict


class PullSummary(TypedDict):
    """What every run() returns; each pull's summary adds its own counts."""
    tables: list[str]


class ArticlePullSummary(PullSummary):
    """The summary of a pull that fetches one article or page per entity:
    missing holds 'name: error' for each that would not fetch."""
    missing: list[str]
