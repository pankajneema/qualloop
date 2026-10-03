"""ADR-015: OpenTelemetry is off unless an OTLP endpoint is configured."""

from app.core.config import Settings
from tests.factories.contract import load


def test_telemetry_is_disabled_without_an_endpoint() -> None:
    init = load("app.core.telemetry", "init_telemetry")
    assert init(Settings(otel_exporter_otlp_endpoint="")) is False


def test_telemetry_is_enabled_when_an_endpoint_is_configured() -> None:
    init = load("app.core.telemetry", "init_telemetry")
    assert init(Settings(otel_exporter_otlp_endpoint="http://localhost:4318")) is True
