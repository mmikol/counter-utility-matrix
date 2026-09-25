"""A scratch database for the recorded matches: created on the test server,
every migration applied, the synthetic World's heroes and maps stored in it,
and dropped when the test is done. A match points at a map and six heroes a
team, and the built database's matches are the owner's, so the tests that
record, list, delete and rebuild write here instead.

    with scratch.database(dsn) as target:     # an empty database, dropped after
        scratch.seed(target)                  # the migrations and the roster
"""

import contextlib
import itertools
import os

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.sql import SQL, Identifier

from db import ROLES
from db.data.names import slug
from db.psql import schema
from tests import synthetic

_NUMBER = itertools.count()


@contextlib.contextmanager
def database(dsn):
    """An empty database on the server `dsn` reaches -> its connection
    string; dropped on the way out, connections and all."""
    name = "countrix_matches_%d_%d" % (os.getpid(), next(_NUMBER))
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(SQL("CREATE DATABASE {}").format(Identifier(name)))
    try:
        yield make_conninfo(dsn, dbname=name)
    finally:
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(Identifier(name)))


def seed(dsn, leave_out=()):
    """Every migration, where the database has no tables yet, then the
    synthetic World's roles, subroles, heroes (the announced one with its
    day), modes and maps, under the blizzard source 001 seeds - every hero
    but the names in `leave_out`."""
    world = synthetic.world()
    with psycopg.connect(dsn) as cx:
        if not schema.table_count(cx):
            schema.apply(cx, schema.read_migrations())
        source = cx.execute("select source_id from sources where code = 'blizzard'").fetchone()[0]
        roles = {code: cx.execute(
            "insert into roles (code, source_id) values (%s, %s) returning role_id",
            (code, source)).fetchone()[0] for code in ROLES}
        subroles = {}
        for hero in sorted(world.heroes.values(), key=lambda h: h.id):
            if hero.subrole not in subroles:
                subroles[hero.subrole] = cx.execute(
                    "insert into subroles (role_id, code, name, passive_description, source_id)"
                    " values (%s, %s, %s, '', %s) returning subrole_id",
                    (roles[hero.role], slug(hero.subrole), hero.subrole, source)).fetchone()[0]
            if hero.name in leave_out:
                continue
            cx.execute(
                "insert into heroes (slug, name, role_id, subrole_id, health, status,"
                " release_date, source_id) values (%s, %s, %s, %s, %s, %s, %s, %s)",
                (slug(hero.name), hero.name, roles[hero.role], subroles[hero.subrole],
                 hero.health, hero.status, hero.release_date, source))
        modes = {}
        for played in sorted(world.maps.values(), key=lambda m: m.id):
            if played.mode not in modes:
                modes[played.mode] = cx.execute(
                    "insert into game_modes (code, name, source_id) values (%s, %s, %s)"
                    " returning mode_id", (played.mode.lower(), played.mode, source)).fetchone()[0]
            map_id = cx.execute(
                "insert into maps (name, source_id) values (%s, %s) returning map_id",
                (played.name, source)).fetchone()[0]
            cx.execute("insert into map_modes (map_id, mode_id, source_id) values (%s, %s, %s)",
                       (map_id, modes[played.mode], source))
