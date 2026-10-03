"""masters and imports: suppliers, supplier_contacts, contact_consents, customers, parts, customer_parts,
supplier_parts, import_batches, import_records

DATA_MODEL sections 0, 2 and 7. All nine tables are tenant tables (forced RLS, supplier sessions denied by default:
the supplier-scoped policies of `parts` and `supplier_contacts` read tables of P04/P05 and land with them).
No table holds data at migration time, so no data step is needed (DATA_MODEL 0.9).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from helpers import (
    add_updated_at_trigger,
    append_only,
    enable_tenant_rls,
    std_columns,
    std_constraints,
)
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP = "qualloop_app"

# Creation order; the downgrade drops in reverse.
TABLES = (
    "suppliers",
    "supplier_contacts",
    "contact_consents",
    "customers",
    "parts",
    "customer_parts",
    "supplier_parts",
    "import_batches",
    "import_records",
)


def _fk(cols: list[str], target: str, name: str) -> sa.ForeignKeyConstraint:
    """Composite FK on (tenant_id, x_id) -> target(tenant_id, id), RESTRICT (DATA_MODEL 0.3)."""
    return sa.ForeignKeyConstraint(
        ["tenant_id", *cols], [f"{target}.tenant_id", f"{target}.id"], name=name
    )


def _grant_updates(table: str, columns: str) -> None:
    """Column-level UPDATE only: id, tenant_id and the creation audit columns are never updatable."""
    op.execute(f"REVOKE UPDATE ON {table} FROM {APP}")
    op.execute(f"GRANT UPDATE ({columns}) ON {table} TO {APP}")


def upgrade() -> None:
    # ------------------------------------------------------------------ suppliers
    op.create_table(
        "suppliers",
        *std_columns(),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("gstin", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("status_changed_by", sa.UUID(), nullable=True),
        sa.Column("status_changed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
        *std_constraints("suppliers"),
        sa.UniqueConstraint("tenant_id", "code", name="suppliers_tenant_id_code_key"),
        _fk(["status_changed_by"], "users", "suppliers_status_changed_by_fkey"),
        sa.CheckConstraint(
            "category IN ('raw_material','bought_out','job_work','service')",
            name="suppliers_category_values",
        ),
        sa.CheckConstraint(
            "status IN ('approved','approved_with_action_plan','on_watch','blocked','inactive')",
            name="suppliers_status_values",
        ),
        sa.CheckConstraint(
            "status_changed_at IS NULL OR status_reason IS NOT NULL",
            name="suppliers_status_reason_present",
        ),
        sa.CheckConstraint("gstin ~ '^[0-9A-Z]{15}$'", name="suppliers_gstin_format"),  # A-90
        sa.CheckConstraint("length(btrim(code)) > 0", name="suppliers_code_not_blank"),  # A-90
        sa.CheckConstraint("length(btrim(name)) > 0", name="suppliers_name_not_blank"),  # A-90
    )
    op.create_index("ix_suppliers_gstin", "suppliers", ["tenant_id", "gstin"])
    op.create_index(
        "ix_suppliers_name_city",
        "suppliers",
        ["tenant_id", sa.text("lower(name)"), sa.text("lower(city)")],
    )
    op.create_index("ix_suppliers_status", "suppliers", ["tenant_id", "status"])
    op.create_index("ix_suppliers_category", "suppliers", ["tenant_id", "category"])
    # List-sort indexes (DATA_MODEL 0.7, API.md 5.1)
    op.create_index(
        "ix_suppliers_name",
        "suppliers",
        ["tenant_id", sa.text("lower(name)"), "id"],
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_index("ix_suppliers_code", "suppliers", ["tenant_id", "code", "id"])
    op.create_index(
        "ix_suppliers_updated",
        "suppliers",
        ["tenant_id", sa.text("updated_at DESC"), sa.text("id DESC")],
    )
    enable_tenant_rls("suppliers")
    add_updated_at_trigger("suppliers")
    _grant_updates(
        "suppliers",
        "code, name, gstin, city, state, category, status, status_reason, status_changed_by, "
        "status_changed_at, archived_at, updated_at, updated_by",
    )

    # ------------------------------------------------------------------ supplier_contacts
    op.create_table(
        "supplier_contacts",
        *std_columns(),
        sa.Column("supplier_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("mobile", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("is_quality_contact", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verified_mobile_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("verified_email_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("disabled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("disabled_reason", sa.Text(), nullable=True),
        sa.Column("replaced_by_contact_id", sa.UUID(), nullable=True),
        *std_constraints("supplier_contacts"),
        _fk(["supplier_id"], "suppliers", "supplier_contacts_supplier_id_fkey"),
        _fk(
            ["replaced_by_contact_id"],
            "supplier_contacts",
            "supplier_contacts_replaced_by_contact_id_fkey",
        ),
        sa.CheckConstraint(
            "NOT active OR mobile IS NOT NULL OR email IS NOT NULL",
            name="supplier_contacts_active_has_destination",
        ),
        sa.CheckConstraint(
            "active OR (disabled_at IS NOT NULL AND disabled_reason IS NOT NULL)",
            name="supplier_contacts_disabled_has_reason",
        ),
        sa.CheckConstraint(
            "replaced_by_contact_id <> id", name="supplier_contacts_not_replaced_by_itself"
        ),
        sa.CheckConstraint(
            r"mobile ~ '^\+[1-9][0-9]{7,14}$'", name="supplier_contacts_mobile_e164"
        ),  # A-90
        sa.CheckConstraint("length(btrim(name)) > 0", name="supplier_contacts_name_not_blank"),
    )
    op.create_index(
        "ix_supplier_contacts_supplier", "supplier_contacts", ["tenant_id", "supplier_id"]
    )
    op.create_index("ix_supplier_contacts_mobile", "supplier_contacts", ["tenant_id", "mobile"])
    op.create_index(
        "ix_supplier_contacts_email", "supplier_contacts", ["tenant_id", sa.text("lower(email)")]
    )
    # DATA_MODEL 0.4: a WhatsApp STOP reply arrives with only a phone number (A-67); read through a definer function.
    op.create_index("supplier_contacts_mobile_idx", "supplier_contacts", ["mobile"])
    enable_tenant_rls("supplier_contacts")
    add_updated_at_trigger("supplier_contacts")
    _grant_updates(
        "supplier_contacts",
        "name, role, mobile, email, is_quality_contact, verified_mobile_at, verified_email_at, "
        "active, disabled_at, disabled_reason, replaced_by_contact_id, updated_at, updated_by",
    )

    # ------------------------------------------------------------------ contact_consents
    op.create_table(
        "contact_consents",
        *std_columns(),
        sa.Column("contact_id", sa.UUID(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("consent_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        *std_constraints("contact_consents"),
        _fk(["contact_id"], "supplier_contacts", "contact_consents_contact_id_fkey"),
        sa.CheckConstraint(
            "channel IN ('whatsapp','email','sms')", name="contact_consents_channel_values"
        ),
        sa.CheckConstraint(
            "status IN ('opted_in','opted_out')", name="contact_consents_status_values"
        ),
        sa.CheckConstraint(
            "source IN ('otp_verification','import','manual','stop_reply','supplier_link')",
            name="contact_consents_source_values",
        ),  # A-90
        sa.CheckConstraint(
            "(status = 'opted_out') = (revoked_at IS NOT NULL)",
            name="contact_consents_revoked_matches_status",
        ),
    )
    op.create_index(
        "contact_consents_one_opt_in_uq",
        "contact_consents",
        ["tenant_id", "contact_id", "channel"],
        unique=True,
        postgresql_where=sa.text("status = 'opted_in'"),
    )
    op.create_index(
        "ix_contact_consents_contact",
        "contact_consents",
        ["tenant_id", "contact_id", "channel", sa.text("consent_at DESC")],
    )
    enable_tenant_rls("contact_consents")
    add_updated_at_trigger("contact_consents")
    _grant_updates("contact_consents", "status, revoked_at, updated_at, updated_by")

    # ------------------------------------------------------------------ customers
    op.create_table(
        "customers",
        *std_columns(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
        *std_constraints("customers"),
        sa.UniqueConstraint("tenant_id", "code", name="customers_tenant_id_code_key"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="customers_name_not_blank"),
        sa.CheckConstraint("length(btrim(code)) > 0", name="customers_code_not_blank"),
    )
    enable_tenant_rls("customers")
    add_updated_at_trigger("customers")
    _grant_updates("customers", "name, archived_at, updated_at, updated_by")

    # ------------------------------------------------------------------ parts
    op.create_table(
        "parts",
        *std_columns(),
        sa.Column("part_no", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("current_revision", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
        *std_constraints("parts"),
        sa.UniqueConstraint("tenant_id", "part_no", name="parts_tenant_id_part_no_key"),
        sa.CheckConstraint("length(btrim(part_no)) > 0", name="parts_part_no_not_blank"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="parts_name_not_blank"),
    )
    op.create_index("ix_parts_part_no", "parts", ["tenant_id", "part_no", "id"])
    enable_tenant_rls("parts")  # supplier-scoped read arrives with ncrs (P04)
    add_updated_at_trigger("parts")
    _grant_updates("parts", "name, category, current_revision, archived_at, updated_at, updated_by")

    # ------------------------------------------------------------------ customer_parts
    op.create_table(
        "customer_parts",
        *std_columns(),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("part_id", sa.UUID(), nullable=False),
        sa.Column("customer_part_no", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
        *std_constraints("customer_parts"),
        sa.UniqueConstraint("tenant_id", "customer_id", "part_id", name="customer_parts_pair_key"),
        _fk(["customer_id"], "customers", "customer_parts_customer_id_fkey"),
        _fk(["part_id"], "parts", "customer_parts_part_id_fkey"),
    )
    op.create_index("ix_customer_parts_part", "customer_parts", ["tenant_id", "part_id"])
    enable_tenant_rls("customer_parts")
    add_updated_at_trigger("customer_parts")
    _grant_updates("customer_parts", "customer_part_no, archived_at, updated_at, updated_by")

    # ------------------------------------------------------------------ supplier_parts
    op.create_table(
        "supplier_parts",
        *std_columns(),
        sa.Column("supplier_id", sa.UUID(), nullable=False),
        sa.Column("part_id", sa.UUID(), nullable=False),
        sa.Column("supplier_part_no", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("ppm_target", sa.Integer(), nullable=True),
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
        *std_constraints("supplier_parts"),
        sa.UniqueConstraint("tenant_id", "supplier_id", "part_id", name="supplier_parts_pair_key"),
        _fk(["supplier_id"], "suppliers", "supplier_parts_supplier_id_fkey"),
        _fk(["part_id"], "parts", "supplier_parts_part_id_fkey"),
        sa.CheckConstraint("status IN ('active','inactive')", name="supplier_parts_status_values"),
        sa.CheckConstraint(
            "ppm_target IS NULL OR ppm_target > 0", name="supplier_parts_ppm_target_positive"
        ),  # A-54
    )
    op.create_index("ix_supplier_parts_part", "supplier_parts", ["tenant_id", "part_id"])
    enable_tenant_rls("supplier_parts")
    add_updated_at_trigger("supplier_parts")
    _grant_updates(
        "supplier_parts",
        "supplier_part_no, status, ppm_target, archived_at, updated_at, updated_by",
    )

    # ------------------------------------------------------------------ import_batches
    op.create_table(
        "import_batches",
        *std_columns(),
        sa.Column("entity", sa.Text(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("file_hash", sa.Text(), nullable=False),
        sa.Column("mapping", pg.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        *[
            sa.Column(c, sa.Integer(), nullable=False, server_default="0")
            for c in (
                "rows_received",
                "rows_valid",
                "rows_imported",
                "rows_duplicate",
                "rows_rejected",
                "rows_unmapped",
                "rows_review",
            )
        ],
        sa.Column("started_by", sa.UUID(), nullable=False),
        sa.Column("confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        *std_constraints("import_batches"),
        _fk(["started_by"], "users", "import_batches_started_by_fkey"),
        sa.CheckConstraint(
            "entity IN ('suppliers','parts','supplier_parts','receipts','ncrs','certificates_meta')",
            name="import_batches_entity_values",
        ),
        sa.CheckConstraint(
            "status IN ('uploaded','mapped','validated','importing','completed','failed','cancelled')",
            name="import_batches_status_values",
        ),
        sa.CheckConstraint(
            "status NOT IN ('importing','completed') OR confirmed_at IS NOT NULL",
            name="import_batches_confirmed_at_present",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(mapping) = 'object'", name="import_batches_mapping_object"
        ),
        sa.CheckConstraint(
            "rows_received >= 0 AND rows_valid >= 0 AND rows_imported >= 0 AND rows_duplicate >= 0 "
            "AND rows_rejected >= 0 AND rows_unmapped >= 0 AND rows_review >= 0",
            name="import_batches_counts_non_negative",
        ),
    )
    op.create_index("ix_import_batches_file_hash", "import_batches", ["tenant_id", "file_hash"])
    op.create_index(
        "ix_import_batches_entity_created",
        "import_batches",
        ["tenant_id", "entity", "created_at"],
    )
    op.create_index(
        "ix_import_batches_created",
        "import_batches",
        ["tenant_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )
    enable_tenant_rls("import_batches")
    add_updated_at_trigger("import_batches")
    _grant_updates(
        "import_batches",
        "file_name, mapping, status, rows_received, rows_valid, rows_imported, rows_duplicate, "
        "rows_rejected, rows_unmapped, rows_review, confirmed_at, updated_at, updated_by",
    )

    # ------------------------------------------------------------------ import_records (append-only)
    op.create_table(
        "import_records",
        *std_columns(),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("row_hash", sa.Text(), nullable=False),
        sa.Column("source_record_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("target_id", sa.UUID(), nullable=True),
        *std_constraints("import_records"),
        _fk(["batch_id"], "import_batches", "import_records_batch_id_fkey"),
        sa.CheckConstraint("row_number >= 1", name="import_records_row_number_positive"),
        sa.CheckConstraint(
            "status IN ('imported','duplicate','rejected','unmapped','review')",
            name="import_records_status_values",
        ),
        sa.CheckConstraint(
            "status = 'imported' OR reason IS NOT NULL", name="import_records_reason_present"
        ),
        sa.CheckConstraint(
            "status <> 'imported' OR target_id IS NOT NULL", name="import_records_target_present"
        ),
    )
    op.create_index(
        "ix_import_records_batch_row",
        "import_records",
        ["tenant_id", "batch_id", "row_number"],
        unique=True,
    )
    op.create_index("ix_import_records_row_hash", "import_records", ["tenant_id", "row_hash"])
    op.create_index("ix_import_records_source", "import_records", ["tenant_id", "source_record_id"])
    enable_tenant_rls("import_records")
    append_only("import_records")
    add_updated_at_trigger("import_records")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
