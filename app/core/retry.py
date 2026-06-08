import asyncio
import logging

from sqlalchemy.exc import OperationalError, DBAPIError

logger = logging.getLogger(__name__)


async def with_retry(fn, retries=3, delay=0.1):

    for attempt in range(retries):

        try:
            return await fn()

        except (OperationalError, DBAPIError) as e:

            if attempt == retries - 1:

                logger.error(
                    "Retry failed permanently",
                    extra={
                        "attempts": retries,
                        "error": str(e),
                    },
                )

                raise

            wait_time = delay * (2 ** attempt)

            logger.warning(
                "Retrying DB operation",
                extra={
                    "attempt": attempt + 1,
                    "wait_time": wait_time,
                },
            )

            await asyncio.sleep(wait_time)