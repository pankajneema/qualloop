"""ADR-015 / ADR-019: PII masked, tokens/OTPs/passwords never logged."""

import json

import pytest
import structlog

from app.core.logging import configure_logging
from tests.factories.contract import load


def test_mask_mobile_keeps_country_code_and_last_four_digits() -> None:
    assert load("app.core.logging", "mask_mobile")("+919876543210") == "+91******3210"


def test_mask_mobile_leaves_short_or_empty_values_unusable_but_never_raises() -> None:
    mask = load("app.core.logging", "mask_mobile")
    assert "9876" not in mask("+9198")
    assert mask("") == ""


def test_mask_email_hides_the_local_part() -> None:
    masked = load("app.core.logging", "mask_email")("rahul.sharma@example.com")
    assert "rahul.sharma" not in masked
    assert "@" in masked


def _log_line(capsys: pytest.CaptureFixture[str], **fields: str) -> str:
    configure_logging("INFO", "ci")
    structlog.get_logger().info("probe", **fields)
    return capsys.readouterr().out.strip().splitlines()[-1]


def test_log_line_masks_mobile_numbers_found_in_any_field(
    capsys: pytest.CaptureFixture[str],
) -> None:
    line = _log_line(capsys, recipient="+919876543210", note="call +919876543210 now")
    assert "+919876543210" not in line
    assert "+91******3210" in line
    json.loads(line)  # still valid JSON


def test_log_line_masks_email_addresses_found_in_any_field(
    capsys: pytest.CaptureFixture[str],
) -> None:
    line = _log_line(capsys, who="rahul.sharma@example.com")
    assert "rahul.sharma" not in line


@pytest.mark.parametrize(
    "key", ["token", "otp", "password", "password_hash", "authorization", "cookie"]
)
def test_secret_named_fields_are_redacted(capsys: pytest.CaptureFixture[str], key: str) -> None:
    line = _log_line(capsys, **{key: "s3cr3t-value-123456"})
    assert "s3cr3t-value-123456" not in line
    assert json.loads(line)["msg"] == "probe"
