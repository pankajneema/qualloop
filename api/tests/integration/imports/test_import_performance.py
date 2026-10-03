"""PHASES P02 mandatory test and gate: the same 5,000-row supplier file imported twice creates zero duplicates and
the report shows 5,000 duplicates (blueprint 8 C3 acceptance); each run takes under 60 seconds locally.

The clock runs from the validate command to the batch being `completed` (upload and column mapping are excluded,
P02 plan section 9). Synchronisation is `broker.join`, never a sleep."""

import time
from uuid import UUID

import pytest
from sqlalchemy import Engine

from tests.factories.api import new_key, problem
from tests.factories.db import SeededTenant, fetch_all
from tests.factories.imports import (
    Importer,
    counts,
    file_for,
    mapping_for,
    sheet_rows,
    summary,
    supplier_row,
)

pytestmark = pytest.mark.integration

ROWS = 5000
BUDGET_SECONDS = 60.0


def timed_validate_and_confirm(
    importer: Importer, batch_id: str, accept_partial: bool | None
) -> float:
    started = time.perf_counter()
    importer.validate(batch_id)
    final = importer.confirm(batch_id, accept_partial)
    elapsed = time.perf_counter() - started
    assert final["status"] == "completed", final
    return elapsed


def test_same_5000_row_supplier_file_twice_creates_zero_duplicates(
    importer: Importer, seeded: SeededTenant, app_engine: Engine
) -> None:
    rows = [supplier_row(i) for i in range(ROWS)]
    data, name, ctype = file_for("suppliers", rows)

    # --- first import: everything is new --------------------------------------------------------------------
    first = importer.upload("suppliers", data, name, ctype)
    assert first["file_hash_seen_before"] is False
    assert importer.map(first["id"], mapping_for("suppliers")).status_code in (200, 201, 202)
    first_seconds = timed_validate_and_confirm(importer, first["id"], None)
    first_done = importer.get(first["id"])
    assert counts(first_done) == {
        "received": ROWS,
        "valid": ROWS,
        "imported": ROWS,
        "duplicate": 0,
        "rejected": 0,
        "unmapped": 0,
        "review": 0,
    }
    count_sql = "SELECT count(*) AS n FROM suppliers"
    assert fetch_all(app_engine, seeded.id, count_sql)[0]["n"] == ROWS
    assert first_seconds < BUDGET_SECONDS, f"first import took {first_seconds:.1f}s"

    # --- second import of the same file: flagged at upload, nothing new -------------------------------------
    second = importer.upload("suppliers", data, name, ctype)
    assert second["file_hash_seen_before"] is True and second["previous_batch_ids"] == [first["id"]]
    assert importer.map(second["id"], mapping_for("suppliers")).status_code in (200, 201, 202)
    started = time.perf_counter()
    validated = importer.validate(second["id"])
    assert (validated["rows_received"], validated["rows_valid"], validated["rows_duplicate"]) == (
        ROWS,
        0,
        ROWS,
    )
    refused = importer.confirm_response(second["id"], key=new_key())
    assert refused.status_code == 422, (
        "5,000 duplicates are 5,000 non-valid rows: explicit confirmation needed"
    )
    assert problem(refused)["code"] in {"validation_error", "invariant_violation"}
    final = importer.confirm(second["id"], accept_partial=True)
    second_seconds = time.perf_counter() - started
    assert final["status"] == "completed"
    assert counts(final) == {
        "received": ROWS,
        "valid": 0,
        "imported": 0,
        "duplicate": ROWS,
        "rejected": 0,
        "unmapped": 0,
        "review": 0,
    }
    assert second_seconds < BUDGET_SECONDS, f"second import took {second_seconds:.1f}s"

    # --- zero duplicates in the database --------------------------------------------------------------------
    assert fetch_all(app_engine, seeded.id, count_sql)[0]["n"] == ROWS
    dup_gstin = fetch_all(
        app_engine,
        seeded.id,
        "SELECT gstin FROM suppliers WHERE gstin IS NOT NULL GROUP BY gstin HAVING count(*) > 1",
    )
    dup_name_city = fetch_all(
        app_engine,
        seeded.id,
        "SELECT 1 FROM suppliers GROUP BY lower(name), lower(city) HAVING count(*) > 1",
    )
    assert dup_gstin == [] and dup_name_city == []

    # --- the report shows 5,000 duplicates, with a reason on every line --------------------------------------
    report = importer.report(second["id"])
    figures = summary(report)
    assert (figures["Received"], figures["Duplicate"], figures["Imported"]) == (ROWS, ROWS, 0)
    body = sheet_rows(report, "Rows")[1:]
    assert len(body) == ROWS
    assert all(r[1] == "duplicate" and isinstance(r[2], str) and r[2].strip() for r in body)
    records = fetch_all(
        app_engine,
        seeded.id,
        "SELECT status, count(*) AS n FROM import_records WHERE batch_id = :b GROUP BY status",
        {"b": UUID(second["id"])},
    )
    assert {r["status"]: r["n"] for r in records} == {"duplicate": ROWS}
