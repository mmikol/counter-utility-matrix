-- counterpick.gg goes: the sources are Blizzard, the wiki and the playbook.
--
-- map_strategy goes: a hero's best maps are derived at load
-- (facts/tables.py) from Blizzard's per-map win rates. counterpick's rates
-- and their snapshots go. counters stays and is filled from the wiki:
-- pull_counters replaces the table whole, so run it after this migration.
BEGIN;

DROP TABLE IF EXISTS map_strategy;

-- hero_meta, meta_snapshots, counters and map_strategy were the only tables
-- holding counterpick rows. Children before parents.
DELETE FROM hero_meta
 WHERE source_id IN (SELECT source_id FROM sources WHERE code = 'counterpick')
    OR snapshot_id IN (SELECT snapshot_id FROM meta_snapshots
                        WHERE source_id IN (SELECT source_id FROM sources
                                             WHERE code = 'counterpick'));
DELETE FROM map_meta
 WHERE source_id IN (SELECT source_id FROM sources WHERE code = 'counterpick');
DELETE FROM meta_snapshots
 WHERE source_id IN (SELECT source_id FROM sources WHERE code = 'counterpick');
DELETE FROM counters
 WHERE source_id IN (SELECT source_id FROM sources WHERE code = 'counterpick');
DELETE FROM sources WHERE code = 'counterpick';

COMMENT ON TABLE counters IS
    'Who answers whom: one row means countered_by_id answers hero_id. Pulled from the Match-Up column of every hero''s wiki article (pull_counters): each written cell is read from the article hero''s seat as a verdict - the other hero answers this one, this one answers the other, or neither - and a verdict either way becomes one directed edge. A pair the two articles contradict on gets no edge. Reloaded whole.';

COMMIT;
