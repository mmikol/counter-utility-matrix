-- THE COUNTERS' BASIS: where in a hero article each counter edge was read.
-- pull_counters read only the Match-Up column of the "Match-Ups and Team
-- Synergy" section. The same articles' ==Strategy== sections name counters
-- too, in sentences no pull read ("Biotic Grenade is a strong counter to
-- all healing effects, such as Roadhog's Take a Breather"), some of them
-- pairs the Match-Up column leaves out or reads the other way. The pull now
-- reads both and marks each edge with the part it came from, so either can
-- be audited against its article: one row per edge per basis.
BEGIN;

ALTER TABLE counters
    ADD COLUMN basis text NOT NULL DEFAULT 'match-up'
        CHECK (basis IN ('match-up', 'strategy')),
    ADD COLUMN evidence text;
ALTER TABLE counters ALTER COLUMN basis DROP DEFAULT;
ALTER TABLE counters DROP CONSTRAINT counters_pkey;
ALTER TABLE counters ADD PRIMARY KEY (hero_id, countered_by_id, basis);

COMMENT ON TABLE counters IS
    'Who answers whom: one row means countered_by_id answers hero_id, read in one part of a hero''s wiki article (pull_counters), which basis names. match-up: the Match-Up column of the article''s "Match-Ups and Team Synergy" section, each written cell read from the article hero''s seat as a verdict - the other hero answers this one, this one answers the other, or neither - a verdict either way one directed edge, and a pair the two articles contradict on no edge. strategy: a sentence of the article''s ==Strategy== section that names another hero beside a counter cue and says which way it runs (db/data/wiki/strategy_sections.py); evidence is that sentence, and a pair the two articles'' sections contradict on gets no edge. An edge both parts state has a row for each. Reloaded whole.';
COMMENT ON COLUMN counters.basis IS 'the part of the article the edge was read in: match-up or strategy';
COMMENT ON COLUMN counters.evidence IS 'the Strategy sentence that states a strategy edge; NULL for a match-up edge';

COMMIT;
