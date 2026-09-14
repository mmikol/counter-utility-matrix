-- The strategies table mirrors one playbook at a time - the shipped one, or an
-- experiment chosen with COUNTER_MATRIX_STRATEGIES. It now says which, so a
-- reader (and the parity test) compares it with the right files.
BEGIN;

ALTER TABLE strategies
    ADD COLUMN playbook text NOT NULL DEFAULT 'inference/strategies';

COMMENT ON COLUMN strategies.playbook IS
    'the folder this row was mirrored from, relative to the repo root: inference/strategies, or an experiment under inference/experiments/';

COMMIT;
