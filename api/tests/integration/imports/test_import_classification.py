"""Blueprint 8 C3 validate -> preview -> confirm: how each row is classified, and what confirm writes.

INV-IMP-02 (natural keys), INV-IMP-04 (duplicates reported, never merged or updated), INV-IMP-06 (partial import needs
explicit confirmation), A-06, A-41 (changed values go to review), A-109 (supplier needs GSTIN or city),
and the messy-Excel edge cases of the P02 plan section 4."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine

from tests.factories.api import ApiClient, new_key, problem
from tests.factories.db import SeededTenant, fetch_all
from tests.factories.imports import (
    OK,
    Importer,
    by_row,
    counts,
    file_for,
    part_row,
    supplier_part_row,
    supplier_row,
)
from tests.factories.masters import make_part, make_supplier, make_supplier_part
from tests.integration.commands.test_command_audit_and_outbox import log_rows, outbox_rows

pytestmark = pytest.mark.integration


def validated(
    importer: Importer, entity: str, rows: Sequence[dict[str, Any] | None], **kw: Any
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    data, name, ctype = file_for(entity, rows, **kw)
    batch = importer.run(entity, data, name, ctype, confirm=False)
    return batch, {n: dict(r) for n, r in by_row(importer.preview(batch["id"])).items()}


def completed(
    importer: Importer, entity: str, rows: Sequence[dict[str, Any] | None], **kw: Any
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    """upload -> map -> validate -> confirm (partial accepted) and the persisted per-row records."""
    data, name, ctype = file_for(entity, rows, **kw)
    batch = importer.run(entity, data, name, ctype, accept_partial=True)
    assert batch["status"] == "completed", batch
    return batch, {n: dict(r) for n, r in by_row(importer.records(batch["id"])).items()}


def suppliers(engine: Engine, tenant: UUID, where: str = "true") -> list[dict[str, Any]]:
    return fetch_all(engine, tenant, f"SELECT * FROM suppliers WHERE {where} ORDER BY code")


def existing_supplier(client: ApiClient, row: dict[str, Any]) -> dict[str, Any]:
    return make_supplier(client, **{**row, "status": "approved"})


# =================================================================================================
# valid rows
# =================================================================================================
def test_clean_supplier_rows_are_valid_and_validate_writes_no_master_rows(
    importer: Importer, seeded: SeededTenant, app_engine: Engine
) -> None:
    batch, preview = validated(importer, "suppliers", [supplier_row(i) for i in range(5)])
    assert counts(batch) == {
        "received": 5,
        "valid": 5,
        "imported": 0,
        "duplicate": 0,
        "rejected": 0,
        "unmapped": 0,
        "review": 0,
    }
    assert {r["status"] for r in preview.values()} == {"valid"}
    assert sorted(preview) == [2, 3, 4, 5, 6], "row numbers are spreadsheet rows (header = row 1)"
    assert suppliers(app_engine, seeded.id) == []


def test_unmapped_extra_columns_including_dates_are_ignored(importer: Importer) -> None:
    batch, preview = validated(
        importer, "suppliers", [supplier_row(i) for i in range(3)], extra_columns=True
    )
    assert batch["rows_valid"] == 3 and {r["status"] for r in preview.values()} == {"valid"}


def test_csv_and_xlsx_with_the_same_rows_classify_identically(importer: Importer) -> None:
    rows = [supplier_row(1), supplier_row(2, category="plastic"), supplier_row(3)]
    xlsx_batch, _ = validated(importer, "suppliers", rows, kind="xlsx")
    csv_batch, _ = validated(importer, "suppliers", rows, kind="csv")
    assert counts(xlsx_batch) == counts(csv_batch)
    assert csv_batch["rows_valid"] == 2 and csv_batch["rows_rejected"] == 1


def test_empty_rows_are_skipped_and_not_counted_but_row_numbers_stay_physical(
    importer: Importer,
) -> None:
    rows: list[dict[str, Any] | None] = [
        supplier_row(1),
        None,
        supplier_row(2),
        None,
        None,
        supplier_row(3),
    ]
    for kind in ("xlsx", "csv"):
        batch, preview = validated(importer, "suppliers", rows, kind=kind)
        assert batch["rows_received"] == 3, kind
        assert sorted(preview) == [2, 4, 7], kind


def test_leading_and_trailing_spaces_are_trimmed_on_import(
    importer: Importer, seeded: SeededTenant, app_engine: Engine
) -> None:
    row = supplier_row(1, name="   Padded Name   ", city="  Pune  ", code=" PAD01 ")
    completed(importer, "suppliers", [row])
    stored = suppliers(app_engine, seeded.id)
    assert [(s["code"], s["name"], s["city"]) for s in stored] == [("PAD01", "Padded Name", "Pune")]


def test_numeric_gstin_read_as_a_number_is_cleaned_to_text(
    importer: Importer, seeded: SeededTenant, app_engine: Engine
) -> None:
    row = supplier_row(1, gstin=123456789012345.0)
    completed(importer, "suppliers", [row])
    assert [s["gstin"] for s in suppliers(app_engine, seeded.id)] == ["123456789012345"]


def test_numeric_part_no_read_as_float_is_cleaned_to_an_integer_string(
    importer: Importer, seeded: SeededTenant, app_engine: Engine
) -> None:
    completed(importer, "parts", [part_row(1, part_no=1234.0), part_row(2, part_no=5678)])
    parts = fetch_all(app_engine, seeded.id, "SELECT part_no FROM parts ORDER BY part_no")
    assert [p["part_no"] for p in parts] == ["1234", "5678"]


@pytest.mark.parametrize("kind", ["xlsx", "csv"])
def test_a_cell_starting_with_equals_is_stored_as_text_not_evaluated(
    importer: Importer, seeded: SeededTenant, app_engine: Engine, kind: str
) -> None:
    payload = '=HYPERLINK("http://evil.example","click")'
    completed(importer, "suppliers", [supplier_row(1, name=payload)], kind=kind)
    assert [s["name"] for s in suppliers(app_engine, seeded.id)] == [payload]


def test_hindi_text_in_a_utf8_file_is_imported_intact(
    importer: Importer, seeded: SeededTenant, app_engine: Engine
) -> None:
    name = "सुंदरम फास्टनर्स"
    for index, (kind, bom) in enumerate((("csv", False), ("csv", True), ("xlsx", False))):
        extra = {"bom": bom} if kind == "csv" else {}
        # a distinct supplier per case, otherwise the later files would be (correct) duplicates
        row = supplier_row(10 + 2 * index, name=f"{name} {index}")
        batch, _ = completed(importer, "suppliers", [row], kind=kind, **extra)
        assert batch["rows_imported"] == 1
    assert {s["name"] for s in suppliers(app_engine, seeded.id)} == {
        f"{name} {i}" for i in range(3)
    }


def test_imported_suppliers_start_approved_with_initial_import_reason_and_are_logged(
    importer: Importer, seeded: SeededTenant, app_engine: Engine
) -> None:
    """A-06: import sets status `approved`, status_reason "initial import", and logs it."""
    completed(importer, "suppliers", [supplier_row(i) for i in range(3)])
    rows = suppliers(app_engine, seeded.id)
    assert len(rows) == 3
    for row in rows:
        assert (row["status"], row["status_reason"]) == ("approved", "initial import")
        assert row["status_changed_at"] is not None
        logged = [
            r for r in log_rows(app_engine, seeded.id, row["id"]) if r["object_type"] == "supplier"
        ]
        assert logged, f"imported supplier {row['code']} has no activity_log row"
        assert logged[0]["after"]["status"] == "approved"


# =================================================================================================
# INV-IMP-02 / INV-IMP-04: duplicates are reported, review is never an update
# =================================================================================================
def test_duplicate_supplier_by_gstin_reported_not_merged(
    importer: Importer, quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    row = supplier_row(2)  # even index: carries a GSTIN
    existing = existing_supplier(quality, row)
    before = suppliers(app_engine, seeded.id, f"id = '{existing['id']}'")[0]
    batch, records = completed(importer, "suppliers", [row, supplier_row(4)])
    assert (batch["rows_duplicate"], batch["rows_imported"], batch["rows_review"]) == (1, 1, 0)
    dup = records[2]
    assert dup["status"] == "duplicate" and "gstin" in dup["reason"].lower()
    assert row["gstin"] in str(dup["source_record_id"])
    assert records[3]["status"] == "imported"
    rows = suppliers(app_engine, seeded.id, f"gstin = '{row['gstin']}'")
    assert len(rows) == 1, "reported, never merged and never inserted twice"
    assert rows[0] == before, "the existing supplier is untouched (including updated_at)"
    assert len(suppliers(app_engine, seeded.id)) == 2


def test_duplicate_supplier_by_name_and_city_reported_not_merged(
    importer: Importer, quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    base = supplier_row(1, name="Acme  Works", city="Pune")  # odd index: no GSTIN
    existing = existing_supplier(quality, base)
    before = suppliers(app_engine, seeded.id, f"id = '{existing['id']}'")[0]
    # same supplier typed differently: case, outer and inner spacing (normalised before comparing)
    typed = {**base, "name": "  ACME works ", "city": "pune "}
    batch, records = completed(importer, "suppliers", [typed])
    assert batch["rows_duplicate"] == 1 and batch["rows_imported"] == 0
    reason = records[2]["reason"].lower()
    assert records[2]["status"] == "duplicate" and "name" in reason and "city" in reason
    assert suppliers(app_engine, seeded.id) == [before]


def test_duplicate_part_by_part_no_reported(
    importer: Importer, quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    row = part_row(7)
    make_part(quality, **row)
    batch, records = completed(importer, "parts", [row, part_row(8)])
    assert (batch["rows_duplicate"], batch["rows_imported"]) == (1, 1)
    assert records[2]["status"] == "duplicate" and "part" in records[2]["reason"].lower()
    parts = fetch_all(app_engine, seeded.id, "SELECT part_no FROM parts ORDER BY part_no")
    assert [p["part_no"] for p in parts] == [row["part_no"], part_row(8)["part_no"]]


def test_duplicate_supplier_part_reported(
    importer: Importer, quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    supplier = make_supplier(quality)
    part = make_part(quality)
    make_supplier_part(quality, supplier["id"], part["id"], supplier_part_no="V-1", ppm_target=500)
    row = supplier_part_row(
        supplier["code"], part["part_no"], supplier_part_no="V-1", ppm_target=500
    )
    batch, records = completed(importer, "supplier_parts", [row])
    assert batch["rows_duplicate"] == 1 and records[2]["status"] == "duplicate"
    assert len(fetch_all(app_engine, seeded.id, "SELECT 1 FROM supplier_parts")) == 1


def test_changed_row_with_same_natural_key_goes_to_review_not_update(
    importer: Importer, quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    """INV-IMP-04 / A-41: same key, different values is reported for a human. The existing row is never updated."""
    sup_row = supplier_row(2)
    sup = existing_supplier(quality, sup_row)
    part = make_part(quality, **part_row(5))
    link_supplier = make_supplier(quality)
    make_supplier_part(quality, link_supplier["id"], part["id"], ppm_target=500)

    def snapshot() -> tuple[Any, ...]:
        return (
            fetch_all(app_engine, seeded.id, "SELECT * FROM suppliers ORDER BY code"),
            fetch_all(app_engine, seeded.id, "SELECT * FROM parts ORDER BY part_no"),
            fetch_all(app_engine, seeded.id, "SELECT * FROM supplier_parts"),
        )

    before = snapshot()
    cases = [
        ("suppliers", supplier_row(2, name="Renamed By The File"), "name"),
        ("parts", part_row(5, name="A different description"), "name"),
        (
            "supplier_parts",
            supplier_part_row(link_supplier["code"], part["part_no"], ppm_target=900),
            "ppm_target",
        ),
    ]
    for entity, row, changed_field in cases:
        batch, records = completed(importer, entity, [row])
        assert (batch["rows_review"], batch["rows_imported"]) == (1, 0), entity
        assert records[2]["status"] == "review", entity
        assert changed_field in records[2]["reason"].lower().replace(" ", "_"), (
            f"{entity}: the reason must name what changed: {records[2]['reason']}"
        )
    assert snapshot() == before, "review never updates, inserts or merges anything"
    assert sup["name"] == sup_row["name"]


def test_duplicates_inside_one_file_point_at_the_first_row(
    importer: Importer,
) -> None:
    rows: list[dict[str, Any] | None] = [
        supplier_row(2),  # row 2: GSTIN key
        supplier_row(3),  # row 3: name+city key
        supplier_row(
            4, gstin=supplier_row(2)["gstin"], code="OTHER-CODE", name="Same GSTIN other name"
        ),
        supplier_row(5, name=supplier_row(3)["name"], city=supplier_row(3)["city"], code="C-5"),
        supplier_row(6),
    ]
    batch, preview = validated(importer, "suppliers", rows)
    statuses = {n: r["status"] for n, r in preview.items()}
    assert statuses == {2: "valid", 3: "valid", 4: "duplicate", 5: "duplicate", 6: "valid"}
    assert "2" in preview[4]["reason"].split() or "row 2" in preview[4]["reason"].lower()
    assert "row 3" in preview[5]["reason"].lower() or "3" in preview[5]["reason"].split()
    assert (batch["rows_valid"], batch["rows_duplicate"]) == (3, 2)


def test_row_matching_an_archived_supplier_goes_to_review(
    importer: Importer, quality: ApiClient
) -> None:
    """P02 plan 4: archived masters are excluded from import matching, so a match is for a human to look at."""
    row = supplier_row(2)
    supplier = existing_supplier(quality, row)
    assert (
        quality.post(f"/suppliers/{supplier['id']}/archive", {"reason": "Closed down"}).status_code
        in OK
    )
    batch, preview = validated(importer, "suppliers", [row])
    assert preview[2]["status"] == "review" and "archived" in preview[2]["reason"].lower()
    assert batch["rows_review"] == 1


# =================================================================================================
# rejected rows: the reason names the field
# =================================================================================================
@pytest.mark.parametrize(
    ("override", "word"),
    [
        ({"code": None}, "code"),
        ({"name": None}, "name"),
        ({"category": None}, "category"),
        ({"category": "plastic"}, "category"),
        ({"gstin": "27ABC", "city": "Pune"}, "gstin"),
        ({"gstin": "27aaaaa0001a1z!", "city": "Pune"}, "gstin"),
    ],
    ids=["no-code", "no-name", "no-category", "bad-category", "short-gstin", "bad-gstin-chars"],
)
def test_invalid_supplier_row_is_rejected_with_a_reason_naming_the_field(
    importer: Importer, override: dict[str, Any], word: str
) -> None:
    row = supplier_row(1, **override)
    batch, preview = validated(importer, "suppliers", [row])
    assert preview[2]["status"] == "rejected" and word in preview[2]["reason"].lower()
    assert (batch["rows_rejected"], batch["rows_valid"]) == (1, 0)


def test_supplier_with_neither_gstin_nor_city_is_rejected_because_it_cannot_be_deduplicated(
    importer: Importer,
) -> None:
    """A-109."""
    _, preview = validated(importer, "suppliers", [supplier_row(1, gstin=None, city=None)])
    reason = preview[2]["reason"].lower()
    assert preview[2]["status"] == "rejected" and "gstin" in reason and "city" in reason


def test_supplier_code_used_by_a_different_supplier_is_rejected_not_a_database_error(
    importer: Importer, quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    make_supplier(quality, code="TAKEN-1", gstin="27ZZZZZ0001A1Z5", name="Existing One")
    row = supplier_row(2, code="TAKEN-1", gstin="27YYYYY0002A1Z5", name="A Different Supplier")
    batch, records = completed(importer, "suppliers", [row])
    assert records[2]["status"] == "rejected" and "code" in records[2]["reason"].lower()
    assert (batch["status"], batch["rows_rejected"], batch["rows_imported"]) == ("completed", 1, 0)
    assert len(suppliers(app_engine, seeded.id)) == 1


def test_a_code_repeated_in_the_file_for_different_suppliers_rejects_the_later_row(
    importer: Importer,
) -> None:
    rows = [supplier_row(2, code="SAME-CODE"), supplier_row(4, code="SAME-CODE")]
    _, preview = validated(importer, "suppliers", rows)
    assert preview[2]["status"] == "valid"
    assert preview[3]["status"] == "rejected" and "code" in preview[3]["reason"].lower()


# =================================================================================================
# supplier_parts: references must exist (unmapped)
# =================================================================================================
def test_supplier_part_with_an_unknown_supplier_code_or_part_is_unmapped_naming_the_reference(
    importer: Importer, quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    supplier = make_supplier(quality)
    part = make_part(quality)
    rows: list[dict[str, Any] | None] = [
        supplier_part_row(supplier["code"], part["part_no"]),
        supplier_part_row("NO-SUCH-SUPPLIER", part["part_no"]),
        supplier_part_row(supplier["code"], "NO-SUCH-PART"),
        supplier_part_row("GHOST-SUPPLIER", "GHOST-PART"),
    ]
    batch, records = completed(importer, "supplier_parts", rows)
    assert counts(batch) == {
        "received": 4,
        "valid": 1,
        "imported": 1,
        "duplicate": 0,
        "rejected": 0,
        "unmapped": 3,
        "review": 0,
    }
    assert records[3]["status"] == "unmapped" and "NO-SUCH-SUPPLIER" in records[3]["reason"]
    assert records[4]["status"] == "unmapped" and "NO-SUCH-PART" in records[4]["reason"]
    assert records[5]["status"] == "unmapped"
    assert "GHOST-SUPPLIER" in records[5]["reason"] or "GHOST-PART" in records[5]["reason"]
    links = fetch_all(app_engine, seeded.id, "SELECT status, ppm_target FROM supplier_parts")
    assert [(r["status"], r["ppm_target"]) for r in links] == [("active", 500)]


@pytest.mark.parametrize("bad", [0, -5, "abc", 12.5])
def test_supplier_part_ppm_target_must_be_a_positive_whole_number(
    importer: Importer, quality: ApiClient, bad: Any
) -> None:
    supplier, part = make_supplier(quality), make_part(quality)
    _, preview = validated(
        importer,
        "supplier_parts",
        [supplier_part_row(supplier["code"], part["part_no"], ppm_target=bad)],
    )
    assert preview[2]["status"] == "rejected" and "ppm_target" in preview[2][
        "reason"
    ].lower().replace(" ", "_")


def test_supplier_part_ppm_target_float_whole_number_and_blank_are_accepted(
    importer: Importer, quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    supplier = make_supplier(quality)
    parts = [make_part(quality), make_part(quality)]
    rows = [
        supplier_part_row(supplier["code"], parts[0]["part_no"], ppm_target=500.0),
        supplier_part_row(supplier["code"], parts[1]["part_no"], ppm_target=None),
    ]
    completed(importer, "supplier_parts", rows)
    values = fetch_all(app_engine, seeded.id, "SELECT ppm_target FROM supplier_parts")
    assert sorted(v["ppm_target"] or 0 for v in values) == [0, 500]


# =================================================================================================
# INV-IMP-06: partial import
# =================================================================================================
def mixed_file() -> list[dict[str, Any] | None]:
    return [supplier_row(2), supplier_row(4), supplier_row(6), supplier_row(8, category="plastic")]


def test_partial_import_requires_explicit_confirmation(
    importer: Importer, seeded: SeededTenant, app_engine: Engine
) -> None:
    data, name, ctype = file_for("suppliers", mixed_file())
    batch = importer.run("suppliers", data, name, ctype, confirm=False)
    bid = batch["id"]
    assert (batch["rows_valid"], batch["rows_rejected"]) == (3, 1)
    for body in (
        {},
        {"accept_partial": False},
        {"accept_partial": None},
        {"accept_partial": "true"},
        {"accept_partial": 1},
    ):
        resp = importer.client.post(f"/imports/{bid}/confirm", body, key=new_key())
        assert resp.status_code == 422, f"{body}: {resp.status_code} {resp.text}"
        assert problem(resp)["code"] in {"validation_error", "invariant_violation"}
        assert "partial" in resp.text.lower(), "the message must tell the user what to confirm"
    importer.drain()
    assert importer.get(bid)["status"] == "validated", (
        "a refused confirm leaves the batch confirmable"
    )
    assert suppliers(app_engine, seeded.id) == []
    final = importer.confirm(bid, accept_partial=True)
    assert final["status"] == "completed" and final["rows_imported"] == 3
    assert len(suppliers(app_engine, seeded.id)) == 3


def test_a_batch_with_only_valid_rows_needs_no_partial_flag(importer: Importer) -> None:
    data, name, ctype = file_for("suppliers", [supplier_row(i) for i in range(3)])
    batch = importer.run("suppliers", data, name, ctype, confirm=False)
    final = importer.confirm(batch["id"])
    assert final["status"] == "completed" and final["rows_imported"] == 3


def test_confirm_records_the_partial_decision_in_the_audit_log_and_emits_import_confirmed(
    importer: Importer, seeded: SeededTenant, app_engine: Engine, clean_outbox: None
) -> None:
    data, name, ctype = file_for("suppliers", mixed_file())
    batch = importer.run("suppliers", data, name, ctype, confirm=False)
    importer.confirm(batch["id"], accept_partial=True)
    bid = UUID(batch["id"])
    confirms = [r for r in log_rows(app_engine, seeded.id, bid) if "confirm" in r["action"]]
    assert len(confirms) == 1 and confirms[0]["object_type"] == "import_batch"
    assert confirms[0]["after"]["accept_partial"] is True
    events = [
        e for e in outbox_rows(app_engine, seeded.id, bid) if e["event_type"] == "IMPORT_CONFIRMED"
    ]
    assert len(events) == 1 and events[0]["aggregate_type"] == "import_batch"


# =================================================================================================
# confirm: idempotency key and re-validation
# =================================================================================================
def test_confirm_requires_an_idempotency_key(importer: Importer) -> None:
    data, name, ctype = file_for("suppliers", [supplier_row(2)])
    bid = importer.run("suppliers", data, name, ctype, confirm=False)["id"]
    resp = importer.client.post(f"/imports/{bid}/confirm", {})
    assert resp.status_code == 422
    assert any(e["field"] == "Idempotency-Key" for e in problem(resp)["errors"])
    assert importer.get(bid)["status"] == "validated"


def test_confirm_with_the_same_key_replays_and_imports_once(
    importer: Importer, seeded: SeededTenant, app_engine: Engine
) -> None:
    data, name, ctype = file_for("suppliers", [supplier_row(i) for i in range(3)])
    bid = importer.run("suppliers", data, name, ctype, confirm=False)["id"]
    key = new_key()
    first = importer.confirm_response(bid, key=key)
    again = importer.confirm_response(bid, key=key)
    assert first.status_code in OK and again.status_code == first.status_code
    assert again.headers["idempotency-replayed"] == "true" and again.json() == first.json()
    importer.drain()
    assert len(suppliers(app_engine, seeded.id)) == 3
    assert (
        len([r for r in log_rows(app_engine, seeded.id, UUID(bid)) if "confirm" in r["action"]])
        == 1
    )


def test_confirm_with_the_same_key_and_a_different_body_is_an_idempotency_mismatch(
    importer: Importer,
) -> None:
    data, name, ctype = file_for("suppliers", mixed_file())
    bid = importer.run("suppliers", data, name, ctype, confirm=False)["id"]
    key = new_key()
    assert importer.confirm_response(bid, accept_partial=True, key=key).status_code in OK
    clash = importer.confirm_response(bid, accept_partial=False, key=key)
    assert clash.status_code == 422 and problem(clash)["code"] == "idempotency_mismatch"


def test_confirm_revalidates_rows_that_became_duplicates_after_the_preview(
    importer: Importer, quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    rows = [supplier_row(2), supplier_row(4), supplier_row(6)]
    data, name, ctype = file_for("suppliers", list(rows))
    batch = importer.run("suppliers", data, name, ctype, confirm=False)
    assert batch["rows_valid"] == 3
    existing_supplier(
        quality, rows[1]
    )  # someone creates the same supplier between preview and confirm
    final = importer.confirm(batch["id"], accept_partial=True)
    assert final["status"] == "completed", "a late duplicate must not fail the batch"
    assert (final["rows_imported"], final["rows_duplicate"]) == (2, 1)
    records = by_row(importer.records(batch["id"]))
    assert records[3]["status"] == "duplicate"
    assert len(suppliers(app_engine, seeded.id)) == 3


def test_confirm_revalidation_rejects_a_code_taken_after_the_preview(
    importer: Importer, quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    rows = [supplier_row(2), supplier_row(4)]
    data, name, ctype = file_for("suppliers", list(rows))
    batch = importer.run("suppliers", data, name, ctype, confirm=False)
    make_supplier(quality, code=rows[0]["code"], name="Unrelated", gstin="27QQQQQ0009A1Z5")
    final = importer.confirm(batch["id"], accept_partial=True)
    assert (
        final["status"] == "completed"
        and final["rows_rejected"] == 1
        and final["rows_imported"] == 1
    )
    assert by_row(importer.records(batch["id"]))[2]["status"] == "rejected"
    assert len(suppliers(app_engine, seeded.id)) == 2


# =================================================================================================
# import_records
# =================================================================================================
def test_every_received_row_gets_an_import_record_with_final_status_and_hash(
    importer: Importer, quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    existing_supplier(quality, supplier_row(2))
    rows: list[dict[str, Any] | None] = [
        supplier_row(2),
        supplier_row(4),
        supplier_row(6, category="plastic"),
        supplier_row(8, name="x"),
    ]
    batch, records = completed(importer, "suppliers", rows)
    assert sorted(records) == [2, 3, 4, 5]
    assert [records[n]["status"] for n in (2, 3, 4, 5)] == [
        "duplicate",
        "imported",
        "rejected",
        "imported",
    ]
    for record in records.values():
        assert len(record["row_hash"]) == 64 and record["row_hash"] == record["row_hash"].lower()
        if record["status"] == "imported":
            assert record["target_id"] is not None
        else:
            assert record["reason"], "every row that was not imported says why"
    db = fetch_all(
        app_engine,
        seeded.id,
        "SELECT status FROM import_records WHERE batch_id = :b",
        {"b": UUID(batch["id"])},
    )
    assert len(db) == 4 == batch["rows_received"]
    imported = {r["target_id"] for r in records.values() if r["status"] == "imported"}
    stored = {str(s["id"]) for s in suppliers(app_engine, seeded.id)}
    assert imported <= stored


def test_identical_rows_have_the_same_row_hash_across_batches_and_different_rows_differ(
    importer: Importer,
) -> None:
    rows = [supplier_row(2), supplier_row(4)]
    _, first = completed(importer, "suppliers", list(rows))
    data, name, ctype = file_for("suppliers", list(reversed(rows)))
    again = importer.run("suppliers", data, name, ctype, accept_partial=True)
    second = by_row(importer.records(again["id"]))
    assert first[2]["row_hash"] == second[3]["row_hash"], (
        "row order and row number are not part of the hash"
    )
    assert first[2]["row_hash"] != first[3]["row_hash"]


def test_records_can_be_filtered_by_status_and_are_ordered_by_row_number(
    importer: Importer,
) -> None:
    rows: list[dict[str, Any] | None] = [
        supplier_row(2),
        supplier_row(4, category="x"),
        supplier_row(6),
        supplier_row(8, category="y"),
    ]
    batch, _ = completed(importer, "suppliers", rows)
    rejected = importer.records(batch["id"], status="rejected")
    assert [r["row_number"] for r in rejected] == [3, 5]
    everything = importer.records(batch["id"])
    assert [r["row_number"] for r in everything] == [2, 3, 4, 5]


def test_preview_can_be_filtered_by_status_for_the_wizard_tabs(importer: Importer) -> None:
    rows: list[dict[str, Any] | None] = [
        supplier_row(2),
        supplier_row(2, code="DUP"),
        supplier_row(4, category="x"),
    ]
    batch, _ = validated(importer, "suppliers", rows)
    assert [r["row_number"] for r in importer.preview(batch["id"], status="duplicate")] == [3]
    assert [r["row_number"] for r in importer.preview(batch["id"], status="rejected")] == [4]
    page = importer.client.get(f"/imports/{batch['id']}/preview", params={"status": "bogus"})
    assert page.status_code in (400, 422)


# =================================================================================================
# A-118: natural keys of different kinds meet
# =================================================================================================
def keyed(code: str, name: str, city: str, gstin: str | None) -> dict[str, Any]:
    return {
        "code": code,
        "name": name,
        "gstin": gstin,
        "city": city,
        "state": "Maharashtra",
        "category": "bought_out",
    }


@pytest.mark.parametrize(
    ("existing_gstin", "file_gstin"),
    [
        (None, "27AAAAA7001A1Z5"),  # row has a GSTIN, the supplier has none
        ("27AAAAA7002A1Z5", "27AAAAA7003A1Z5"),  # different GSTIN
        ("27AAAAA7004A1Z5", None),  # the reverse: row has none, the supplier has one
    ],
    ids=["gstin-vs-none", "gstin-vs-other-gstin", "none-vs-gstin"],
)
def test_a_row_matching_an_existing_supplier_by_name_and_city_under_another_gstin_goes_to_review(
    importer: Importer,
    quality: ApiClient,
    seeded: SeededTenant,
    app_engine: Engine,
    existing_gstin: str | None,
    file_gstin: str | None,
) -> None:
    existing = existing_supplier(quality, keyed("OLD-1", "Acme Works", "Pune", existing_gstin))
    before = suppliers(app_engine, seeded.id)
    row = keyed("NEW-1", "  ACME  works ", "pune", file_gstin)
    batch, records = completed(importer, "suppliers", [row])
    assert (batch["rows_review"], batch["rows_imported"], batch["rows_duplicate"]) == (1, 0, 0)
    assert records[2]["status"] == "review"
    reason = records[2]["reason"].lower()
    assert "name" in reason and "city" in reason, "names the name + city key"
    assert "gstin" in reason, "and the GSTIN key"
    assert suppliers(app_engine, seeded.id) == before, "never imported, never merged"
    assert existing["id"] in {str(s["id"]) for s in before}


def test_a_gstin_row_with_no_name_and_city_match_is_still_valid(
    importer: Importer, quality: ApiClient
) -> None:
    """Contrast case: with no supplier of that name and city, a GSTIN row is simply valid."""
    existing_supplier(quality, keyed("OTHER-1", "Different Name", "Pune", None))
    _, preview = validated(
        importer, "suppliers", [keyed("NEW-2", "Acme Works", "Pune", "27AAAAA7005A1Z5")]
    )
    assert preview[2]["status"] == "valid"


@pytest.mark.parametrize(
    ("first_gstin", "second_gstin"),
    [("27AAAAA7006A1Z5", None), (None, "27AAAAA7007A1Z5"), ("27AAAAA7008A1Z5", "27AAAAA7009A1Z5")],
    ids=["gstin-then-none", "none-then-gstin", "gstin-then-other-gstin"],
)
def test_the_cross_key_rule_also_applies_within_one_file(
    importer: Importer, first_gstin: str | None, second_gstin: str | None
) -> None:
    rows: list[dict[str, Any] | None] = [
        keyed("F-1", "Acme Works", "Pune", first_gstin),
        keyed("F-2", "acme works", "PUNE", second_gstin),
    ]
    batch, preview = validated(importer, "suppliers", rows)
    assert preview[2]["status"] == "valid"
    assert preview[3]["status"] == "review", "the later row is the one held back"
    reason = preview[3]["reason"].lower()
    assert "name" in reason and "city" in reason and "row 2" in reason
    assert (batch["rows_valid"], batch["rows_review"]) == (1, 1)


def test_two_rows_with_the_same_name_and_city_and_no_gstin_are_still_plain_duplicates(
    importer: Importer,
) -> None:
    rows: list[dict[str, Any] | None] = [
        keyed("D-1", "Acme Works", "Pune", None),
        keyed("D-2", "Acme Works", "Pune", None),
    ]
    _, preview = validated(importer, "suppliers", rows)
    assert preview[3]["status"] == "duplicate"
