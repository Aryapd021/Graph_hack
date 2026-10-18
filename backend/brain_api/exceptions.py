"""Domain exceptions and HTTP error mappings for Company Brain API.

Per ARCHITECTURE.md Section 13, 14:
Status mapping:
- BAD_REQUEST 400
- NOT_FOUND 404
- RATE_LIMITED 429
- GRAPH_UNAVAILABLE 503
- LLM_ERROR 502
- INTERNAL 500
"""

from brain_core.models import ErrorBody, ErrorCode, ErrorResponse


class AppException(Exception):
    """Base application exception with standardized ErrorCode and HTTP status code."""

    def __init__(self, code: ErrorCode, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def to_response_model(self) -> ErrorResponse:
        return ErrorResponse(error=ErrorBody(code=self.code, message=self.message))


class BadRequestException(AppException):
    def __init__(self, message: str = "Invalid request") -> None:
        super().__init__(code="BAD_REQUEST", message=message, status_code=400)


class NotFoundException(AppException):
    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(code="NOT_FOUND", message=message, status_code=404)


class RateLimitedException(AppException):
    def __init__(self, message: str = "Too many requests. Please slow down.") -> None:
        super().__init__(code="RATE_LIMITED", message=message, status_code=429)


class GraphUnavailableException(AppException):
    def __init__(self, message: str = "FalkorDB is unreachable") -> None:
        super().__init__(code="GRAPH_UNAVAILABLE", message=message, status_code=503)


class LLMErrorException(AppException):
    def __init__(self, message: str = "LLM provider error") -> None:
        super().__init__(code="LLM_ERROR", message=message, status_code=502)


class InternalException(AppException):
    def __init__(self, message: str = "Internal server error") -> None:
        super().__init__(code="INTERNAL", message=message, status_code=500)
