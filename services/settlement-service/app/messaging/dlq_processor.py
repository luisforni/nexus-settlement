import asyncio
import json
import uuid
from typing import Any

from aiokafka import AIOKafkaConsumer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.messaging.kafka_producer import kafka_producer
from app.models.settlement import Settlement, SettlementStatus

logger = get_logger(__name__)

_DLQ_CONSUMER_GROUP = settings.KAFKA_DLQ_CONSUMER_GROUP_ID
_DLQ_TOPIC = settings.KAFKA_TOPIC_SETTLEMENTS_DLQ
_MAX_RETRIES = settings.KAFKA_DLQ_MAX_RETRIES

class DLQProcessor:

    def __init__(self) -> None:
        self._consumer: AIOKafkaConsumer | None = None
        self._running: bool = False

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            _DLQ_TOPIC,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=_DLQ_CONSUMER_GROUP,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            max_poll_interval_ms=300_000,
            session_timeout_ms=30_000,
            heartbeat_interval_ms=10_000,
        )
        await self._consumer.start()
        self._running = True
        logger.info(
            "DLQ processor started",
            extra={"topic": _DLQ_TOPIC, "group_id": _DLQ_CONSUMER_GROUP},
        )

    async def stop(self) -> None:
        self._running = False
        if self._consumer is not None:
            await self._consumer.stop()
            logger.info("DLQ processor stopped")

    async def run(self) -> None:

        if self._consumer is None:
            raise RuntimeError("DLQProcessor.start() must be called first")

        async for message in self._consumer:
            if not self._running:
                break
            try:
                await self._handle(message.value)
            except asyncio.CancelledError:
                raise
            except Exception as exc:

                logger.critical(
                    "DLQ processor error — committing offset to prevent infinite loop",
                    extra={"error": str(exc), "offset": message.offset},
                )
            finally:
                await self._consumer.commit()

    async def _handle(self, envelope: Any) -> None:
        if not isinstance(envelope, dict):
            logger.warning("Non-dict DLQ envelope — skipping", extra={"raw": envelope})
            return

        event_type = envelope.get("event_type")
        if event_type != "dlq.settlement.failed":
            logger.debug("Unrecognised DLQ event type — skipping", extra={"event_type": event_type})
            return

        payload = envelope.get("payload", {})
        original_envelope = payload.get("original_envelope", {})
        retry_count: int = int(payload.get("retry_count", 0))
        error_type: str = payload.get("error_type", "UnknownError")
        error_message: str = payload.get("error_message", "")
        source_topic: str = payload.get("original_topic", settings.KAFKA_TOPIC_SETTLEMENTS)

        orig_payload = original_envelope.get("payload", {}) if isinstance(original_envelope, dict) else {}
        settlement_id_raw = orig_payload.get("settlement_id")

        logger.warning(
            "DLQ message received",
            extra={
                "settlement_id": settlement_id_raw,
                "retry_count": retry_count,
                "error_type": error_type,
                "error_message": error_message,
                "source_topic": source_topic,
            },
        )

        if retry_count < _MAX_RETRIES:
            await self._re_inject(
                original_envelope=original_envelope,
                source_topic=source_topic,
                retry_count=retry_count,
                settlement_id_raw=settlement_id_raw,
            )
        else:
            await self._permanently_fail(
                settlement_id_raw=settlement_id_raw,
                error_type=error_type,
                error_message=error_message,
                retry_count=retry_count,
                original_envelope=original_envelope,
            )

    async def _re_inject(
        self,
        *,
        original_envelope: Any,
        source_topic: str,
        retry_count: int,
        settlement_id_raw: Any,
    ) -> None:
        """Re-publish the original message to the source topic for another attempt."""
        if not isinstance(original_envelope, dict):
            logger.error("Cannot re-inject — original_envelope is not a dict")
            return

        logger.info(
            "DLQ: re-injecting message into source topic",
            extra={
                "settlement_id": settlement_id_raw,
                "retry_count": retry_count + 1,
                "source_topic": source_topic,
            },
        )

        envelope_to_publish = dict(original_envelope)
        meta = envelope_to_publish.setdefault("_dlq_meta", {})
        meta["reinjection_count"] = retry_count + 1

        orig_payload = envelope_to_publish.get("payload", {})
        key = str(settlement_id_raw) if settlement_id_raw else None
        event_type = envelope_to_publish.get("event_type", "settlement.created")

        await kafka_producer.publish(
            topic=source_topic,
            event_type=event_type,
            payload=orig_payload,
            key=key,
        )

    async def _permanently_fail(
        self,
        *,
        settlement_id_raw: Any,
        error_type: str,
        error_message: str,
        retry_count: int,
        original_envelope: Any,
    ) -> None:
        """Mark the settlement FAILED in the DB and alert ops via notification topic."""
        settlement_id: uuid.UUID | None = None
        if settlement_id_raw:
            try:
                settlement_id = uuid.UUID(str(settlement_id_raw))
            except ValueError:
                pass

        if settlement_id is not None:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    await self._mark_failed_in_db(session, settlement_id, error_message)

        await kafka_producer.publish(
            topic=settings.KAFKA_TOPIC_NOTIFICATIONS,
            event_type="dlq.permanently_failed",
            payload={
                "settlement_id": str(settlement_id) if settlement_id else settlement_id_raw,
                "error_type": error_type,
                "error_message": error_message,
                "retry_count": retry_count,
                "dlq_topic": _DLQ_TOPIC,
                "original_event_type": original_envelope.get("event_type")
                if isinstance(original_envelope, dict)
                else None,
            },
            key=str(settlement_id) if settlement_id else None,
        )

        logger.error(
            "DLQ: settlement permanently failed after max retries — ops alert published",
            extra={
                "settlement_id": str(settlement_id) if settlement_id else settlement_id_raw,
                "retry_count": retry_count,
                "error_type": error_type,
            },
        )

    @staticmethod
    async def _mark_failed_in_db(
        session: AsyncSession,
        settlement_id: uuid.UUID,
        reason: str,
    ) -> None:
        result = await session.execute(
            select(Settlement)
            .where(Settlement.id == settlement_id)
            .with_for_update()
        )
        settlement = result.scalar_one_or_none()
        if settlement is None:
            logger.warning(
                "DLQ: settlement not found in DB — cannot mark as FAILED",
                extra={"settlement_id": str(settlement_id)},
            )
            return

        if settlement.status in (SettlementStatus.COMPLETED, SettlementStatus.FAILED):
            logger.info(
                "DLQ: settlement already in terminal state — skipping DB update",
                extra={"settlement_id": str(settlement_id), "status": settlement.status},
            )
            return

        settlement.status = SettlementStatus.FAILED
        settlement.version += 1
        await session.flush()

        logger.warning(
            "DLQ: settlement marked FAILED in database",
            extra={"settlement_id": str(settlement_id), "reason": reason},
        )

dlq_processor = DLQProcessor()
