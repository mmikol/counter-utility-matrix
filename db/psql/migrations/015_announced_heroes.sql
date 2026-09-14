-- A hero the wiki knows ahead of release: on the roster in its role, its
-- kit in the facts, never in a pick or a pool until Blizzard lists it.
BEGIN;

ALTER TABLE heroes
    ADD COLUMN status text NOT NULL DEFAULT 'released'
        CHECK (status IN ('released', 'announced')),
    ADD COLUMN release_date date;

COMMENT ON COLUMN heroes.status IS
    'released: on Blizzard''s roster and playable; announced: known from the wiki ahead of release - shown and described, never picked';
COMMENT ON COLUMN heroes.release_date IS 'the announced release day, when the wiki states one';

COMMIT;
