"""Pull + clean + store: overwatch.fandom.com - seasons.

The Season article names one subpage per era ({{main|Season/2022-2026}},
{{main|Season/2026}}); each subpage lists its seasons as "=== Season 6:
Invasion ===" headings with the run in parentheses beneath: "(10 August
2023 - 10 October 2023)". A subpage that opens by naming its story arc
('''''Reign of Talon''''' is the 2026 arc) prefixes its seasons with the
arc, as the wiki does: "Reign of Talon Season 1: Conquest".

A season is stored once it has started; one with no full start date, or a
start date ahead of today, is reported as upcoming. note is the subpage the
season came from. The table is reloaded wholesale and every rates snapshot
is restamped with its season.
"""

import re
from collections.abc import Sequence
from datetime import date

import psycopg

from db import psql
from db.data import PullSummary, fetch
from db.data.wiki import WIKI, WikiError, fetch_wikitext, markup

# --- extract: markup -> Python ---------------------------------------------

SEASON_PAGE = "Season"

SUBPAGE_RE = re.compile(r"\{\{\s*main\s*\|\s*(%s/[^}|]+?)\s*\}\}" % SEASON_PAGE, re.I)
ARC_RE = re.compile(r"^\s*'{2,5}([^'\n]+?)'{2,5} is the \d{4} arc\b", re.M)
HEADING_RE = re.compile(r"^===\s*(Season\s+\d+.*?)\s*===[ \t]*$", re.M | re.I)

MONTHS = [
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december"]
# "4 October 2022", "June 20, 2024", "June 20 2024"; the year may be left
# to the other end of the run: "(February 18 - 22 April 2025)".
DATE = (r"(?:(\d{1,2})\s+(%(m)s)|(%(m)s)\s+(\d{1,2}))(?:,?\s*(\d{4}))?"
        % {"m": "|".join(MONTHS)})
RUN_RE = re.compile(r"\(\s*%s\s*[-–—]\s*%s\s*\)" % (DATE, DATE), re.I)


def _date(groups: Sequence[str | None], year: str) -> date:
    """A date from a DATE match's first four groups - the day and the month in
    either order, one pair matched and the other None - and a year."""
    day_first, month_first, month_second, day_second = groups[:4]
    day, month = day_first or day_second, month_first or month_second
    if day is None or month is None:
        raise ValueError("not a DATE match: %r" % (groups,))
    return date(int(year), MONTHS.index(month.lower()) + 1, int(day))


def parse_run(text: str) -> date | None:
    """'(February 18 - 22 April 2025)' -> the start date; None without one."""
    match = RUN_RE.search(text)
    if not match:
        return None
    start, end = match.groups()[:5], match.groups()[5:]
    if start[4]:
        return _date(start, start[4])
    if not end[4]:
        return None
    started = _date(start, end[4])
    if started > _date(end, end[4]):                  # "(December 9 - February 10, 2026)"
        started = started.replace(year=started.year - 1)
    return started


def parse_subpages(text: str) -> list[str]:
    """The era subpages the Season article points at, in page order."""
    pages: list[str] = []
    for title in SUBPAGE_RE.findall(text):
        if title not in pages:
            pages.append(title)
    if not pages:
        raise WikiError("%s: no {{main|%s/...}} subpage" % (SEASON_PAGE, SEASON_PAGE))
    return pages


def parse_seasons(text: str) -> list[tuple[str, date | None]]:
    """[(name, start date or None)] for one era subpage, in page order."""
    arc = ARC_RE.search(markup.FILE_LINK_RE.sub("", text))
    seasons: list[tuple[str, date | None]] = []
    for match in HEADING_RE.finditer(text):
        name = markup.wikitext_to_text(match.group(1))
        if arc:
            name = "%s %s" % (arc.group(1).strip(), name)
        seasons.append((name, parse_run(markup.section_body(text, match.end()))))
    return seasons


# --- store ---------------------------------------------------------------------

class SeasonsSummary(PullSummary):
    seasons: int
    latest: str
    latest_started: str
    stamped: int
    upcoming: list[str]


def run(connection: psycopg.Connection, pull: fetch.PullContext) -> SeasonsSummary:
    """Reload the seasons that have started and restamp every rates snapshot
    with its season, in one transaction -> the seasons, the latest, the
    snapshots stamped and the seasons still to come."""
    seasons: list[tuple[str, date | None, str]] = []
    # A subpage that will not fetch fails the pull whole, not through
    # fetch_articles: the table is reloaded and every snapshot restamped, so
    # a missing era would stamp its snapshots with an earlier era's season.
    # fetch_wikitext already serves the cached copy when the network fails.
    for page in parse_subpages(fetch_wikitext(pull, SEASON_PAGE)):
        found = parse_seasons(fetch_wikitext(pull, page))
        seasons.extend((name, started, page) for name, started in found)
    today = psql.now().date()
    started = sorted(((name, start, page) for name, start, page in seasons
                      if start is not None and start <= today), key=lambda s: s[1])
    upcoming = [name for name, start, _ in seasons if not start or start > today]
    if not started:
        raise WikiError("%s: no season with a start date" % SEASON_PAGE)

    cursor = connection.cursor()
    source_id = psql.register_source(cursor, WIKI, psql.now())
    cursor.execute("UPDATE meta_snapshots SET season_id = NULL")
    cursor.execute("DELETE FROM seasons")
    for name, start, page in started:
        cursor.execute(
            "INSERT INTO seasons (name, started, note, source_id)"
            " VALUES (%s, %s, %s, %s)", (name, start, page, source_id))
    cursor.execute(
        "UPDATE meta_snapshots ms SET season_id ="
        " (SELECT season_id FROM seasons s"
        "  WHERE s.started <= ms.captured_at::date"
        "  ORDER BY s.started DESC, s.season_id DESC LIMIT 1)")
    stamped = cursor.rowcount
    connection.commit()
    pull.log("  seasons    %d, latest %s (%s); %d snapshots stamped" % (
        len(started), started[-1][0], started[-1][1], stamped))
    return {"seasons": len(started), "latest": started[-1][0],
            "latest_started": started[-1][1].isoformat(), "stamped": stamped,
            "upcoming": upcoming, "tables": ["seasons", "meta_snapshots"]}
