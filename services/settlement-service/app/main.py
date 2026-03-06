from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import engine
from app.db.base import Base
from app.messaging.kafka_producer import kafka_producer

logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:

    logger.info(
        "Settlement Service starting",
        extra={"environment": settings.ENVIRONMENT},
    )
    try:
        await kafka_producer.start()
    except Exception as exc:
        logger.warning(
            "Kafka producer failed to start — Kafka events will be skipped",
            extra={"error": str(exc)},
        )
    yield
    logger.info("Settlement Service shutting down")
    await kafka_producer.stop()
    await engine.dispose()

def create_application() -> FastAPI:

    application = FastAPI(
        title="Nexus Settlement Service",
        description="Distributed financial settlement management.",
        version="1.0.0",

        docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
        redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
        openapi_url=(
            "/openapi.json" if settings.ENVIRONMENT != "production" else None
        ),
        lifespan=lifespan,
    )

    if settings.ENVIRONMENT == "production":
        application.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=settings.ALLOWED_HOSTS,
        )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type", "X-Request-Id", "Idempotency-Key"],
    )

    application.include_router(api_router, prefix="/api/v1")

    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        excluded_handlers=["/api/v1/health", "/metrics"],
    ).instrument(application).expose(application)

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:

        logger.warning(
            "Request validation failed",
            extra={"errors": exc.errors()},
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=jsonable_encoder({"error": "Validation Error", "detail": exc.errors()}),
        )

    return application

app = create_application()
