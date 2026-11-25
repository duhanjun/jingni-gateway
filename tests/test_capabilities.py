# -*- coding: utf-8 -*-
"""能力矩阵回归测试。

覆盖：
- GM gmtrade 只允许三个查询 action；
- TDX tdxtrade 不开放通用 RPC；
- 显式 unsupported / runtime_missing 的区分；
- ``/rpc/whitelist``、``/rpc/methods`` 只暴露 supported；
- 明确不支持的调用返回 ``NOT_SUPPORTED``，而不是运行时的 ``NOT_FOUND``。
"""

from fastapi.testclient import TestClient
import pytest

import main
import api.gm as gm_api
import core.rpc as rpc
from api.gm import set_gm_provider
from config import config
from core.capabilities import (
    RUNTIME_MISSING,
    SUPPORTED,
    UNSUPPORTED,
    build_capability_snapshot,
    evaluate_rpc,
    resolve_module,
)
from core.whitelist import BLOCKED_RPC_FUNCTIONS, RPC_WHITELIST

TEST_HEADERS = {"X-API-Key": config.API_KEY}


def test_gm_gmtrade_only_three_queries_supported():
    result = resolve_module("gm", "gmtrade")

    assert result.exposed is True
    assert result.supported == ["get_cash", "get_position", "get_orders"]

    unsupported = {item.function: item for item in result.unsupported}
    assert unsupported["credit_buying_on_margin"].status == UNSUPPORTED
    assert "信用" in unsupported["credit_buying_on_margin"].reason
    assert unsupported["order_volume"].status == UNSUPPORTED


def test_tdx_trade_is_typed_only():
    result = resolve_module("tdxquant", "tdxtrade")

    assert result.exposed is False
    assert result.supported == []
    assert all(item.status == UNSUPPORTED for item in result.unsupported)

    status, reason = evaluate_rpc("tdxquant", "tdxtrade", "query_stock_orders")
    assert status == UNSUPPORTED
    assert "/trade" in reason


def test_tdx_known_unsupported_functions_are_explicit():
    for function in ("get_version", "subscribe_quote", "get_financial_data_by_date"):
        status, reason = evaluate_rpc("tdxquant", "tdxdata", function)
        assert status == UNSUPPORTED
        assert reason


def test_runtime_missing_is_filtered_out():
    class PartialRef:
        def history_n(self, **kwargs):
            return []

    result = resolve_module(
        "gm",
        "gmdata",
        probe=lambda function: callable(getattr(PartialRef(), function, None)),
    )

    assert result.supported == ["history_n"]
    missing = {item.function: item for item in result.unsupported}
    assert missing["history"].status == RUNTIME_MISSING


def test_build_snapshot_contains_supported_and_typed_trade():
    class Proxy:
        def get_cash(self, **kwargs):
            return {}

        def get_position(self, **kwargs):
            return []

        def get_orders(self, **kwargs):
            return []

    snapshot = build_capability_snapshot(
        "gm",
        module_refs={"gmtrade": Proxy(), "gmdata": None},
    )

    assert snapshot["rpc"]["supported"]["gmtrade"] == [
        "get_cash", "get_position", "get_orders",
    ]
    assert snapshot["typed_trade"]["operations"]
    assert "unsupported" in snapshot["rpc"]


def test_export_data_is_not_exposed():
    assert "export_data" not in RPC_WHITELIST["xttrader"]
    assert ("xttrader", "export_data") in BLOCKED_RPC_FUNCTIONS

    status, reason = evaluate_rpc("xtquant", "xttrader", "export_data")
    assert status == UNSUPPORTED
    assert "高危" in reason


class _FakeGMProxy:
    def get_cash(self, **kwargs):
        return {}

    def get_position(self, **kwargs):
        return []

    def get_orders(self, **kwargs):
        return []


class _FakeGMData:
    def history_n(self, **kwargs):
        return []


class _FakeGMProvider:
    name = "gm"
    is_available = True
    token_configured = True
    account_configured = True
    gmtrade_available = True
    _token_set = True

    def get_module_reference(self, module):
        return {
            "gmdata": _FakeGMData(),
            "gmtrade": _FakeGMProxy(),
        }.get(module)

    def get_rpc_whitelist(self):
        return {}


def test_gm_http_surfaces_only_supported():
    original_provider = gm_api._gm_provider_instance
    original_trade_service = gm_api._gm_trade_service
    set_gm_provider(_FakeGMProvider())

    try:
        client = TestClient(main.app)

        whitelist = client.get(
            "/api/v1/gm/rpc/whitelist", headers=TEST_HEADERS
        ).json()
        assert whitelist["whitelist"]["gmtrade"] == [
            "get_cash", "get_position", "get_orders",
        ]

        methods = client.get(
            "/api/v1/gm/rpc/methods", headers=TEST_HEADERS
        ).json()
        names = {(item["module"], item["name"]) for item in methods["methods"]}
        assert ("gmtrade", "credit_buying_on_margin") not in names
        assert ("gmtrade", "get_cash") in names

        response = client.post(
            "/api/v1/gm/rpc/execute",
            headers=TEST_HEADERS,
            json={
                "module": "gmtrade",
                "function": "credit_buying_on_margin",
                "kwargs": {},
            },
        ).json()
        assert response["success"] is False
        assert response["error_code"] == "NOT_SUPPORTED"
        assert response["support_status"] == "unsupported"

        capabilities = client.get(
            "/api/v1/gm/rpc/capabilities", headers=TEST_HEADERS
        ).json()
        assert "gmdata" in capabilities["rpc"]["supported"]
        assert "gmtrade" in capabilities["rpc"]["unsupported"]
    finally:
        gm_api._gm_provider_instance = original_provider
        gm_api._gm_trade_service = original_trade_service


@pytest.mark.asyncio
async def test_websocket_rpc_uses_capability_gate():
    class FakeGM:
        def get_cash(self, **kwargs):
            return {}

        def credit_buying_on_margin(self, **kwargs):
            return {}

    original_module = rpc._gm_api_module
    rpc._gm_api_module = FakeGM()

    try:
        rejected = await rpc.execute_rpc_call(
            "gmtrade", "credit_buying_on_margin", [], {}
        )
        assert rejected["success"] is False
        assert rejected["error_code"] == "NOT_SUPPORTED"
        assert rejected["support_status"] == "unsupported"

        accepted = await rpc.execute_rpc_call("gmtrade", "get_cash", [], {})
        assert accepted["success"] is True
    finally:
        rpc._gm_api_module = original_module
