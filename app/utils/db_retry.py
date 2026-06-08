import asyncio
import logging
import random

from sqlalchemy.exc import DBAPIError
from asyncpg.exceptions import (
    DeadlockDetectedError,
    SerializationError,
)

from app.core.metrics import db_retry_total


logger = logging.getLogger(__name__)

MAX_RETRIES = 3


def is_retryable_db_error(e: DBAPIError) -> bool:
    return isinstance(
        e.orig,
        (
            DeadlockDetectedError,
            SerializationError,
        ),
    )


async def with_retry(
    func,
    db,
    *,
    operation: str = "db_operation",
    max_retries: int = MAX_RETRIES,
):
    for attempt in range(max_retries):
        try:
            return await func()

        except DBAPIError as e:

            should_retry = is_retryable_db_error(e)

            # Not retryable → fail immediately
            if not should_retry:
                raise

            await db.rollback()

            logger.warning(
                "Retrying DB transaction "
                "(attempt %s/%s) "
                "operation=%s "
                "error=%s",
                attempt + 1,
                max_retries,
                operation,
                str(e.orig),
            )

            # Final failure
            if attempt == max_retries - 1:

                logger.error(
                    "Retry failed permanently "
                    "operation=%s "
                    "attempts=%s "
                    "error=%s",
                    operation,
                    max_retries,
                    str(e.orig),
                )

                raise

            # Track ACTUAL retry
            db_retry_total.labels(
                operation=operation,
            ).inc()

            # Exponential-ish backoff + jitter
            await asyncio.sleep(
                (0.1 * (attempt + 1))
                + random.uniform(0, 0.05)
            )