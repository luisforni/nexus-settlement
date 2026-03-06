import asyncio
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.messaging.kafka_producer import KafkaProducer
from app.api.v1.endpoints.settlements import get_settlement_service as _real_get_settlement_service
from app.services.settlement_service import SettlementService

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="session")
def event_loop():

    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture(scope="session")
async def test_engine():

    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()

@pytest.fixture
def mock_kafka() -> KafkaProducer:

    producer = AsyncMock(spec=KafkaProducer)
    producer.publish = AsyncMock(return_value=None)
    return producer

@pytest_asyncio.fixture
async def client(
    db_session: AsyncSession,
    mock_kafka: KafkaProducer,
) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP test client with injected DB and Kafka dependencies."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    def override_settlement_service() -> SettlementService:
        return SettlementService(db=db_session, kafka=mock_kafka)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[_real_get_settlement_service] = override_settlement_service

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()

@pytest.fixture
def valid_settlement_payload() -> dict[str, Any]:

    return {
        "idempotency_key": str(uuid.uuid4()),
        "amount": "1000.50",
        "currency": "USD",
        "payer_id": str(uuid.uuid4()),
        "payee_id": str(uuid.uuid4()),
    }
