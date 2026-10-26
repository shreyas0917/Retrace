"""API error types and helpers."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base application error mapped to a structured API response."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Missing or invalid API key") -> None:
        super().__init__(
            code="UNAUTHORIZED",
            message=message,
            status_code=401,
        )


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(
            code="NOT_FOUND",
            message=message,
            status_code=404,
        )


class ConflictError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            code="CONFLICT",
            message=message,
            status_code=409,
            details=details,
        )


class InvalidStateError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            code="INVALID_STATE",
            message=message,
            status_code=409,
            details=details,
        )


class DependencyUnavailableError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            code="DEPENDENCY_UNAVAILABLE",
            message=message,
            status_code=503,
            details=details,
        )


class EmbeddingError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            code="EMBEDDING_FAILED",
            message=message,
            status_code=502,
            details=details,
        )


class GenerationError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            code="GENERATION_FAILED",
            message=message,
            status_code=502,
            details=details,
        )


class GenerationTimeoutError(AppError):
    def __init__(self, message: str = "Generation timed out", details: dict[str, Any] | None = None) -> None:
        super().__init__(
            code="GENERATION_TIMEOUT",
            message=message,
            status_code=504,
            details=details,
        )


class ForbiddenError(AppError):
    """Authenticated but not allowed (e.g. CSRF guard rejected the request)."""

    def __init__(
        self,
        message: str = "Forbidden",
        code: str = "FORBIDDEN",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=403,
            details=details,
        )


class RateLimitedError(AppError):
    def __init__(self, retry_after_seconds: int, message: str = "Too many requests") -> None:
        super().__init__(
            code="RATE_LIMITED",
            message=message,
            status_code=429,
            details={"retry_after_seconds": retry_after_seconds},
        )
        self.retry_after_seconds = retry_after_seconds


class PayloadTooLargeError(AppError):
    def __init__(self, max_bytes: int, message: str = "Request body too large") -> None:
        super().__init__(
            code="PAYLOAD_TOO_LARGE",
            message=message,
            status_code=413,
            details={"max_request_bytes": max_bytes},
        )
