import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.messaging.settlement_processor import SettlementProcessor

def _make_message(value: object, offset: int = 0) -> MagicMock:
    msg = MagicMock()
    msg.value = value
    msg.offset = offset
    return msg

class _MockConsumer:

    def __init__(self, messages: list) -> None:
        self._messages = messages
        self.commit = AsyncMock()

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for msg in self._messages:
            yield msg

class TestProcessorRunOffsetCommit:

    @pytest.mark.asyncio
    async def test_commit_called_after_successful_handle(self) -> None:

        processor = SettlementProcessor()
        processor._running = True

        msg = _make_message({"event_type": "some.other.event"})
        consumer = _MockConsumer([msg])
        processor._consumer = consumer

        with patch.object(processor, "_handle", new_callable=AsyncMock):
            await processor.run()

        consumer.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_commit_not_called_when_handle_raises(self) -> None:

        processor = SettlementProcessor()
        processor._running = True

        msg = _make_message({"event_type": "settlement.created"})
        consumer = _MockConsumer([msg])
        processor._consumer = consumer

        with patch.object(
            processor, "_handle", new_callable=AsyncMock,
            side_effect=RuntimeError("simulated DB failure"),
        ):
            await processor.run()

        consumer.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_commit_called_for_each_successful_message(self) -> None:

        processor = SettlementProcessor()
        processor._running = True

        messages = [
            _make_message({"event_type": "settlement.completed"}, offset=i)
            for i in range(3)
        ]
        consumer = _MockConsumer(messages)
        processor._consumer = consumer

        with patch.object(processor, "_handle", new_callable=AsyncMock):
            await processor.run()

        assert consumer.commit.call_count == 3

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates_without_commit(self) -> None:

        processor = SettlementProcessor()
        processor._running = True

        msg = _make_message({})
        consumer = _MockConsumer([msg])
        processor._consumer = consumer

        with patch.object(
            processor, "_handle", new_callable=AsyncMock,
            side_effect=asyncio.CancelledError(),
        ):
            with pytest.raises(asyncio.CancelledError):
                await processor.run()

        consumer.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_loop_continues_after_handle_exception(self) -> None:

        processor = SettlementProcessor()
        processor._running = True

        msg_fail = _make_message({"event_type": "settlement.created"}, offset=0)
        msg_ok = _make_message({"event_type": "other.event"}, offset=1)
        consumer = _MockConsumer([msg_fail, msg_ok])
        processor._consumer = consumer

        call_count = 0

        async def _side_effect(value):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient error on first message")

        with patch.object(processor, "_handle", side_effect=_side_effect):
            await processor.run()

        assert consumer.commit.call_count == 1

class TestHandleMethod:

    @pytest.mark.asyncio
    async def test_non_dict_envelope_skipped(self) -> None:

        processor = SettlementProcessor()
        await processor._handle("not a dict")

    @pytest.mark.asyncio
    async def test_non_settlement_created_skipped(self) -> None:

        processor = SettlementProcessor()
        await processor._handle({
            "event_type": "settlement.completed",
            "payload": {"settlement_id": str(uuid.uuid4())},
        })

    @pytest.mark.asyncio
    async def test_missing_settlement_id_skipped(self) -> None:

        processor = SettlementProcessor()
        await processor._handle({
            "event_type": "settlement.created",
            "payload": {},
        })

    @pytest.mark.asyncio
    async def test_invalid_uuid_settlement_id_skipped(self) -> None:

        processor = SettlementProcessor()
        await processor._handle({
            "event_type": "settlement.created",
            "payload": {"settlement_id": "definitely-not-a-uuid"},
        })

    @pytest.mark.asyncio
    async def test_missing_event_type_skipped(self) -> None:

        processor = SettlementProcessor()
        await processor._handle({"payload": {"settlement_id": str(uuid.uuid4())}})
