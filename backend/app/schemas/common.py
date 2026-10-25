"""Pydantic response schemas for Phase 1 infrastructure endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class DependencyStatus(BaseModel):
    postgres: Literal["ok", "error"]
    chroma: Literal["ok", "error"]
    embedding_model: str
    details: dict[str, Any] = Field(default_factory=dict)


class StatusResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str = "retrace-backend"
    dependencies: DependencyStatus


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody
    request_id: str | None = None
