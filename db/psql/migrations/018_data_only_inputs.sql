-- The strategies are the one input a user writes. Every other table is
-- pulled from a source.
--
-- map_playstyle goes: a map's styles are derived at load (ui/facts/model.py)
-- from the wiki's hero playstyle tags and the per-map win rates. comp_archetypes
-- goes: it only ever said two slots per role, which ui/facts/compute.py holds
-- as EXPECTED_SHAPE. seasons and synergies stay and are filled from the wiki:
-- pull_seasons and pull_synergies each replace the table whole, so run both
-- after this migration to replace the rows the CSVs loaded.
BEGIN;

DROP TABLE IF EXISTS map_playstyle;
DROP TABLE IF EXISTS comp_archetypes;

-- 004 wrote the patches prose above CREATE TABLE seasons; it is patches' own.
COMMENT ON TABLE patches IS
    'The game versions the meta moves with. A win rate is true of a patch, so a snapshot records which patch was live when it was captured. Pulled from the wiki''s Patches cargo table (pull_patches); name is the wiki''s own page name, since Blizzard ships most balance patches unversioned.';

COMMENT ON TABLE seasons IS
    'Seasons: the coarser delineator. A patch tweaks numbers; a season swaps the hero pool and map rotation, so a snapshot records both. Pulled from the wiki''s Season pages (pull_seasons): every season that has started, with its start date; note is the wiki subpage it came from. Reloaded whole; every rates snapshot is restamped with its season.';

COMMENT ON TABLE synergies IS
    'Which heroes work WITH which. Pulled from the Synergy section of every hero''s wiki article (pull_synergies): a pair per hero linked in another hero''s section. score is 2 when both articles name each other, 1 when one does; note is the wiki''s advice for the pair, cut to one clause. Bidirectional, unlike counters: each pair is stored once, lower hero_id first, and read from either side. Reloaded whole.';

COMMIT;
