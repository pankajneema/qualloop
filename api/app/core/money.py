"""Money is integer paise, never float (ADR-005, INV-MON-*). Database columns are BIGINT `*_paise` with CHECK > 0."""

from typing import Annotated, NewType

from pydantic import Field, StrictInt

Paise = NewType("Paise", int)

BIGINT_MAX = 2**63 - 1

# Pydantic type for money fields in command bodies: strict integer (no float, no "100", no bool), 1 .. bigint max.
PaiseAmount = Annotated[StrictInt, Field(gt=0, le=BIGINT_MAX)]
