import asyncio
import os
import time
import uuid
from collections import defaultdict
from typing import Callable

import redis.asyncio as aioredis
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from .database import get_user_by_key_hash, hash_key

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
FREE_DAILY_ROWS = int(os.getenv("FREE_DAILY_ROWS", "500"))
PAID_DAILY_ROWS = int(os.getenv("PAID_DAILY_ROWS", "500000"))
RATE_LIMIT_TTL = 86400  # 24 h in seconds
REDIS_TIMEOUT = 1.0     # seconds before we consider Redis unavailable

# Paths that require a valid X-API-Key header
_AUTH_PATHS = frozenset({"/transform", "/explain", "/preview"})

# Paths where row-budget is checked and decremented
_RATE_LIMIT_PATHS = frozenset({"/transform", "/explain"})

# In-memory sliding-window fallback for PAID users when Redis is unavailable.
# Structure: {key_hash: [(unix_timestamp, row_count), ...]}
_paid_fallback: dict[str, list[tuple[float, int]]] = defaultdict(list)

_redis_client: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


def _rl_key(key_hash: str) -> str:
    from datetime import date
    return f"rl:{key_hash}:{date.today().isoformat()}"


def _paid_fallback_used(key_hash: str) -> int:
    cutoff = time.time() - RATE_LIMIT_TTL
    _paid_fallback[key_hash] = [
        (ts, n) for ts, n in _paid_fallback[key_hash] if ts > cutoff
    ]
    return sum(n for _, n in _paid_fallback[key_hash])


def _paid_fallback_add(key_hash: str, rows: int) -> None:
    _paid_fallback[key_hash].append((time.time(), rows))


async def check_row_budget(user: dict, row_count: int) -> tuple[bool, int, int]:
    """
    Returns (allowed, used, daily_limit).
    Does NOT modify the counter — call commit_row_usage after a successful transform.

    Free tier:  fail-closed — 503 if Redis is unreachable.
    Paid tier:  in-memory sliding-window fallback if Redis is unreachable.
    """
    limit = PAID_DAILY_ROWS if user["tier"] == "PAID" else FREE_DAILY_ROWS
    key = _rl_key(user["api_key_hash"])

    try:
        async with asyncio.timeout(REDIS_TIMEOUT):
            current = await _get_redis().get(key)
        used = int(current) if current else 0
        allowed = (used + row_count) <= limit
        return allowed, used, limit
    except Exception:
        if user["tier"] == "PAID":
            used = _paid_fallback_used(user["api_key_hash"])
            allowed = (used + row_count) <= limit
            return allowed, used, limit
        # Free tier: fail-closed
        raise RuntimeError("REDIS_UNAVAILABLE")


async def commit_row_usage(user: dict, row_count: int) -> None:
    """Increment the daily row counter after a successful transform."""
    key = _rl_key(user["api_key_hash"])
    try:
        async with asyncio.timeout(REDIS_TIMEOUT):
            pipe = _get_redis().pipeline()
            pipe.incrby(key, row_count)
            pipe.expire(key, RATE_LIMIT_TTL)
            await pipe.execute()
    except Exception:
        if user["tier"] == "PAID":
            _paid_fallback_add(user["api_key_hash"], row_count)
        # Free tier: Redis down after the transform succeeded — best effort, no crash


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates X-API-Key on protected paths and injects request_id."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        path = request.url.path
        if path in _AUTH_PATHS:
            api_key = request.headers.get("X-API-Key", "").strip()
            if not api_key:
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "Missing X-API-Key header",
                        "code": "MISSING_API_KEY",
                        "try": 'curl -X POST /transform -H "X-API-Key: dc_YOUR_KEY" -F "file=@data.csv" -F "instructions=..."',
                    },
                    headers={"X-Request-Id": request_id},
                )

            user = get_user_by_key_hash(hash_key(api_key))
            if not user:
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "Invalid API key",
                        "code": "INVALID_API_KEY",
                        "try": "curl -X POST /register -H 'Content-Type: application/json' -d '{\"email\":\"you@example.com\"}'",
                    },
                    headers={"X-Request-Id": request_id},
                )

            request.state.user = dict(user)

        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response
