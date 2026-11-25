# -*- coding: utf-8 -*-
"""TDX 错误载荷语义测试。

代码层待修项：``/trade/asset`` 过去在 ``ErrorId != "0"`` 时仍返回
``success=true`` 的错误载荷。现在统一抛 ``TdxError``，由 API 转成
``success=false`` + ``TDX_ERROR``。

真实联调补充：未登录时 ``query_stock_orders`` / ``query_stock_positions``
可能返回空列表，接口因此误报 ``success=true``。现在空结果会先用资产探测
确认登录；未登录返回 ``TDX_NOT_LOGGED_IN``，已登录的空账户仍返回 ``[]``。
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api.tdxquant as tdx_api
import main as main_module
from config import config
from core.tdx_trade import TdxError, TdxNotLoggedInError, TdxTradeService
from api.tdxquant import _tdx_sdk_error

HEADERS = {"X-API-Key": config.API_KEY}


class FakeTq:
    def __init__(self, asset=None, orders=None, positions=None):
        self.asset = asset
        self.orders = orders
        self.positions = positions
        self.calls = []

    def query_stock_asset(self, handle):
        self.calls.append("asset")
        return self.asset

    def query_stock_orders(self, handle):
        self.calls.append("orders")
        return self.orders

    def query_stock_positions(self, handle):
        self.calls.append("positions")
        return self.positions

    def order_stock(self, **kwargs):
        self.calls.append("order")
        return {"ErrorId": "0", "Value": 1}


class FakeProvider:
    def __init__(self, tq):
        self._tq = tq
        self.is_available = True
        self.is_initialized = True

    def ensure_initialized(self):
        return self._tq

    def account_handle(self):
        return 1

    def probe_account(self):
        asset = self._tq.asset
        if isinstance(asset, dict) and "Cash" in asset and asset.get("Cash") is not None:
            return {"logged_in": True, "cash": asset.get("Cash")}
        return {"logged_in": False, "reason": "账户未登录或资产为空"}

    def get_module_reference(self, module_name):
        return None


def _service(tq):
    cfg = SimpleNamespace(
        CONNECT_TIMEOUT=5,
        TDX=SimpleNamespace(
            timeout=5,
            cancel_reconcile_timeout=2,
            poll_interval=0.1,
            idempotency_db=None,
        ),
    )
    return TdxTradeService(FakeProvider(tq), cfg, state_path=None)


def test_asset_error_id_raises_instead_of_returning_payload():
    tq = FakeTq(asset={"ErrorId": "1", "Msg": "资金账户未登录"})
    service = _service(tq)

    with pytest.raises(TdxError) as exc_info:
        asyncio.run(service.query_asset())

    message = str(exc_info.value)
    assert "资产查询失败" in message
    assert "资金账户未登录" in message
    assert "ErrorId=1" in message


def test_orders_error_id_raises():
    tq = FakeTq(orders={"ErrorId": "5", "Msg": "查询过于频繁"})
    service = _service(tq)

    with pytest.raises(TdxError) as exc_info:
        asyncio.run(service.query_orders())

    assert "委托查询失败" in str(exc_info.value)
    assert "查询过于频繁" in str(exc_info.value)


def test_positions_error_id_raises():
    tq = FakeTq(positions={"ErrorId": "9", "Msg": "持仓查询异常"})
    service = _service(tq)

    with pytest.raises(TdxError) as exc_info:
        asyncio.run(service.query_positions())

    assert "持仓查询失败" in str(exc_info.value)


def test_asset_zero_error_id_still_returns_data():
    tq = FakeTq(asset={"ErrorId": "0", "Cash": "1000.5", "Value": []})
    service = _service(tq)

    result = asyncio.run(service.query_asset())

    assert result["cash"] == 1000.5


def test_empty_orders_without_login_raises_not_logged_in():
    tq = FakeTq(asset={"ErrorId": "0", "Value": []}, orders=[])
    service = _service(tq)

    with pytest.raises(TdxNotLoggedInError):
        asyncio.run(service.query_orders())


def test_empty_positions_without_login_raises_not_logged_in():
    tq = FakeTq(asset={"ErrorId": "0", "Value": []}, positions=[])
    service = _service(tq)

    with pytest.raises(TdxNotLoggedInError):
        asyncio.run(service.query_positions())


def test_empty_positions_with_login_still_returns_empty():
    tq = FakeTq(asset={"ErrorId": "0", "Cash": "1000.5"}, positions=[])
    service = _service(tq)

    assert asyncio.run(service.query_positions()) == []


def test_empty_orders_with_login_still_returns_empty():
    tq = FakeTq(asset={"ErrorId": "0", "Cash": "1000.5"}, orders=[])
    service = _service(tq)

    assert asyncio.run(service.query_orders()) == []


def test_place_order_without_login_refuses_before_send():
    tq = FakeTq(asset={"ErrorId": "0", "Value": []})
    service = _service(tq)

    with pytest.raises(TdxNotLoggedInError):
        asyncio.run(service.place_order(
            stock_code="600000.SH",
            order_type=0,
            order_volume=100,
            price_type=0,
            price=10.0,
        ))

    assert "order" not in tq.calls


def test_api_place_order_without_login_reports_not_logged_in(client_with_error_provider):
    client, api_module = client_with_error_provider
    api_module._tdx_trade_service = _service(
        FakeTq(asset={"ErrorId": "0", "Value": []})
    )

    response = client.post(
        "/api/v1/tdxquant/trade/order",
        headers=HEADERS,
        json={
            "stock_code": "600000.SH",
            "order_type": 0,
            "order_volume": 100,
            "price_type": 0,
            "price": 10.0,
            "notify": 0,
        },
    )

    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "TDX_NOT_LOGGED_IN"


@pytest.fixture
def client_with_error_provider():
    tq = FakeTq(asset={"ErrorId": "1", "Msg": "账户异常"})
    provider = FakeProvider(tq)
    tdx_api.set_tdx_provider(provider)
    tdx_api._tdx_trade_service = _service(tq)
    yield TestClient(main_module.app), tdx_api
    tdx_api._tdx_trade_service = None
    tdx_api._tdx_provider_instance = None


def test_api_asset_returns_success_false(client_with_error_provider):
    client, api_module = client_with_error_provider

    response = client.get("/api/v1/tdxquant/trade/asset", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "TDX_ERROR"
    assert "账户异常" in body["error"]


def test_api_orders_returns_success_false(client_with_error_provider):
    client, api_module = client_with_error_provider
    api_module._tdx_trade_service = _service(
        FakeTq(orders={"ErrorId": "7", "Msg": "委托查询失败"})
    )

    response = client.get("/api/v1/tdxquant/trade/orders", headers=HEADERS)

    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "TDX_ERROR"


def test_api_empty_orders_without_login_reports_not_logged_in(client_with_error_provider):
    client, api_module = client_with_error_provider
    api_module._tdx_trade_service = _service(
        FakeTq(asset={"ErrorId": "0", "Value": []}, orders=[])
    )

    response = client.get("/api/v1/tdxquant/trade/orders", headers=HEADERS)

    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "TDX_NOT_LOGGED_IN"


def test_api_empty_positions_without_login_reports_not_logged_in(client_with_error_provider):
    client, api_module = client_with_error_provider
    api_module._tdx_trade_service = _service(
        FakeTq(asset={"ErrorId": "0", "Value": []}, positions=[])
    )

    response = client.get("/api/v1/tdxquant/trade/positions", headers=HEADERS)

    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "TDX_NOT_LOGGED_IN"


def test_tdx_sdk_dict_error_is_detected():
    assert "周期格式错误" in _tdx_sdk_error({"error": -5, "msg": "周期格式错误：1min"})
    assert _tdx_sdk_error({}) is None
    assert _tdx_sdk_error({"error": 0, "msg": "ok"}) is None
