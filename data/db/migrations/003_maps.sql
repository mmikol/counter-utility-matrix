-- MAPS: the maps, the game modes, and every playable combination.
--
-- Competitive.
--
-- Scope: Standard Play only. The wiki also documents Former Standard Play
-- (Assault, Clash), Stadium, Arcade, Custom Games, Training and seasonal
-- modes. None of those are Open Queue Competitive, so none are stored.
--
-- Source: overwatch.fandom.com. Blizzard has no maps page; it names maps only
-- as a filter on its /rates/ statistics page, with no mode or roster listing.

BEGIN;

CREATE TABLE game_modes (
    mode_id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code      text NOT NULL UNIQUE,
    name      text NOT NULL UNIQUE,
    source_id integer NOT NULL REFERENCES sources(source_id),
    cao       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE maps (
    map_id    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name      text NOT NULL UNIQUE,
    source_id integer NOT NULL REFERENCES sources(source_id),
    cao       timestamptz NOT NULL DEFAULT now()
);

-- One row per playable combination: this table is the set of matches that can
-- actually be drawn in Open Queue Competitive.
--
-- Every map currently belongs to exactly one mode, so today this holds one row
-- per map. It is modelled many-to-many anyway because that is what the domain
-- allows - a map can be re-released under a second mode - and because a
-- degenerate join here costs nothing.
CREATE TABLE map_modes (
    map_id    integer NOT NULL REFERENCES maps(map_id) ON DELETE CASCADE,
    mode_id   integer NOT NULL REFERENCES game_modes(mode_id),
    source_id integer NOT NULL REFERENCES sources(source_id),
    cao       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (map_id, mode_id)
);

CREATE INDEX ix_map_modes_mode ON map_modes (mode_id);

-- Stages within a map: King's Row's first point, Ilios' Well.
--
-- Defined and deliberately empty. No source publishes per-stage rates -
-- Blizzard's map filter lists thirty whole maps and stops - so there is
-- nothing to load here yet. It exists so map_meta can carry a stage_id
-- now rather than needing the column bolted on later.
CREATE TABLE map_stages (
    stage_id  integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    map_id    integer NOT NULL REFERENCES maps(map_id) ON DELETE CASCADE,
    position  smallint NOT NULL,
    name      text NOT NULL,
    source_id integer NOT NULL REFERENCES sources(source_id),
    cao       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (map_id, position),
    UNIQUE (map_id, name)
);

COMMIT;
