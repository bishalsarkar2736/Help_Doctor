from datetime import datetime, UTC

from sqlalchemy import text

from app.db.postgres import engine

try:
    from app.db.redis import get_redis
except ImportError:
    redis_client = None


class HealthService:

    @staticmethod
    async def check_database() -> dict:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

            return {
                "status": "healthy",
                "checked_at": datetime.now(UTC).isoformat(),
            }

        except Exception as exc:
            return {
                "status": "unhealthy",
                "error": str(exc),
                "checked_at": datetime.now(UTC).isoformat(),
            }
        
        
    @staticmethod
    async def check_redis() -> dict:
        redis_client = None
            # return {
            #     "status": "unknown",
            #     "error": "Redis client not configured",
            #     "checked_at": datetime.now(UTC).isoformat(),
            # }

        try:

            redis_client = await get_redis()

            await redis_client.ping()

            return {
                "status": "healthy",
                "checked_at": datetime.now(UTC).isoformat(),
            }

        except Exception as exc:
            return {
                "status": "unhealthy",
                "error": str(exc),
                "checked_at": datetime.now(UTC).isoformat(),
            }
        
        finally:
            if redis_client:
                await redis_client.aclose()


    # @staticmethod
    # async def check_scheduler(app) -> dict:
    #     scheduler = getattr(
    #         app.state,
    #         "scheduler",
    #         None,
    #     )

    #     if scheduler is None:
    #         return {
    #             "status": "unknown",
    #             "error": "Scheduler not initialized",
    #             "checked_at": datetime.now(UTC).isoformat(),
    #         }

    #     return {
    #         "status": (
    #             "healthy"
    #             if scheduler.running
    #             else "unhealthy"
    #         ),
    #         "checked_at": datetime.now(UTC).isoformat(),
    #     }

    # @staticmethod
    # async def check_workers() -> dict:
    #     """
    #     Placeholder until worker heartbeat exists.
    #     """

    #     return {
    #         "status": "unknown",
    #         "message": (
    #             "Worker heartbeat monitoring "
    #             "not implemented"
    #         ),
    #         "checked_at": datetime.now(UTC).isoformat(),
    #     }