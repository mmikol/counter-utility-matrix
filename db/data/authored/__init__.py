"""The inputs we write instead of fetch - the CSVs in this folder - and the
loader that reloads them whole. Like every source package, this one
declares the `sources` row its rows become.

    seasons        the coarse delineator of rates snapshots (the wiki's
                   season pages are lore with no dates); loading recomputes
                   season_id on every snapshot, so a season added later
                   corrects history
    synergies      one PAIR per row, scored, with the reasoning in `note`;
                   written once in either order, stored once in canonical
                   order - the same pair twice is an error
    archetypes     what a composition IS by playstyle: this style wants
                   this many of this role
    map_playstyle  what kind of fight each map rewards (1-3)

Every input follows one contract: the file is the whole truth, a malformed
row or an unknown name is a loud error to fix in the file (nothing is
dropped), and loading replaces the table. The `load_authored` tool runs
them all (or a subset) and then mirrors the strategies catalog.
"""

import csv
import os
from datetime import date


from db import AUTHORED_DIR
from db import psql

# The sources row these files become. There is nothing to download - the
# "url" is the directory - but every row still names its source. The code
# stays `user` for continuity with databases built before the rename.
AUTHORED = ("user", "Hand-authored inputs", "db/data/authored/")


class AuthoredError(Exception):
    pass


def _csv(path, expected):
    """(line number, row) for every row, after the header is checked."""
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != expected:
            raise AuthoredError("%s: header must be %s, found %s"
                                % (path, ",".join(expected), reader.fieldnames))
        for n, row in enumerate(reader, start=2):
            yield n, row


def _path(name):
    return os.path.join(AUTHORED_DIR, name + ".csv")


# --- seasons -------------------------------------------------------------------

def read_seasons(path):
    rows, seen = [], set()
    for n, row in _csv(path, ["name", "started", "note"]):
        name = row["name"].strip()
        if not name:
            raise AuthoredError("line %d: name is required" % n)
        if name.lower() in seen:
            raise AuthoredError("line %d: duplicate season %s" % (n, name))
        seen.add(name.lower())
        try:
            started = date.fromisoformat(row["started"].strip())
        except ValueError:
            raise AuthoredError("line %d: started must be YYYY-MM-DD" % n)
        rows.append((name, started, row["note"].strip() or None))
    return rows


def load_seasons(connection, path=None, log=print):
    rows = read_seasons(path or _path("seasons"))
    cursor = connection.cursor()
    source_id = psql.register_source(cursor, AUTHORED, psql.now())
    cursor.execute("UPDATE meta_snapshots SET season_id = NULL")
    cursor.execute("DELETE FROM seasons")
    for name, started, note in rows:
        cursor.execute(
            "INSERT INTO seasons (name, started, note, source_id)"
            " VALUES (%s, %s, %s, %s)", (name, started, note, source_id))
    cursor.execute(
        "UPDATE meta_snapshots ms SET season_id ="
        " (SELECT season_id FROM seasons s"
        "  WHERE s.started <= ms.captured_at::date"
        "  ORDER BY s.started DESC, s.season_id DESC LIMIT 1)")
    stamped = cursor.rowcount
    connection.commit()
    log("seasons: %d loaded; %d snapshots stamped" % (len(rows), stamped))
    return {"seasons": len(rows), "stamped": stamped,
            "tables": ["seasons", "meta_snapshots"]}


# --- synergies -----------------------------------------------------------------

def read_synergies(path):
    rows, seen = [], set()
    for n, row in _csv(path, ["hero", "other", "score", "note"]):
        hero, other = row["hero"].strip(), row["other"].strip()
        if not hero or not other:
            raise AuthoredError("line %d: hero and other are required" % n)
        if hero.lower() == other.lower():
            raise AuthoredError("line %d: %s paired with itself" % (n, hero))
        key = frozenset((hero.lower(), other.lower()))
        if key in seen:
            raise AuthoredError("line %d: duplicate pair %s / %s - synergy is"
                                " bidirectional, write each pair once" % (n, hero, other))
        seen.add(key)
        score = row["score"].strip()
        rows.append((hero, other, int(score) if score else None,
                     row["note"].strip() or None))
    return rows


def load_synergies(connection, path=None, log=print):
    rows = read_synergies(path or _path("synergies"))
    cursor = connection.cursor()
    source_id = psql.register_source(cursor, AUTHORED, psql.now())
    hero_ids = psql.lookup_ids(cursor, "heroes", "name", "hero_id")
    unknown = sorted({name for pair in rows for name in pair[:2]
                      if name.lower() not in hero_ids})
    if unknown:
        raise AuthoredError("names not in the roster (fix synergies.csv): %s"
                            % ", ".join(unknown))
    cursor.execute("DELETE FROM synergies")
    for hero, other, score, note in rows:
        a, b = sorted((hero_ids[hero.lower()], hero_ids[other.lower()]))
        cursor.execute(
            "INSERT INTO synergies (hero_id, other_id, score, note,"
            " source_id) VALUES (%s, %s, %s, %s, %s)",
            (a, b, score, note, source_id))
    connection.commit()
    log("authored synergies: %d claims loaded" % len(rows))
    return {"synergies": len(rows), "tables": ["synergies"]}


# --- archetypes ----------------------------------------------------------------

def read_archetypes(path):
    rows, seen = [], set()
    for n, row in _csv(path, ["style", "role", "slots", "note"]):
        style, role = row["style"].strip().lower(), row["role"].strip().lower()
        if not style or not role:
            raise AuthoredError("line %d: style and role are required" % n)
        if (style, role) in seen:
            raise AuthoredError("line %d: duplicate %s/%s" % (n, style, role))
        seen.add((style, role))
        rows.append((style, role, int(row["slots"]), row["note"].strip() or None))
    return rows


def load_archetypes(connection, path=None, log=print):
    rows = read_archetypes(path or _path("archetypes"))
    cursor = connection.cursor()
    source_id = psql.register_source(cursor, AUTHORED, psql.now())
    role_ids = psql.lookup_ids(cursor, "roles", "code", "role_id")
    unknown = sorted({r for _, r, _, _ in rows if r not in role_ids})
    if unknown:
        raise AuthoredError("unknown role codes (fix archetypes.csv): %s"
                            % ", ".join(unknown))
    cursor.execute("DELETE FROM comp_archetypes")
    for style, role, slots, note in rows:
        cursor.execute(
            "INSERT INTO comp_archetypes (style, role_id, slots, note,"
            " source_id) VALUES (%s, %s, %s, %s, %s)",
            (style, role_ids[role], slots, note, source_id))
    connection.commit()
    log("archetype slots: %d loaded" % len(rows))
    return {"slots": len(rows), "styles": sorted({s for s, *_ in rows}),
            "tables": ["comp_archetypes"]}


# --- map playstyle ---------------------------------------------------------------

def read_map_playstyle(path):
    rows, seen = [], set()
    for n, row in _csv(path, ["map", "style", "score", "note"]):
        name, style = row["map"].strip(), row["style"].strip().lower()
        if not name or not style:
            raise AuthoredError("line %d: map and style are required" % n)
        if (name.lower(), style) in seen:
            raise AuthoredError("line %d: duplicate %s/%s" % (n, name, style))
        seen.add((name.lower(), style))
        score = row["score"].strip()
        rows.append((name, style, int(score) if score else None,
                     row["note"].strip() or None))
    return rows


def load_map_playstyle(connection, path=None, log=print):
    rows = read_map_playstyle(path or _path("map_playstyle"))
    cursor = connection.cursor()
    source_id = psql.register_source(cursor, AUTHORED, psql.now())
    map_ids = psql.lookup_ids(cursor, "maps", "name", "map_id")
    unknown = sorted({m for m, *_ in rows if m.lower() not in map_ids})
    if unknown:
        raise AuthoredError("maps not in the pool (fix map_playstyle.csv): %s"
                            % ", ".join(unknown))
    cursor.execute("DELETE FROM map_playstyle")
    for name, style, score, note in rows:
        cursor.execute(
            "INSERT INTO map_playstyle (map_id, style, score, note,"
            " source_id) VALUES (%s, %s, %s, %s, %s)",
            (map_ids[name.lower()], style, score, note, source_id))
    connection.commit()
    log("map playstyle claims: %d" % len(rows))
    return {"claims": len(rows), "maps": len({m for m, *_ in rows}),
            "tables": ["map_playstyle"]}


LOADERS = {"seasons": load_seasons, "synergies": load_synergies,
           "archetypes": load_archetypes, "map_playstyle": load_map_playstyle}
