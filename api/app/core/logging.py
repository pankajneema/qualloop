"""structlog JSON logging. request_id / tenant_id live in contextvars (ADR-015)."""

import logging
import sys

import structlog


def bind_request_context(request_id: str, tenant_id: str | None = None) -> None:
    structlog.contextvars.bind_contextvars(request_id=request_id, tenant_id=tenant_id)


def clear_request_context() -> None:
    structlog.contextvars.clear_contextvars()


def configure_logging(level: str = "INFO", env: str = "local") -> None:
    """JSON to stdout; pretty console renderer only when QL_ENV=local and stdout is a TTY."""
    renderer: structlog.types.Processor
    if env == "local" and sys.stdout.isatty():
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        structlog.processors.EventRenamer("msg"),
    ]
    structlog.configure(
        processors=[*processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        cache_logger_on_first_use=False,
    )
    # Route stdlib logging (uvicorn, sqlalchemy) through the same JSON pipeline.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        ],
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True  # replaced by our access log middleware
    # httpx logs full request URLs at INFO; URLs can carry tokens, so keep it quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)
