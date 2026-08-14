-- Least-privilege runtime role for the HelpDoctor application.
--
-- WHY
-- The application connected as the database owner: a superuser, owner of all
-- 39 tables and 35 sequences, carrying BYPASSRLS. It performs no DDL — no
-- create_all, no DDL(), and the only raw statement it runs is SELECT 1 in the
-- health check — so none of that was needed. A SQL-injection or logic flaw in
-- a single query had the whole cluster behind it.
--
-- WHAT THIS DOES NOT DO
-- No ownership is transferred, nothing is dropped, and helpdoctor_user is left
-- exactly as it is. Alembic, scripts/verify_schema and the backups keep using
-- it. This script only ADDS a role and grants, which is what makes the
-- rollback a configuration change rather than a migration.
--
-- USAGE
--   psql -v app_password="'...'" -f scripts/create_app_role.sql
--
-- Idempotent: safe to run on every deploy, and required after any migration
-- that predates the default privileges below.

\set ON_ERROR_STOP on

-- psql interpolates :'var' into SQL text, but NOT inside a DO $$ … $$ body —
-- that body is a string literal to the parser. So the password is carried in a
-- session GUC, which current_setting() can read from inside the block.
SELECT set_config('helpdoctor.app_password', :'app_password', false);

-- ---------------------------------------------------------------------------
-- The role
-- ---------------------------------------------------------------------------
-- Every attribute is spelled out rather than relying on defaults, because the
-- point of this role is what it CANNOT do. NOBYPASSRLS is stated even though
-- it is the default: if row-level security is adopted later, a role that
-- silently bypasses it would make the policies decorative.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'helpdoctor_app') THEN
        EXECUTE format(
            'CREATE ROLE helpdoctor_app LOGIN PASSWORD %L '
            'NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
            current_setting('helpdoctor.app_password')
        );
    ELSE
        EXECUTE format(
            'ALTER ROLE helpdoctor_app LOGIN PASSWORD %L '
            'NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
            current_setting('helpdoctor.app_password')
        );
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- Connect and schema
-- ---------------------------------------------------------------------------
GRANT CONNECT ON DATABASE :"db" TO helpdoctor_app;

-- USAGE only. Without CREATE the role cannot add objects to the schema, which
-- is the difference between "can write rows" and "can change the database".
GRANT USAGE ON SCHEMA public TO helpdoctor_app;
REVOKE CREATE ON SCHEMA public FROM helpdoctor_app;

-- ---------------------------------------------------------------------------
-- Data
-- ---------------------------------------------------------------------------
-- DML only. Deliberately absent:
--   TRUNCATE  - the application never truncates; only the test harness does,
--               and it uses the privileged role.
--   REFERENCES- creating foreign keys is DDL.
--   TRIGGER   - likewise.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
    TO helpdoctor_app;

-- All 35 primary keys use nextval() defaults (there are no identity columns),
-- so USAGE here is what makes INSERT possible at all.
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO helpdoctor_app;

-- ---------------------------------------------------------------------------
-- Future objects — the part that is easy to forget and expensive to miss
-- ---------------------------------------------------------------------------
-- GRANT ... ON ALL TABLES applies only to the tables that exist right now. The
-- next Alembic revision creates a table owned by helpdoctor_user, and without
-- this the application gets "permission denied" on a table it has never seen —
-- at runtime, in production, after a deploy that looked clean.
--
-- FOR ROLE helpdoctor_user is essential: default privileges attach to the
-- CREATING role, and migrations run as the owner, not as whoever runs this
-- script.
ALTER DEFAULT PRIVILEGES FOR ROLE helpdoctor_user IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO helpdoctor_app;

ALTER DEFAULT PRIVILEGES FOR ROLE helpdoctor_user IN SCHEMA public
    GRANT USAGE ON SEQUENCES TO helpdoctor_app;
