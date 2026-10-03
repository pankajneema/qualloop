"""Excel safety (ADR-014, INV-IMP-08): formula-injection neutralisation shared by every exported workbook.

A text cell that starts with `=`, `+`, `-`, `@`, TAB or CR is interpreted as a formula by spreadsheet programs. Every
string written into an exported workbook passes `neutralise_cell`, which prefixes such text with an apostrophe so it is
shown as text. Numbers, booleans and None are returned unchanged (a negative number is a number, not a formula).
"""

DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def neutralise_cell(value: object) -> object:
    """`value` safe to write into a cell: dangerous text gets a leading apostrophe; everything else is unchanged.

    Idempotent: a neutralised cell starts with an apostrophe, which is not a dangerous prefix."""
    if isinstance(value, str) and value.startswith(DANGEROUS_PREFIXES):
        return "'" + value
    return value
