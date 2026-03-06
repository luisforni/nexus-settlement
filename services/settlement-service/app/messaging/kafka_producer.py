import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaConnectionError, KafkaTimeoutError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

def _json_serialiser(value: Any) -> bytes:

    return json.dumps(value, default=str, ensure_ascii=False).encode("utf-8")

class KafkaProducer:

    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:

        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=_json_serialiser,
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            acks="all",
            enable_idempotence=True,
            compression_type="gzip",
            linger_ms=5,
            request_timeout_ms=10_000,
            retry_backoff_ms=200,
            max_request_size=1_048_576,
        )
        await self._producer.start()
        logger.info(
            "Kafka producer started",
            extra={"bootstrap_servers": settings.KAFKA_BOOTSTRAP_SERVERS},
        )

    async def stop(self) -> None:

        if self._producer is not None:
            await self._producer.stop()
            logger.info("Kafka producer stopped")

    async def publish(
        self,
        topic: str,
        event_type: str,
        payload: dict[str, Any],
        key: str | None = None,
    ) -> None:
        """Publish a JSON event to the specified Kafka topic.

        Builds a canonical envelope that matches shared/contracts/settlement-event.json
        and adds a SHA-256 integrity hash (OWASP A08).
        Consumers verify this hash before processing.

        Args:
            topic: Target Kafka topic name.
            event_type: Event type string (e.g. "settlement.created").
            payload: Event payload (must be JSON-serialisable).
            key: Optional partition key (used for ordering guarantees).

        Raises:
            RuntimeError: If the producer has not been started.
        """
        if self._producer is None:
            raise RuntimeError(
                "KafkaProducer.start() must be called before publish()"
            )

        envelope: dict[str, Any] = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "schema_version": "1.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "payload": payload,
        }

        canonical = json.dumps(payload, sort_keys=True, default=str)
        envelope["integrity_hash"] = hashlib.sha256(canonical.encode()).hexdigest()

        try:
            await self._producer.send_and_wait(
                topic=topic,
                key=key,
                value=envelope,
            )
            logger.debug(
                "Kafka event published",
                extra={"topic": topic, "key": key, "event_type": event_type},
            )
        except (KafkaConnectionError, KafkaTimeoutError) as exc:
            logger.error(
                "Kafka publish failed",
                extra={"topic": topic, "error": str(exc)},
            )
            raise

kafka_producer = KafkaProducer()
