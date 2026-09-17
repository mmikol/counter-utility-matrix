-- SCHEMA MIGRATIONS: the ledger of what was applied.
--
-- The database has always been rebuilt from scratch, so nothing tracked
-- which migrations a cluster carried - and a container holding an older
-- schema looked "populated" and was never rebuilt. This ledger lets the
-- entrypoint (and db_status) compare the files on disk with what the
-- database applied, and rebuild when they differ. db/psql/schema.py fills it
-- after applying; rows carry no source_id because they are not data.

BEGIN;

CREATE TABLE schema_migrations (
    filename   text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

COMMIT;
