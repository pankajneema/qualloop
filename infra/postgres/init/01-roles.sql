-- DEV/CI ONLY. Placeholder passwords; staging/prod roles are created by IaC with secrets-manager passwords.
-- Idempotent: safe to re-run (CI runs it with psql against a fresh service container).
-- Roles per ADR-004: owner (migrations), app (runtime, NOBYPASSRLS), sysfn (NOLOGIN definer-function owner).

SELECT 'CREATE ROLE qualloop_owner LOGIN PASSWORD ''qualloop_owner'' NOSUPERUSER NOBYPASSRLS NOCREATEROLE'
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'qualloop_owner') \gexec
SELECT 'CREATE ROLE qualloop_app LOGIN PASSWORD ''qualloop_app'' NOSUPERUSER NOBYPASSRLS NOCREATEROLE'
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'qualloop_app') \gexec
SELECT 'CREATE ROLE qualloop_sysfn NOLOGIN NOSUPERUSER NOBYPASSRLS'
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'qualloop_sysfn') \gexec

SELECT 'CREATE DATABASE qualloop OWNER qualloop_owner'
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'qualloop') \gexec
SELECT 'CREATE DATABASE qualloop_test OWNER qualloop_owner'
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'qualloop_test') \gexec

-- No TEMP for PUBLIC (hardening, D-3); the owner keeps it as database owner.
REVOKE TEMP ON DATABASE qualloop FROM PUBLIC;
REVOKE TEMP ON DATABASE qualloop_test FROM PUBLIC;

-- Data migrations (DATA_MODEL 0.9) run `SET LOCAL ROLE qualloop_app` from the owner connection: allow SET, no inheritance.
GRANT qualloop_app TO qualloop_owner WITH INHERIT FALSE, SET TRUE;
