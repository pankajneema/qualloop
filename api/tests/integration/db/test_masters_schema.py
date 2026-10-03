"""DATA_MODEL 2 (masters) and 7 (imports): constraints, uniqueness, composite foreign keys, grants, policies and the
list-sort indexes of 0.7. Every statement runs as `qualloop_app` under a tenant GUC; DDL facts come from the owner
connection's catalog reads."""

from typing import Any
from uuid import UUID, uuid4

import psycopg.errors
import pytest
from sqlalchemy import Connection, Engine, text

from tests.factories.db import create_tenant, tenant_conn
from tests.factories.dberr import expect_db_error
from tests.factories.rows import MASTERS_TABLES

pytestmark = pytest.mark.integration

CHECK = psycopg.errors.CheckViolation
UNIQUE = psycopg.errors.UniqueViolation
FK = psycopg.errors.ForeignKeyViolation
DENIED = psycopg.errors.InsufficientPrivilege
APPEND_ONLY = psycopg.errors.IntegrityConstraintViolation


def insert(conn: Connection, table: str, tenant: UUID, **cols: Any) -> UUID:
    cols = {"id": uuid4(), "tenant_id": tenant, **cols}
    names = ", ".join(cols)
    binds = ", ".join(f"CAST(:{k} AS jsonb)" if k == "mapping" else f":{k}" for k in cols)
    conn.execute(text(f"INSERT INTO {table} ({names}) VALUES ({binds})"), cols)
    return cols["id"]  # type: ignore[no-any-return]


def supplier(conn: Connection, tenant: UUID, **over: Any) -> UUID:
    cols = {
        "code": uuid4().hex[:10],
        "name": "Acme",
        "category": "bought_out",
        "status": "approved",
        **over,
    }
    return insert(conn, "suppliers", tenant, **cols)


def contact(conn: Connection, tenant: UUID, supplier_id: UUID | None = None, **over: Any) -> UUID:
    cols = {
        "supplier_id": supplier_id or supplier(conn, tenant),
        "name": "Asha",
        "mobile": "+919876543210",
        **over,
    }
    return insert(conn, "supplier_contacts", tenant, **cols)


def part(conn: Connection, tenant: UUID, **over: Any) -> UUID:
    return insert(conn, "parts", tenant, **{"part_no": uuid4().hex[:8], "name": "Bracket", **over})


def customer(conn: Connection, tenant: UUID, **over: Any) -> UUID:
    return insert(conn, "customers", tenant, **{"name": "OEM", "code": uuid4().hex[:8], **over})


def user(conn: Connection, tenant: UUID) -> UUID:
    return insert(
        conn, "users", tenant, email=f"u.{uuid4().hex}@example.test", name="U", role="quality"
    )


def batch(conn: Connection, tenant: UUID, **over: Any) -> UUID:
    cols = {
        "entity": "suppliers",
        "file_name": "f.csv",
        "file_hash": uuid4().hex * 2,
        "mapping": "{}",
        "status": "uploaded",
        "started_by": user(conn, tenant),
        **over,
    }
    return insert(conn, "import_batches", tenant, **cols)


@pytest.fixture
def tenant(app_engine: Engine) -> UUID:
    return create_tenant(app_engine)


# =================================================================================================
# suppliers
# =================================================================================================
@pytest.mark.parametrize(
    "status", ["approved", "approved_with_action_plan", "on_watch", "blocked", "inactive"]
)
def test_supplier_status_accepts_the_five_values(
    app_engine: Engine, tenant: UUID, status: str
) -> None:
    with tenant_conn(app_engine, tenant) as conn:
        supplier(conn, tenant, status=status)


@pytest.mark.parametrize("status", ["suspended", "APPROVED", "approved ", "", "pending", "active"])
def test_supplier_status_rejects_other_values(
    app_engine: Engine, tenant: UUID, status: str
) -> None:
    with expect_db_error(CHECK), tenant_conn(app_engine, tenant) as conn:
        supplier(conn, tenant, status=status)


@pytest.mark.parametrize("category", ["raw_material", "bought_out", "job_work", "service"])
def test_supplier_category_accepts_the_four_values(
    app_engine: Engine, tenant: UUID, category: str
) -> None:
    with tenant_conn(app_engine, tenant) as conn:
        supplier(conn, tenant, category=category)


@pytest.mark.parametrize("category", ["plastic", "Raw Material", "", "raw-material"])
def test_supplier_category_rejects_other_values(
    app_engine: Engine, tenant: UUID, category: str
) -> None:
    with expect_db_error(CHECK), tenant_conn(app_engine, tenant) as conn:
        supplier(conn, tenant, category=category)


@pytest.mark.parametrize("gstin", ["27AAAAA0001A1Z5", "123456789012345", "ABCDEFGHIJKLMNO", None])
def test_supplier_gstin_accepts_fifteen_uppercase_alphanumerics_or_null(
    app_engine: Engine, tenant: UUID, gstin: str | None
) -> None:
    with tenant_conn(app_engine, tenant) as conn:
        supplier(conn, tenant, gstin=gstin)


@pytest.mark.parametrize(
    "gstin",
    [
        "27AAAAA0001A1Z",
        "27AAAAA0001A1Z55",
        "27aaaaa0001a1z5",
        "27AAAAA0001A1Z!",
        "27 AAAA0001A1Z5",
        "",
    ],
)
def test_supplier_gstin_rejects_other_shapes(app_engine: Engine, tenant: UUID, gstin: str) -> None:
    with expect_db_error(CHECK), tenant_conn(app_engine, tenant) as conn:
        supplier(conn, tenant, gstin=gstin)


def test_supplier_gstin_is_not_unique_duplicates_are_reported_never_merged(
    app_engine: Engine, tenant: UUID
) -> None:
    with tenant_conn(app_engine, tenant) as conn:
        supplier(conn, tenant, gstin="27AAAAA0001A1Z5")
        supplier(conn, tenant, gstin="27AAAAA0001A1Z5")
        assert (
            conn.execute(
                text("SELECT count(*) FROM suppliers WHERE gstin = '27AAAAA0001A1Z5'")
            ).scalar_one()
            == 2
        )


def test_supplier_code_is_unique_per_tenant_and_reusable_across_tenants(
    app_engine: Engine, tenant: UUID
) -> None:
    other = create_tenant(app_engine)
    with tenant_conn(app_engine, tenant) as conn:
        supplier(conn, tenant, code="DUP")
    with expect_db_error(UNIQUE), tenant_conn(app_engine, tenant) as conn:
        supplier(conn, tenant, code="DUP")
    with tenant_conn(app_engine, other) as conn:
        supplier(conn, other, code="DUP")


def test_supplier_status_changed_at_requires_a_status_reason(
    app_engine: Engine, tenant: UUID
) -> None:
    with expect_db_error(CHECK), tenant_conn(app_engine, tenant) as conn:
        supplier(
            conn,
            tenant,
            status="blocked",
            status_changed_at="2026-10-01T00:00:00Z",
            status_reason=None,
        )
    with tenant_conn(app_engine, tenant) as conn:
        supplier(
            conn,
            tenant,
            status="blocked",
            status_changed_at="2026-10-01T00:00:00Z",
            status_reason="Quality hold",
        )
        supplier(conn, tenant)  # never changed: no reason needed


def test_supplier_name_code_category_and_status_are_required(
    app_engine: Engine, tenant: UUID
) -> None:
    full = {"code": "C1", "name": "N", "category": "service", "status": "approved"}
    for missing in full:
        cols = {k: v for k, v in full.items() if k != missing}
        with (
            expect_db_error(psycopg.errors.NotNullViolation),
            tenant_conn(app_engine, tenant) as conn,
        ):
            insert(conn, "suppliers", tenant, **cols)


# =================================================================================================
# supplier_contacts
# =================================================================================================
def test_contact_defaults(app_engine: Engine, tenant: UUID) -> None:
    with tenant_conn(app_engine, tenant) as conn:
        cid = contact(conn, tenant)
        row = conn.execute(
            text(
                "SELECT is_quality_contact, active, disabled_at, replaced_by_contact_id FROM supplier_contacts WHERE id = :i"
            ),
            {"i": cid},
        ).one()
    assert tuple(row) == (False, True, None, None)


def test_an_active_contact_needs_a_mobile_or_an_email(app_engine: Engine, tenant: UUID) -> None:
    with expect_db_error(CHECK), tenant_conn(app_engine, tenant) as conn:
        contact(conn, tenant, mobile=None, email=None)
    with tenant_conn(app_engine, tenant) as conn:
        contact(conn, tenant, mobile=None, email="a@supplier.example.test")
        contact(conn, tenant, mobile="+919876543210", email=None)


def test_an_inactive_contact_needs_disabled_at_and_a_reason(
    app_engine: Engine, tenant: UUID
) -> None:
    for cols in (
        {"active": False},
        {"active": False, "disabled_at": "2026-10-01T00:00:00Z"},
        {"active": False, "disabled_reason": "Left"},
    ):
        with expect_db_error(CHECK), tenant_conn(app_engine, tenant) as conn:
            contact(conn, tenant, **cols)
    with tenant_conn(app_engine, tenant) as conn:
        contact(
            conn, tenant, active=False, disabled_at="2026-10-01T00:00:00Z", disabled_reason="Left"
        )
        contact(
            conn,
            tenant,
            active=False,
            mobile=None,
            email=None,
            disabled_at="2026-10-01T00:00:00Z",
            disabled_reason="Left",
        )


@pytest.mark.parametrize("mobile", ["+919876543210", "+14155552671", "+4402079460958"])
def test_contact_mobile_accepts_e164(app_engine: Engine, tenant: UUID, mobile: str) -> None:
    with tenant_conn(app_engine, tenant) as conn:
        contact(conn, tenant, mobile=mobile)


@pytest.mark.parametrize(
    "mobile", ["9876543210", "98765 43210", "+0123456789", "+91-9876543210", "+91987", "abc", ""]
)
def test_contact_mobile_rejects_non_e164(app_engine: Engine, tenant: UUID, mobile: str) -> None:
    with expect_db_error(CHECK), tenant_conn(app_engine, tenant) as conn:
        contact(conn, tenant, mobile=mobile)


def test_a_contact_cannot_be_replaced_by_itself(app_engine: Engine, tenant: UUID) -> None:
    with tenant_conn(app_engine, tenant) as conn:
        cid = contact(conn, tenant)
    with expect_db_error(CHECK), tenant_conn(app_engine, tenant) as conn:
        conn.execute(
            text("UPDATE supplier_contacts SET replaced_by_contact_id = id WHERE id = :i"),
            {"i": cid},
        )


def test_replaced_by_must_be_a_contact_of_the_same_tenant(app_engine: Engine, tenant: UUID) -> None:
    other = create_tenant(app_engine)
    with tenant_conn(app_engine, other) as conn:
        foreign = contact(conn, other)
    with tenant_conn(app_engine, tenant) as conn:
        mine = contact(conn, tenant)
    with expect_db_error(FK), tenant_conn(app_engine, tenant) as conn:
        conn.execute(
            text("UPDATE supplier_contacts SET replaced_by_contact_id = :f WHERE id = :i"),
            {"f": foreign, "i": mine},
        )


def test_contact_supplier_must_belong_to_the_same_tenant(app_engine: Engine, tenant: UUID) -> None:
    """A composite FK: knowing another tenant's supplier id is not enough to attach a contact to it."""
    other = create_tenant(app_engine)
    with tenant_conn(app_engine, other) as conn:
        foreign_supplier = supplier(conn, other)
    with expect_db_error(FK), tenant_conn(app_engine, tenant) as conn:
        contact(conn, tenant, supplier_id=foreign_supplier)


# =================================================================================================
# contact_consents
# =================================================================================================
def consent(conn: Connection, tenant: UUID, contact_id: UUID, **over: Any) -> UUID:
    cols = {
        "contact_id": contact_id,
        "channel": "whatsapp",
        "status": "opted_in",
        "source": "manual",
        "consent_at": "2026-10-01T00:00:00Z",
        **over,
    }
    return insert(conn, "contact_consents", tenant, **cols)


@pytest.mark.parametrize(
    "cols",
    [
        {"channel": "telegram"},
        {"status": "maybe"},
        {"source": "carrier_pigeon"},
        {"status": "opted_out"},  # opted_out needs revoked_at
        {"revoked_at": "2026-10-02T00:00:00Z"},  # opted_in must not have revoked_at
    ],
    ids=["channel", "status", "source", "opted-out-no-revoked", "opted-in-with-revoked"],
)
def test_consent_checks(app_engine: Engine, tenant: UUID, cols: dict[str, Any]) -> None:
    with tenant_conn(app_engine, tenant) as conn:
        cid = contact(conn, tenant)
    with expect_db_error(CHECK), tenant_conn(app_engine, tenant) as conn:
        consent(conn, tenant, cid, **cols)


@pytest.mark.parametrize(
    "source", ["otp_verification", "import", "manual", "stop_reply", "supplier_link"]
)
def test_consent_source_accepts_the_documented_values(
    app_engine: Engine, tenant: UUID, source: str
) -> None:
    with tenant_conn(app_engine, tenant) as conn:
        consent(conn, tenant, contact(conn, tenant), source=source)


def test_only_one_opted_in_consent_per_contact_and_channel_but_history_is_kept(
    app_engine: Engine, tenant: UUID
) -> None:
    with tenant_conn(app_engine, tenant) as conn:
        cid = contact(conn, tenant)
        consent(conn, tenant, cid)
        consent(conn, tenant, cid, channel="email")  # another channel is independent
    with expect_db_error(UNIQUE), tenant_conn(app_engine, tenant) as conn:
        consent(conn, tenant, cid)
    with tenant_conn(app_engine, tenant) as conn:
        conn.execute(
            text(
                "UPDATE contact_consents SET status = 'opted_out', revoked_at = now() WHERE contact_id = :c AND channel = 'whatsapp'"
            ),
            {"c": cid},
        )
        consent(conn, tenant, cid)  # re-opt-in inserts a new row
        n = conn.execute(
            text(
                "SELECT count(*) FROM contact_consents WHERE contact_id = :c AND channel = 'whatsapp'"
            ),
            {"c": cid},
        ).scalar_one()
    assert n == 2


def test_consent_update_grant_is_limited_to_status_revoked_at_and_audit_columns(
    owner_engine: Engine,
) -> None:
    with owner_engine.connect() as conn:
        allowed = {
            c
            for (c,) in conn.execute(
                text(
                    "SELECT attname FROM pg_attribute WHERE attrelid = 'public.contact_consents'::regclass "
                    "AND attnum > 0 AND NOT attisdropped "
                    "AND has_column_privilege('qualloop_app', 'public.contact_consents', attname, 'UPDATE')"
                )
            )
        }
    assert allowed == {"status", "revoked_at", "updated_at", "updated_by"}


def test_consent_time_and_channel_cannot_be_rewritten(app_engine: Engine, tenant: UUID) -> None:
    with tenant_conn(app_engine, tenant) as conn:
        consent(conn, tenant, contact(conn, tenant))
    for column, value in (
        ("consent_at", "now()"),
        ("channel", "'email'"),
        ("source", "'import'"),
        ("contact_id", "gen_random_uuid()"),
    ):
        with expect_db_error(DENIED, "permission denied"), tenant_conn(app_engine, tenant) as conn:
            conn.execute(text(f"UPDATE contact_consents SET {column} = {value}"))


# =================================================================================================
# customers, parts, customer_parts, supplier_parts
# =================================================================================================
def test_customer_code_and_part_no_are_unique_per_tenant(app_engine: Engine, tenant: UUID) -> None:
    other = create_tenant(app_engine)
    with tenant_conn(app_engine, tenant) as conn:
        customer(conn, tenant, code="OEM")
        part(conn, tenant, part_no="PN-1")
    with expect_db_error(UNIQUE), tenant_conn(app_engine, tenant) as conn:
        customer(conn, tenant, code="OEM")
    with expect_db_error(UNIQUE), tenant_conn(app_engine, tenant) as conn:
        part(conn, tenant, part_no="PN-1")
    with tenant_conn(app_engine, other) as conn:
        customer(conn, other, code="OEM")
        part(conn, other, part_no="PN-1")


def test_parts_has_no_customer_id_column(owner_engine: Engine) -> None:
    with owner_engine.connect() as conn:
        cols = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'parts'"
                )
            )
        }
    assert "customer_id" not in cols
    assert {"part_no", "name", "category", "current_revision", "archived_at"} <= cols


def test_part_can_link_to_many_customers_in_the_schema(app_engine: Engine, tenant: UUID) -> None:
    with tenant_conn(app_engine, tenant) as conn:
        pid = part(conn, tenant)
        for _ in range(3):
            insert(conn, "customer_parts", tenant, customer_id=customer(conn, tenant), part_id=pid)
        assert (
            conn.execute(
                text("SELECT count(*) FROM customer_parts WHERE part_id = :p"), {"p": pid}
            ).scalar_one()
            == 3
        )


def test_customer_part_pair_is_unique(app_engine: Engine, tenant: UUID) -> None:
    with tenant_conn(app_engine, tenant) as conn:
        pid, cid = part(conn, tenant), customer(conn, tenant)
        insert(conn, "customer_parts", tenant, customer_id=cid, part_id=pid)
    with expect_db_error(UNIQUE), tenant_conn(app_engine, tenant) as conn:
        insert(conn, "customer_parts", tenant, customer_id=cid, part_id=pid)


def test_customer_part_cannot_reference_another_tenants_part(
    app_engine: Engine, tenant: UUID
) -> None:
    other = create_tenant(app_engine)
    with tenant_conn(app_engine, other) as conn:
        foreign = part(conn, other)
    with tenant_conn(app_engine, tenant) as conn:
        cid = customer(conn, tenant)
    with expect_db_error(FK), tenant_conn(app_engine, tenant) as conn:
        insert(conn, "customer_parts", tenant, customer_id=cid, part_id=foreign)


@pytest.mark.parametrize("status", ["active", "inactive"])
def test_supplier_part_status_accepts_active_and_inactive(
    app_engine: Engine, tenant: UUID, status: str
) -> None:
    with tenant_conn(app_engine, tenant) as conn:
        insert(
            conn,
            "supplier_parts",
            tenant,
            supplier_id=supplier(conn, tenant),
            part_id=part(conn, tenant),
            status=status,
        )


@pytest.mark.parametrize("status", ["archived", "ACTIVE", "", "pending"])
def test_supplier_part_status_rejects_other_values(
    app_engine: Engine, tenant: UUID, status: str
) -> None:
    with expect_db_error(CHECK), tenant_conn(app_engine, tenant) as conn:
        insert(
            conn,
            "supplier_parts",
            tenant,
            supplier_id=supplier(conn, tenant),
            part_id=part(conn, tenant),
            status=status,
        )


@pytest.mark.parametrize("ppm", [0, -1])
def test_supplier_part_ppm_target_must_be_positive_or_null(
    app_engine: Engine, tenant: UUID, ppm: int
) -> None:
    with expect_db_error(CHECK), tenant_conn(app_engine, tenant) as conn:
        insert(
            conn,
            "supplier_parts",
            tenant,
            supplier_id=supplier(conn, tenant),
            part_id=part(conn, tenant),
            status="active",
            ppm_target=ppm,
        )
    with tenant_conn(app_engine, tenant) as conn:
        insert(
            conn,
            "supplier_parts",
            tenant,
            supplier_id=supplier(conn, tenant),
            part_id=part(conn, tenant),
            status="active",
            ppm_target=None,
        )
        insert(
            conn,
            "supplier_parts",
            tenant,
            supplier_id=supplier(conn, tenant),
            part_id=part(conn, tenant),
            status="active",
            ppm_target=1,
        )


def test_supplier_part_pair_is_unique(app_engine: Engine, tenant: UUID) -> None:
    with tenant_conn(app_engine, tenant) as conn:
        sid, pid = supplier(conn, tenant), part(conn, tenant)
        insert(conn, "supplier_parts", tenant, supplier_id=sid, part_id=pid, status="active")
    with expect_db_error(UNIQUE), tenant_conn(app_engine, tenant) as conn:
        insert(conn, "supplier_parts", tenant, supplier_id=sid, part_id=pid, status="active")


# =================================================================================================
# import_batches / import_records
# =================================================================================================
@pytest.mark.parametrize(
    "entity", ["suppliers", "parts", "supplier_parts", "receipts", "ncrs", "certificates_meta"]
)
def test_import_batch_entity_accepts_the_six_blueprint_values(
    app_engine: Engine, tenant: UUID, entity: str
) -> None:
    with tenant_conn(app_engine, tenant) as conn:
        batch(conn, tenant, entity=entity)


@pytest.mark.parametrize(
    "status", ["uploaded", "mapped", "validated", "importing", "completed", "failed", "cancelled"]
)
def test_import_batch_status_accepts_the_seven_values(
    app_engine: Engine, tenant: UUID, status: str
) -> None:
    extra = {"confirmed_at": "2026-10-01T00:00:00Z"} if status in ("importing", "completed") else {}
    with tenant_conn(app_engine, tenant) as conn:
        batch(conn, tenant, status=status, **extra)


@pytest.mark.parametrize(
    "cols", [{"entity": "widgets"}, {"status": "validating"}, {"status": "done"}]
)
def test_import_batch_rejects_unknown_entity_and_status(
    app_engine: Engine, tenant: UUID, cols: dict[str, Any]
) -> None:
    with expect_db_error(CHECK), tenant_conn(app_engine, tenant) as conn:
        batch(conn, tenant, **cols)


@pytest.mark.parametrize("status", ["importing", "completed"])
def test_import_batch_importing_or_completed_needs_confirmed_at(
    app_engine: Engine, tenant: UUID, status: str
) -> None:
    with expect_db_error(CHECK), tenant_conn(app_engine, tenant) as conn:
        batch(conn, tenant, status=status)


@pytest.mark.parametrize(
    "column",
    [
        "rows_received",
        "rows_valid",
        "rows_imported",
        "rows_duplicate",
        "rows_rejected",
        "rows_unmapped",
        "rows_review",
    ],
)
def test_import_batch_counts_default_to_zero_and_never_go_negative(
    app_engine: Engine, tenant: UUID, column: str
) -> None:
    with tenant_conn(app_engine, tenant) as conn:
        bid = batch(conn, tenant)
        assert (
            conn.execute(
                text(f"SELECT {column} FROM import_batches WHERE id = :i"), {"i": bid}
            ).scalar_one()
            == 0
        )
    with expect_db_error(CHECK), tenant_conn(app_engine, tenant) as conn:
        conn.execute(text(f"UPDATE import_batches SET {column} = -1 WHERE id = :i"), {"i": bid})


def test_import_batch_mapping_must_be_a_json_object(app_engine: Engine, tenant: UUID) -> None:
    for bad in ("[]", '"x"', "1", "null"):
        with expect_db_error(CHECK), tenant_conn(app_engine, tenant) as conn:
            batch(conn, tenant, mapping=bad)


def test_the_same_file_hash_may_appear_in_many_batches(app_engine: Engine, tenant: UUID) -> None:
    """File hash is not unique: a re-upload is flagged by the application, not blocked (blueprint 8 C3)."""
    with tenant_conn(app_engine, tenant) as conn:
        batch(conn, tenant, file_hash="a" * 64)
        batch(conn, tenant, file_hash="a" * 64)


def test_import_batch_update_grant_excludes_identity_and_file_columns(owner_engine: Engine) -> None:
    with owner_engine.connect() as conn:
        for column in (
            "id",
            "tenant_id",
            "created_at",
            "created_by",
            "file_hash",
            "entity",
            "started_by",
        ):
            allowed = conn.execute(
                text(
                    "SELECT has_column_privilege('qualloop_app', 'public.import_batches', :c, 'UPDATE')"
                ),
                {"c": column},
            ).scalar_one()
            assert allowed is False, f"import_batches.{column} must not be updatable"
        for column in ("status", "mapping", "rows_valid", "rows_imported", "confirmed_at"):
            assert (
                conn.execute(
                    text(
                        "SELECT has_column_privilege('qualloop_app', 'public.import_batches', :c, 'UPDATE')"
                    ),
                    {"c": column},
                ).scalar_one()
                is True
            ), column


def record(conn: Connection, tenant: UUID, batch_id: UUID, row: int = 1, **over: Any) -> UUID:
    cols = {
        "batch_id": batch_id,
        "row_number": row,
        "row_hash": "f" * 64,
        "status": "imported",
        "target_id": uuid4(),
        **over,
    }
    return insert(conn, "import_records", tenant, **cols)


@pytest.mark.parametrize("status", ["imported", "duplicate", "rejected", "unmapped", "review"])
def test_import_record_status_accepts_the_five_values(
    app_engine: Engine, tenant: UUID, status: str
) -> None:
    extra: dict[str, Any] = {} if status == "imported" else {"reason": "because", "target_id": None}
    with tenant_conn(app_engine, tenant) as conn:
        record(conn, tenant, batch(conn, tenant), status=status, **extra)


@pytest.mark.parametrize(
    "cols",
    [{"status": "valid", "reason": "x"}, {"row_number": 0}, {"row_number": -3}],
    ids=lambda c: str(c),
)
def test_import_record_rejects_unknown_status_and_non_positive_row_numbers(
    app_engine: Engine, tenant: UUID, cols: dict[str, Any]
) -> None:
    with expect_db_error(CHECK), tenant_conn(app_engine, tenant) as conn:
        record(conn, tenant, batch(conn, tenant), **cols)


@pytest.mark.parametrize("status", ["duplicate", "rejected", "unmapped", "review"])
def test_import_record_that_was_not_imported_needs_a_reason(
    app_engine: Engine, tenant: UUID, status: str
) -> None:
    with expect_db_error(CHECK), tenant_conn(app_engine, tenant) as conn:
        record(conn, tenant, batch(conn, tenant), status=status, reason=None, target_id=None)


def test_import_record_that_was_imported_needs_a_target(app_engine: Engine, tenant: UUID) -> None:
    with expect_db_error(CHECK), tenant_conn(app_engine, tenant) as conn:
        record(conn, tenant, batch(conn, tenant), status="imported", target_id=None)


def test_import_record_row_number_is_unique_within_a_batch(
    app_engine: Engine, tenant: UUID
) -> None:
    with tenant_conn(app_engine, tenant) as conn:
        bid, other = batch(conn, tenant), batch(conn, tenant)
        record(conn, tenant, bid, 1)
        record(conn, tenant, other, 1)  # another batch may reuse the number
    with expect_db_error(UNIQUE), tenant_conn(app_engine, tenant) as conn:
        record(conn, tenant, bid, 1)


def test_import_record_cannot_reference_another_tenants_batch(
    app_engine: Engine, tenant: UUID
) -> None:
    other = create_tenant(app_engine)
    with tenant_conn(app_engine, other) as conn:
        foreign = batch(conn, other)
    with expect_db_error(FK), tenant_conn(app_engine, tenant) as conn:
        record(conn, tenant, foreign)


def test_import_records_are_append_only(
    app_engine: Engine, owner_engine: Engine, tenant: UUID
) -> None:
    """DATA_MODEL 7.2 grants CR: no UPDATE, no DELETE privilege, and the trigger blocks them even if one were granted."""
    with tenant_conn(app_engine, tenant) as conn:
        record(conn, tenant, batch(conn, tenant))
    for statement in (
        "UPDATE import_records SET reason = 'tampered'",
        "UPDATE import_records SET status = 'rejected'",
        "DELETE FROM import_records",
    ):
        with expect_db_error(DENIED, "permission denied"), tenant_conn(app_engine, tenant) as conn:
            conn.execute(text(statement))
    with owner_engine.connect() as owner:
        owner.execute(text("GRANT UPDATE, DELETE ON import_records TO qualloop_app"))
    try:
        for statement in (
            "UPDATE import_records SET reason = 'tampered'",
            "DELETE FROM import_records",
        ):
            with (
                expect_db_error(APPEND_ONLY, "append-only"),
                tenant_conn(app_engine, tenant) as conn,
            ):
                conn.execute(text(statement))
    finally:
        with owner_engine.connect() as owner:
            owner.execute(text("REVOKE UPDATE, DELETE ON import_records FROM qualloop_app"))


# =================================================================================================
# grants, policies and indexes common to the nine tables
# =================================================================================================
@pytest.mark.parametrize("table", MASTERS_TABLES)
def test_identity_and_creation_columns_are_never_updatable_and_nothing_is_deletable(
    owner_engine: Engine, table: str
) -> None:
    with owner_engine.connect() as conn:
        for column in ("id", "tenant_id", "created_at", "created_by"):
            assert (
                conn.execute(
                    text(
                        "SELECT has_column_privilege('qualloop_app', CAST(:t AS regclass), :c, 'UPDATE')"
                    ),
                    {"t": f"public.{table}", "c": column},
                ).scalar_one()
                is False
            ), f"{table}.{column}"
        assert (
            conn.execute(
                text("SELECT has_table_privilege('qualloop_app', CAST(:t AS regclass), 'DELETE')"),
                {"t": f"public.{table}"},
            ).scalar_one()
            is False
        )


def test_import_records_grant_no_update_on_any_column(owner_engine: Engine) -> None:
    with owner_engine.connect() as conn:
        updatable = conn.execute(
            text(
                "SELECT attname FROM pg_attribute WHERE attrelid = 'public.import_records'::regclass "
                "AND attnum > 0 AND NOT attisdropped "
                "AND has_column_privilege('qualloop_app', 'public.import_records', attname, 'UPDATE')"
            )
        ).all()
    assert updatable == []


def policies(engine: Engine) -> dict[str, set[str]]:
    with engine.connect() as conn:
        out: dict[str, set[str]] = {}
        for table, name in conn.execute(
            text(
                "SELECT c.relname, p.polname FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid WHERE c.relnamespace = 'public'::regnamespace"
            )
        ):
            out.setdefault(table, set()).add(name)
    return out


@pytest.mark.parametrize("table", MASTERS_TABLES)
def test_p02_tables_use_tenant_policy_and_deny_suppliers_by_default(
    owner_engine: Engine, table: str
) -> None:
    """parts and supplier_contacts keep `p_supplier_deny` until P04/P05 create the tables their scoped predicates read;
    the STOP-resolution policy `contacts_sysfn` is P05."""
    have = policies(owner_engine).get(table, set())
    assert have == {"p_tenant", "p_supplier_deny"}, f"{table}: {sorted(have)}"


EXPECTED_INDEXES = {
    "ix_suppliers_name": ["(tenant_id, lower(name), id)", "archived_at IS NULL"],
    "ix_suppliers_code": ["(tenant_id, code, id)"],
    "ix_suppliers_updated": ["(tenant_id, updated_at DESC, id DESC)"],
    "ix_parts_part_no": ["(tenant_id, part_no, id)"],
    "ix_import_batches_created": ["(tenant_id, created_at DESC, id DESC)"],
    "ix_import_records_batch_row": ["UNIQUE", "(tenant_id, batch_id, row_number)"],
    "supplier_contacts_mobile_idx": ["(mobile)"],
}


@pytest.mark.parametrize("name", sorted(EXPECTED_INDEXES))
def test_list_sort_and_lookup_indexes_exist_as_documented(owner_engine: Engine, name: str) -> None:
    """DATA_MODEL 0.7 and 0.4: the keyset sorts of API.md 5.1 are served by these indexes."""
    with owner_engine.connect() as conn:
        definition = conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' AND indexname = :n"),
            {"n": name},
        ).scalar()
    assert definition, f"index {name} is missing"
    for fragment in EXPECTED_INDEXES[name]:
        assert fragment in definition, f"{name}: {fragment!r} not in {definition}"
