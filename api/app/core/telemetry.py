"""OpenTelemetry setup (ADR-015). Disabled unless `QL_OTEL_EXPORTER_OTLP_ENDPOINT` is set (the local default).

`init_telemetry` only installs the tracer provider and exporter. Library instrumentation is attached separately
(`instrument_app`, `instrument_engine`, `instrument_redis`) and only when telemetry is enabled, so a default run has
no instrumentation overhead and tests never emit spans.
"""

import threading

import structlog
from fastapi import FastAPI
from sqlalchemy import Engine

from app.core.config import Settings

log = structlog.get_logger("telemetry")

_lock = threading.Lock()
_initialised = False

SERVICE_NAME = "qualloop-api"


def init_telemetry(settings: Settings, service_name: str = SERVICE_NAME) -> bool:
    """Install the tracer provider once. Returns False (and does nothing) when no OTLP endpoint is configured."""
    global _initialised
    endpoint = settings.otel_exporter_otlp_endpoint.strip()
    if not endpoint:
        return False
    with _lock:
        if _initialised:
            return True
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        url = endpoint.rstrip("/")
        if not url.endswith("/v1/traces"):
            url += "/v1/traces"
        provider = TracerProvider(
            resource=Resource.create(
                {"service.name": service_name, "service.version": settings.version}
            )
        )
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=url)))
        trace.set_tracer_provider(provider)
        _initialised = True
        log.info("telemetry_enabled", service=service_name)
    return True


def instrument_app(app: FastAPI) -> None:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)


def instrument_engine(engine: Engine) -> None:
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    SQLAlchemyInstrumentor().instrument(engine=engine)


def instrument_redis() -> None:
    from opentelemetry.instrumentation.redis import RedisInstrumentor

    RedisInstrumentor().instrument()
