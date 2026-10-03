"""INV-IMP-08 (ADR-014): every cell that starts with = + - @ TAB CR is prefixed with an apostrophe in any Excel export.

Contract: `app.core.excel.neutralise_cell(value)` (shared by the import report now and by exports in P08)."""

import pytest

from tests.factories.contract import load

DANGEROUS = ["=", "+", "-", "@", "\t", "\r"]


def neutralise(value: object) -> object:
    return load("app.core.excel", "neutralise_cell")(value)


@pytest.mark.parametrize("lead", DANGEROUS)
def test_a_string_starting_with_a_formula_character_is_prefixed_with_an_apostrophe(
    lead: str,
) -> None:
    value = f'{lead}HYPERLINK("http://evil.example")'
    assert neutralise(value) == "'" + value


@pytest.mark.parametrize(
    "value",
    [
        "Acme Works",
        "",
        " =leading space is not a formula start",
        "a=b",
        "x+y",
        "name@example.test",
        "'already quoted",
        "0",
        "Pune",
    ],
)
def test_other_strings_are_unchanged(value: str) -> None:
    assert neutralise(value) == value


@pytest.mark.parametrize("value", [0, 5, -5, 3.14, -0.5, True, None])
def test_non_strings_are_unchanged_so_negative_numbers_stay_numbers(value: object) -> None:
    result = neutralise(value)
    assert result == value and type(result) is type(value)


def test_the_rule_is_applied_once_not_twice() -> None:
    once = neutralise("=1+1")
    assert once == "'=1+1"
    assert neutralise(once) == once, (
        "an already-neutralised cell starts with an apostrophe, not a formula character"
    )
