"""Retrace FastAPI application — Phase 1 foundation."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes_benchmark import router as benchmark_router
from app.api.routes_corpus import router as corpus_router
from app.api.routes_diagnose import router as diagnose_router
from app.api.routes_experiments import router as experiments_router
from app.api.routes_generate import router as generate_router
from app.api.routes_health import router as health_router
from app.api.routes_investigate import router as investigate_router
from app.api.routes_retrieve import router as retrieve_router
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestIdMiddleware
from app.db import models  # noqa: F401 — register models with metadata
from app.db.session import init_db

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    init_db()
    # Warm embedding model so first ingest/retrieve is not a cold surprise
    try:
        from app.services.embeddings import get_embedding_model

        get_embedding_model(settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("embedding_warmup_skipped", error=str(exc))
    logger.info(
        "app_started",
        environment=settings.environment,
        embedding_model=settings.embedding_model,
        generation_model=settings.model_name,
    )
    yield
    logger.info("app_stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="Retrace",
        description="RAG reliability and failure-localization system",
        version="0.9.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    application.add_middleware(RequestIdMiddleware)

    application.include_router(health_router)
    application.include_router(corpus_router)
    application.include_router(retrieve_router)
    application.include_router(generate_router)
    application.include_router(diagnose_router)
    application.include_router(benchmark_router)
    application.include_router(experiments_router)
    application.include_router(investigate_router)

    @application.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        headers: dict[str, str] | None = (
            {"X-Request-ID": request_id} if request_id else None
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                },
                "request_id": request_id,
            },
            headers=headers,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        headers = {"X-Request-ID": request_id} if request_id else None
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "Request validation failed",
                    "details": {"errors": jsonable_encoder(exc.errors())},
                },
                "request_id": request_id,
            },
            headers=headers,
        )

    @application.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.exception("unhandled_error", error=str(exc), request_id=request_id)
        code = "DATABASE_ERROR" if isinstance(exc, SQLAlchemyError) else "INTERNAL_ERROR"
        headers = {"X-Request-ID": request_id} if request_id else None
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": code,
                    "message": "An internal error occurred",
                    "details": {},
                },
                "request_id": request_id,
            },
            headers=headers,
        )

    return application


app = create_app()
