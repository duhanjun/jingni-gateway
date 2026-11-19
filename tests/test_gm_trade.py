# -*- coding: utf-8 -*-
"""GM 类型化交易服务测试（不依赖真实 gm SDK）。"""

import asyncio
from types import SimpleNamespace

import pytest

from core.gm_trade import GMNotLoggedInError, GMTradeService


class FakeGM:
    def __init__(self):
        self.calls = []
        self.order_result = [{"order_id": "gm-order-1"}]
        self.cancel_result = True

    def order_volume(self, **kwargs):
        self.calls.append(("order_volume", kwargs))
        return list(self.order_result)

    def order_cancel(self, **kwargs):
        self.calls.append(("order_cancel", kwargs))
        return self.cancel_result

    def get_orders(self, **kwargs):
        return [{"order_id": "gm-order-1", "status": 2}]

    def get_cash(self, **kwargs):
        return {"cash": 1000.0, "total_asset": 1000.0}

    def get_position(self, **kwargs):
        return [{"symbol": "SHSE.600000", "volume": 100}]


def _service(account="gm-account"):
    cfg = SimpleNamespace(
        GM=SimpleNamespace(account_id=account, token="test-token"),
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
    assert cancel_kwargs["cl_ord_id"] == "gm-order-1"
    assert cancel_kwargs["account_id"] == "gm-account"


def test_empty_cash_raises_not_logged_in():
    service, api = _service()
    api.get_cash = lambda **kwargs: {}

    with pytest.raises(GMNotLoggedInError):
        asyncio.run(service.query_asset())
