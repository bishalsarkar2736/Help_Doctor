import asyncio
import httpx
import logging


logger = logging.getLogger(__name__)


RETRYABLE_EXCEPTIONS = (
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
    httpx.PoolTimeout,
)


async def retry_http_call(
    func,
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
):
    delay = base_delay

    for attempt in range(1, attempts + 1):

        try:
            return await func()

        except RETRYABLE_EXCEPTIONS as exc:

            logger.warning(
                "http_retry_attempt",
                extra={
                    "attempt": attempt,
                    "max_attempts": attempts,
                    "error": str(exc),
                },
            )

            if attempt == attempts:
                
                logger.error(
                    "http_retry_exhausted",
                    extra={
                        "attempts": attempts,
                        "error": str(exc),
                    },
                )

                raise

            await asyncio.sleep(delay)

            delay *= 2