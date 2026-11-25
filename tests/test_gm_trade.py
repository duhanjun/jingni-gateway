# -*- coding: utf-8 -*-
"""GM 类型化交易服务测试（不依赖真实 gm SDK）。"""

import asyncio
from types import SimpleNamespace

import pytest

from core.gm_trade import GMNotLoggedInError, GMTradeService


class FakeGM:
    def __init__(self):
        self.calls = []
        self.order_result = [{"order_id": "gm-order-1", "cl_ord_id": "gm-clord-1"}]
        self.cancel_result = True
        self.order_status = 2

    def order_volume(self, **kwargs):
        self.calls.append(("order_volume", kwargs))
        return list(self.order_result)

    def order_cancel(self, **kwargs):
        self.calls.append(("order_cancel", kwargs))
        self.order_status = 5
        return self.cancel_result

    def get_orders(self, **kwargs):
        return [{
            "order_id": "gm-order-1",
            "cl_ord_id": "gm-clord-1",
            "status": self.order_status,
        }]

    def get_cash(self, **kwargs):
        return {"cash": 1000.0, "total_asset": 1000.0}

    def get_position(self, **kwargs):
        return [{"symbol": "SHSE.600000", "volume": 100}]


def _service(account="gm-account"):
    cfg = SimpleNamespace(
        GM=SimpleNamespace(
            account_id=account,
            token="test-token",
            cancel_reconcile_timeout=0.2,
            cancel_poll_interval=0.05,
            cancel_poll_max_interval=0.1,
        ),
        CONNECT_TIMEOUT=5,
    )
    api = FakeGM()
    return GMTradeService(api, cfg), api


def test_place_order_maps_gm_constants():
    service, api = _service()

    result = asyncio.run(service.place_order(
        "SHSE.600000", 100, 0, 0, 10.13, position_effect=1
    ))

    assert result["success"] is True
    assert result["order_id"] == "gm-order-1"
    kwargs = api.calls[0][1]
    assert kwargs["side"] == 1
    assert kwargs["order_type"] == 1
    assert kwargs["account"] == "gm-account"


def test_place_order_maps_immediate_rejection():
    service, api = _service()
    api.order_result = [{"order_id": "gm-rejected-1"}]
    api.get_orders = lambda **kwargs: [{
        "order_id": "gm-rejected-1",
        "status": 8,
        "ord_rej_reason_detail": "[GMBROKER] 仓位不足: 委托冻结(100) > 可用持仓(0)",
    }]

    result = asyncio.run(service.place_order(
        "SHSE.510300", 100, 0, 1, 0.0, position_effect=1
    ))

    assert result["success"] is False
    assert result["state"] == "rejected"
    assert result["status"] == 8
    assert "仓位不足" in result["reject_reason"]


def test_place_order_idempotent():
    service, api = _service()

    first = asyncio.run(service.place_order(
        "SHSE.600000", 100, 0, 0, 10.13, client_order_id="gm-key-1"
    ))
    second = asyncio.run(service.place_order(
        "SHSE.600000", 100, 0, 0, 10.13, client_order_id="gm-key-1"
    ))

    assert len([c for c in api.calls if c[0] == "order_volume"]) == 1
    assert first["order_id"] == "gm-order-1"
    assert second["idempotent_replay"] is True


def test_cancel_and_queries():
    service, api = _service()

    cancel = asyncio.run(service.cancel_order("gm-order-1"))
    orders = asyncio.run(service.query_orders())
    asset = asyncio.run(service.query_asset())
    positions = asyncio.run(service.query_positions())

    assert cancel["success"] is True
    assert len(orders) == 1
    assert asset["cash"] == 1000.0
    assert positions[0]["symbol"] == "SHSE.600000"
    cancel_kwargs = [c[1] for c in api.calls if c[0] == "order_cancel"][0]
    assert cancel_kwargs["cl_ord_id"] == "gm-clord-1"
    assert cancel_kwargs["account_id"] == "gm-account"


def test_cancel_unknown_client_id_does_not_report_success():
    service, api = _service()

    result = asyncio.run(service.cancel_order("unknown-local-key", cl_ord_id="unknown-local-key"))

    assert result["success"] is False
    assert result["cancel_state"] == "failed"
    assert result["error"] == "ORDER_NOT_FOUND"
    assert not [c for c in api.calls if c[0] == "order_cancel"]


def test_cancel_requires_terminal_order_status():
    service, api = _service()
    api.order_cancel = lambda **kwargs: True
    api.order_status = 1

    result = asyncio.run(service.cancel_order("gm-order-1"))

    assert result["success"] is False
    assert result["cancel_state"] == "failed"
    assert result["status"] == 1
    assert result["error"] == "CANCEL_NOT_CONFIRMED"


def test_empty_cash_raises_not_logged_in():
    service, api = _service()
    api.get_cash = lambda **kwargs: {}

    with pytest.raises(GMNotLoggedInError):
        asyncio.run(service.query_asset())


def test_query_positions_filters_zero_volume_placeholder():
    service, api = _service()
    api.get_position = lambda **kwargs: [
        {"symbol": "SHSE.510300", "volume": "0"},
        {"symbol": "SHSE.601398", "volume": "100"},
    ]

    positions = asyncio.run(service.query_positions())

    assert [p["symbol"] for p in positions] == ["SHSE.601398"]
