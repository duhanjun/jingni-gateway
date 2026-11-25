# -*- coding: utf-8 -*-
"""XtQuant 交易实例初始化测试（不依赖真实 SDK）。

覆盖代码层待修项：
- session_id 不再用 int(account)，非纯数字账户可创建实例；
- start / connect 返回真实结果，失败不再假成功；
- provider 内三参 XtQuantTrader 构造死代码已移除。
"""

import inspect

import pytest

import config as config_module
import core.rpc as rpc
from core.rpc import (
    create_xttrader_instance,
    execute_xttrader_method,
    get_xttrader_instance,
    get_xttrader_state,
    resolve_session_id,
)
from providers.xtquant_provider import XtQuantProvider


class FakeCallback:
    def __init__(self):
        self.events = []


class FakeTrader:
    def __init__(self, path, session_id):
        self.path = path
        self.session_id = session_id
        self.callbacks = []
        self.start_calls = 0
        self.connect_calls = 0
        self.connect_code = 0
        self.raise_on_start = False
        self.raise_on_connect = False

    def register_callback(self, callback):
        self.callbacks.append(callback)

    def start(self):
        self.start_calls += 1
        if self.raise_on_start:
            raise RuntimeError("start boom")
        return None

    def connect(self):
        self.connect_calls += 1
        if self.raise_on_connect:
            raise RuntimeError("connect boom")
        return self.connect_code

    def stop(self):
        return None


class FakeXtTraderModule:
    XtQuantTrader = FakeTrader
    XtQuantTraderCallback = FakeCallback


@pytest.fixture
def fake_module(monkeypatch):
    monkeypatch.setattr(rpc, "_xttrader_module", FakeXtTraderModule())
    monkeypatch.setattr(rpc, "_xttrader_instance", None)
    monkeypatch.setattr(rpc, "_xttrader_account", None)
    monkeypatch.setattr(rpc, "_xttrader_callback", None)
    rpc._reset_xttrader_state()
    yield
    monkeypatch.setattr(rpc, "_xttrader_instance", None)
    rpc._reset_xttrader_state()


def test_resolve_session_id_accepts_non_numeric_account(monkeypatch):
    monkeypatch.setattr(config_module.config, "QMT_SESSION_ID", None, raising=False)

    first = resolve_session_id("ABC-001")
    second = resolve_session_id("ABC-001")

    assert isinstance(first, int)
    assert first > 0
    assert first == second
    assert resolve_session_id("XYZ-999") != first


def test_resolve_session_id_prefers_explicit_config(monkeypatch):
    monkeypatch.setattr(config_module.config, "QMT_SESSION_ID", 777, raising=False)

    assert resolve_session_id("ABC-001") == 777


def test_resolve_session_id_rejects_invalid_config(monkeypatch):
    monkeypatch.setattr(config_module.config, "QMT_SESSION_ID", "abc", raising=False)

    with pytest.raises(ValueError):
        resolve_session_id("ABC-001")


def test_resolve_session_id_rejects_empty_account(monkeypatch):
    monkeypatch.setattr(config_module.config, "QMT_SESSION_ID", None, raising=False)

    with pytest.raises(ValueError):
        resolve_session_id("")


def test_create_instance_with_non_numeric_account(fake_module):
    result = create_xttrader_instance("ABC-001", mini_qmt_path=r"C:\qmt\userdata_mini")

    assert result["success"] is True
    assert result["session_id"] == resolve_session_id("ABC-001")

    instance = get_xttrader_instance()
    raw = instance.wrapped
    assert isinstance(raw, FakeTrader)
    assert raw.session_id == result["session_id"]
    assert raw.path == r"C:\qmt\userdata_mini"
    assert len(raw.callbacks) == 1
    assert isinstance(raw.callbacks[0], FakeCallback)


def test_create_instance_is_idempotent(fake_module):
    first = create_xttrader_instance("ABC-001", mini_qmt_path="C:/qmt")
    second = create_xttrader_instance("ABC-001", mini_qmt_path="C:/qmt")

    assert first["success"] is True
    assert second["success"] is True
    assert second["data"].startswith("交易实例已存在")
    assert first["session_id"] == second.get("session_id", first["session_id"])


def test_create_instance_rejects_non_stock_account(fake_module):
    result = create_xttrader_instance(
        "ABC-001", mini_qmt_path="C:/qmt", account_type="CREDIT"
    )

    assert result["success"] is False
    assert "普通股票账户" in result["error"]
    assert get_xttrader_instance() is None


def test_start_returns_real_failure(fake_module):
    create_xttrader_instance("ABC-001", mini_qmt_path="C:/qmt")
    raw = get_xttrader_instance().wrapped
    raw.raise_on_start = True

    result = execute_xttrader_method("start", [], {})

    assert result["success"] is False
    assert "start 失败" in result["error"]
    assert get_xttrader_state()["started"] is False


def test_start_is_idempotent_and_stateful(fake_module):
    create_xttrader_instance("ABC-001", mini_qmt_path="C:/qmt")
    raw = get_xttrader_instance().wrapped

    first = execute_xttrader_method("start", [], {})
    second = execute_xttrader_method("start", [], {})

    assert first["success"] is True
    assert first["already_started"] is False
    assert second["already_started"] is True
    assert raw.start_calls == 1
    assert get_xttrader_state()["started"] is True


def test_connect_reports_return_code(fake_module):
    create_xttrader_instance("ABC-001", mini_qmt_path="C:/qmt")
    raw = get_xttrader_instance().wrapped
    raw.connect_code = -1

    failed = execute_xttrader_method("connect", [], {})

    assert failed["success"] is False
    assert failed["data"] == -1
    assert "返回码" in failed["error"]
    assert get_xttrader_state()["connected"] is False

    raw.connect_code = 0
    ok = execute_xttrader_method("connect", [], {})

    assert ok["success"] is True
    assert ok["already_connected"] is False
    assert get_xttrader_state()["connected"] is True
    assert get_xttrader_state()["connect_code"] == 0

    again = execute_xttrader_method("connect", [], {})

    assert again["success"] is True
    assert again["already_connected"] is True
    assert raw.connect_calls == 2


def test_connect_exception_is_failure(fake_module):
    create_xttrader_instance("ABC-001", mini_qmt_path="C:/qmt")
    raw = get_xttrader_instance().wrapped
    raw.raise_on_connect = True

    result = execute_xttrader_method("connect", [], {})

    assert result["success"] is False
    assert "connect 失败" in result["error"]


def test_provider_has_no_three_arg_trader_dead_code():
    source = inspect.getsource(XtQuantProvider)

    assert "int(account))" not in source
    assert "def start_trader" not in source
    assert "def connect_trader" not in source
    assert "create_xttrader_instance" in source
