"""platform: tenants, plants, users, activity_log, outbox_events, idempotency_keys, job_dead_letters

DATA_MODEL sections 0, 1, 8 (platform definer functions) and 9 (technical tables, A-73 / A-89).
No table here holds data at migration time, so no data step is needed (DATA_MODEL 0.9 applies to later revisions).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from helpers import (
    add_updated_at_trigger,
    append_only,
    enable_supplier_scoped_rls,
    enable_tenant_rls,
    std_columns,
    std_constraints,
)
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP = "qualloop_app"
SYSFN = "qualloop_sysfn"
SAFE_PATH = "SET search_path = pg_catalog, public, pg_temp"

TABLES = (
    "tenants",
    "plants",
    "users",
    "activity_log",
    "outbox_events",
    "idempotency_keys",
    "job_dead_letters",
)
DEFINER_FUNCTIONS = (
    "app_resolve_login(text)",
    "app_active_tenant_ids()",
    "app_claim_outbox_batch(integer)",
)


def _jsonb(name: str, *, nullable: bool = True) -> sa.Column[object]:
    return sa.Column(name, pg.JSONB(), nullable=nullable)


def _require_sysfn_membership() -> None:
    """The owner must be able to SET ROLE qualloop_sysfn (infra/postgres/init/01-roles.sql grants it).

    Definer functions must be owned by qualloop_sysfn (ADR-004 item 2), and the owner cannot create roles or
    change ownership to a role it cannot SET, so fail early with a clear message instead of halfway through."""
    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT pg_has_role(current_user, '{SYSFN}', 'SET') THEN
            RAISE EXCEPTION 'role % must be allowed to SET ROLE {SYSFN}; add '
              '"GRANT {SYSFN} TO qualloop_owner WITH INHERIT FALSE, SET TRUE" to infra/postgres/init/01-roles.sql',
              current_user;
          END IF;
        END $$
        """
    )


def upgrade() -> None:
    _require_sysfn_membership()

    # ------------------------------------------------------------------ tenants
    op.create_table(
        "tenants",
        *std_columns(tenant_fk=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("plan", sa.Text(), nullable=False),
        sa.Column("settings", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *std_constraints("tenants"),
        sa.CheckConstraint("tenant_id = id", name="tenants_tenant_id_is_id"),
        sa.CheckConstraint("jsonb_typeof(settings) = 'object'", name="tenants_settings_object"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="tenants_name_not_blank"),  # A-90
    )
    enable_tenant_rls("tenants")
    enable_supplier_scoped_rls("tenants", select_predicate="true")
    # Only name, plan, settings (and audit columns) may change; the tenant never moves or re-ids.
    op.execute(f"REVOKE UPDATE ON tenants FROM {APP}")
    op.execute(f"GRANT UPDATE (name, plan, settings, updated_at, updated_by) ON tenants TO {APP}")
    add_updated_at_trigger("tenants")

    # ------------------------------------------------------------------ plants
    op.create_table(
        "plants",
        *std_columns(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("timezone", sa.Text(), nullable=False, server_default="Asia/Kolkata"),
        *std_constraints("plants"),
        sa.UniqueConstraint("tenant_id", "code", name="plants_tenant_id_code_key"),
        sa.CheckConstraint("code ~ '^[A-Z0-9]{1,10}$'", name="plants_code_format"),  # A-90
        sa.CheckConstraint("length(btrim(name)) > 0", name="plants_name_not_blank"),  # A-90
    )
    enable_tenant_rls("plants")
    add_updated_at_trigger("plants")

    # ------------------------------------------------------------------ users
    op.create_table(
        "users",
        *std_columns(),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("mobile", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("can_approve", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "plant_ids",
            pg.ARRAY(pg.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("password_hash", sa.Text(), nullable=True),  # A-74
        *std_constraints("users"),
        sa.CheckConstraint("role IN ('admin','quality','viewer')", name="users_role_values"),
        sa.CheckConstraint(r"mobile ~ '^\+[1-9][0-9]{7,14}$'", name="users_mobile_e164"),  # A-90
        sa.CheckConstraint("length(btrim(name)) > 0", name="users_name_not_blank"),  # A-90
        sa.CheckConstraint("length(btrim(email)) > 0", name="users_email_not_blank"),  # A-90
    )
    # Login resolves the tenant from the email (A-03): the one documented non-tenant-first index.
    op.create_index("users_email_uq", "users", [sa.text("lower(email)")], unique=True)
    op.create_index("ix_users_tenant_role", "users", ["tenant_id", "role"])
    op.create_index(
        "ix_users_tenant_approvers",
        "users",
        ["tenant_id"],
        postgresql_where=sa.text("can_approve AND active"),
    )
    enable_tenant_rls("users")
    add_updated_at_trigger("users")
    op.execute(
        """
        CREATE FUNCTION trg_users_plant_ids_valid() RETURNS trigger LANGUAGE plpgsql AS
        $$
        BEGIN
          IF TG_OP = 'UPDATE' AND NEW.plant_ids IS NOT DISTINCT FROM OLD.plant_ids THEN
            RETURN NEW;
          END IF;
          IF cardinality(NEW.plant_ids) = 0 THEN
            RETURN NEW;
          END IF;
          IF array_position(NEW.plant_ids, NULL) IS NOT NULL
             OR (SELECT count(*) FROM plants p
                  WHERE p.tenant_id = NEW.tenant_id AND p.id = ANY (NEW.plant_ids))
                <> (SELECT count(DISTINCT x) FROM unnest(NEW.plant_ids) AS x) THEN
            RAISE EXCEPTION 'users.plant_ids must reference plants of the same tenant'
              USING ERRCODE = 'foreign_key_violation';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_users_plant_ids_valid BEFORE INSERT OR UPDATE ON users "
        "FOR EACH ROW EXECUTE FUNCTION trg_users_plant_ids_valid()"
    )

    # ------------------------------------------------------------------ activity_log
    op.create_table(
        "activity_log",
        *std_columns(),
        sa.Column("object_type", sa.Text(), nullable=False),
        sa.Column("object_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        _jsonb("before"),
        _jsonb("after"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("ip", pg.INET(), nullable=True),
        *std_constraints("activity_log"),
        sa.CheckConstraint(
            "actor_type IN ('user','supplier_session','system','ai')", name="activity_log_actor_type"
        ),
        sa.CheckConstraint(
            "actor_type NOT IN ('user','supplier_session') OR actor_id IS NOT NULL",
            name="activity_log_actor_id_required",
        ),
        sa.CheckConstraint(
            "actor_type <> 'supplier_session' OR session_id IS NOT NULL",
            name="activity_log_supplier_session_required",
        ),
        sa.CheckConstraint(
            "before IS NULL OR jsonb_typeof(before) = 'object'", name="activity_log_before_object"
        ),
        sa.CheckConstraint(
            "after IS NULL OR jsonb_typeof(after) = 'object'", name="activity_log_after_object"
        ),
    )
    op.create_index(
        "ix_activity_log_object",
        "activity_log",
        ["tenant_id", "object_type", "object_id", "created_at"],
    )
    op.create_index("ix_activity_log_created", "activity_log", ["tenant_id", "created_at"])
    op.create_index(
        "ix_activity_log_actor", "activity_log", ["tenant_id", "actor_id", "created_at"]
    )
    enable_tenant_rls("activity_log")
    # A supplier session may append audit rows but never read them (writers never use RETURNING).
    enable_supplier_scoped_rls("activity_log", select_predicate="false", insert=True)
    append_only("activity_log")
    add_updated_at_trigger("activity_log")

    # ------------------------------------------------------------------ outbox_events
    op.create_table(
        "outbox_events",
        *std_columns(),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("processed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        *std_constraints("outbox_events"),
        sa.UniqueConstraint("tenant_id", "event_id", name="outbox_events_tenant_id_event_id_key"),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="outbox_events_payload_object"),
        sa.CheckConstraint("attempts >= 0", name="outbox_events_attempts_non_negative"),
    )
    # Cross-tenant dispatcher scans (DATA_MODEL 0.4): used only through app_claim_outbox_batch().
    op.create_index(
        "outbox_events_pending_idx",
        "outbox_events",
        ["created_at"],
        postgresql_where=sa.text("processed_at IS NULL AND attempts < 5"),
    )
    op.create_index(
        "outbox_events_dead_idx",
        "outbox_events",
        ["created_at"],
        postgresql_where=sa.text("processed_at IS NULL AND attempts >= 5"),
    )
    op.create_index(
        "ix_outbox_events_aggregate",
        "outbox_events",
        ["tenant_id", "aggregate_type", "aggregate_id", "created_at"],
    )
    enable_tenant_rls("outbox_events")
    enable_supplier_scoped_rls("outbox_events", select_predicate="false", insert=True)
    add_updated_at_trigger("outbox_events")
    # CR + u(processed_at, attempts, last_error, updated_*): the event itself is immutable.
    op.execute(f"REVOKE UPDATE ON outbox_events FROM {APP}")
    op.execute(
        "GRANT UPDATE (processed_at, attempts, last_error, updated_at, updated_by) "
        f"ON outbox_events TO {APP}"
    )

    # ------------------------------------------------------------------ idempotency_keys (A-73)
    op.create_table(
        "idempotency_keys",
        *std_columns(),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        _jsonb("response_body"),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        *std_constraints("idempotency_keys"),
        sa.UniqueConstraint(
            "tenant_id", "actor_id", "key", name="idempotency_keys_tenant_id_actor_id_key_key"
        ),
        sa.CheckConstraint(
            "response_status IS NULL OR response_status BETWEEN 100 AND 599",
            name="idempotency_keys_status_range",
        ),
    )
    # Expiry cleanup scans across tenants (DATA_MODEL 9): the second documented non-tenant-first index.
    op.create_index("ix_idempotency_keys_expires", "idempotency_keys", ["expires_at"])
    enable_tenant_rls("idempotency_keys")
    actor_is_me = "actor_id = app_guc_uuid('app.actor_id')"
    enable_supplier_scoped_rls(
        "idempotency_keys", select_predicate=actor_is_me, insert=True, update_predicate=actor_is_me
    )
    add_updated_at_trigger("idempotency_keys")
    op.execute(f"GRANT DELETE ON idempotency_keys TO {APP}")  # expiry cleanup only (never suppliers)

    # ------------------------------------------------------------------ job_dead_letters (A-89)
    op.create_table(
        "job_dead_letters",
        *std_columns(),
        sa.Column("queue", sa.Text(), nullable=False),
        sa.Column("actor_name", sa.Text(), nullable=False),
        sa.Column("message_id", sa.Text(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=True),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("dead_lettered_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.UUID(), nullable=True),
        *std_constraints("job_dead_letters"),
        sa.UniqueConstraint("tenant_id", "message_id", name="job_dead_letters_tenant_id_message_id_key"),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="job_dead_letters_payload_object"),
        sa.CheckConstraint("attempts > 0", name="job_dead_letters_attempts_positive"),
    )
    op.create_index(
        "ix_job_dead_letters_unresolved",
        "job_dead_letters",
        ["tenant_id", "dead_lettered_at"],
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    enable_tenant_rls("job_dead_letters")
    add_updated_at_trigger("job_dead_letters")
    op.execute(f"REVOKE UPDATE ON job_dead_letters FROM {APP}")
    op.execute(
        "GRANT UPDATE (resolved_at, resolved_by, updated_at, updated_by) "
        f"ON job_dead_letters TO {APP}"
    )

    # ------------------------------------------------------------------ definer functions (DATA_MODEL 8)
    # Owner qualloop_sysfn, pinned search_path, schema-qualified tables, ids only, EXECUTE for the app role only.
    # sysfn is NOBYPASSRLS: it sees rows only through the role-specific *_sysfn policies below, and only the
    # columns granted to it.
    op.execute(f"GRANT SELECT (id) ON tenants TO {SYSFN}")
    op.execute(
        "CREATE POLICY tenants_sysfn ON tenants AS PERMISSIVE FOR SELECT TO "
        f"{SYSFN} USING (true)"
    )
    op.execute(f"GRANT SELECT (id, tenant_id, email) ON users TO {SYSFN}")
    op.execute(
        "CREATE POLICY users_sysfn_login ON users AS PERMISSIVE FOR SELECT TO "
        f"{SYSFN} USING (true)"
    )
    op.execute(f"GRANT SELECT ON outbox_events TO {SYSFN}")
    op.execute(f"GRANT UPDATE (processed_at) ON outbox_events TO {SYSFN}")  # needed for FOR UPDATE
    op.execute(
        "CREATE POLICY outbox_sysfn_select ON outbox_events AS PERMISSIVE FOR SELECT TO "
        f"{SYSFN} USING (true)"
    )
    op.execute(
        "CREATE POLICY outbox_sysfn_update ON outbox_events AS PERMISSIVE FOR UPDATE TO "
        f"{SYSFN} USING (true) WITH CHECK (true)"
    )

    op.execute(
        f"""
        CREATE FUNCTION app_resolve_login(p_email text)
        RETURNS TABLE (tenant_id uuid, user_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER {SAFE_PATH} AS
        $$
          SELECT u.tenant_id, u.id FROM public.users u WHERE lower(u.email) = lower(p_email)
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION app_active_tenant_ids()
        RETURNS SETOF uuid
        LANGUAGE sql STABLE SECURITY DEFINER {SAFE_PATH} AS
        $$
          SELECT t.id FROM public.tenants t
        $$
        """
    )
    # Backoff: a failed event is claimable again once updated_at + 5 s x 2^attempts has passed (ADR-006).
    # Rows with attempts >= 5 are dead letters and are never claimed.
    op.execute(
        f"""
        CREATE FUNCTION app_claim_outbox_batch(p_limit integer)
        RETURNS TABLE (id uuid, tenant_id uuid, event_id uuid, event_type text, aggregate_type text,
                       aggregate_id uuid, payload jsonb, attempts integer)
        LANGUAGE sql VOLATILE SECURITY DEFINER {SAFE_PATH} AS
        $$
          SELECT o.id, o.tenant_id, o.event_id, o.event_type, o.aggregate_type, o.aggregate_id,
                 o.payload, o.attempts
            FROM public.outbox_events o
           WHERE o.processed_at IS NULL
             AND o.attempts < 5
             AND (o.attempts = 0
                  OR o.updated_at + (5 * power(2, o.attempts)) * interval '1 second' <= now())
           ORDER BY o.created_at, o.id
           LIMIT p_limit
             FOR UPDATE OF o SKIP LOCKED
        $$
        """
    )
    for signature in DEFINER_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {APP}")
    # ALTER FUNCTION ... OWNER needs CREATE on the schema for the new owner; held only inside this migration.
    op.execute(f"GRANT CREATE ON SCHEMA public TO {SYSFN}")
    for signature in DEFINER_FUNCTIONS:
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {SYSFN}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {SYSFN}")


def downgrade() -> None:
    # Functions are owned by qualloop_sysfn; the owner can SET ROLE to it but does not inherit its privileges.
    op.execute(f"SET LOCAL ROLE {SYSFN}")
    for signature in DEFINER_FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {signature}")
    op.execute("RESET ROLE")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("DROP FUNCTION IF EXISTS trg_users_plant_ids_valid()")
