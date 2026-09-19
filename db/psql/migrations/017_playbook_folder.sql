-- There is no experiments folder. The column names whichever folder
-- COUNTER_MATRIX_STRATEGIES chose, inference/strategies by default.
BEGIN;

COMMENT ON COLUMN strategies.playbook IS
    'the folder this row was mirrored from, relative to the repo root: inference/strategies, or the folder COUNTER_MATRIX_STRATEGIES names';

COMMIT;
