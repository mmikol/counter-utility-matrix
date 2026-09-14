-- 011: a role for the query tool - SELECT on every table, nothing else.
--
-- The tool already refuses anything but one SELECT; this makes the database
-- refuse the rest too. Both database users the project uses are superusers
-- (the embedded cluster's owner, the compose image's POSTGRES_USER), and a
-- superuser's SELECT can read files off the disk it runs on. `SET LOCAL ROLE
-- matrix_reader` inside the query's transaction drops to a role that cannot.
-- Roles are cluster-wide, so this is guarded: a rebuild reapplies it safely.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'matrix_reader') THEN
        CREATE ROLE matrix_reader NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO matrix_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO matrix_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO matrix_reader;
