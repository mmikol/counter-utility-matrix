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
from datetime import date

from db import psql
from db.data import fetch
from db.data.wiki import WIKI, WikiError, fetch_wikitext, markup

# --- extract: markup -> Python ---------------------------------------------

SEASON_PAGE = "Season"

SUBPAGE_RE = re.compile(r"\{\{\s*main\s*\|\s*(%s/[^}|]+?)\s*\}\}" % SEASON_PAGE, re.I)
ARC_RE = re.compile(r"^\s*'{2,5}([^'\n]+?)'{2,5} is the \d{4} arc\b", re.M)
HEADING_RE = re.compile(r"^===\s*(Season\s+\d+.*?)\s*===[ \t]*$", re.M | re.I)

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]
# "4 October 2022", "June 20, 2024", "June 20 2024"; the year may be left
# to the other end of the run: "(February 18 - 22 April 2025)".
DATE = (r"(?:(\d{1,2})\s+(%(m)s)|(%(m)s)\s+(\d{1,2}))(?:,?\s*(\d{4}))?"
        % {"m": "|".join(MONTHS)})
RUN_RE = re.compile(r"\(\s*%s\s*[-–—]\s*%s\s*\)" % (DATE, DATE), re.I)


def _date(day_first, month_first, month_second, day_second, year):
    month = MONTHS.index((month_first or month_second).lower()) + 1
    return date(int(year), month, int(day_first or day_second))


def parse_run(text):
    """'(February 18 - 22 April 2025)' -> the start date; None without one."""
    match = RUN_RE.search(text)
    if not match:
        return None
    start, end = match.groups()[:5], match.groups()[5:]
    if start[4]:
        return _date(*start)
    if not end[4]:
        return None
    started = _date(*start[:4], end[4])
    if started > _date(*end):                        # "(December 9 - February 10, 2026)"
        started = started.replace(year=started.year - 1)
    return started


def parse_subpages(text):
    """The era subpages the Season article points at, in page order."""
    pages = []
    for title in SUBPAGE_RE.findall(text):
        if title not in pages:
            pages.append(title)
    if not pages:
        raise WikiError("%s: no {{main|%s/...}} subpage" % (SEASON_PAGE, SEASON_PAGE))
    return pages


def parse_seasons(text):
    """[(name, start date or None)] for one era subpage, in page order."""
    arc = ARC_RE.search(markup.FILE_LINK_RE.sub("", text))
    seasons = []
    for match in HEADING_RE.finditer(text):
        name = markup.wikitext_to_text(match.group(1))
        if arc:
            name = "%s %s" % (arc.group(1).strip(), name)
        seasons.append((name, parse_run(markup.section_body(text, match.end()))))
    return seasons


# --- store ---------------------------------------------------------------------

def run(connection, cache_dir=None, session=None, log=print):
    session = fetch.session(session)
    seasons = []
    for page in parse_subpages(fetch_wikitext(session, SEASON_PAGE, cache_dir)):
        found = parse_seasons(fetch_wikitext(session, page, cache_dir))
        seasons.extend((name, started, page) for name, started in found)
    today = psql.now().date()
    started = sorted((s for s in seasons if s[1] and s[1] <= today), key=lambda s: s[1])
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
    log("  seasons    %d, latest %s (%s); %d snapshots stamped"
        % (len(started), started[-1][0], started[-1][1], stamped))
    return {"seasons": len(started), "latest": started[-1][0],
            "latest_started": started[-1][1].isoformat(), "stamped": stamped,
            "upcoming": upcoming, "tables": ["seasons", "meta_snapshots"]}
