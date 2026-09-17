-- OUTCOMES (history): the match that followed a recommendation - one row
-- per played match with the result, the map, blue's side and, in
-- outcome_picks, both sixes and the bans; a fit read them to nudge the
-- weights toward the metrics that separated wins from losses.
--
-- Superseded: 014 dropped both tables - nothing learns from played matches
-- now (the backlog's "weights that learn" is the way back). The file stays
-- as the sequence's record.

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
