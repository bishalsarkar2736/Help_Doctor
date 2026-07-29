import asyncio
from functools import wraps

from app.db.postgres import engine


def run_async(func):
    """
    Allows Celery (sync worker) to run async functions.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):

        async def _runner():
            try:
                return await func(*args, **kwargs)
            finally:
                # asyncio.run() closes the event loop when it returns, but the
                # engine's pooled asyncpg connections are bound to the loop that
                # created them. Leaving them pooled makes the NEXT task (running
                # in a new loop) fail with "RuntimeError: Event loop is closed".
                # Dispose while this loop is still alive so they close cleanly.
                await engine.dispose()

        return asyncio.run(_runner())

    return wrapper
