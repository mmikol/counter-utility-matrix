"""The owner's recorded matches, read: one Match a map played, with both
sixes, the bans, blue's side and blue's result. Blue is always the owner's
team. The door's record_match writes them (db.matches); the facts layer
reads the tables, and the inference layer reads these records, never the
tables.

    Match           one recorded map, the names as the roster spells them
    load_matches    every recorded match, oldest first
"""

import datetime
from typing import NamedTuple

import psycopg

from db import psql


class Match(NamedTuple):
    """One recorded map: its id, the day it was played, the map, blue's side
    ('attack', 'defense', or '' on a map without sides), blue's result
    ('win', 'loss' or 'draw'), both sixes and the bans in the order they
    were entered, the digest of the playbook in force when it was recorded
    (catalog.playbook_digest) and the owner's note, '' when there is none."""
    match_id: int
    played_on: datetime.date
    map_name: str
    side: str           # 'attack', 'defense' or '' on an unsided map
    result: str         # 'win', 'loss' or 'draw', blue's
    blue: tuple[str, ...]
    red: tuple[str, ...]
    bans: tuple[str, ...]
    playbook_digest: str
    note: str


def load_matches(connection: psycopg.Connection) -> list[Match]:
    """Every recorded match, oldest first: by played_on, then match_id. A
    database the migrations have not brought to the matches table (024)
    holds none."""
    if psql.scalar(connection.execute("select to_regclass('matches')")) is None:
        return []
    picks: dict[tuple[int, str], list[str]] = {}
    for match_id, team, name in connection.execute("""
            select p.match_id, p.team, h.name from match_picks p
            join heroes h using (hero_id)
            order by p.match_id, p.team, p.position"""):
        picks.setdefault((match_id, team), []).append(name)
    return [
        Match(
            match_id=match_id, played_on=played_on, map_name=map_name, side=side,
            result=result, blue=tuple(picks.get((match_id, "blue"), ())),
            red=tuple(picks.get((match_id, "red"), ())),
            bans=tuple(picks.get((match_id, "ban"), ())), playbook_digest=digest, note=note)
        for match_id, played_on, map_name, side, result, digest, note in connection.execute("""
            select m.match_id, m.played_on, p.name, m.side, m.result,
                   m.playbook_digest, m.note
            from matches m join maps p using (map_id)
            order by m.played_on, m.match_id""")]
