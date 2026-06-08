import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette import status

from app.try_except.exceptions import AppException

logger = logging.getLogger("app.error")


def app_exception_handler(request: Request, exc: AppException):
    logger.warning(
        "Application error",
        extra={"error_type": exc.__class__.__name__},
    )

    status_map = {
        "BadRequestError": status.HTTP_400_BAD_REQUEST,
        "NotFoundError": status.HTTP_404_NOT_FOUND,
        "ConflictError": status.HTTP_409_CONFLICT,
        "UnauthorizedError": status.HTTP_401_UNAUTHORIZED,
        "ForbiddenError": status.HTTP_403_FORBIDDEN,
        "ValidationError": status.HTTP_422_UNPROCESSABLE_CONTENT,
    }

    status_code = status_map.get(
        exc.__class__.__name__,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )

    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "type": exc.__class__.__name__,
                "message": exc.message,
            }
        },
    )


def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled server error")

    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "type": "InternalServerError",
                "message": "Unexpected error occurred",
            }
        },
    )
