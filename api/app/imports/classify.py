"""Row classification (blueprint 8 C3, P02 plan 2.4): valid | duplicate | review | rejected | unmapped.

Pure and set-based: the existing masters are loaded once and indexed in dictionaries, so 5,000 rows cost five thousand
dictionary lookups and no query. Duplicates are REPORTED, never merged or updated (INV-IMP-04); a row whose key exists
with changed values goes to `review` (A-41); keys of different kinds meet through name + city (A-118).
"""

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.core.ids import new_id
from app.imports.normalise import (
    gstin_key,
    name_city_key,
    normalise_text,
    row_hash,
)
from app.imports.parsing import ParsedRow
from app.imports.spec import (
    DUPLICATE,
    REJECTED,
    REVIEW,
    SUPPLIER_CATEGORIES,
    UNMAPPED,
    VALID,
)
from app.masters.service import (
    PartSnapshot,
    SupplierPartSnapshot,
    SupplierSnapshot,
)

_GSTIN = re.compile(r"^[0-9A-Z]{15}$")
_WHOLE = re.compile(r"^[0-9]+$")
MAX_PPM = 2_147_483_647


@dataclass
class Classified:
    row_number: int
    values: dict[str, str | None]
    status: str
    reason: str | None
    source_record_id: str | None
    row_hash: str
    new_id: UUID | None = None  # set for `valid` rows: the id the created master will get
    data: dict[str, Any] = field(
        default_factory=dict
    )  # normalised values / resolved ids for creation


def _result(
    row: ParsedRow,
    status: str,
    reason: str | None = None,
    source: str | None = None,
    data: dict[str, Any] | None = None,
) -> Classified:
    return Classified(
        row_number=row.row_number,
        values=dict(row.values),
        status=status,
        reason=reason,
        source_record_id=source,
        row_hash=row_hash(row.values),
        new_id=new_id() if status == VALID else None,
        data=data or {},
    )


def _first_live[T](items: Sequence[T], archived: Any) -> T | None:
    """The match to compare against: a live one if there is one, else an archived one."""
    live = [i for i in items if not archived(i)]
    return live[0] if live else (items[0] if items else None)


def _same(a: str | None, b: str | None, *, fold: bool) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return normalise_text(a) == normalise_text(b) if fold else a == b


# =================================================================================================== suppliers
def _validate_supplier(
    values: Mapping[str, str | None],
) -> tuple[dict[str, str | None], str | None]:
    code, name = values.get("code"), values.get("name")
    gstin = (values.get("gstin") or "").upper() or None
    city, state = values.get("city"), values.get("state")
    category = values.get("category")
    if category is not None:
        category = re.sub(r"[\s-]+", "_", category.strip().lower())
    if not code:
        return {}, "code is required"
    if len(code) > 100:
        return {}, "code is longer than 100 characters"
    if not name:
        return {}, "name is required"
    if not category:
        return {}, f"category is required (one of {', '.join(SUPPLIER_CATEGORIES)})"
    if category not in SUPPLIER_CATEGORIES:
        return {}, f"category must be one of {', '.join(SUPPLIER_CATEGORIES)}"
    if gstin is not None and not _GSTIN.match(gstin):
        return {}, "gstin must be 15 letters or digits"
    if gstin is None and not city:
        return {}, "needs a GSTIN or a city to detect duplicates (gstin and city are both empty)"
    clean = {
        "code": code,
        "name": name,
        "gstin": gstin,
        "city": city,
        "state": state,
        "category": category,
    }
    return clean, None


def _supplier_changes(
    clean: Mapping[str, str | None], existing: SupplierSnapshot, mapped: Collection[str]
) -> list[str]:
    current = {
        "code": existing.code,
        "name": existing.name,
        "gstin": existing.gstin,
        "city": existing.city,
        "state": existing.state,
        "category": existing.category,
    }
    fold = {"name", "city", "state"}
    return [
        f
        for f in ("code", "name", "gstin", "city", "state", "category")
        if f in mapped and not _same(clean[f], current[f], fold=f in fold)
    ]


def classify_suppliers(
    rows: Sequence[ParsedRow],
    existing: Sequence[SupplierSnapshot],
    mapped: Collection[str],
) -> list[Classified]:
    by_gstin: dict[str, list[SupplierSnapshot]] = {}
    by_nc: dict[tuple[str, str], list[SupplierSnapshot]] = {}
    by_code: dict[str, SupplierSnapshot] = {}
    for s in existing:
        by_code[s.code] = s
        if s.gstin:
            by_gstin.setdefault(s.gstin, []).append(s)
        nc = name_city_key(s.name, s.city)
        if nc is not None:
            by_nc.setdefault(nc, []).append(s)
    file_gstin: dict[str, int] = {}
    file_nc: dict[tuple[str, str], list[tuple[int, bool]]] = {}  # (row number, has gstin)
    file_codes: dict[str, int] = {}
    out: list[Classified] = []

    for row in rows:
        clean, error = _validate_supplier(row.values)
        if error is not None:
            out.append(_result(row, REJECTED, error))
            continue
        gstin = clean["gstin"]
        nc = name_city_key(clean["name"], clean["city"])
        key_text = gstin if gstin else (f"{nc[0]}|{nc[1]}" if nc else None)

        def reply(
            status: str,
            reason: str,
            _row: ParsedRow = row,
            _key: str | None = key_text,
            _clean: dict[str, str | None] = clean,
        ) -> Classified:
            out_row = _result(_row, status, reason, _key, _clean)
            out.append(out_row)
            return out_row

        def compare(
            match: SupplierSnapshot, how: str, _clean: dict[str, str | None] = clean
        ) -> tuple[str, str]:
            if match.archived:
                return (
                    REVIEW,
                    f"Matches archived supplier {match.code} by {how}; archived suppliers are never changed.",
                )
            changed = _supplier_changes(_clean, match, mapped)
            if changed:
                return (
                    REVIEW,
                    f"Same {how} as supplier {match.code} but values differ: {', '.join(changed)}.",
                )
            return DUPLICATE, f"{how[0].upper() + how[1:]} already exists as supplier {match.code}."

        # 1. the same natural key, in the data
        if gstin:
            match = _first_live(by_gstin.get(gstin, []), lambda s: s.archived)
            if match is not None:
                status, reason = compare(match, f"GSTIN {gstin}")
                reply(status, reason)
                continue
            if gstin in file_gstin:
                reply(DUPLICATE, f"Same GSTIN {gstin} as row {file_gstin[gstin]} of this file.")
                continue
        elif nc is not None:
            plain = [s for s in by_nc.get(nc, []) if not s.gstin]
            match = _first_live(plain, lambda s: s.archived)
            if match is not None:
                status, reason = compare(match, "name and city")
                reply(status, reason)
                continue
            earlier_plain = [n for n, has_gstin in file_nc.get(nc, []) if not has_gstin]
            if earlier_plain:
                reply(DUPLICATE, f"Same name and city as row {earlier_plain[0]} of this file.")
                continue

        # 2. keys of different kinds meet through name + city (A-118): a human decides. SPEC-GAP: A-118
        if nc is not None:
            others = [
                s for s in by_nc.get(nc, []) if (s.gstin or None) != gstin and (gstin or s.gstin)
            ]
            other = _first_live(others, lambda s: s.archived)
            if other is not None:
                reply(
                    REVIEW,
                    f"Name and city match supplier {other.code} but the GSTIN differs "
                    f"({gstin or 'none'} in the file, {other.gstin or 'none'} on record); "
                    "not imported, not merged.",
                )
                continue
            earlier = [n for n, has_gstin in file_nc.get(nc, []) if has_gstin or gstin]
            if earlier:
                reply(
                    REVIEW,
                    f"Name and city match row {earlier[0]} of this file but the GSTIN differs; "
                    "not imported, not merged.",
                )
                continue

        # 3. the supplier code is unique per tenant (rejected, not a database error)
        code = clean["code"] or ""
        taken = by_code.get(code)
        if taken is not None:
            reply(
                REJECTED,
                f"code {code} is already used by supplier {taken.name} ({taken.gstin or 'no GSTIN'}).",
            )
            continue
        if code in file_codes:
            reply(
                REJECTED,
                f"code {code} is already used by row {file_codes[code]} of this file for a different supplier.",
            )
            continue

        accepted = reply(VALID, "")
        accepted.reason = None
        if gstin:
            file_gstin[gstin] = row.row_number
        if nc is not None:
            file_nc.setdefault(nc, []).append((row.row_number, bool(gstin)))
        file_codes[code] = row.row_number
    return out


# ======================================================================================================== parts
def classify_parts(
    rows: Sequence[ParsedRow], existing: Sequence[PartSnapshot], mapped: Collection[str]
) -> list[Classified]:
    by_no = {p.part_no: p for p in existing}
    seen: dict[str, int] = {}
    out: list[Classified] = []
    for row in rows:
        part_no, name = row.values.get("part_no"), row.values.get("name")
        if not part_no:
            out.append(_result(row, REJECTED, "part_no is required"))
            continue
        if not name:
            out.append(_result(row, REJECTED, "name is required", part_no))
            continue
        clean = {
            "part_no": part_no,
            "name": name,
            "category": row.values.get("category"),
            "current_revision": row.values.get("current_revision"),
        }
        match = by_no.get(part_no)
        if match is not None:
            if match.archived:
                out.append(
                    _result(
                        row,
                        REVIEW,
                        f"Part {part_no} exists but is archived; archived parts are never changed.",
                        part_no,
                        clean,
                    )
                )
                continue
            current = {
                "name": match.name,
                "category": match.category,
                "current_revision": match.current_revision,
            }
            changed = [
                f
                for f in ("name", "category", "current_revision")
                if f in mapped and not _same(clean[f], current[f], fold=True)
            ]
            if changed:
                out.append(
                    _result(
                        row,
                        REVIEW,
                        f"Part {part_no} already exists but values differ: {', '.join(changed)}.",
                        part_no,
                        clean,
                    )
                )
            else:
                out.append(
                    _result(row, DUPLICATE, f"Part {part_no} already exists.", part_no, clean)
                )
            continue
        if part_no in seen:
            out.append(
                _result(
                    row,
                    DUPLICATE,
                    f"Same part_no {part_no} as row {seen[part_no]} of this file.",
                    part_no,
                    clean,
                )
            )
            continue
        seen[part_no] = row.row_number
        out.append(_result(row, VALID, None, part_no, clean))
    return out


# ================================================================================================ supplier_parts
def classify_supplier_parts(
    rows: Sequence[ParsedRow],
    suppliers: Sequence[SupplierSnapshot],
    parts: Sequence[PartSnapshot],
    existing: Sequence[SupplierPartSnapshot],
    mapped: Collection[str],
) -> list[Classified]:
    supplier_by_code = {s.code: s for s in suppliers}
    part_by_no = {p.part_no: p for p in parts}
    link_by_pair = {(link.supplier_id, link.part_id): link for link in existing}
    seen: dict[tuple[UUID, UUID], int] = {}
    out: list[Classified] = []
    for row in rows:
        supplier_code, part_no = row.values.get("supplier_code"), row.values.get("part_no")
        if not supplier_code:
            out.append(_result(row, REJECTED, "supplier_code is required"))
            continue
        if not part_no:
            out.append(_result(row, REJECTED, "part_no is required", supplier_code))
            continue
        source = f"{supplier_code}/{part_no}"
        ppm_text = row.values.get("ppm_target")
        ppm: int | None = None
        if ppm_text is not None:
            if not _WHOLE.match(ppm_text) or not 0 < int(ppm_text) <= MAX_PPM:
                out.append(
                    _result(row, REJECTED, "ppm_target must be a positive whole number", source)
                )
                continue
            ppm = int(ppm_text)
        supplier, part = supplier_by_code.get(supplier_code), part_by_no.get(part_no)
        missing: list[str] = []
        if supplier is None:
            missing.append(f"supplier code {supplier_code} does not exist")
        elif supplier.archived:
            missing.append(f"supplier {supplier_code} is archived")
        if part is None:
            missing.append(f"part {part_no} does not exist")
        elif part.archived:
            missing.append(f"part {part_no} is archived")
        if missing or supplier is None or part is None:
            text = "; ".join(missing)
            out.append(_result(row, UNMAPPED, text[0].upper() + text[1:] + ".", source))
            continue
        clean: dict[str, Any] = {
            "supplier_id": supplier.id,
            "part_id": part.id,
            "supplier_part_no": row.values.get("supplier_part_no"),
            "ppm_target": ppm,
        }
        pair = (supplier.id, part.id)
        link = link_by_pair.get(pair)
        if link is not None:
            if link.archived:
                out.append(
                    _result(
                        row,
                        REVIEW,
                        f"The link {source} exists but is archived; restore it in the app.",
                        source,
                        clean,
                    )
                )
                continue
            changed = []
            if "supplier_part_no" in mapped and not _same(
                clean["supplier_part_no"], link.supplier_part_no, fold=False
            ):
                changed.append("supplier_part_no")
            if "ppm_target" in mapped and ppm != link.ppm_target:
                changed.append("ppm_target")
            if changed:
                out.append(
                    _result(
                        row,
                        REVIEW,
                        f"The link {source} already exists but values differ: {', '.join(changed)}.",
                        source,
                        clean,
                    )
                )
            else:
                out.append(
                    _result(row, DUPLICATE, f"The link {source} already exists.", source, clean)
                )
            continue
        if pair in seen:
            out.append(
                _result(
                    row,
                    DUPLICATE,
                    f"Same supplier and part as row {seen[pair]} of this file.",
                    source,
                    clean,
                )
            )
            continue
        seen[pair] = row.row_number
        out.append(_result(row, VALID, None, source, clean))
    return out


def counts(results: Sequence[Classified]) -> dict[str, int]:
    tally = {VALID: 0, DUPLICATE: 0, REJECTED: 0, UNMAPPED: 0, REVIEW: 0}
    for r in results:
        tally[r.status] += 1
    return tally


__all__ = [
    "Classified",
    "classify_parts",
    "classify_supplier_parts",
    "classify_suppliers",
    "counts",
    "gstin_key",
]
