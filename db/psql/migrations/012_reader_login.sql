-- 012: the reader role is a login of its own, and the hatches are shut.
--
-- 011 made `query` drop to matrix_reader with SET ROLE, but a session that
-- starts as a superuser can be talked back up by SQL that runs SQL
-- (query_to_xml and friends evaluate their text at execution time, past the
-- checks that stop a plain call). So the query tool now CONNECTS as the
-- reader - a non-superuser session has nothing to climb back to - and the
-- functions that run text as SQL or change settings are withdrawn from
-- PUBLIC; superusers ignore those ACLs, so the application is unaffected.
-- The password is the role's name: the role can only SELECT, and the
-- database answers on this machine only.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'matrix_reader') THEN
        CREATE ROLE matrix_reader NOLOGIN;
    END IF;
END $$;
ALTER ROLE matrix_reader LOGIN PASSWORD 'matrix_reader';
ALTER ROLE matrix_reader SET statement_timeout = '10s';

REVOKE EXECUTE ON FUNCTION set_config(text, text, boolean) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION query_to_xml(text, boolean, boolean, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION query_to_xmlschema(text, boolean, boolean, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION query_to_xml_and_xmlschema(text, boolean, boolean, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION cursor_to_xml(refcursor, integer, boolean, boolean, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION cursor_to_xmlschema(refcursor, boolean, boolean, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_sleep(double precision) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_sleep_for(interval) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_sleep_until(timestamp with time zone) FROM PUBLIC;
