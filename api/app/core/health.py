"""Liveness and readiness handlers (REPO_LAYOUT section 6)."""

from pathlib import Path

import redis
import structlog
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine

router = APIRouter(tags=["health"])
log = structlog.get_logger()

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _check_db() -> bool:
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return True


def _check_redis() -> bool:
    client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
    try:
        return bool(client.ping())
    finally:
        client.close()


def _check_migrations() -> bool:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_ALEMBIC_INI.parent / "alembic"))
    heads = set(ScriptDirectory.from_config(cfg).get_heads())
    with get_engine().connect() as conn:
        rows = conn.execute(text("SELECT version_num FROM alembic_version")).all()
    return {r[0] for r in rows} == heads


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": get_settings().version}


@router.get("/readyz")
def readyz() -> JSONResponse:
    checks: dict[str, str] = {}
    for name, fn in (("db", _check_db), ("redis", _check_redis), ("migrations", _check_migrations)):
        try:
            checks[name] = "ok" if fn() else "fail"
        except Exception as exc:
            log.warning("readiness_check_failed", check=name, error_type=type(exc).__name__)
            checks[name] = "fail"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ready" if ok else "not_ready", "checks": checks},
    )
