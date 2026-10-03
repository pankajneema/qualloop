"""baseline: extensions, helper functions, default privileges (no business tables)

Revision ID: 0001
Revises:
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = ("qualloop_owner", "qualloop_app", "qualloop_sysfn")


def upgrade() -> None:
    # Roles are cluster-level and created by infra (infra/postgres/init/01-roles.sql locally and in CI;
    # IaC in staging/prod). The migration only verifies them, so a missing role fails loudly and early.
    op.execute(
        """
        DO $$
        DECLARE r text;
        BEGIN
          FOREACH r IN ARRAY ARRAY['qualloop_owner','qualloop_app','qualloop_sysfn'] LOOP
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
              RAISE EXCEPTION 'required role % does not exist; run infra/postgres/init/01-roles.sql', r;
            END IF;
          END LOOP;
          IF EXISTS (SELECT 1 FROM pg_roles
                     WHERE rolname IN ('qualloop_app','qualloop_sysfn') AND (rolsuper OR rolbypassrls)) THEN
            RAISE EXCEPTION 'qualloop_app / qualloop_sysfn must be NOSUPERUSER NOBYPASSRLS';
          END IF;
        END $$
        """
    )

    # Only drop the extension on downgrade if this migration created it (marked via its comment).
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'btree_gist') THEN
            CREATE EXTENSION btree_gist;
            COMMENT ON EXTENSION btree_gist IS 'created by qualloop migration 0001';
          END IF;
        END $$
        """
    )

    # No temp tables for anyone but the owner (D-3): a TEMP schema is a search_path attack surface.
    op.execute(
        "DO $$ BEGIN EXECUTE format('REVOKE TEMP ON DATABASE %I FROM PUBLIC', current_database()); END $$"
    )

    # Schema access + default privileges. App role never gets DELETE (section 0.3);
    # append-only tables additionally lose UPDATE through helpers.append_only().
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA public TO qualloop_app, qualloop_sysfn")
    # /readyz (runs as the app role) compares the DB revision with the code head.
    op.execute("GRANT SELECT ON alembic_version TO qualloop_app")
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE qualloop_owner IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE ON TABLES TO qualloop_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE qualloop_owner IN SCHEMA public "
        "GRANT USAGE, SELECT ON SEQUENCES TO qualloop_app"
    )

    op.execute(
        """
        CREATE FUNCTION app_current_tenant_id() RETURNS uuid LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('app.tenant_id', true), '')::uuid $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app_current_actor_type() RETURNS text LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('app.actor_type', true), '') $$
        """
    )
    # UUIDv7 for SQL-side inserts (seeds, triggers): 48-bit unix ms + random, version bits -> 0111.
    # Supplier-session context (ADR-004/009). NULL when unset; set per transaction by the supplier resolver.
    for fn, guc, typ in (
        ("app_current_supplier_session_id", "app.supplier_session_id", "uuid"),
        ("app_current_magic_link_id", "app.magic_link_id", "uuid"),
        ("app_current_scope_object_type", "app.scope_object_type", "text"),
        ("app_current_scope_object_id", "app.scope_object_id", "uuid"),
        ("app_current_supplier_id", "app.supplier_id", "uuid"),
        ("app_current_actor_id", "app.actor_id", "uuid"),
    ):
        cast = "::uuid" if typ == "uuid" else ""
        op.execute(
            f"CREATE FUNCTION {fn}() RETURNS {typ} LANGUAGE sql STABLE AS "
            f"$$ SELECT nullif(current_setting('{guc}', true), ''){cast} $$"
        )
    op.execute(
        "CREATE FUNCTION app_guc_uuid(name text) RETURNS uuid LANGUAGE sql STABLE AS "
        "$$ SELECT nullif(current_setting(name, true), '')::uuid $$"
    )
    op.execute(
        "CREATE FUNCTION app_is_supplier() RETURNS boolean LANGUAGE sql STABLE AS "
        "$$ SELECT coalesce(app_current_actor_type() = 'supplier_session', false) $$"
    )
    # NOTE: any future SECURITY DEFINER function must declare SET search_path = pg_catalog, public, pg_temp.
    op.execute(
        """
        CREATE FUNCTION app_uuid_v7() RETURNS uuid LANGUAGE sql VOLATILE AS
        $$
          SELECT encode(
            set_bit(set_bit(
              overlay(uuid_send(gen_random_uuid())
                      placing substring(int8send(floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint) FROM 3)
                      FROM 1 FOR 6),
              52, 1), 53, 1),
            'hex')::uuid
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION trg_set_updated_at() RETURNS trigger LANGUAGE plpgsql AS
        $$ BEGIN NEW.updated_at := now(); RETURN NEW; END $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION trg_append_only() RETURNS trigger LANGUAGE plpgsql AS
        $$ BEGIN
             RAISE EXCEPTION '% is append-only: % not allowed', TG_TABLE_NAME, TG_OP
               USING ERRCODE = 'integrity_constraint_violation';
           END $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS trg_append_only()")
    op.execute("DROP FUNCTION IF EXISTS trg_set_updated_at()")
    op.execute("DROP FUNCTION IF EXISTS app_uuid_v7()")
    op.execute("DROP FUNCTION IF EXISTS app_current_actor_type()")
    op.execute("DROP FUNCTION IF EXISTS app_is_supplier()")
    op.execute("DROP FUNCTION IF EXISTS app_guc_uuid(text)")
    for fn in (
        "app_current_supplier_session_id",
        "app_current_magic_link_id",
        "app_current_scope_object_type",
        "app_current_scope_object_id",
        "app_current_supplier_id",
        "app_current_actor_id",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {fn}()")
    op.execute("DROP FUNCTION IF EXISTS app_current_tenant_id()")
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE qualloop_owner IN SCHEMA public "
        "REVOKE USAGE, SELECT ON SEQUENCES FROM qualloop_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE qualloop_owner IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE ON TABLES FROM qualloop_app"
    )
    op.execute("REVOKE SELECT ON alembic_version FROM qualloop_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM qualloop_app, qualloop_sysfn")
    op.execute(
        """
        DO $$
        BEGIN
          IF obj_description((SELECT oid FROM pg_extension WHERE extname = 'btree_gist'),
                             'pg_extension') = 'created by qualloop migration 0001' THEN
            DROP EXTENSION btree_gist;
          END IF;
        END $$
        """
    )
    op.execute("DO $$ BEGIN EXECUTE format('GRANT TEMP ON DATABASE %I TO PUBLIC', current_database()); END $$")
    # Roles are cluster-level and owned by infra, so they are not dropped here.
