# -*- coding: utf-8 -*-
"""XtQuant 类型化交易服务测试（不依赖真实 xtquant）。"""

import asyncio
from types import SimpleNamespace

import pytest

import core.xt_trade as xt_trade
from core.xt_trade import XtConfigError, XtTradeService


def _service(account="11048389"):
    cfg = SimpleNamespace(ACCOUNT_ID=account, CONNECT_TIMEOUT=5)
    provider = SimpleNamespace(_config=cfg)
    return XtTradeService(provider, cfg)


def test_place_order_maps_constants(monkeypatch):
    calls = []

    def fake(function, args, kwargs):
        calls.append((function, kwargs))
        if function == "order_stock":
            return {"success": True, "data": 12345}
        return {"success": True, "data": None}

    monkeypatch.setattr(xt_trade, "execute_xttrader_method", fake)
    service = _service()

    result = asyncio.run(service.place_order("600000.SH", 0, 100, 0, 10.13))

    assert result["success"] is True
    assert result["order_id"] == "12345"
    assert calls[0][0] == "order_stock"
    assert calls[0][1]["account"] == "11048389"
    assert calls[0][1]["order_type"] == xt_trade.STOCK_BUY
    assert calls[0][1]["price_type"] == xt_trade.FIX_PRICE


def test_place_order_requires_account():
    service = _service(account="")
    with pytest.raises(XtConfigError):
        asyncio.run(service.place_order("600000.SH", 0, 100, 0, 10.13))


def test_place_order_idempotent(monkeypatch):
    calls = []

    def fake(function, args, kwargs):
        calls.append(function)
        return {"success": True, "data": 888}

    monkeypatch.setattr(xt_trade, "execute_xttrader_method", fake)
    service = _service()

    first = asyncio.run(service.place_order(
        "600000.SH", 0, 100, 0, 10.13, client_order_id="xt-key-1"
    ))
    second = asyncio.run(service.place_order(
        "600000.SH", 0, 100, 0, 10.13, client_order_id="xt-key-1"
    ))

    assert calls.count("order_stock") == 1
    assert first["order_id"] == "888"
    assert second["idempotent_replay"] is True


def test_cancel_and_queries(monkeypatch):
    def fake(function, args, kwargs):
        if function == "cancel_order_stock":
            return {"success": True, "data": 0}
        if function == "query_stock_orders":
            return {"success": True, "data": [{"order_id": 1, "order_status": 2}]}
        if function == "query_stock_asset":
            return {"success": True, "data": {"cash": 1000.0}}
        if function == "query_stock_positions":
            return {"success": True, "data": [{"stock_code": "600000.SH", "volume": 100}]}
        return {"success": False, "error": "unknown"}

    monkeypatch.setattr(xt_trade, "execute_xttrader_method", fake)
    service = _service()

    cancel = asyncio.run(service.cancel_order(12345))
    orders = asyncio.run(service.query_orders())
    asset = asyncio.run(service.query_asset())
    positions = asyncio.run(service.query_positions())

    assert cancel["success"] is True
    assert len(orders) == 1
    assert asset["cash"] == 1000.0
    assert positions[0]["stock_code"] == "600000.SH"
