"""
api/middleware.py
=================
Custom ASGI middleware.

APIKeyMiddleware
---------------
When CIDX_API_KEY is set, every request must include:
    X-API-Key: <your-key>

Requests without a valid key receive 401 Unauthorized.

The /health endpoint is excluded from auth so load balancer probes work.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_EXEMPT_PATHS = {"/health"}


class APIKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, api_key: str) -> None:
        super().__init__(app)   # type: ignore[arg-type]
        self._api_key = api_key

    async def dispatch(self, request: Request, call_next: object) -> object:
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)  # type: ignore[operator]

        provided = request.headers.get("X-API-Key")
        if provided != self._api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing X-API-Key header"},
            )

        return await call_next(request)  # type: ignore[operator]
