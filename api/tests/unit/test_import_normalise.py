"""Pure rules of the import engine (blueprint 8 C3, P02 plan section 4): cell cleaning, natural keys, row hash.

Contract (docs/build/phases/P02-test-contract.md section 1): module `app.imports.normalise`."""

from typing import Any

import pytest

from tests.factories.contract import load


def fn(name: str) -> Any:
    return load("app.imports.normalise", name)


# --- clean_cell -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("  Acme  ", "Acme"),
        ("\tPune\r\n", "Pune"),
        (1234.0, "1234"),
        (1234, "1234"),
        (0.0, "0"),
        (12.5, "12.5"),
        (123456789012345.0, "123456789012345"),
        ("1234.0", "1234.0"),  # text stays text: only real numbers are normalised
        ("", None),
        ("   ", None),
        (None, None),
        ("=SUM(1,2)", "=SUM(1,2)"),  # stored as text, never evaluated or stripped
    ],
)
def test_clean_cell(raw: object, clean: str | None) -> None:
    assert fn("clean_cell")(raw) == clean


# --- normalise_text ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "normal"),
    [
        ("  Acme   Works ", "acme works"),
        ("ACME\tWorks", "acme works"),
        ("Straße", "strasse"),
        ("", ""),
    ],
)
def test_normalise_text_trims_collapses_and_casefolds(raw: str, normal: str) -> None:
    assert fn("normalise_text")(raw) == normal


# --- supplier natural key (INV-IMP-02) ---------------------------------------------------------------------------------
def test_gstin_key_ignores_case_and_outer_spaces() -> None:
    key = fn("supplier_natural_key")
    assert key("27AAAAA0001A1Z5", "Acme", "Pune") == key(
        " 27aaaaa0001a1z5 ", "Other name", "Mumbai"
    )


def test_gstin_key_beats_name_and_city() -> None:
    key = fn("supplier_natural_key")
    assert key("27AAAAA0001A1Z5", "Acme", "Pune") != key("27AAAAA0002A1Z5", "Acme", "Pune")


def test_name_and_city_key_is_normalised() -> None:
    key = fn("supplier_natural_key")
    assert key(None, "Acme  Works", "Pune") == key(None, " ACME works ", "pune ")
    assert key(None, "Acme Works", "Pune") != key(None, "Acme Works", "Mumbai")
    assert key(None, "Acme Works", "Pune") != key(None, "Acme Work", "Pune")


def test_a_name_city_key_never_equals_a_gstin_key() -> None:
    key = fn("supplier_natural_key")
    assert key("27AAAAA0001A1Z5", None, None) != key(None, "27AAAAA0001A1Z5", "Pune")


@pytest.mark.parametrize(
    ("gstin", "name", "city"),
    [
        (None, "Acme", None),
        (None, None, "Pune"),
        (None, None, None),
        ("", "Acme", ""),
        ("  ", " ", " "),
    ],
)
def test_supplier_without_gstin_and_without_both_name_and_city_has_no_key(
    gstin: str | None, name: str | None, city: str | None
) -> None:
    """A-109: such a row cannot be deduplicated and is rejected by the importer."""
    assert fn("supplier_natural_key")(gstin, name, city) is None


# --- row hash (INV-IMP-02) --------------------------------------------------------------------------------------------
def test_row_hash_is_64_lowercase_hex_and_stable() -> None:
    row_hash = fn("row_hash")
    value = row_hash({"code": "S1", "name": "Acme", "city": "Pune"})
    assert len(value) == 64 and value == value.lower() and int(value, 16) >= 0
    assert value == row_hash({"code": "S1", "name": "Acme", "city": "Pune"})


def test_row_hash_ignores_field_order_and_outer_whitespace() -> None:
    row_hash = fn("row_hash")
    assert row_hash({"code": "S1", "name": "Acme"}) == row_hash({"name": "  Acme ", "code": "S1"})


def test_row_hash_changes_with_any_value() -> None:
    row_hash = fn("row_hash")
    base = {"code": "S1", "name": "Acme", "city": "Pune"}
    assert (
        len(
            {
                row_hash(base),
                row_hash({**base, "city": "Nashik"}),
                row_hash({**base, "name": "Acme 2"}),
                row_hash({**base, "code": "S2"}),
            }
        )
        == 4
    )


def test_row_hash_distinguishes_a_value_from_a_neighbouring_field() -> None:
    """('ab','c') and ('a','bc') must not collide: fields are delimited."""
    row_hash = fn("row_hash")
    assert row_hash({"x": "ab", "y": "c"}) != row_hash({"x": "a", "y": "bc"})


def test_row_hash_treats_blank_and_missing_alike() -> None:
    row_hash = fn("row_hash")
    assert row_hash({"code": "S1", "city": None}) == row_hash({"code": "S1", "city": "  "})
