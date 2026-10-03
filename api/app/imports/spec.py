"""What each import entity accepts (P02 plan 2.4, A-112): target fields, required flags, accepted values."""

from dataclasses import dataclass
from typing import Final

ENTITIES: Final = ("suppliers", "parts", "supplier_parts")


@dataclass(frozen=True)
class TargetField:
    name: str
    required: bool


# Order = the order the wizard and the report show them in.
TARGET_FIELDS: Final[dict[str, tuple[TargetField, ...]]] = {
    "suppliers": (
        TargetField("code", True),
        TargetField("name", True),
        TargetField("gstin", False),
        TargetField("city", False),
        TargetField("state", False),
        TargetField("category", True),
    ),
    "parts": (
        TargetField("part_no", True),
        TargetField("name", True),
        TargetField("category", False),
        TargetField("current_revision", False),
    ),
    "supplier_parts": (
        TargetField("supplier_code", True),
        TargetField("part_no", True),
        TargetField("supplier_part_no", False),
        TargetField("ppm_target", False),
    ),
}

SUPPLIER_CATEGORIES: Final = ("raw_material", "bought_out", "job_work", "service")

# Row statuses. `valid` exists only in a preview; a persisted record is `imported` instead.
VALID, DUPLICATE, REJECTED, UNMAPPED, REVIEW, IMPORTED = (
    "valid",
    "duplicate",
    "rejected",
    "unmapped",
    "review",
    "imported",
)
PREVIEW_STATUSES: Final = (VALID, DUPLICATE, REJECTED, UNMAPPED, REVIEW)
RECORD_STATUSES: Final = (IMPORTED, DUPLICATE, REJECTED, UNMAPPED, REVIEW)

# Batch statuses (DATA_MODEL 7.1, A-41)
UPLOADED, MAPPED, VALIDATED, IMPORTING, COMPLETED, FAILED, CANCELLED = (
    "uploaded",
    "mapped",
    "validated",
    "importing",
    "completed",
    "failed",
    "cancelled",
)
