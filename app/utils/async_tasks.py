import asyncio
import logging

logger = logging.getLogger(__name__)


def run_background(coro):
    try:
        asyncio.create_task(coro)
    except RuntimeError:
        # fallback if no running loop (rare edge case)
        logger.warning("No running event loop for background task")

