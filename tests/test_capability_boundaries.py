# -*- coding: utf-8 -*-
"""能力边界测试：入口层必须和功能矩阵的“明确不支持”一致。

覆盖：
- TDX 没有 WebSocket RPC，只能走 HTTP；
- 行情 / 交易事件推送默认 NOT_SUPPORTED；
- 通用 RPC 的 NOT_WHITELISTED / NOT_SUPPORTED / USE_TRADE_ENDPOINT 区分；
- 能力矩阵补齐 ws / typed_trade 元数据（多账户、幂等）。
"""

import pytest
from fastapi.testclient import TestClient

import core.rpc as rpc
import main as main_module
from config import config
from core.capabilities import (
    WS_EXPOSED_MODULES,
    build_capability_snapshot,
    evaluate_rpc,
    evaluate_ws_module,
)

HEADERS = {"X-API-Key": config.API_KEY}
WS_AUTH = f"?api_key={config.API_KEY}&client_id="


def _receive_until(ws, wanted_type: str):
    """跳过 connected 等握手消息，拿到目标类型。"""
    while True:
        message = ws.receive_json()
        if message.get("type") == wanted_type:
            return message


def test_ws_module_map_excludes_tdx():
    assert WS_EXPOSED_MODULES["tdxquant"] == ()
    assert set(WS_EXPOSED_MODULES["xtquant"]) == {"xtdata", "xttrader"}
    assert set(WS_EXPOSED_MODULES["gm"]) == {"gmdata", "gmtrade"}


def test_evaluate_ws_module_rejects_tdx_with_http_hint():
    status, reason = evaluate_ws_module("tdxquant", "tdxdata")

    assert status == "unsupported"
    assert "WebSocket RPC" in reason
    assert "HTTP" in reason


def test_execute_rpc_call_rejects_tdx_module():
    import asyncio

    result = asyncio.run(
        rpc.execute_rpc_call("tdxdata", "get_stock_list", [], {})
    )

    assert result["success"] is False
    assert result["error_code"] == "USE_HTTP_ENDPOINT"
    assert "HTTP" in result["error"]


def test_execute_rpc_call_rejects_unlisted_function():
    import asyncio

    result = asyncio.run(
        rpc.execute_rpc_call("xtdata", "definitely_not_declared", [], {})
    )

    assert result["success"] is False
    assert result["error_code"] == "NOT_WHITELISTED"


def test_gmtrade_ws_rpc_uses_gm_api_module(monkeypatch):
    class FakeGM:
        def get_cash(self):
            return {"cash": 100.0}

    monkeypatch.setattr(rpc, "_gm_api_module", FakeGM())

    import asyncio

    result = asyncio.run(rpc.execute_rpc_call("gmtrade", "get_cash", [], {}))

    assert result["success"] is True
    assert result["data"] == {"cash": 100.0}


def test_capability_snapshot_contains_boundary_metadata():
    snapshot = build_capability_snapshot("xtquant", runtime_available=True)

    assert snapshot["ws"] == {
        "rpc_modules": ["xtdata", "xttrader"],
        "market_data_push": False,
        "trade_event_push": False,
    }
    assert snapshot["typed_trade"]["multi_account"] is False
    assert snapshot["typed_trade"]["idempotency"] == "process_memory"


def test_gm_capability_has_process_memory_idempotency():
    snapshot = build_capability_snapshot("gm", runtime_available=True)
    assert snapshot["typed_trade"]["multi_account"] is False
    assert snapshot["typed_trade"]["idempotency"] == "process_memory"


def test_tdx_capability_has_sqlite_idempotency():
    snapshot = build_capability_snapshot("tdxquant", runtime_available=True)
    assert snapshot["typed_trade"]["multi_account"] is False
    assert snapshot["typed_trade"]["idempotency"] == "process_memory+sqlite"
    assert snapshot["ws"]["rpc_modules"] == []


def test_websocket_market_data_push_is_not_supported():
    client = TestClient(main_module.app)

    with client.websocket_connect("/ws" + WS_AUTH + "boundary-md") as ws:
        assert ws.receive_json()["type"] == "connected"
        ws.send_json({"type": "subscribe_quote", "stock_code": "600000.SH"})
        message = _receive_until(ws, "error")

    assert message["error_code"] == "NOT_SUPPORTED"
    assert message["feature"] == "market_data_push"
    assert "HTTP" in message["message"]


def test_websocket_whole_quote_is_not_supported():
    client = TestClient(main_module.app)

    with client.websocket_connect("/ws" + WS_AUTH + "boundary-whole") as ws:
        assert ws.receive_json()["type"] == "connected"
        ws.send_json({"type": "subscribe_whole_quote", "code_list": ["600000.SH"]})
        message = _receive_until(ws, "error")

    assert message["error_code"] == "NOT_SUPPORTED"
    assert message["feature"] == "market_data_push"


def test_websocket_trade_event_is_not_supported():
    client = TestClient(main_module.app)

    with client.websocket_connect("/ws" + WS_AUTH + "boundary-trade") as ws:
        assert ws.receive_json()["type"] == "connected"
        ws.send_json({"type": "subscribe_trade_event", "provider": "xtquant"})
        message = _receive_until(ws, "error")

    assert message["error_code"] == "NOT_SUPPORTED"
    assert message["feature"] == "trade_event_push"
    assert "/trade/orders" in message["message"]


def test_websocket_rpc_rejects_tdx_module():
    client = TestClient(main_module.app)

    with client.websocket_connect("/ws" + WS_AUTH + "boundary-rpc") as ws:
        assert ws.receive_json()["type"] == "connected"
        ws.send_json({
            "type": "rpc_call",
            "module": "tdxdata",
            "function": "get_stock_list",
            "kwargs": {},
            "request_id": "r1",
        })
        message = _receive_until(ws, "rpc_response")

    assert message["success"] is False
    assert message["error_code"] == "USE_HTTP_ENDPOINT"
    assert message["support_status"] == "unsupported"


def test_tdx_http_rejects_typed_trade_module():
    import api.tdxquant as tdx_api

    tdx_api.set_tdx_provider(None)
    client = TestClient(main_module.app)

    response = client.post(
        "/api/v1/tdxquant/rpc/execute",
        headers=HEADERS,
        json={
            "module": "tdxtrade",
            "function": "place_order",
            "kwargs": {},
        },
    )

    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "USE_TRADE_ENDPOINT"


@pytest.mark.parametrize(
    "function",
    [
        "credit_buying_on_margin", "credit_short_selling", "option_comb",
        "fund_buy", "ipo_buy", "schedule",
    ],
)
def test_gm_advanced_actions_are_unsupported(function):
    status, reason = evaluate_rpc("gm", "gmtrade", function)

    assert status == "unsupported"
    assert "get_cash" in reason


def test_gm_algorithm_order_is_typed_only():
    status, reason = evaluate_rpc("gm", "gmtrade", "order_target_value")

    assert status == "unsupported"
    assert "order_volume" in reason or "类型化" in reason


@pytest.mark.parametrize(
    "function",
    ["get_gpjy_value", "get_zdt_data", "subscribe_quote", "get_version"],
)
def test_tdx_extension_surface_is_unsupported(function):
    status, reason = evaluate_rpc("tdxquant", "tdxdata", function)

    assert status == "unsupported"
    assert reason


def test_tdx_trade_module_has_no_generic_rpc():
    status, reason = evaluate_rpc("tdxquant", "tdxtrade", "query_stock_asset")

    assert status == "unsupported"
    assert "类型化" in reason or "/trade" in reason


def test_xtquant_export_data_is_not_declared():
    status, reason = evaluate_rpc("xtquant", "xtdata", "export_data")

    assert status == "not_declared"


def test_root_exposes_boundaries():
    client = TestClient(main_module.app)
    response = client.get("/")

    body = response.json()
    assert body["boundaries"]["tdx_websocket_rpc"] is False
    assert body["boundaries"]["tdx_transport"] == "http_only"
    assert body["boundaries"]["trade_event_push"] is False
    assert body["boundaries"]["multi_account"] is False
