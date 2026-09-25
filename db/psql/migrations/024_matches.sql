-- MATCHES: the games the owner plays, recorded by hand, the second input a
-- user writes beside the playbook. The owner plays on console, so a game is
-- entered through the door's record_match - the board's record tab, the
-- /record skill - never logged by the game. One row is one map. Nothing
-- here is pulled: every row carries the `user` source, as the strategies
-- do, and db_rebuild keeps the rows across the drop.
--
-- 009 recorded the match that followed a recommendation and 014 dropped it;
-- these tables record what was played, whatever the board said.
BEGIN;

-- The owner's recorded games, one row a map, written by record_match. blue
-- is always the owner's team, so side and result are blue's: side is attack
-- or defense on an Escort or Hybrid map and '' on a map without sides,
-- result is win, loss or draw. played_on is the day the map was played.
-- playbook_digest is catalog.playbook_digest of the playbook in force when
-- the match was recorded, so a reader can tell which rules the board scored
-- under. note is the owner's own line, '' when there is none.
CREATE TABLE matches (
    match_id        integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    played_on       date NOT NULL,
    map_id          integer NOT NULL REFERENCES maps(map_id),
    side            text NOT NULL CHECK (side IN ('attack', 'defense', '')),
    result          text NOT NULL CHECK (result IN ('win', 'loss', 'draw')),
    playbook_digest text NOT NULL,
    note            text NOT NULL DEFAULT '',
    source_id       integer NOT NULL REFERENCES sources(source_id),
    cao             timestamptz NOT NULL DEFAULT now()
);

-- Both sixes and the bans of a recorded match. team is blue (the owner's),
-- red or ban; position orders a team's heroes as they were entered, from 1.
-- A six is the six on the field longest, so a hero swapped in late is not
-- in it. A hero holds one seat a team, and may play for both teams.
CREATE TABLE match_picks (
    match_id  integer NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    team      text NOT NULL CHECK (team IN ('blue', 'red', 'ban')),
    position  smallint NOT NULL CHECK (position BETWEEN 1 AND 6),
    hero_id   integer NOT NULL REFERENCES heroes(hero_id),
    source_id integer NOT NULL REFERENCES sources(source_id),
    cao       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, team, position),
    UNIQUE (match_id, team, hero_id)
);

CREATE INDEX ix_matches_map ON matches (map_id);
CREATE INDEX ix_match_picks_hero ON match_picks (hero_id);

COMMENT ON COLUMN matches.played_on IS 'the day the map was played';
COMMENT ON COLUMN matches.side IS
    'blue''s side: attack or defense on an Escort or Hybrid map, '''' on a map without sides';
COMMENT ON COLUMN matches.result IS 'win, loss or draw, from blue''s point of view: blue is the owner''s team';
COMMENT ON COLUMN matches.playbook_digest IS
    'catalog.playbook_digest of the playbook in force when the match was recorded';
COMMENT ON COLUMN matches.note IS 'the owner''s own line about the map, '''' when there is none';
COMMENT ON COLUMN match_picks.team IS 'blue (the owner''s team), red or ban';
COMMENT ON COLUMN match_picks.position IS 'the order the team''s heroes were entered in, from 1';

COMMIT;
