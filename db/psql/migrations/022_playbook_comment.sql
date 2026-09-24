-- The strategies.playbook comment under the Countrix name. 017 applied it
-- naming COUNTER_MATRIX_STRATEGIES, the setting's name before the rename;
-- this carries the rename to every database that applied 017 before it.
BEGIN;

COMMENT ON COLUMN strategies.playbook IS
    'the folder this row was mirrored from, relative to the repo root: inference/strategies, or the folder COUNTRIX_STRATEGIES names';

COMMIT;
