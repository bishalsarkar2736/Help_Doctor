import asyncio
import logging

logger = logging.getLogger(__name__)

MAX_AI_RETRIES = 3


async def with_ai_retry(
    func,
):
    for attempt in range(MAX_AI_RETRIES):

        try:
            return await func()

        except Exception as e:

            if attempt == MAX_AI_RETRIES - 1:
                raise

            logger.warning(
                "Retrying AI request "
                "(attempt %s/%s)",
                attempt + 1,
                MAX_AI_RETRIES,
            )

            await asyncio.sleep(
                0.5 * (attempt + 1)
            )