# -*- coding: utf-8 -*-
"""ConnectionManager 限额/重连/心跳状态测试。"""

import asyncio

from core.websocket import ConnectionManager


class FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = None
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)

    async def send_json(self, message):
        self.sent.append(message)


def test_connect_and_invalid_key():
    manager = ConnectionManager(max_connections=2)
    ws = FakeWebSocket()

    assert asyncio.run(manager.connect(ws, "c1", "key", "key")) is True
    assert ws.accepted is True
    assert ws.sent[0]["type"] == "connected"

    ws2 = FakeWebSocket()
    assert asyncio.run(manager.connect(ws2, "c2", "bad", "key")) is False
    assert ws2.closed == (4001, "Invalid API Key")


def test_max_connections():
    manager = ConnectionManager(max_connections=1)
    ws1 = FakeWebSocket()
    ws2 = FakeWebSocket()

    assert asyncio.run(manager.connect(ws1, "c1", "key", "key")) is True
    assert asyncio.run(manager.connect(ws2, "c2", "key", "key")) is False
    assert ws2.closed == (4003, "Max connections reached")
    assert len(manager.active_connections) == 1


def test_same_client_replaces_old_connection():
    manager = ConnectionManager(max_connections=1)
    old = FakeWebSocket()
    new = FakeWebSocket()

    assert asyncio.run(manager.connect(old, "c1", "key", "key")) is True
    assert asyncio.run(manager.connect(new, "c1", "key", "key")) is True
    assert old.closed == (4002, "Replaced by new connection")
    assert manager.active_connections["c1"] is new


def test_touch_updates_heartbeat():
    manager = ConnectionManager(heartbeat_interval=1)
    ws = FakeWebSocket()
    asyncio.run(manager.connect(ws, "c1", "key", "key"))

    manager.touch("c1")

    assert "c1" in manager._last_heartbeat
    assert manager.get_stats()["max_connections"] == 100
