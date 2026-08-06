"""Bounding what the assistant is allowed to spend.

The assistant answers without a login, so anyone who can reach it can spend
money on somebody else's OpenAI account. Two counters stand between a public
endpoint and an unbounded bill.

Both are applied ONLY to requests that actually reach the model. The
deterministic path — router, tools, database — costs nothing and is not
throttled alongside it: a clinic hitting its AI ceiling should still be able to
answer "when do you close?" all day.

FAIL CLOSED
-----------
When Redis is unreachable the counters cannot be trusted, and an uncounted call
is exactly the one that runs unbounded. So an unavailable counter refuses the
model rather than waving it through, and the caller falls back to the
deterministic answer — degraded, never expensive.
"""

import logging

from app.config import get_settings
from app.core.time import utc_now
from app.db.redis import get_redis

logger = logging.getLogger(__name__)

# Fixed windows rather than sliding. A sliding window is more precise and needs
# per-request bookkeeping; these are spend guards, and being approximately
# right at the boundary of a minute costs nothing worth the complexity.
_MINUTE_TTL = 60
_DAY_TTL = 60 * 60 * 24


def _minute_key(ip: str) -> str:
    minute = utc_now().strftime("%Y%m%d%H%M")
    return f"assistant:llm:ip:{ip}:{minute}"


def _day_key(clinic_id: int) -> str:
    # UTC day, deliberately, even though clinics are local. A budget is a
    # billing control, not something a patient experiences, and pinning it to
    # UTC means one clinic's rollover cannot be moved by editing its timezone.
    day = utc_now().strftime("%Y%m%d")
    return f"assistant:llm:clinic:{clinic_id}:{day}"


async def _increment(key: str, ttl: int) -> int | None:
    """Count this request, returning the new total, or None if unknown."""
    try:
        redis = await get_redis()

        count = await redis.incr(key)

        if count == 1:
            # Only on creation: re-setting it on every request would slide the
            # window forward and the counter would never expire under load.
            await redis.expire(key, ttl)

        return int(count)

    except Exception:
        # Logged without the key, which carries the caller's IP.
        logger.warning("assistant quota counter unavailable", exc_info=True)
        return None


class QuotaDecision:
    """Whether the model may be called, and why not when it may not."""

    __slots__ = ("allowed", "reason")

    def __init__(self, allowed: bool, reason: str = ""):
        self.allowed = allowed
        self.reason = reason

    def __bool__(self) -> bool:
        return self.allowed


async def check_llm_quota(*, ip: str, clinic_id: int) -> QuotaDecision:
    """May this request spend a model call?

    Checked before the call, and counted as part of checking: a check that did
    not count would let concurrent requests all pass the same limit.
    """
    settings = get_settings()

    per_minute = await _increment(_minute_key(ip), _MINUTE_TTL)

    if per_minute is None:
        return QuotaDecision(False, "quota_unavailable")

    if per_minute > settings.MAX_LLM_REQUESTS_PER_IP_PER_MINUTE:
        return QuotaDecision(False, "rate_limited")

    per_day = await _increment(_day_key(clinic_id), _DAY_TTL)

    if per_day is None:
        return QuotaDecision(False, "quota_unavailable")

    if per_day > settings.MAX_LLM_REQUESTS_PER_CLINIC_PER_DAY:
        return QuotaDecision(False, "daily_budget_exceeded")

    return QuotaDecision(True)
