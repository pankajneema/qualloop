"""P02 helpers: generate xlsx / csv import files and drive the import flow end to end.

Files are built in memory by the tests (no binary fixtures are committed). `openpyxl` is loaded lazily through
`contract.load`, so a missing dependency fails only the tests that build xlsx files (P02 test contract, section 4).
"""

import csv
import hashlib
import io
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from uuid import UUID

import httpx

from tests.factories.api import ApiClient, new_key
from tests.factories.contract import load

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_TYPE = "text/csv"
OK = (200, 201, 202)

# Header text in the generated files differs from the target field names on purpose: the mapping step has to work.
SUPPLIER_COLUMNS = {
    "code": "Supplier Code",
    "name": "Supplier Name",
    "gstin": "GSTIN No",
    "city": "City",
    "state": "State",
    "category": "Category",
}
PART_COLUMNS = {
    "part_no": "Part No",
    "name": "Description",
    "category": "Group",
    "current_revision": "Rev",
}
SUPPLIER_PART_COLUMNS = {
    "supplier_code": "Vendor Code",
    "part_no": "Part No",
    "supplier_part_no": "Vendor Part",
    "ppm_target": "PPM Target",
}
COLUMNS_BY_ENTITY = {
    "suppliers": SUPPLIER_COLUMNS,
    "parts": PART_COLUMNS,
    "supplier_parts": SUPPLIER_PART_COLUMNS,
}


def mapping_for(entity: str) -> dict[str, str]:
    """target field -> source column header, for the default generated files."""
    return dict(COLUMNS_BY_ENTITY[entity])


# --- row generators ---------------------------------------------------------------------------------------------
def supplier_row(i: int, **over: Any) -> dict[str, Any]:
    """Unique per `i`: even rows carry a GSTIN, odd rows only name + city (so both natural keys are used)."""
    row: dict[str, Any] = {
        "code": f"SUP{i:05d}",
        "name": f"Supplier {i:05d} Industries",
        "gstin": f"27AAAAA{i:04d}A1Z5" if i % 2 == 0 else None,
        "city": f"City{i % 50}",
        "state": "Maharashtra",
        "category": "bought_out",
    }
    row.update(over)
    return row


def part_row(i: int, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "part_no": f"PN-{i:05d}",
        "name": f"Bracket {i:05d}",
        "category": "Fasteners",
        "current_revision": "A",
    }
    row.update(over)
    return row


def supplier_part_row(supplier_code: str, part_no: str, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "supplier_code": supplier_code,
        "part_no": part_no,
        "supplier_part_no": f"V-{part_no}",
        "ppm_target": 500,
    }
    row.update(over)
    return row


# --- file builders ------------------------------------------------------------------------------------------------
def _table(
    columns: Mapping[str, str], rows: Sequence[Mapping[str, Any] | None], extra: bool
) -> tuple[list[str], list[list[Any] | None]]:
    targets = list(columns)
    headers = [columns[t] for t in targets]
    body: list[list[Any] | None] = []
    for row in rows:
        body.append(None if row is None else [row.get(t) for t in targets])
    if extra:  # an unmapped date column and a free-text column: both must be ignored for masters
        headers += ["Last Audit", "Remarks"]
        body = [None if r is None else [*r, "2026-01-15", "ignore me"] for r in body]
    return headers, body


def xlsx_bytes(
    columns: Mapping[str, str],
    rows: Sequence[Mapping[str, Any] | None],
    *,
    extra_columns: bool = False,
    sheet_title: str = "Suppliers",
    force_text: bool = True,
) -> bytes:
    """An .xlsx workbook. `None` in `rows` is an empty row. Strings are written as text even when they start with
    `=` (a real file would hold the literal text); numbers stay numbers (floats included)."""
    workbook_cls = load("openpyxl", "Workbook")
    wb = workbook_cls()
    ws = wb.active
    ws.title = sheet_title
    headers, body = _table(columns, rows, extra_columns)
    for col, header in enumerate(headers, start=1):
        ws.cell(row=1, column=col, value=header)
    for r, row in enumerate(body, start=2):
        if row is None:
            continue
        for col, value in enumerate(row, start=1):
            if value is None:
                continue
            cell = ws.cell(row=r, column=col, value=value)
            if force_text and isinstance(value, str):
                cell.data_type = "s"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def xlsx_raw(
    rows: Sequence[Sequence[Any]], *, extra_sheet: bool = False, merge: str | None = None
) -> bytes:
    """A workbook from raw rows (first row = header). Optionally a second sheet and one merged range."""
    wb = load("openpyxl", "Workbook")()
    ws = wb.active
    ws.title = "First"
    for row in rows:
        ws.append(list(row))
    if merge:
        ws.merge_cells(merge)
    if extra_sheet:
        other = wb.create_sheet("Second")
        other.append(["Supplier Code", "Supplier Name"])
        other.append(["WRONG-SHEET", "Must never be read"])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def csv_bytes(
    columns: Mapping[str, str],
    rows: Sequence[Mapping[str, Any] | None],
    *,
    extra_columns: bool = False,
    encoding: str = "utf-8",
    bom: bool = False,
) -> bytes:
    headers, body = _table(columns, rows, extra_columns)
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(headers)
    for row in body:
        writer.writerow([] if row is None else ["" if v is None else v for v in row])
    text = buf.getvalue()
    data = text.encode(encoding)
    return (b"\xef\xbb\xbf" + data) if bom else data


def file_for(
    entity: str,
    rows: Sequence[Mapping[str, Any] | None],
    *,
    kind: str = "xlsx",
    **kw: Any,
) -> tuple[bytes, str, str]:
    """(bytes, file_name, content_type) for the default columns of `entity`."""
    columns = COLUMNS_BY_ENTITY[entity]
    if kind == "csv":
        return csv_bytes(columns, rows, **kw), f"{entity}.csv", CSV_TYPE
    return xlsx_bytes(columns, rows, **kw), f"{entity}.xlsx", XLSX_TYPE


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- driving the flow ---------------------------------------------------------------------------------------------
def stage_file(
    client: ApiClient, tenant_id: UUID, data: bytes, content_type: str = XLSX_TYPE
) -> str:
    """POST /files/upload-url, PUT the bytes to the quarantine bucket, run the scan synchronously (promotes the
    object to the files bucket). Returns the object key."""
    resp = client.post(
        "/files/upload-url", {"purpose": "import", "content_type": content_type, "size": len(data)}
    )
    assert resp.status_code == 200, resp.text
    info = resp.json()
    put = httpx.put(info["url"], content=data, headers={"Content-Type": content_type}, timeout=120)
    assert put.status_code in (200, 204), put.text
    result = load("app.core.files.scanner", "scan_quarantined")(tenant_id, info["key"])
    assert result.status == "available", f"scan: {result}"
    return str(info["key"])


class Importer:
    """One user's view of the import wizard as API calls. `drain` runs the in-process `imports` worker until idle."""

    def __init__(self, client: ApiClient, tenant_id: UUID, drain: Callable[[], None]) -> None:
        self.client = client
        self.tenant_id = tenant_id
        self.drain = drain

    # -- steps -----------------------------------------------------------------------------------------------
    def create_response(
        self,
        entity: str,
        data: bytes,
        file_name: str,
        content_type: str = XLSX_TYPE,
    ) -> httpx.Response:
        key = stage_file(self.client, self.tenant_id, data, content_type)
        return self.client.post("/imports", {"entity": entity, "key": key, "file_name": file_name})

    def upload(
        self, entity: str, data: bytes, file_name: str, content_type: str = XLSX_TYPE
    ) -> dict[str, Any]:
        resp = self.create_response(entity, data, file_name, content_type)
        assert resp.status_code in OK, resp.text
        batch: dict[str, Any] = resp.json()
        return batch

    def map(self, batch_id: str, mapping: Mapping[str, str]) -> httpx.Response:
        return self.client.post(f"/imports/{batch_id}/map", {"mapping": dict(mapping)})

    def validate_response(self, batch_id: str) -> httpx.Response:
        return self.client.post(f"/imports/{batch_id}/validate", {})

    def get(self, batch_id: str) -> dict[str, Any]:
        resp = self.client.get(f"/imports/{batch_id}")
        assert resp.status_code == 200, resp.text
        batch: dict[str, Any] = resp.json()
        return batch

    def validate(self, batch_id: str) -> dict[str, Any]:
        resp = self.validate_response(batch_id)
        assert resp.status_code in OK, resp.text
        self.drain()
        return self.get(batch_id)

    def confirm_response(
        self, batch_id: str, accept_partial: bool | None = None, key: str | None = None
    ) -> httpx.Response:
        body: dict[str, Any] = {} if accept_partial is None else {"accept_partial": accept_partial}
        return self.client.post(f"/imports/{batch_id}/confirm", body, key=key or new_key())

    def confirm(
        self, batch_id: str, accept_partial: bool | None = None, key: str | None = None
    ) -> dict[str, Any]:
        resp = self.confirm_response(batch_id, accept_partial, key)
        assert resp.status_code in OK, resp.text
        self.drain()
        return self.get(batch_id)

    # -- whole pipeline ----------------------------------------------------------------------------------------
    def run(
        self,
        entity: str,
        data: bytes,
        file_name: str,
        content_type: str = XLSX_TYPE,
        *,
        mapping: Mapping[str, str] | None = None,
        confirm: bool = True,
        accept_partial: bool | None = None,
    ) -> dict[str, Any]:
        """upload -> map -> validate (-> confirm). Returns the final batch read model."""
        batch = self.upload(entity, data, file_name, content_type)
        mapped = self.map(batch["id"], mapping or mapping_for(entity))
        assert mapped.status_code in OK, mapped.text
        validated = self.validate(batch["id"])
        assert validated["status"] == "validated", validated
        if not confirm:
            return validated
        return self.confirm(batch["id"], accept_partial)

    # -- reading results ---------------------------------------------------------------------------------------
    def _all(self, path: str, **params: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(200):
            query = {"limit": 200, **params, **({"cursor": cursor} if cursor else {})}
            resp = self.client.get(path, params=query)
            assert resp.status_code == 200, f"GET {path}: {resp.status_code} {resp.text}"
            page = resp.json()
            items.extend(page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                return items
        raise AssertionError(f"{path}: pagination never terminated")

    def preview(self, batch_id: str, **params: Any) -> list[dict[str, Any]]:
        return self._all(f"/imports/{batch_id}/preview", **params)

    def records(self, batch_id: str, **params: Any) -> list[dict[str, Any]]:
        return self._all(f"/imports/{batch_id}/records", **params)

    def report(self, batch_id: str) -> Any:
        resp = self.client.get(f"/imports/{batch_id}/report.xlsx")
        assert resp.status_code == 200, resp.text
        return load("openpyxl", "load_workbook")(io.BytesIO(resp.content))


def by_row(items: Sequence[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    return {int(i["row_number"]): i for i in items}


def counts(batch: Mapping[str, Any]) -> dict[str, int]:
    return {
        k: int(batch[f"rows_{k}"])
        for k in ("received", "valid", "imported", "duplicate", "rejected", "unmapped", "review")
    }


def sheet_rows(workbook: Any, name: str) -> list[list[Any]]:
    return [list(r) for r in workbook[name].iter_rows(values_only=True)]


def summary(workbook: Any) -> dict[str, Any]:
    """`Summary` sheet as {label: value} (column A label, column B value; a header row is tolerated)."""
    return {str(r[0]): r[1] for r in sheet_rows(workbook, "Summary") if r and r[0] is not None}
