import asyncio
from functools import wraps

def run_async(func):
    """
    Allows Celery (sync worker) to run async functions.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapper