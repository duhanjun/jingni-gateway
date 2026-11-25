# -*- coding: utf-8 -*-
"""XtQuant 撤单终态对账测试（fake xttrader，不依赖真实 SDK）。"""

import asyncio
from types import SimpleNamespace

import pytest

import core.xt_trade as xt_trade
from core.xt_trade import (
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_JUNK,
    ORDER_STATUS_PART_CANCEL,
    ORDER_STATUS_REPORTED,
    ORDER_STATUS_SUCCEEDED,
    XtConfigError,
    XtTradeService,
)


def _service(account="11048389"):
    cfg = SimpleNamespace(
        ACCOUNT_ID=account,
        CONNECT_TIMEOUT=5,
        XT_CANCEL_RECONCILE_TIMEOUT=0.15,
        XT_CANCEL_POLL_INTERVAL=0.01,
    )
    provider = SimpleNamespace(_config=cfg)
    return XtTradeService(provider, cfg)


def _patch_calls(monkeypatch, statuses, cancel_data=0, cancel_success=True):
    """statuses 为每次 query 返回的 order_status；用完后重复最后一个。"""
    calls = {"cancel": 0, "query": 0}
    state = {"statuses": list(statuses)}

    def fake(function, args, kwargs):
        if function == "cancel_order_stock":
            calls["cancel"] += 1
            return {"success": cancel_success, "data": cancel_data}
        if function == "query_stock_orders":
            calls["query"] += 1
            if not state["statuses"]:
                return {"success": True, "data": []}
            index = min(calls["query"] - 1, len(state["statuses"]) - 1)
            return {
                "success": True,
                "data": [{"order_id": 12345, "order_status": state["statuses"][index]}],
            }
        return {"success": False, "error": "unknown"}

    monkeypatch.setattr(xt_trade, "execute_xttrader_method", fake)
    return calls


@pytest.mark.parametrize(
    "terminal_status", [ORDER_STATUS_CANCELED, ORDER_STATUS_PART_CANCEL, ORDER_STATUS_JUNK]
)
def test_cancel_confirms_terminal_status(monkeypatch, terminal_status):
    calls = _patch_calls(monkeypatch, [ORDER_STATUS_REPORTED, terminal_status])
    service = _service()

    result = asyncio.run(service.cancel_order(12345))

    assert result["success"] is True
    assert result["cancel_state"] == "confirmed"
    assert result["status"] == terminal_status
    assert result["request_accepted"] is True
    assert calls["cancel"] == 1
    assert calls["query"] >= 2


def test_cancel_pending_when_status_never_terminal(monkeypatch):
    _patch_calls(monkeypatch, [ORDER_STATUS_REPORTED])
    service = _service()

    result = asyncio.run(service.cancel_order(12345))

    assert result["success"] is False
    assert result["cancel_state"] == "pending"
    assert result["status"] == ORDER_STATUS_REPORTED
    assert result["error"] == "CANCEL_NOT_CONFIRMED"


def test_cancel_failed_when_order_already_filled(monkeypatch):
    _patch_calls(monkeypatch, [ORDER_STATUS_SUCCEEDED])
    service = _service()

    result = asyncio.run(service.cancel_order(12345))

    assert result["success"] is False
    assert result["cancel_state"] == "failed"
    assert result["error"] == "ORDER_ALREADY_FILLED"


def test_cancel_unknown_when_order_disappears(monkeypatch):
    _patch_calls(monkeypatch, [])
    service = _service()

    result = asyncio.run(service.cancel_order(12345))

    assert result["success"] is False
    assert result["cancel_state"] == "unknown"
    assert result["status"] is None
    assert result["error"] == "ORDER_NOT_FOUND"


def test_cancel_terminal_wins_even_if_submission_rejected(monkeypatch):
    _patch_calls(
        monkeypatch,
        [ORDER_STATUS_CANCELED],
        cancel_data=-1,
        cancel_success=False,
    )
    service = _service()

    result = asyncio.run(service.cancel_order(12345))

    assert result["cancel_state"] == "confirmed"
    assert result["success"] is True
    assert result["request_accepted"] is False


def test_cancel_requires_account():
    service = _service(account="")
    with pytest.raises(XtConfigError):
        asyncio.run(service.cancel_order(12345))
