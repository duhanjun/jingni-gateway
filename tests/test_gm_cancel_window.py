# -*- coding: utf-8 -*-
"""GM 撤单对账窗口与北交所代码测试（不依赖真实 gm SDK）。"""

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from api.gm import GMOrderRequest
from core.gm_trade import GMTradeService


class FakeGM:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.query_count = 0
        self.calls = []
        self.cancel_result = True

    def get_orders(self, **kwargs):
        self.query_count += 1
        if not self.statuses:
            return []
        index = min(self.query_count - 1, len(self.statuses) - 1)
        return [{
            "order_id": "gm-order-1",
            "cl_ord_id": "gm-clord-1",
            "status": self.statuses[index],
        }]

    def order_cancel(self, **kwargs):
        self.calls.append(("order_cancel", kwargs))
        return self.cancel_result


def _service(statuses, timeout=0.5, interval=0.05, max_interval=0.2):
    cfg = SimpleNamespace(
        GM=SimpleNamespace(
            account_id="gm-account",
            token="test-token",
            cancel_reconcile_timeout=timeout,
            cancel_poll_interval=interval,
            cancel_poll_max_interval=max_interval,
        ),
        CONNECT_TIMEOUT=5,
    )
    api = FakeGM(statuses)
    return GMTradeService(api, cfg), api


def test_late_terminal_state_is_confirmed_not_failed():
    service, api = _service([1, 1, 1, 1, 5], timeout=0.6, interval=0.05)

    result = asyncio.run(service.cancel_order("gm-order-1"))

    assert result["success"] is True
    assert result["cancel_state"] == "confirmed"
    assert result["status"] == 5
    assert result["polls"] >= 4
    assert result["waited_ms"] >= 200


def test_cancel_timeout_reports_failed_after_deadline():
    service, api = _service([1], timeout=0.3, interval=0.05)

    result = asyncio.run(service.cancel_order("gm-order-1"))

    assert result["success"] is False
    assert result["cancel_state"] == "failed"
    assert result["error"] == "CANCEL_NOT_CONFIRMED"
    assert result["polls"] >= 1


def test_cancel_state_true_but_request_rejected_is_not_success():
    service, api = _service([5], timeout=0.2, interval=0.05)
    api.cancel_result = False

    result = asyncio.run(service.cancel_order("gm-order-1"))

    assert result["cancel_state"] == "confirmed"
    assert result["success"] is False
    assert result["request_accepted"] is False


def test_cancel_none_return_is_treated_as_accepted():
    service, api = _service([5], timeout=0.2, interval=0.05)
    api.cancel_result = None

    result = asyncio.run(service.cancel_order("gm-order-1"))

    assert result["cancel_state"] == "confirmed"
    assert result["success"] is True
    assert result["request_accepted"] is True


@pytest.mark.parametrize(
    "symbol", ["SHSE.600000", "SZSE.000001", "BJSE.920001"]
)
def test_gm_order_accepts_all_three_exchanges(symbol):
    request = GMOrderRequest(
        symbol=symbol, volume=100, side=0, order_type=0, price=10.0
    )
    assert request.symbol == symbol


@pytest.mark.parametrize(
    "symbol", ["BJSE.92001", "SHSE.6000000", "BSE.920001", "600000.SH"]
)
def test_gm_order_rejects_invalid_symbols(symbol):
    with pytest.raises(ValidationError):
        GMOrderRequest(symbol=symbol, volume=100, side=0, order_type=0, price=10.0)
