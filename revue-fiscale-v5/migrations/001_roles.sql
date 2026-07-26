-- 001 — Roles et privileges
-- Le role applicatif n est ni superuser, ni proprietaire, ni BYPASSRLS.
-- C est la condition n 2 de l isolation (voir docs/09-multitenant.md).

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_revue') THEN
        CREATE ROLE app_revue LOGIN PASSWORD 'changeme';
    END IF;
END $$;

ALTER ROLE app_revue NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;

GRANT USAGE ON SCHEMA public TO app_revue;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_revue;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO app_revue;
