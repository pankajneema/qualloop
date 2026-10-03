"""P01 contract items 9 and 10 (security review): least-privilege UPDATE on `users`, and database errors that must not
carry bound parameter values (PII) into exception text, logs or dead-letter rows."""

from uuid import uuid4

import psycopg.errors
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from tests.factories.contract import load
from tests.factories.db import SeededTenant, fetch_all, tenant_conn
from tests.factories.dberr import expect_db_error

pytestmark = pytest.mark.integration

UPDATABLE_USER_COLUMNS = {
    "name",
    "mobile",
    "role",
    "can_approve",
    "plant_ids",
    "active",
    "password_hash",
    "updated_at",
    "updated_by",
}


# --- item 10 ----------------------------------------------------------------------------------------
def test_qualloop_app_may_update_only_the_documented_columns_of_users(app_engine: Engine) -> None:
    with app_engine.connect() as conn:
        granted = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.column_privileges "
                    "WHERE table_schema = 'public' AND table_name = 'users' "
                    "AND grantee = 'qualloop_app' AND privilege_type = 'UPDATE'"
                )
            )
        }
    assert granted == UPDATABLE_USER_COLUMNS, (
        f"unexpected UPDATE on {sorted(granted - UPDATABLE_USER_COLUMNS)}; "
        f"missing {sorted(UPDATABLE_USER_COLUMNS - granted)}"
    )


def test_no_table_wide_update_privilege_on_users_for_the_app_role(app_engine: Engine) -> None:
    with app_engine.connect() as conn:
        table_wide = conn.execute(
            text("SELECT has_table_privilege('qualloop_app', 'public.users', 'UPDATE')")
        ).scalar_one()
    # has_table_privilege is true only for a table-level grant (or when ALL columns are granted)
    assert table_wide is False


@pytest.mark.parametrize("column", ["email", "tenant_id", "id", "created_at", "created_by"])
def test_updating_an_immutable_user_column_is_denied(
    app_engine: Engine, seeded: SeededTenant, column: str
) -> None:
    assert seeded.quality
    value = {
        "email": "changed@example.test",
        "tenant_id": str(uuid4()),
        "id": str(uuid4()),
        "created_at": "2020-01-01T00:00:00Z",
        "created_by": str(uuid4()),
    }[column]
    with (
        expect_db_error(psycopg.errors.InsufficientPrivilege, "permission denied"),
        tenant_conn(app_engine, seeded.id) as conn,
    ):
        conn.execute(
            text(f"UPDATE users SET {column} = CAST(:v AS {_type(column)}) WHERE id = :i"),
            {"v": value, "i": seeded.quality.id},
        )
    row = fetch_all(
        app_engine,
        seeded.id,
        "SELECT email, tenant_id, id FROM users WHERE id = :i",
        {"i": seeded.quality.id},
    )
    assert row and row[0]["email"] == seeded.quality.email and row[0]["tenant_id"] == seeded.id


def _type(column: str) -> str:
    return {"email": "text", "created_at": "timestamptz"}.get(column, "uuid")


def test_updating_the_allowed_user_columns_still_works(
    app_engine: Engine, seeded: SeededTenant
) -> None:
    assert seeded.quality
    with tenant_conn(app_engine, seeded.id) as conn:
        conn.execute(
            text(
                "UPDATE users SET name = 'Renamed User', mobile = '+919800000042', can_approve = true, "
                "password_hash = NULL WHERE id = :i"
            ),
            {"i": seeded.quality.id},
        )
    row = fetch_all(
        app_engine,
        seeded.id,
        "SELECT name, can_approve FROM users WHERE id = :i",
        {"i": seeded.quality.id},
    )[0]
    assert row["name"] == "Renamed User" and row["can_approve"] is True


# --- item 9 ----------------------------------------------------------------------------------------
def failing_insert_with_email(tenant: SeededTenant, email: str) -> DBAPIError:
    tenant_tx = load("app.core.db", "tenant_tx")
    with pytest.raises(DBAPIError) as excinfo, tenant_tx(tenant.id) as session:
        session.execute(
            text("INSERT INTO users (tenant_id, email, no_such_column) VALUES (:t, :e, 1)"),
            {"t": tenant.id, "e": email},
        )
    return excinfo.value


def test_the_engine_hides_statement_parameters(engine_env: None) -> None:
    engine = load("app.core.db", "get_engine")()
    assert engine.hide_parameters is True


def test_a_failing_statement_does_not_put_the_bound_email_in_the_exception_text(
    seeded: SeededTenant, engine_env: None
) -> None:
    email = f"very.private.{uuid4().hex[:8]}@example.test"
    error = failing_insert_with_email(seeded, email)
    assert email not in str(error)
    assert email not in repr(error)
    assert "[parameters:" not in str(error)
    assert "no_such_column" in str(error) or "no_such_column" in str(error.orig), (
        "still a useful error"
    )


def test_a_failing_statement_does_not_log_the_bound_email(
    seeded: SeededTenant, engine_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    email = f"logged.private.{uuid4().hex[:8]}@example.test"
    failing_insert_with_email(seeded, email)
    captured = capsys.readouterr()
    assert email not in captured.out and email not in captured.err
