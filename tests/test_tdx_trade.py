# -*- coding: utf-8 -*-
"""TdxTradeService 的纯逻辑测试：用 fake tq 验证下单映射与撤单对账。"""

import asyncio
import sys
import types
from types import SimpleNamespace

import pytest

from providers.tdx_provider import TdxProvider
from core.tdx_trade import TdxTradeService
from core.whitelist import is_function_whitelisted


def test_tdx_get_version_is_not_advertised():
    # tqcenter 的 tq 对象没有 get_version；白名单不能暴露不存在的函数
    assert is_function_whitelisted("tdxdata", "get_version") is False


class FakeTq:
    def __init__(self):
        self.initialized = False
        self.order_result = {
            "ErrorId": "0", "Msg": "提交交易成功！", "Value": 2, "Wtbh": "227988",
        }
        self.cancel_result = {"ErrorId": "0", "Msg": "提交撤单失败", "Value": 0}
        self.orders = []
        self.asset = {"ErrorId": "0", "Cash": "1000000.00", "Asset": "1000000.00"}
        self.order_calls = []
        self.cancel_calls = []
        self.query_count = 0
        self.status_sequence = [1]

    def initialize(self, path):
        self.initialized = True

    def stock_account(self, account, account_type):
        return 1

    def order_stock(self, **kwargs):
        self.order_calls.append(kwargs)
        return dict(self.order_result)

    def cancel_order_stock(self, account_id, stock_code, order_id):
        self.cancel_calls.append((account_id, stock_code, order_id))
        return dict(self.cancel_result)

    def query_stock_orders(self, account_id):
        self.query_count += 1
        status = self.status_sequence[min(self.query_count - 1, len(self.status_sequence) - 1)]
        return [{"Wtbh": "227988", "Code": "600000.SH", "Status": status,
                 "WtVol": "100", "WtPrice": "10.130", "CjVol": "0",
                 "CjPrice": "0.000", "BSFlag": 0, "Time": "130000"}]

    def query_stock_asset(self, account_id):
        return dict(self.asset)

    def query_stock_positions(self, account_id):
        return []

    def close(self):
        self.initialized = False


def _make_config(tmp_path):
    plugin = tmp_path / "PYPlugins" / "user"
    plugin.mkdir(parents=True)
    tdx = SimpleNamespace(
        enabled=True,
        install_path=str(tmp_path),
        account="11048389",
        account_type="stock",
        timeout=5,
        cancel_reconcile_timeout=0.2,
        poll_interval=0.01,
    )
    return SimpleNamespace(TDX=tdx)


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    fake = FakeTq()
    module = types.ModuleType("tqcenter")
    module.tq = fake
    monkeypatch.setitem(sys.modules, "tqcenter", module)

    provider = TdxProvider(_make_config(tmp_path))
    provider.initialize()
    service = TdxTradeService(provider, provider._config)
    yield provider, service, fake
    provider.cleanup()


def test_place_order_accepted(fake_env):
    provider, service, fake = fake_env

    result = asyncio.run(service.place_order(
        stock_code="600000.SH",
        order_type=0,
        order_volume=100,
        price_type=0,
        price=10.13,
        notify=0,
    ))

    assert result["state"] == "accepted"
    assert result["success"] is True
    assert result["order_id"] == "227988"
    assert fake.order_calls[0]["account_id"] == 1
    assert fake.order_calls[0]["order_volume"] == 100
    assert fake.order_calls[0]["price"] == 10.13


@pytest.mark.parametrize("value,expected", [(0, "failed"), (1, "pending_confirm")])
def test_place_order_maps_value(fake_env, value, expected):
    provider, service, fake = fake_env
    fake.order_result = {"ErrorId": "0", "Msg": "x", "Value": value}
    if value == 1:
        fake.order_result["Wtbh"] = ""

    result = asyncio.run(service.place_order("600000.SH", 0, 100, 0, 10.13, 0))

    assert result["state"] == expected
    assert result["order_id"] is None


def test_cancel_reconciles_false_failure(fake_env):
    provider, service, fake = fake_env
    fake.status_sequence = [1, 1, 0]

    result = asyncio.run(service.cancel_order("600000.SH", "227988"))

    assert result["raw_value"] == 0
    assert result["cancel_state"] == "confirmed"
    assert result["status"] == 0
    assert result["polls"] >= 2
    assert fake.cancel_calls == [(1, "600000.SH", "227988")]


def test_cancel_pending_when_status_never_terminal(fake_env):
    provider, service, fake = fake_env
    fake.status_sequence = [1]

    result = asyncio.run(service.cancel_order("600000.SH", "227988"))

    assert result["cancel_state"] == "pending"
    assert result["status"] == 1
    assert result["success"] is False


def test_cancel_retries_submission_when_first_rejected(fake_env):
    provider, service, fake = fake_env
    # 前 3 次轮询仍未撤销，说明第一次提交被拒；第 2 次提交后落地
    fake.status_sequence = [1, 1, 1, 1, 1, 0]

    result = asyncio.run(service.cancel_order("600000.SH", "227988"))

    assert result["cancel_state"] == "confirmed"
    assert result["attempts"] >= 2
    assert len(fake.cancel_calls) >= 2


def test_place_order_idempotent_by_client_order_id(fake_env):
    provider, service, fake = fake_env

    first = asyncio.run(service.place_order(
        "600000.SH", 0, 100, 0, 10.13, 0, client_order_id="order-key-1"
    ))
    second = asyncio.run(service.place_order(
        "600000.SH", 0, 100, 0, 10.13, 0, client_order_id="order-key-1"
    ))

    assert len(fake.order_calls) == 1
    assert first["order_id"] == "227988"
    assert second["idempotent_replay"] is True
    assert second["order_id"] == "227988"


def test_place_order_pending_confirm_is_idempotent(fake_env):
    provider, service, fake = fake_env
    fake.order_result = {
        "ErrorId": "0", "Msg": "已发送信号至客户端，待用户确认！", "Value": 1,
    }

    first = asyncio.run(service.place_order(
        "600000.SH", 0, 100, 0, 9.00, 1, client_order_id="notify-key-1"
    ))
    second = asyncio.run(service.place_order(
        "600000.SH", 0, 100, 0, 9.00, 1, client_order_id="notify-key-1"
    ))

    assert len(fake.order_calls) == 1
    assert first["state"] == "pending_confirm"
    assert second["idempotent_replay"] is True
    assert second["state"] == "pending_confirm"


def test_idempotency_survives_service_restart(fake_env, tmp_path):
    provider, _, fake = fake_env
    db_path = str(tmp_path / "tdx_idempotency.sqlite3")

    first_service = TdxTradeService(provider, provider._config, state_path=db_path)
    first = asyncio.run(first_service.place_order(
        "600000.SH", 0, 100, 0, 10.13, 0, client_order_id="restart-key-1"
    ))

    # 新实例模拟网关重启：内存缓存为空，但 SQLite 仍应命中
    second_service = TdxTradeService(provider, provider._config, state_path=db_path)
    second = asyncio.run(second_service.place_order(
        "600000.SH", 0, 100, 0, 10.13, 0, client_order_id="restart-key-1"
    ))

    assert first["order_id"] == "227988"
    assert len(fake.order_calls) == 1
    assert second["idempotent_replay"] is True
    assert second["order_id"] == "227988"


def test_probe_account_distinguishes_unlogged(fake_env):
    provider, service, fake = fake_env

    fake.asset = {"ErrorId": "0", "Value": []}
    result = provider.probe_account()

    assert result["logged_in"] is False
    assert "未登录" in result["reason"]

    fake.asset = {"ErrorId": "0", "Cash": "1000.00", "Asset": "1000.00"}
    result = provider.probe_account()

    assert result["logged_in"] is True
    assert result["cash"] == "1000.00"
