"""ADR-005: UUIDv7 ids, money as integer paise, plant-timezone dates and calendar-month periods."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
import time_machine
from pydantic import TypeAdapter, ValidationError

from tests.factories.contract import load

FROZEN = datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC)


def test_new_id_is_uuid_version_7_with_rfc4122_variant() -> None:
    new_id = load("app.core.ids", "new_id")
    value = new_id()
    assert isinstance(value, UUID)
    assert value.version == 7
    assert value.variant == "specified in RFC 4122"


def test_new_id_embeds_the_current_unix_milliseconds() -> None:
    new_id = load("app.core.ids", "new_id")
    with time_machine.travel(FROZEN, tick=False):
        value = new_id()
    assert value.int >> 80 == int(FROZEN.timestamp() * 1000)


def test_new_ids_are_unique_and_sort_by_creation_time() -> None:
    new_id = load("app.core.ids", "new_id")
    ids: list[UUID] = []
    for seconds in range(5):
        with time_machine.travel(FROZEN.replace(second=seconds), tick=False):
            ids.extend(new_id() for _ in range(50))
    assert len(set(ids)) == len(ids)
    assert ids == sorted(ids)


# A fixed instant in the past, so these tests never move the process-wide "last id" ahead of the real clock.
ID_CLOCK = datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC)
ONE_MS_COUNTER_SPACE = 4096  # 12-bit per-millisecond counter (A-99)


def test_ids_stay_strictly_increasing_across_a_per_millisecond_counter_overflow() -> None:
    """More ids than the 12-bit counter holds, all inside ONE frozen millisecond, then more in the same
    millisecond: every id must still sort after the previous one (keyset pagination on `id` depends on it)."""
    new_id = load("app.core.ids", "new_id")
    with time_machine.travel(ID_CLOCK, tick=False):
        first_batch = [new_id() for _ in range(ONE_MS_COUNTER_SPACE + 904)]
        second_batch = [new_id() for _ in range(ONE_MS_COUNTER_SPACE + 904)]
    ids = first_batch + second_batch
    assert len(set(ids)) == len(ids)
    regressions = [i for i in range(1, len(ids)) if ids[i] <= ids[i - 1]]
    assert regressions == [], f"id order broke at positions {regressions[:5]}"


def test_ids_generated_after_an_overflow_in_the_same_millisecond_do_not_embed_an_earlier_time() -> (
    None
):
    new_id = load("app.core.ids", "new_id")
    with time_machine.travel(ID_CLOCK, tick=False):
        burst = [new_id() for _ in range(ONE_MS_COUNTER_SPACE + 10)]
        after = new_id()
    assert after.int >> 80 >= max(i.int >> 80 for i in burst)


@pytest.mark.parametrize("step_back_ms", [1, 3, 500])
def test_a_clock_that_steps_backwards_still_produces_increasing_ids(step_back_ms: int) -> None:
    """NTP can move the clock back a little. Ids must not go backwards with it (small steps only: a test that
    jumps hours back, like `test_new_id_embeds_the_current_unix_milliseconds`, is a different, explicit case)."""
    new_id = load("app.core.ids", "new_id")
    with time_machine.travel(ID_CLOCK, tick=False):
        before = [new_id() for _ in range(5)]
    with time_machine.travel(ID_CLOCK - timedelta(milliseconds=step_back_ms), tick=False):
        after = [new_id() for _ in range(5)]
    ids = before + after
    assert all(ids[i] > ids[i - 1] for i in range(1, len(ids))), "ids went backwards with the clock"


@pytest.mark.parametrize("value", [1, 100, 4_20_000_00, 2**63 - 1])
def test_paise_amount_accepts_positive_integers(value: int) -> None:
    adapter: TypeAdapter[int] = TypeAdapter(load("app.core.money", "PaiseAmount"))
    assert adapter.validate_python(value) == value


@pytest.mark.parametrize(
    "value",
    [0, -1, 1.5, 100.0, "100", True, None, 2**63],
    ids=["zero", "negative", "float", "integral-float", "string", "bool", "none", "over-bigint"],
)
def test_paise_amount_rejects_floats_strings_non_positive_and_overflow(value: Any) -> None:
    adapter: TypeAdapter[int] = TypeAdapter(load("app.core.money", "PaiseAmount"))
    with pytest.raises(ValidationError):
        adapter.validate_python(value)


def test_paise_amount_rejects_float_in_json_mode_too() -> None:
    adapter: TypeAdapter[int] = TypeAdapter(load("app.core.money", "PaiseAmount"))
    with pytest.raises(ValidationError):
        adapter.validate_json("12.50")
    assert adapter.validate_json("1250") == 1250


def test_plant_today_uses_the_plant_timezone_not_utc() -> None:
    plant_today = load("app.core.timeutils", "plant_today")
    instant = datetime(2026, 10, 3, 20, 0, tzinfo=UTC)  # 01:30 on 4 Oct in Kolkata
    assert plant_today("Asia/Kolkata", instant) == date(2026, 10, 4)
    assert plant_today("America/New_York", instant) == date(2026, 10, 3)
    assert plant_today("UTC", instant) == date(2026, 10, 3)


def test_plant_today_defaults_to_the_current_instant() -> None:
    plant_today = load("app.core.timeutils", "plant_today")
    with time_machine.travel(datetime(2026, 12, 31, 19, 0, tzinfo=UTC), tick=False):
        assert plant_today("Asia/Kolkata") == date(2027, 1, 1)


def test_plant_today_rejects_unknown_timezone() -> None:
    plant_today = load("app.core.timeutils", "plant_today")
    with pytest.raises(ValueError, match="timezone"):
        plant_today("Mars/Olympus_Mons", FROZEN)


def test_month_period_cutoff_is_next_local_midnight_expressed_in_utc() -> None:
    """ADR-005 section 3: September in Asia/Kolkata ends at 2026-09-30T18:30:00Z."""
    month_period = load("app.core.timeutils", "month_period")
    period = month_period("Asia/Kolkata", 2026, 9)
    assert period.start == date(2026, 9, 1)
    assert period.end == date(2026, 9, 30)
    assert period.cutoff == datetime(2026, 9, 30, 18, 30, tzinfo=UTC)


def test_month_period_event_one_second_before_cutoff_belongs_to_september_and_at_cutoff_to_october() -> (
    None
):
    month_period = load("app.core.timeutils", "month_period")
    september = month_period("Asia/Kolkata", 2026, 9)
    october = month_period("Asia/Kolkata", 2026, 10)
    last_in_september = datetime(2026, 9, 30, 18, 29, 59, tzinfo=UTC)
    first_in_october = datetime(2026, 9, 30, 18, 30, 0, tzinfo=UTC)
    assert last_in_september < september.cutoff
    assert not first_in_october < september.cutoff
    assert first_in_october >= october.start_utc
    assert october.cutoff == datetime(2026, 10, 31, 18, 30, tzinfo=UTC)


def test_month_period_handles_leap_february_and_year_rollover() -> None:
    month_period = load("app.core.timeutils", "month_period")
    feb = month_period("UTC", 2028, 2)
    assert (feb.start, feb.end) == (date(2028, 2, 1), date(2028, 2, 29))
    assert feb.cutoff == datetime(2028, 3, 1, tzinfo=UTC)
    dec = month_period("UTC", 2026, 12)
    assert dec.end == date(2026, 12, 31)
    assert dec.cutoff == datetime(2027, 1, 1, tzinfo=UTC)
