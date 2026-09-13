-- Overwatch DB - initial schema.
--
-- Scope: Open Queue Competitive. Stadium Powers are excluded - they apply only
-- to the Stadium game mode. Gameplay text and numbers only, no lore, no media.
--
-- This migration defines only what every other table depends on. The three
-- domains are created by the migrations that follow, in dependency order:
--
--     002_heroes   heroes, their abilities, weapons, perks and stats
--     003_maps     maps, game modes, and the combinations that are playable
--     004_meta     win/pick/ban rates - measurements, nothing else
--     005_playbook the judgements: playstyles, counters, best maps, and our
--                  hand-authored synergies
--
-- Together these four are the baseline. Changes after deployment go in new
-- migrations on top of them rather than editing these.
--
-- Sources differ in how much weight they carry, and the pipeline is split that
-- way - data/authoritative/ for what a source recorded, data/heuristic/ for
-- what a source judges. The split is not repeated here: a table is a table,
-- and source_id already says which kind of claim any given row is.

BEGIN;

CREATE TABLE sources (
    source_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code      text NOT NULL UNIQUE,
    name      text NOT NULL,
    url       text NOT NULL,
    cao       timestamptz NOT NULL DEFAULT now()
);

-- Seeded here so the vocabulary tables below can reference a source. The
-- pipelines refresh cao whenever they run.
INSERT INTO sources (code, name, url) VALUES
    ('blizzard', 'Blizzard Overwatch site', 'https://overwatch.blizzard.com/en-us/'),
    ('wiki', 'Overwatch Wiki', 'https://overwatch.fandom.com/'),
    ('counterpick', 'counterpick.gg', 'https://counterpickgg.com/');

COMMIT;
