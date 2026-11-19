# -*- coding: utf-8 -*-
"""gmtrade sidecar 代理的映射与可用性测试（不启动真实 sidecar）。"""

from core.gmtrade_proxy import GMTradeProxy


def test_proxy_method_mapping(monkeypatch):
    proxy = GMTradeProxy(
        python_path="python.exe",
        bridge_script="bridge.py",
        token="token",
        account_id="account",
    )
    calls = []

    def fake_request(action, params):
        calls.append((action, params))
        return {"ok": True}

    monkeypatch.setattr(proxy, "_request", fake_request)

    proxy.get_cash(account_id="acc")
    proxy.get_position(account_id="acc")
    proxy.get_orders()
    proxy.order_volume(symbol="SHSE.600000", volume=100, side=1)
    proxy.order_cancel(cl_ord_id="cl-1", account_id="acc")

    assert calls[0] == ("cash", {"account_id": "acc"})
    assert calls[1] == ("positions", {"account_id": "acc"})
    assert calls[2] == ("orders", {})
    assert calls[3][0] == "place"
    assert calls[3][1]["symbol"] == "SHSE.600000"
    assert calls[4][0] == "cancel"
    assert calls[4][1]["cl_ord_id"] == "cl-1"


def test_proxy_unavailable_when_paths_missing():
    proxy = GMTradeProxy(
        python_path="Z:\\missing\\python.exe",
        bridge_script="Z:\\missing\\bridge.py",
        token="token",
        account_id="account",
    )
    assert proxy.available is False
