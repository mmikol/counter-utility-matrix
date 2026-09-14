-- Recording compositions and match outcomes is no longer a feature: the
-- inference layer's decisions are not stored, and nothing learns from
-- played matches. The tables that held them go, with their rows.
BEGIN;

DROP TABLE IF EXISTS outcome_picks;
DROP TABLE IF EXISTS outcomes;
DROP TABLE IF EXISTS recommendation_evidence;
DROP TABLE IF EXISTS recommendation_picks;
DROP TABLE IF EXISTS recommendations;

COMMIT;
