"""
Integration test fixtures.

Tests run against live services started via ``docker-compose up``.  Base URLs
are read from environment variables so the suite works both locally (default
values) and inside CI (override via env).

Start the stack before running:
    docker-compose up -d
    pytest tests/integration -v
"""

import asyncio
import os
import uuid
from typing import Any

import pytest
import pytest_asyncio
import httpx

# ── Service base URLs — override via env vars in CI ───────────────────────────
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4000")
SETTLEMENT_URL = os.environ.get("SETTLEMENT_URL", "http://localhost:18001")
FRAUD_URL = os.environ.get("FRAUD_URL", "http://localhost:18002")
NOTIFICATION_URL = os.environ.get("NOTIFICATION_URL", "http://localhost:8003")

# Shared bearer token that has the required scopes.  In CI inject the real
# value; locally the api-gateway accepts this test token when NODE_ENV=test.
TEST_TOKEN = os.environ.get("INTEGRATION_TEST_TOKEN", "integration-test-token")


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def gateway() -> httpx.AsyncClient:
    """Async HTTP client aimed at the API gateway."""
    async with httpx.AsyncClient(
        base_url=GATEWAY_URL,
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        timeout=10.0,
    ) as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def settlement_svc() -> httpx.AsyncClient:
    """Direct client to settlement-service (bypasses gateway auth)."""
    async with httpx.AsyncClient(
        base_url=SETTLEMENT_URL,
        headers={"X-User-Id": "00000000-0000-0000-0000-000000000099"},
        timeout=10.0,
    ) as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def fraud_svc() -> httpx.AsyncClient:
    """Direct client to fraud-detection service."""
    async with httpx.AsyncClient(base_url=FRAUD_URL, timeout=10.0) as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def notification_svc() -> httpx.AsyncClient:
    async with httpx.AsyncClient(base_url=NOTIFICATION_URL, timeout=10.0) as client:
        yield client


def settlement_payload(**overrides: Any) -> dict[str, Any]:
    return {
        "idempotency_key": str(uuid.uuid4()),
        "amount": "500.00",
        "currency": "USD",
        "payer_id": str(uuid.uuid4()),
        "payee_id": str(uuid.uuid4()),
        "user_email": "integration@example.com",
        **overrides,
    }
