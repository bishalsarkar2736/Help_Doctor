import asyncio
import logging

from app.workers.outbox_worker import process_outbox

from app.config import get_settings
from app.try_except.logging import setup_logging

settings = get_settings()

# The same JSON configuration the API installs, rather than basicConfig's plain
# text. This process emits outbox_integrity_error, duplicate_notification_skipped
# and every dead-letter record, so it was the one side of the system whose
# diagnostics structured log tooling could not read.
setup_logging(settings.DEBUG)

logger = logging.getLogger(__name__)


POLL_INTERVAL = 5  # seconds


def _startup_context() -> dict:
    """Which database this worker attached to, without the credentials.

    This replaces

        print("WORKER DB URL:", settings.database_url)

    which wrote the whole connection string — password included — to stdout on
    every worker start, and therefore into container logs and anything
    collecting them. A password in a log is a password that has leaked, however
    private the log is meant to be.

    The operational question behind that print was worth answering: a worker
    pointed at the wrong database is a real incident and hard to spot. So the
    answer is kept and the secret is not.

    Built from the individual settings rather than by redacting the URL. There
    is no string here that ever contains the password, so no regex or
    replacement can be written slightly wrong and put it back. The username is
    left out too — it is half a credential and identifies nothing the host,
    port and database name do not.
    """
    return {
        "db_host": settings.POSTGRES_HOST,
        "db_port": settings.POSTGRES_PORT,
        "db_name": settings.POSTGRES_DB,
    }


async def main():
    logger.info("outbox_worker_started", extra=_startup_context())

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