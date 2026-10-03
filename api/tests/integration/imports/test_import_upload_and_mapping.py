"""Blueprint 8 C3 steps 1-3 (upload, detect columns, map) and the batch state machine over HTTP.

INV-IMP-01 (file hash flagged before processing), A-113 (mapping prefill), A-114 (formats), A-112 (entities),
batch statuses of DATA_MODEL 7.1 (allowed and forbidden transitions)."""

import re
from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import Engine, text

from tests.factories.api import ApiClient, ApiFactory, problem
from tests.factories.contract import load
from tests.factories.db import SeededTenant, fetch_all, tenant_conn
from tests.factories.imports import (
    CSV_TYPE,
    OK,
    SUPPLIER_COLUMNS,
    XLSX_TYPE,
    Importer,
    csv_bytes,
    file_for,
    mapping_for,
    part_row,
    sha256,
    stage_file,
    supplier_part_row,
    supplier_row,
    xlsx_raw,
)
from tests.integration.commands.test_command_audit_and_outbox import log_rows
from tests.integration.files.helpers import PDF

pytestmark = pytest.mark.integration

UUID7 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
SUPPLIER_HEADERS = [*SUPPLIER_COLUMNS.values(), "Last Audit", "Remarks"]
SAMPLE_ROWS = {
    "suppliers": supplier_row(1),
    "parts": part_row(1),
    "supplier_parts": supplier_part_row("S-1", "P-1"),
}


def small_suppliers(n: int = 3, **kw: Any) -> tuple[bytes, str, str]:
    return file_for("suppliers", [supplier_row(i) for i in range(n)], **kw)


def batch_rows(engine: Engine, tenant: UUID) -> list[dict[str, Any]]:
    return fetch_all(engine, tenant, "SELECT * FROM import_batches ORDER BY created_at, id")


# =================================================================================================
# POST /imports
# =================================================================================================
def test_upload_registers_a_batch_in_uploaded_status_with_hash_and_detected_columns(
    importer: Importer, seeded: SeededTenant, app_engine: Engine
) -> None:
    data, name, ctype = small_suppliers(extra_columns=True)
    resp = importer.create_response("suppliers", data, name, ctype)
    assert resp.status_code in OK, resp.text
    batch = resp.json()
    assert UUID7.match(batch["id"])
    assert (batch["entity"], batch["status"], batch["file_name"]) == ("suppliers", "uploaded", name)
    assert batch["file_hash"] == sha256(data)
    assert batch["columns"] == SUPPLIER_HEADERS, "header row 1 of the first sheet, in file order"
    assert batch["mapping"] == {}
    assert all(batch[f"rows_{k}"] == 0 for k in ("received", "valid", "imported", "duplicate"))
    assert batch["started_by"] == str(seeded.quality.id if seeded.quality else "")
    assert batch["confirmed_at"] is None
    assert batch["file_hash_seen_before"] is False and batch["previous_batch_ids"] == []
    rows = batch_rows(app_engine, seeded.id)
    assert [str(r["id"]) for r in rows] == [batch["id"]]
    assert rows[0]["file_hash"] == sha256(data) and rows[0]["status"] == "uploaded"


def test_batch_read_model_lists_target_fields_with_required_flags(importer: Importer) -> None:
    expected_required = {
        "suppliers": {"code", "name", "category"},
        "parts": {"part_no", "name"},
        "supplier_parts": {"supplier_code", "part_no"},
    }
    for entity, required in expected_required.items():
        data, name, ctype = file_for(entity, [SAMPLE_ROWS[entity]])
        batch = importer.upload(entity, data, name, ctype)
        fields = {f["name"]: f["required"] for f in batch["target_fields"]}
        assert {n for n, req in fields.items() if req} == required, entity
        assert set(mapping_for(entity)) <= set(fields), entity


def test_same_file_hash_flagged_before_processing(
    importer: Importer, seeded: SeededTenant, app_engine: Engine
) -> None:
    """INV-IMP-01: the second upload of identical bytes is flagged at upload, before any processing."""
    data, name, ctype = small_suppliers()
    first = importer.upload("suppliers", data, name, ctype)
    second = importer.upload("suppliers", data, name, ctype)
    assert first["file_hash_seen_before"] is False
    assert second["file_hash_seen_before"] is True
    assert second["previous_batch_ids"] == [first["id"]]
    assert second["status"] == "uploaded", "flagged only: nothing has been processed"
    assert second["rows_received"] == 0
    assert importer.get(second["id"])["file_hash_seen_before"] is True, (
        "the flag is kept on the batch"
    )
    assert fetch_all(app_engine, seeded.id, "SELECT 1 FROM import_records") == []
    assert fetch_all(app_engine, seeded.id, "SELECT 1 FROM suppliers") == []
    third = importer.upload("suppliers", data, name, ctype)
    assert set(third["previous_batch_ids"]) == {first["id"], second["id"]}


def test_a_file_that_differs_by_one_byte_is_not_flagged(importer: Importer) -> None:
    data, name, ctype = small_suppliers(kind="csv")
    importer.upload("suppliers", data, name, ctype)
    other = importer.upload("suppliers", data + b"\r\n", name, ctype)
    assert other["file_hash_seen_before"] is False


def test_file_hash_flag_never_crosses_tenants(
    api: ApiFactory,
    seeded_pair: tuple[SeededTenant, SeededTenant],
    drain: Callable[[], None],
) -> None:
    a, b = seeded_pair
    assert a.quality and b.quality
    data, name, ctype = small_suppliers()
    first = Importer(api.login_as(a.quality), a.id, drain).upload("suppliers", data, name, ctype)
    other = Importer(api.login_as(b.quality), b.id, drain).upload("suppliers", data, name, ctype)
    assert other["file_hash_seen_before"] is False and other["previous_batch_ids"] == []
    assert first["id"] != other["id"]


@pytest.mark.parametrize("bom", [False, True], ids=["utf8", "utf8-with-bom"])
def test_csv_columns_are_detected_with_or_without_a_byte_order_mark(
    importer: Importer, bom: bool
) -> None:
    data, name, ctype = small_suppliers(kind="csv", bom=bom)
    batch = importer.upload("suppliers", data, name, ctype)
    assert batch["columns"][0] == "Supplier Code", "a BOM must not leak into the first header"


@pytest.mark.parametrize("encoding", ["cp1252", "utf-16"])
def test_csv_in_another_encoding_is_rejected_and_never_becomes_a_batch(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine, encoding: str
) -> None:
    """A-114: CSV must be UTF-8 (with or without BOM). The P01 scan job may already quarantine such a file as a
    content mismatch; if it lets it through, `POST /imports` must refuse it and name UTF-8 in the message."""
    rows = [supplier_row(1, name="Soci\u00e9t\u00e9 G\u00e9n\u00e9rale")]
    data = csv_bytes(SUPPLIER_COLUMNS, rows, encoding=encoding)
    info = quality.post(
        "/files/upload-url", {"purpose": "import", "content_type": CSV_TYPE, "size": len(data)}
    ).json()
    httpx.put(info["url"], content=data, headers={"Content-Type": CSV_TYPE}, timeout=60)
    scan = load("app.core.files.scanner", "scan_quarantined")(seeded.id, info["key"])
    resp = quality.post(
        "/imports", {"entity": "suppliers", "key": info["key"], "file_name": "suppliers.csv"}
    )
    assert resp.status_code in (404, 415, 422), resp.text
    if scan.status == "available":
        assert "utf-8" in str(problem(resp)).lower(), "the message must tell the user what to do"
    assert batch_rows(app_engine, seeded.id) == []


def test_merged_header_cells_do_not_break_column_detection(importer: Importer) -> None:
    data = xlsx_raw([["Supplier Code", "", "Category"], ["S1", "x", "bought_out"]], merge="A1:B1")
    resp = importer.create_response("suppliers", data, "merged.xlsx")
    assert resp.status_code in OK, resp.text
    columns = resp.json()["columns"]
    assert "Supplier Code" in columns and "Category" in columns
    assert None not in columns and "" not in columns


def test_only_the_first_sheet_is_read(importer: Importer) -> None:
    data = xlsx_raw(
        [
            ["Supplier Code", "Supplier Name", "City", "Category"],
            ["S1", "First Sheet Co", "Pune", "bought_out"],
        ],
        extra_sheet=True,
    )
    batch = importer.upload("suppliers", data, "two-sheets.xlsx")
    assert batch["columns"] == ["Supplier Code", "Supplier Name", "City", "Category"]
    assert (
        importer.map(
            batch["id"],
            {
                "code": "Supplier Code",
                "name": "Supplier Name",
                "city": "City",
                "category": "Category",
            },
        ).status_code
        in OK
    )
    validated = importer.validate(batch["id"])
    assert validated["rows_received"] == 1 and validated["rows_valid"] == 1
    assert "WRONG-SHEET" not in str(importer.preview(batch["id"]))


@pytest.mark.parametrize("entity", ["receipts", "ncrs", "certificates_meta", "widgets", ""])
def test_entities_not_built_in_p02_or_unknown_are_rejected(
    importer: Importer, seeded: SeededTenant, app_engine: Engine, entity: str
) -> None:
    """A-112: only suppliers, parts and supplier_parts exist in P02 (the DB CHECK allows six, the API three)."""
    data, name, ctype = small_suppliers()
    resp = importer.create_response(entity, data, name, ctype)
    assert resp.status_code == 422, resp.text
    assert problem(resp)["code"] == "validation_error"
    assert batch_rows(app_engine, seeded.id) == []


@pytest.mark.parametrize("file_name", ["suppliers.exe", "suppliers.pdf", "suppliers", ""])
def test_file_name_must_be_xlsx_or_csv(
    importer: Importer, seeded: SeededTenant, app_engine: Engine, file_name: str
) -> None:
    data, _name, ctype = small_suppliers()
    resp = importer.create_response("suppliers", data, file_name, ctype)
    assert resp.status_code in (415, 422), resp.text
    assert batch_rows(app_engine, seeded.id) == []


def test_a_key_from_another_tenant_cannot_be_imported(
    api: ApiFactory,
    seeded_pair: tuple[SeededTenant, SeededTenant],
    app_engine: Engine,
) -> None:
    a, b = seeded_pair
    assert a.quality and b.quality
    key_b = stage_file(api.login_as(b.quality), b.id, small_suppliers()[0])
    resp = api.login_as(a.quality).post(
        "/imports", {"entity": "suppliers", "key": key_b, "file_name": "suppliers.xlsx"}
    )
    assert resp.status_code == 404, resp.text
    assert problem(resp)["code"] == "not_found"
    assert batch_rows(app_engine, a.id) == [] and batch_rows(app_engine, b.id) == []


def test_a_key_that_is_not_an_import_upload_is_refused(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    """A PDF document staged for another purpose cannot be turned into an import batch."""
    info = quality.post(
        "/files/upload-url",
        {"purpose": "document", "content_type": "application/pdf", "size": len(PDF)},
    ).json()
    assert httpx.put(
        info["url"], content=PDF, headers={"Content-Type": "application/pdf"}
    ).status_code in (
        200,
        204,
    )
    load("app.core.files.scanner", "scan_quarantined")(seeded.id, info["key"])
    resp = quality.post(
        "/imports", {"entity": "suppliers", "key": info["key"], "file_name": "suppliers.csv"}
    )
    assert resp.status_code in (404, 415, 422), resp.text
    assert batch_rows(app_engine, seeded.id) == []


def test_a_file_that_failed_the_scan_cannot_become_a_batch(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    """PDF bytes uploaded as text/csv: the scan quarantines it (content type mismatch); it must never be importable."""
    info = quality.post(
        "/files/upload-url", {"purpose": "import", "content_type": CSV_TYPE, "size": len(PDF)}
    ).json()
    httpx.put(info["url"], content=PDF, headers={"Content-Type": CSV_TYPE}, timeout=60)
    result = load("app.core.files.scanner", "scan_quarantined")(seeded.id, info["key"])
    assert result.status == "quarantined"
    resp = quality.post(
        "/imports", {"entity": "suppliers", "key": info["key"], "file_name": "suppliers.csv"}
    )
    assert resp.status_code in (404, 415, 422), resp.text
    assert batch_rows(app_engine, seeded.id) == []


def test_a_corrupt_workbook_is_a_clean_client_error_never_a_server_error(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    junk = b"PK\x03\x04" + b"\x00" * 64 + b"this is not a workbook"
    info = quality.post(
        "/files/upload-url", {"purpose": "import", "content_type": XLSX_TYPE, "size": len(junk)}
    ).json()
    httpx.put(info["url"], content=junk, headers={"Content-Type": XLSX_TYPE}, timeout=60)
    load("app.core.files.scanner", "scan_quarantined")(seeded.id, info["key"])
    resp = quality.post(
        "/imports", {"entity": "suppliers", "key": info["key"], "file_name": "broken.xlsx"}
    )
    assert resp.status_code in (404, 415, 422), resp.text
    problem(resp)
    assert batch_rows(app_engine, seeded.id) == []


# =================================================================================================
# POST /imports/{batch}/map
# =================================================================================================
def test_map_saves_the_mapping_and_moves_the_batch_to_mapped(
    importer: Importer, seeded: SeededTenant, app_engine: Engine
) -> None:
    data, name, ctype = small_suppliers()
    batch = importer.upload("suppliers", data, name, ctype)
    resp = importer.map(batch["id"], mapping_for("suppliers"))
    assert resp.status_code in OK, resp.text
    assert resp.json()["status"] == "mapped" and resp.json()["mapping"] == mapping_for("suppliers")
    row = batch_rows(app_engine, seeded.id)[0]
    assert row["status"] == "mapped" and row["mapping"] == mapping_for("suppliers")
    assert any(
        r["object_type"] == "import_batch"
        for r in log_rows(app_engine, seeded.id, UUID(batch["id"]))
    )


@pytest.mark.parametrize(
    "mapping",
    [
        {"code": "Supplier Code", "category": "Category"},  # required `name` missing
        {**mapping_for("suppliers"), "colour": "City"},  # unknown target field
        {**mapping_for("suppliers"), "state": "No Such Column"},  # source column not in the file
        {**mapping_for("suppliers"), "state": ""},
        {**mapping_for("suppliers"), "state": 5},
        {},
    ],
    ids=[
        "required-missing",
        "unknown-target",
        "unknown-source-column",
        "blank-source",
        "non-string",
        "empty",
    ],
)
def test_map_rejects_an_invalid_mapping_and_the_batch_stays_uploaded(
    importer: Importer, seeded: SeededTenant, app_engine: Engine, mapping: dict[str, Any]
) -> None:
    batch = importer.upload("suppliers", *small_suppliers()[:1], "suppliers.xlsx", XLSX_TYPE)
    resp = importer.client.post(f"/imports/{batch['id']}/map", {"mapping": mapping})
    assert resp.status_code == 422, resp.text
    assert problem(resp)["code"] == "validation_error"
    assert importer.get(batch["id"])["status"] == "uploaded"
    assert batch_rows(app_engine, seeded.id)[0]["mapping"] == {}


def test_map_rejects_a_body_without_a_mapping_object(importer: Importer) -> None:
    batch = importer.upload("suppliers", *small_suppliers()[:1], "suppliers.xlsx", XLSX_TYPE)
    for body in ({}, {"mapping": ["Supplier Code"]}, {"mapping": "x"}):
        assert importer.client.post(f"/imports/{batch['id']}/map", body).status_code == 422


def test_mapping_is_prefilled_from_the_tenants_last_mapping_for_that_entity(
    importer: Importer,
) -> None:
    """A-113: no table, the most recent batch mapping of the same entity is suggested for the next upload."""
    data, name, ctype = small_suppliers(extra_columns=True)
    first = importer.upload("suppliers", data, name, ctype)
    assert first["suggested_mapping"] == {}, "a tenant's first import has nothing to suggest"
    custom = {**mapping_for("suppliers"), "city": "Remarks"}  # a deliberately unusual mapping
    assert importer.map(first["id"], custom).status_code in OK
    again, name2, ctype2 = file_for(
        "suppliers", [supplier_row(10), supplier_row(11)], extra_columns=True
    )
    second = importer.upload("suppliers", again, name2, ctype2)
    assert second["suggested_mapping"] == custom
    assert second["mapping"] == {}, "a suggestion is not a saved mapping"
    parts, pname, pctype = file_for("parts", [part_row(1)])
    assert importer.upload("parts", parts, pname, pctype)["suggested_mapping"] == {}, "per entity"


def test_prefilled_mapping_drops_columns_the_new_file_does_not_have(importer: Importer) -> None:
    first = importer.upload(
        "suppliers", *small_suppliers(extra_columns=True)[:1], "a.xlsx", XLSX_TYPE
    )
    assert (
        importer.map(first["id"], {**mapping_for("suppliers"), "state": "Remarks"}).status_code
        in OK
    )
    slim = xlsx_raw(
        [
            ["Supplier Code", "Supplier Name", "City", "Category", "GSTIN No", "State"],
            ["S1", "One", "Pune", "bought_out", None, "MH"],
        ]
    )
    second = importer.upload("suppliers", slim, "slim.xlsx")
    suggested = second["suggested_mapping"]
    assert suggested["code"] == "Supplier Code"
    assert set(suggested.values()) <= set(second["columns"])


def test_mapping_suggestion_never_comes_from_another_tenant(
    api: ApiFactory,
    seeded_pair: tuple[SeededTenant, SeededTenant],
    drain: Callable[[], None],
) -> None:
    a, b = seeded_pair
    assert a.quality and b.quality
    data, name, ctype = small_suppliers()
    ia = Importer(api.login_as(a.quality), a.id, drain)
    batch = ia.upload("suppliers", data, name, ctype)
    assert ia.map(batch["id"], mapping_for("suppliers")).status_code in OK
    other = Importer(api.login_as(b.quality), b.id, drain).upload(
        "suppliers", *file_for("suppliers", [supplier_row(77)])[:1], "b.xlsx", XLSX_TYPE
    )
    assert other["suggested_mapping"] == {}


# =================================================================================================
# Batch state machine (DATA_MODEL 7.1): allowed and forbidden transitions
# =================================================================================================
def to_state(importer: Importer, state: str, engine: Engine | None = None) -> str:
    """Drive a fresh batch of three valid suppliers to `state`; returns its id.

    The in-process worker runs continuously, so a batch would never stay `importing`. That one state is
    set directly in the database (status + confirmed_at, as the confirm command would) to hold it there."""
    data, name, ctype = small_suppliers()
    batch = importer.upload("suppliers", data, name, ctype)
    bid: str = batch["id"]
    if state == "uploaded":
        return bid
    assert importer.map(bid, mapping_for("suppliers")).status_code in OK
    if state == "mapped":
        return bid
    assert importer.validate(bid)["status"] == "validated"
    if state == "validated":
        return bid
    if state == "cancelled":
        assert importer.client.post(f"/imports/{bid}/cancel", {}).status_code in OK
        return bid
    if state == "importing":
        assert engine is not None
        with tenant_conn(engine, importer.tenant_id, actor_type="system") as conn:
            conn.execute(
                text(
                    "UPDATE import_batches SET status = 'importing', confirmed_at = now() WHERE id = :i"
                ),
                {"i": UUID(bid)},
            )
        return bid
    assert state == "completed"
    assert importer.confirm(bid)["status"] == "completed"
    return bid


def call(importer: Importer, action: str, bid: str) -> httpx.Response:
    if action == "map":
        return importer.map(bid, mapping_for("suppliers"))
    if action == "validate":
        return importer.validate_response(bid)
    if action == "confirm":
        return importer.confirm_response(bid)
    return importer.client.post(f"/imports/{bid}/cancel", {})


FORBIDDEN = [
    ("uploaded", "validate"),
    ("uploaded", "confirm"),
    ("mapped", "confirm"),
    ("cancelled", "map"),
    ("cancelled", "validate"),
    ("cancelled", "confirm"),
    ("cancelled", "cancel"),
    ("completed", "map"),
    ("completed", "validate"),
    ("completed", "confirm"),
    ("completed", "cancel"),
    ("importing", "cancel"),
    ("importing", "confirm"),
    ("importing", "map"),
    ("importing", "validate"),
]


@pytest.mark.parametrize(("state", "action"), FORBIDDEN, ids=lambda v: str(v))
def test_forbidden_batch_transition_is_409_invalid_transition_and_changes_nothing(
    importer: Importer, app_engine: Engine, state: str, action: str
) -> None:
    bid = to_state(importer, state, app_engine)
    before = importer.get(bid)
    resp = call(importer, action, bid)
    assert resp.status_code == 409, f"{state} -> {action}: {resp.status_code} {resp.text}"
    assert problem(resp)["code"] in {"invalid_transition", "conflict"}
    after = importer.get(bid)
    assert (after["status"], after["mapping"]) == (before["status"], before["mapping"])
    assert after["status"] == state


@pytest.mark.parametrize("state", ["uploaded", "mapped", "validated"])
def test_a_batch_can_be_cancelled_until_it_is_confirmed(importer: Importer, state: str) -> None:
    bid = to_state(importer, state)
    resp = importer.client.post(f"/imports/{bid}/cancel", {})
    assert resp.status_code in OK, resp.text
    assert resp.json()["status"] == "cancelled"
    assert importer.get(bid)["status"] == "cancelled"


def test_cancelling_a_validated_batch_creates_nothing(
    importer: Importer, seeded: SeededTenant, app_engine: Engine
) -> None:
    bid = to_state(importer, "validated")
    assert importer.client.post(f"/imports/{bid}/cancel", {}).status_code in OK
    assert fetch_all(app_engine, seeded.id, "SELECT 1 FROM suppliers") == []
    assert fetch_all(app_engine, seeded.id, "SELECT 1 FROM import_records") == []


def test_validate_moves_a_mapped_batch_to_validated_with_counts_and_no_master_rows(
    importer: Importer, seeded: SeededTenant, app_engine: Engine
) -> None:
    bid = to_state(importer, "mapped")
    resp = importer.validate_response(bid)
    assert resp.status_code in OK, resp.text
    importer.drain()
    batch = importer.get(bid)
    assert batch["status"] == "validated"
    assert (batch["rows_received"], batch["rows_valid"], batch["rows_imported"]) == (3, 3, 0)
    assert fetch_all(app_engine, seeded.id, "SELECT 1 FROM suppliers") == [], (
        "validate never writes masters"
    )
    assert fetch_all(app_engine, seeded.id, "SELECT 1 FROM import_records") == [], (
        "import_records are written at confirm time (DATA_MODEL 7.2)"
    )


def test_records_are_empty_until_confirm_and_preview_is_not_available_before_validate(
    importer: Importer,
) -> None:
    bid = to_state(importer, "mapped")
    assert importer.client.get(f"/imports/{bid}/preview").status_code in (404, 409)
    importer.validate(bid)
    assert importer.client.get(f"/imports/{bid}/records").json() == {
        "items": [],
        "next_cursor": None,
    }
    assert len(importer.preview(bid)) == 3


# =================================================================================================
# GET /imports
# =================================================================================================
def test_batch_list_is_newest_first_keyset_paginated_and_tenant_scoped(
    api: ApiFactory,
    seeded_pair: tuple[SeededTenant, SeededTenant],
    drain: Callable[[], None],
) -> None:
    a, b = seeded_pair
    assert a.quality and b.quality
    imp_a = Importer(api.login_as(a.quality), a.id, drain)
    imp_b = Importer(api.login_as(b.quality), b.id, drain)
    created = [
        imp_a.upload(
            "suppliers", *file_for("suppliers", [supplier_row(i)])[:1], f"f{i}.xlsx", XLSX_TYPE
        )["id"]
        for i in range(4)
    ]
    foreign = imp_b.upload(
        "suppliers", *file_for("suppliers", [supplier_row(99)])[:1], "b.xlsx", XLSX_TYPE
    )
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        page = imp_a.client.get(
            "/imports", params={"limit": 3, **({"cursor": cursor} if cursor else {})}
        ).json()
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert cursor is None
    assert seen == list(reversed(created)), "created_at DESC, id DESC"
    assert foreign["id"] not in seen


# =================================================================================================
# audit
# =================================================================================================
def test_each_import_command_writes_an_activity_log_row_on_the_batch(
    importer: Importer, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.quality
    bid = to_state(importer, "validated")
    assert importer.client.post(f"/imports/{bid}/cancel", {}).status_code in OK
    rows = [
        r
        for r in log_rows(app_engine, seeded.id, UUID(bid))
        if r["object_type"] == "import_batch" and r["actor_type"] == "user"
    ]
    verbs = ("create", "map", "validate", "cancel")
    for verb in verbs:
        matching = [r for r in rows if verb in r["action"]]
        assert len(matching) == 1, f"{verb}: {[r['action'] for r in rows]}"
        assert matching[0]["actor_id"] == seeded.quality.id
        assert matching[0]["action"].startswith("import.")
