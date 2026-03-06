import asyncio
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints.fraud import get_fraud_service
from app.main import app
from app.models.fraud_detector import FraudDetector
from app.services.fraud_service import FraudService

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def detector() -> FraudDetector:

    return FraudDetector.untrained()

@pytest_asyncio.fixture
async def client(detector: FraudDetector) -> AsyncGenerator[AsyncClient, None]:

    def override_fraud_service() -> FraudService:
        return FraudService(detector=detector)

    app.dependency_overrides[get_fraud_service] = override_fraud_service

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
