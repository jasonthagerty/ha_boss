"""Tests for the dead-man's-switch heartbeat."""

import time
from unittest.mock import AsyncMock

import pytest

from ha_boss.monitoring.heartbeat import send_heartbeat


@pytest.mark.asyncio
async def test_send_heartbeat_stamps_helper_with_epoch_timestamp():
    """Heartbeat calls input_datetime.set_datetime with a current epoch timestamp."""
    client = AsyncMock()
    before = int(time.time())

    await send_heartbeat(client, "input_datetime.ha_boss_heartbeat")

    client.call_service.assert_awaited_once()
    domain, service, data = client.call_service.await_args.args
    assert (domain, service) == ("input_datetime", "set_datetime")
    assert data["entity_id"] == "input_datetime.ha_boss_heartbeat"
    assert before <= data["timestamp"] <= int(time.time())


@pytest.mark.asyncio
async def test_send_heartbeat_propagates_failure():
    """A failed service call raises so the caller can log and retry next beat."""
    client = AsyncMock()
    client.call_service.side_effect = Exception("HA unreachable")

    with pytest.raises(Exception, match="HA unreachable"):
        await send_heartbeat(client, "input_datetime.ha_boss_heartbeat")
