"""Gunicorn worker class for the API container: uvicorn without its own `X-Forwarded-*` handling.

uvicorn's `ProxyHeadersMiddleware` rewrites `scope["client"]` from `X-Forwarded-For` for peers in `FORWARDED_ALLOW_IPS`
(default 127.0.0.1). The application resolves the client address itself from `QL_TRUSTED_PROXIES`
(`app.core.auth.deps.resolve_client_ip`, A-106); two rewriters would disagree, so uvicorn's is switched off.
"""

import warnings
from typing import Any

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from uvicorn.workers import UvicornWorker


class AppUvicornWorker(UvicornWorker):
    CONFIG_KWARGS: dict[str, Any] = {  # noqa: RUF012 - same declaration as the base class
        **UvicornWorker.CONFIG_KWARGS,
        "proxy_headers": False,
    }
