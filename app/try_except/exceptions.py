# app/core/exceptions.py

class AppException(Exception):
    """Base class for all application exceptions."""
    status_code = 500
    message = "Application error"

    def __init__(self, message: str | None = None):
        if message:
            self.message = message
        super().__init__(self.message)


class BadRequestError(AppException):
    status_code = 400

class NotFoundError(AppException):
    status_code = 404


class ConflictError(AppException):
    status_code = 409


class UnauthorizedError(AppException):
    status_code = 401


class ForbiddenError(AppException):
    status_code = 403


class ValidationError(AppException):
    status_code = 422

class RateLimitExceededError(AppException):
    status_code = 429


class InternalServerError(AppException):
    status_code = 500

class ConfigurationError(AppException):
    status_code = 500


class ServiceUnavailableError(AppException):
    status_code = 503