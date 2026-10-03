"""The reconciliation report (blueprint 8 C3, INV-IMP-05): an .xlsx with a Summary sheet and one line per received row.

Every cell passes `neutralise_cell` (INV-IMP-08), and the workbook is built in write-only mode (flat memory for large
files). It is generated on download from the persisted `import_records` and the preview values, so it always matches them."""

import io
from collections.abc import Sequence
from typing import Any

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from app.core.excel import neutralise_cell
from app.imports.models import ImportBatch, ImportRecord
from app.imports.spec import TARGET_FIELDS

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _cell(value: object) -> object:
    if isinstance(value, str):
        value = ILLEGAL_CHARACTERS_RE.sub("", value)
    return neutralise_cell(value)


def build_report(
    batch: ImportBatch, records: Sequence[ImportRecord], preview: Sequence[dict[str, Any]]
) -> bytes:
    values_by_row = {int(r["row_number"]): r["values"] for r in preview}
    fields = [f.name for f in TARGET_FIELDS[batch.entity] if f.name in batch.mapping]
    workbook = Workbook(write_only=True)

    summary = workbook.create_sheet("Summary")
    for label, number in (
        ("Received", batch.rows_received),
        ("Valid", batch.rows_valid),
        ("Imported", batch.rows_imported),
        ("Duplicate", batch.rows_duplicate),
        ("Rejected", batch.rows_rejected),
        ("Unmapped", batch.rows_unmapped),
        ("Needs review", batch.rows_review),
    ):
        summary.append([_cell(label), number])

    rows = workbook.create_sheet("Rows")
    rows.append([_cell(h) for h in ("Row", "Status", "Reason", *fields)])
    for record in records:
        values = values_by_row.get(record.row_number, {})
        rows.append(
            [
                record.row_number,
                _cell(record.status),
                _cell(record.reason),
                *[_cell(values.get(f)) for f in fields],
            ]
        )
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()
