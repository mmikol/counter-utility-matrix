-- OUTCOMES: what actually happened - the feedback the inference layer learns
-- from.
--
-- A recommendation is an opinion the database produced; an outcome is the
-- match that followed. One row per played match: the result, the map and
-- blue's side, and - in outcome_picks - both sixes and the bans. rec_id
-- links back to the recommendation that was played when there was one,
-- and is NULL for a match recorded on its own.
--
-- Like recommendations, outcomes are the one thing no pull tool can
-- re-fetch: they are mirrored to data/raw and restored after every
-- rebuild. inference/fit.py reads them to nudge the goal weights toward
-- the metrics that separated wins from losses.

BEGIN;

CREATE TABLE outcomes (
    outcome_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    played_at  timestamptz NOT NULL DEFAULT now(),
    rec_id     integer REFERENCES recommendations(rec_id) ON DELETE SET NULL,
    map_id     integer REFERENCES maps(map_id),
    side       text CHECK (side IN ('attack', 'defense')),
    result     text NOT NULL CHECK (result IN ('win', 'loss', 'draw')),
    note       text,
    source_id  integer NOT NULL REFERENCES sources(source_id),
    cao        timestamptz NOT NULL DEFAULT now()
);

-- team is 'blue', 'red' or 'ban'; position orders the picks within a team.
CREATE TABLE outcome_picks (
    outcome_id integer NOT NULL REFERENCES outcomes(outcome_id) ON DELETE CASCADE,
    team       text NOT NULL CHECK (team IN ('blue', 'red', 'ban')),
    position   smallint NOT NULL,
    hero_id    integer NOT NULL REFERENCES heroes(hero_id),
    source_id  integer NOT NULL REFERENCES sources(source_id),
    cao        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (outcome_id, team, position)
);

CREATE INDEX ix_outcomes_map ON outcomes (map_id);
CREATE INDEX ix_outcome_picks_hero ON outcome_picks (hero_id);

COMMIT;
