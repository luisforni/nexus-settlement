from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import get_logger
from app.models.fraud_detector import FraudDetector

logger = get_logger(__name__)

_detector: FraudDetector | None = None

def get_detector() -> FraudDetector:

    if _detector is None:
        raise RuntimeError("FraudDetector has not been initialised")
    return _detector

@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:

    global _detector

    logger.info(
        "Fraud Detection Service starting — loading model",
        extra={"model_path": settings.FRAUD_MODEL_PATH},
    )
    try:
        _detector = FraudDetector.load(settings.FRAUD_MODEL_PATH)
        logger.info(
            "Fraud model loaded successfully",
            extra={"model_version": _detector.version},
        )
    except FileNotFoundError:
        logger.warning(
            "Model artifact not found — starting with untrained model",
            extra={"model_path": settings.FRAUD_MODEL_PATH},
        )
        _detector = FraudDetector.untrained()

    yield

    logger.info("Fraud Detection Service shutting down")
    _detector = None

def create_application() -> FastAPI:

    application = FastAPI(
        title="Nexus Fraud Detection Service",
        description="AI-powered real-time fraud scoring for settlements.",
        version="1.0.0",
        docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
        redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
        openapi_url=(
            "/openapi.json" if settings.ENVIRONMENT != "production" else None
        ),
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Request-Id"],
    )

    application.include_router(api_router, prefix="/api/v1")

    Instrumentator(
        should_ignore_untemplated=True,
        excluded_handlers=["/api/v1/health", "/metrics"],
    ).instrument(application).expose(application)

    @application.exception_handler(RequestValidationError)
    async def validation_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        logger.warning("Validation error", extra={"errors": exc.errors()})
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": "Validation Error", "detail": exc.errors()},
        )

    return application

app = create_application()
