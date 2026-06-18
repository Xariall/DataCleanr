"""
Rate-limit unit tests run against the in-memory paid fallback only
(no real Redis required).
"""
import asyncio
import os
import time
from unittest.mock import AsyncMock, patch

import pytest
import app.middleware as mw


@pytest.fixture(autouse=True)
def reset_fallback():
    mw._paid_fallback.clear()
    yield
    mw._paid_fallback.clear()


def _paid_user(key_hash: str = "fakehash") -> dict:
    return {"tier": "PAID", "api_key_hash": key_hash}


def _free_user(key_hash: str = "fakehash") -> dict:
    return {"tier": "FREE", "api_key_hash": key_hash}


# Helper: make Redis always raise so we fall through to in-memory path
def _redis_down():
    return patch.object(mw._get_redis(), "get", side_effect=Exception("Redis down"))


@pytest.mark.asyncio
async def test_paid_fallback_allows_within_limit():
    user = _paid_user("hash1")
    with patch("app.middleware._get_redis") as mock_redis:
        mock_redis.return_value.get = AsyncMock(side_effect=Exception("down"))
        allowed, used, limit = await mw.check_row_budget(user, 100)
    assert allowed is True
    assert limit == mw.PAID_DAILY_ROWS


@pytest.mark.asyncio
async def test_paid_fallback_blocks_over_limit():
    user = _paid_user("hash2")
    # Stuff the fallback near-limit
    mw._paid_fallback["hash2"] = [(time.time(), mw.PAID_DAILY_ROWS - 10)]

    with patch("app.middleware._get_redis") as mock_redis:
        mock_redis.return_value.get = AsyncMock(side_effect=Exception("down"))
        allowed, _, _ = await mw.check_row_budget(user, 100)
    assert allowed is False


@pytest.mark.asyncio
async def test_free_user_redis_down_raises():
    user = _free_user("hash3")
    with patch("app.middleware._get_redis") as mock_redis:
        mock_redis.return_value.get = AsyncMock(side_effect=Exception("down"))
        with pytest.raises(RuntimeError, match="REDIS_UNAVAILABLE"):
            await mw.check_row_budget(user, 1)


@pytest.mark.asyncio
async def test_commit_row_usage_paid_fallback_on_redis_down():
    user = _paid_user("hash4")
    # pipeline() is sync; patch it to raise so commit falls to in-memory path
    with patch("app.middleware._get_redis") as mock_redis:
        mock_redis.return_value.pipeline.side_effect = Exception("Redis down")
        # Should not raise
        await mw.commit_row_usage(user, 50)
    # Verify in-memory counter was incremented
    used = mw._paid_fallback_used("hash4")
    assert used == 50
