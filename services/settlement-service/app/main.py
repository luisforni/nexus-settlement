import asyncio
import sys
import os
from contextlib import asynccontextmanager, suppress
from typing import AsyncGenerator

_vault_loader_path = os.path.join(
    os.path.dirname(__file__), "../../../../infrastructure/vault"
)
sys.path.insert(0, os.path.abspath(_vault_loader_path))
try:
    from vault_loader import load_vault_secrets
    load_vault_secrets()
except ImportError:
    pass
finally:
    sys.path.pop(0)

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
from app.core.tracing import instrument_app, setup_tracing
from app.db.session import engine
from app.db.base import Base
from app.messaging.kafka_producer import kafka_producer
from app.messaging.settlement_processor import settlement_processor
from app.messaging.dlq_processor import dlq_processor
from app.services.fraud_client import fraud_client

setup_tracing()

logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:

    logger.info(
        "Settlement Service starting",
        extra={"environment": settings.ENVIRONMENT},
    )
    await kafka_producer.start()

    async def _processor_with_watchdog() -> None:

        while True:
            try:
                await settlement_processor.run()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Settlement processor crashed — restarting in 5 s",
                    extra={"error": str(exc)},
                )
                await asyncio.sleep(5)

    async def _dlq_processor_with_watchdog() -> None:

        while True:
            try:
                await dlq_processor.run()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "DLQ processor crashed — restarting in 5 s",
                    extra={"error": str(exc)},
                )
                await asyncio.sleep(5)

    processor_task: asyncio.Task | None = None
    dlq_task: asyncio.Task | None = None
    try:
        await settlement_processor.start()
        processor_task = asyncio.create_task(
            _processor_with_watchdog(), name="settlement-processor"
        )
        logger.info("Settlement processor task started")
    except Exception as exc:
        logger.warning(
            "Settlement processor failed to start — state machine will not advance",
            extra={"error": str(exc)},
        )

    try:
        await dlq_processor.start()
        dlq_task = asyncio.create_task(
            _dlq_processor_with_watchdog(), name="dlq-processor"
        )
        logger.info("DLQ processor task started")
    except Exception as exc:
        logger.warning(
            "DLQ processor failed to start — DLQ messages will not be re-injected",
            extra={"error": str(exc)},
        )

    yield

    logger.info("Settlement Service shutting down")

    for task, name in [(processor_task, "settlement-processor"), (dlq_task, "dlq-processor")]:
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    await settlement_processor.stop()
    await dlq_processor.stop()

    await fraud_client.aclose()
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

    instrument_app(application)

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
