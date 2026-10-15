"""FastAPI application entrypoint for the Viral Shorts AI backend."""
from __future__ import annotations

import logging
import re
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from shared.config import settings

from .api import router as api_router
from .api.routes import limiter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("viral_shorts_ai")

_JOB_ID_RE = re.compile(r"/jobs/([0-9a-fA-F-]{36}|[0-9a-fA-F]{32})")


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})


def create_app() -> FastAPI:
    app = FastAPI(title="Viral Shorts AI", version="0.1.0")

    # Rate limiting (slowapi).
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)

    # CORS: only the configured frontend origin is allowed. When no frontend
    # URL is configured, no origins are allowed (never fall back to "*").
    origins = [settings.frontend_url] if getattr(settings, "frontend_url", None) else []
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        match = _JOB_ID_RE.search(request.url.path)
        logger.info(
            "request method=%s path=%s status=%s duration_ms=%.1f job_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            match.group(1) if match else "-",
        )
        return response

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        if isinstance(exc, HTTPException):
            return JSONResponse(
                status_code=exc.status_code, content={"detail": exc.detail}
            )
        # Traceback goes to server logs only; the client gets a generic message
        # with no internals (no paths, no tracebacks, no secrets).
        logger.exception("Unhandled exception during request")
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
