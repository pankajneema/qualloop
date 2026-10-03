"""Pure rules of the import engine (blueprint 8 C3, P02 plan section 4): cell cleaning, natural keys, row hash."""

import hashlib
import re
from collections.abc import Mapping

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_cell(value: object) -> str | None:
    """A spreadsheet cell as clean text, or None when it is empty.

    Strings are stripped and keep their content (a text `1234.0` stays text; a leading `=` is just text). Real numbers
    become text without a spurious `.0` (Excel often reads a numeric GSTIN or part number as a float)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return repr(value)
    text = value if isinstance(value, str) else str(value)
    text = _CONTROL.sub("", text).strip()
    return text or None


def normalise_text(value: str) -> str:
    """Trim, collapse inner whitespace runs to one space and case-fold (`Straße` -> `strasse`)."""
    return " ".join(value.split()).casefold()


def gstin_key(gstin: str | None) -> str | None:
    cleaned = clean_cell(gstin)
    return cleaned.upper() if cleaned else None


def name_city_key(name: str | None, city: str | None) -> tuple[str, str] | None:
    cleaned_name, cleaned_city = clean_cell(name), clean_cell(city)
    if not cleaned_name or not cleaned_city:
        return None
    return normalise_text(cleaned_name), normalise_text(cleaned_city)


def supplier_natural_key(gstin: str | None, name: str | None, city: str | None) -> str | None:
    """The supplier natural key (blueprint 8 C3, A-109): the GSTIN when there is one, else name + city.

    None when there is no GSTIN and name or city is missing: such a row cannot be deduplicated. The value is opaque; a
    GSTIN key never equals a name + city key."""
    g = gstin_key(gstin)
    if g:
        return f"gstin:{g}"
    nc = name_city_key(name, city)
    if nc is None:
        return None
    return f"namecity:{nc[0]}\x1f{nc[1]}"


def row_hash(values: Mapping[str, object]) -> str:
    """SHA-256 (lower-case hex) over the cleaned values: independent of key order, outer whitespace and blank-vs-missing.

    Fields are length-prefixed, so `("ab", "c")` and `("a", "bc")` differ. Case is not folded."""
    parts: list[str] = []
    for key in sorted(values):
        cleaned = clean_cell(values[key])
        if cleaned is None:
            continue
        parts.append(f"{len(key)}:{key}={len(cleaned)}:{cleaned}")
    return hashlib.sha256("\x1e".join(parts).encode()).hexdigest()
