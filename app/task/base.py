import asyncio


def run_async(func):
    """
    Allows Celery (sync worker) to run async functions.
    """

    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapper