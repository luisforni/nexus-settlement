import asyncio
import json
import uuid
from collections import defaultdict
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

class SettlementProcessor:

    def __init__(self) -> None:
        self._consumer: AIOKafkaConsumer | None = None
        self._running: bool = False

        self._retry_counts: dict[tuple[int, int], int] = defaultdict(int)

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            settings.KAFKA_TOPIC_SETTLEMENTS,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=settings.KAFKA_PROCESSOR_GROUP_ID,
            auto_offset_reset=settings.KAFKA_AUTO_OFFSET_RESET,
            enable_auto_commit=False,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            max_poll_interval_ms=300_000,
            session_timeout_ms=30_000,
            heartbeat_interval_ms=10_000,
        )
        await self._consumer.start()
        self._running = True
        logger.info(
            "Settlement processor started",
            extra={
                "topic": settings.KAFKA_TOPIC_SETTLEMENTS,
                "group_id": settings.KAFKA_PROCESSOR_GROUP_ID,
            },
        )

    async def stop(self) -> None:
        self._running = False
        if self._consumer is not None:
            await self._consumer.stop()
            logger.info("Settlement processor stopped")

    async def run(self) -> None:

        if self._consumer is None:
            raise RuntimeError("SettlementProcessor.start() must be called first")

        async for message in self._consumer:
            if not self._running:
                break

            msg_key = (message.partition, message.offset)
            try:
                await self._handle(message.value)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._retry_counts[msg_key] += 1
                attempt = self._retry_counts[msg_key]

                if attempt >= settings.KAFKA_DLQ_MAX_RETRIES:

                    logger.error(
                        "Settlement processor exhausted retries — routing to DLQ",
                        extra={
                            "error": str(exc),
                            "partition": message.partition,
                            "offset": message.offset,
                            "retry_count": attempt,
                            "dlq_topic": settings.KAFKA_TOPIC_SETTLEMENTS_DLQ,
                        },
                    )
                    await self._publish_to_dlq(
                        original_message=message.value,
                        error=exc,
                        retry_count=attempt,
                        source_topic=settings.KAFKA_TOPIC_SETTLEMENTS,
                        partition=message.partition,
                        offset=message.offset,
                    )
                    del self._retry_counts[msg_key]
                    await self._consumer.commit()
                else:
                    logger.warning(
                        "Settlement processor error — will retry (offset NOT committed)",
                        extra={
                            "error": str(exc),
                            "partition": message.partition,
                            "offset": message.offset,
                            "attempt": attempt,
                            "max_retries": settings.KAFKA_DLQ_MAX_RETRIES,
                        },
                    )
            else:

                self._retry_counts.pop(msg_key, None)
                await self._consumer.commit()

    async def _publish_to_dlq(
        self,
        *,
        original_message: Any,
        error: Exception,
        retry_count: int,
        source_topic: str,
        partition: int,
        offset: int,
    ) -> None:
        """Wrap the failed message in a DLQ envelope and publish to the DLQ topic."""
        dlq_payload: dict[str, Any] = {
            "original_topic": source_topic,
            "partition": partition,
            "offset": offset,
            "retry_count": retry_count,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "original_envelope": original_message,
        }
        try:
            await kafka_producer.publish(
                topic=settings.KAFKA_TOPIC_SETTLEMENTS_DLQ,
                event_type="dlq.settlement.failed",
                payload=dlq_payload,
                key=str(original_message.get("payload", {}).get("settlement_id", "unknown"))
                if isinstance(original_message, dict)
                else None,
            )
        except Exception as pub_exc:

            logger.critical(
                "Failed to publish to DLQ — committing offset anyway to unblock consumer",
                extra={"error": str(pub_exc), "source_topic": source_topic},
            )

    async def _handle(self, envelope: Any) -> None:
        if not isinstance(envelope, dict):
            logger.warning("Non-dict Kafka envelope — skipping")
            return

        event_type = envelope.get("event_type")
        if event_type != "settlement.created":
            return

        payload = envelope.get("payload", {})
        settlement_id_raw = payload.get("settlement_id")
        if not settlement_id_raw:
            logger.warning("Missing settlement_id in payload — skipping")
            return

        try:
            settlement_id = uuid.UUID(str(settlement_id_raw))
        except ValueError:
            logger.warning(
                "Invalid settlement_id — skipping",
                extra={"raw": settlement_id_raw},
            )
            return

        notification_context = {
            "user_email": payload.get("user_email"),
            "user_phone": payload.get("user_phone"),
            "webhook_url": payload.get("webhook_url"),
        }

        async with AsyncSessionLocal() as session:
            async with session.begin():
                await self._process_settlement(session, settlement_id, notification_context)

    async def _process_settlement(
        self,
        session: AsyncSession,
        settlement_id: uuid.UUID,
        notification_context: dict,
    ) -> None:
        """Transition one settlement through PENDING → PROCESSING → COMPLETED/FAILED."""
        result = await session.execute(
            select(Settlement)
            .where(Settlement.id == settlement_id)
            .with_for_update()
        )
        settlement = result.scalar_one_or_none()

        if settlement is None:
            logger.warning(
                "Settlement not found in processor",
                extra={"settlement_id": str(settlement_id)},
            )
            return

        if settlement.status != SettlementStatus.PENDING:
            logger.info(
                "Settlement already past PENDING — idempotent skip",
                extra={"settlement_id": str(settlement_id), "status": settlement.status},
            )
            return

        settlement.status = SettlementStatus.PROCESSING
        settlement.version += 1
        await session.flush()

        await kafka_producer.publish(
            topic=settings.KAFKA_TOPIC_SETTLEMENTS,
            event_type="settlement.processing",
            key=str(settlement_id),
            payload={
                "settlement_id": str(settlement_id),
                "status": settlement.status.value,
                "amount": str(settlement.amount),
                "currency": settlement.currency,
                "payer_id": str(settlement.payer_id),
                "payee_id": str(settlement.payee_id),
            },
        )
        logger.info(
            "Settlement → PROCESSING",
            extra={"settlement_id": str(settlement_id)},
        )

        try:
            settlement.status = SettlementStatus.COMPLETED
            settlement.version += 1
            await session.flush()

            await kafka_producer.publish(
                topic=settings.KAFKA_TOPIC_SETTLEMENTS,
                event_type="settlement.completed",
                key=str(settlement_id),
                payload={
                    "settlement_id": str(settlement_id),
                    "status": settlement.status.value,
                    "amount": str(settlement.amount),
                    "currency": settlement.currency,
                    "payer_id": str(settlement.payer_id),
                    "payee_id": str(settlement.payee_id),
                    **{k: v for k, v in notification_context.items() if v is not None},
                },
            )
            logger.info(
                "Settlement → COMPLETED",
                extra={"settlement_id": str(settlement_id)},
            )

        except Exception as exc:
            settlement.status = SettlementStatus.FAILED
            settlement.failure_reason = str(exc)
            settlement.version += 1
            await session.flush()

            await kafka_producer.publish(
                topic=settings.KAFKA_TOPIC_SETTLEMENTS,
                event_type="settlement.failed",
                key=str(settlement_id),
                payload={
                    "settlement_id": str(settlement_id),
                    "status": settlement.status.value,
                    "amount": str(settlement.amount),
                    "currency": settlement.currency,
                    "payer_id": str(settlement.payer_id),
                    "payee_id": str(settlement.payee_id),
                    "reason": settlement.failure_reason,
                    **{k: v for k, v in notification_context.items() if v is not None},
                },
            )
            logger.error(
                "Settlement → FAILED",
                extra={"settlement_id": str(settlement_id), "reason": str(exc)},
            )

settlement_processor = SettlementProcessor()
