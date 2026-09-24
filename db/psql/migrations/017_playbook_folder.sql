-- There is no experiments folder. The column names whichever folder
-- COUNTRIX_STRATEGIES chose, inference/strategies by default.
-- The statement below is as applied, with the setting's old name; 022 re-issues it.
BEGIN;

COMMENT ON COLUMN strategies.playbook IS
    'the folder this row was mirrored from, relative to the repo root: inference/strategies, or the folder COUNTER_MATRIX_STRATEGIES names';

COMMIT;
