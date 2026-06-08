import asyncio
import logging

from app.workers.outbox_worker import process_outbox

from app.config import get_settings

settings = get_settings()
print("WORKER DB URL:", settings.database_url)

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)


POLL_INTERVAL = 5  # seconds


async def main():
    logger.info("Outbox worker started...")

    try:
        while True:
            try:
                processed = await process_outbox()

                if processed:
                    logger.info(
                        "outbox_batch_processed",
                        extra={
                            "processed": processed,
                        },
                    )

            except Exception:
                logger.exception("Worker crashed, retrying...")

            await asyncio.sleep(POLL_INTERVAL)

    except asyncio.CancelledError:
        logger.info("Worker shutting down gracefully...")
        raise


    

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Worker stopped manually")