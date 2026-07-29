from unittest.mock import AsyncMock, patch

import pytest

from app.core import cache


@pytest.mark.asyncio
async def test_get_cache_returns_none_when_redis_down():
    with patch("app.core.cache.get_redis", side_effect=ConnectionError("down")):
        assert await cache.get_cache("some-key") is None


@pytest.mark.asyncio
async def test_writes_do_not_raise_when_redis_down():
    with patch("app.core.cache.get_redis", side_effect=ConnectionError("down")):
        # Best-effort — must not propagate.
        await cache.set_cache("k", {"a": 1})
        await cache.delete_cache("k")


@pytest.mark.asyncio
async def test_get_cache_happy_path():
    fake_redis = AsyncMock()
    fake_redis.get = AsyncMock(return_value='{"x": 5}')
    with patch("app.core.cache.get_redis", AsyncMock(return_value=fake_redis)):
        assert await cache.get_cache("k") == {"x": 5}
