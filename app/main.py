import logging
import os
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware

from .database import init_db
from .middleware import AuthMiddleware
from .routes import router
from .webhooks import webhooks_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
_log = logging.getLogger("datacleanr")

_SENTRY_DSN = os.getenv("SENTRY_DSN", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if _SENTRY_DSN:
        sentry_sdk.init(dsn=_SENTRY_DSN, traces_sample_rate=0.1)
        _log.info("Sentry enabled")
    init_db()
    _log.info("DataCleanr started — DB ready")
    yield
    _log.info("DataCleanr shutdown")


app = FastAPI(
    title="DataCleanr",
    description="AI-powered CSV/JSON/xlsx transformation API. POST a file + plain English instructions, get clean CSV back.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Middleware order: outermost runs first on request, last on response.
# GZip wraps everything; Auth runs next.
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(AuthMiddleware)

app.include_router(router)
app.include_router(webhooks_router)
