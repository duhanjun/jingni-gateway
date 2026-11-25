# -*- coding: utf-8 -*-
"""超时契约与 xtquant 请求体参数测试。

代码层待修项：
- GM 的 ``RpcExecuteRequest.timeout`` 曾是 ``Optional[int]``，传 null 会让
  future 永久等待；现在限定 1–600 且非空。
- xtquant RPC 请求体没有 ``args`` / ``timeout``，只接受 kwargs 且只能吃
  query 超时；现在补齐。
"""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import main as main_module
from config import config
from core.executor import API_MIN_TIMEOUT, MAX_TIMEOUT, normalize_timeout, run_module_call
from models.common import RpcExecuteRequest
from api.xtquant import XtQuantRpcExecuteRequest

HEADERS = {"X-API-Key": config.API_KEY}


@pytest.mark.parametrize("timeout", [None, 0, -1, 601, "abc"])
def test_rpc_execute_request_rejects_bad_timeout(timeout):
    with pytest.raises(ValidationError):
        RpcExecuteRequest(
            module="gmdata", function="get_cash", kwargs={}, timeout=timeout
        )


@pytest.mark.parametrize("timeout", [1, 30, 600])
def test_rpc_execute_request_accepts_valid_timeout(timeout):
    request = RpcExecuteRequest(
        module="gmdata", function="get_cash", kwargs={}, timeout=timeout
    )
    assert request.timeout == timeout


def test_rpc_execute_request_defaults_to_30():
    request = RpcExecuteRequest(module="gmdata", function="get_cash")
    assert request.timeout == 30


def test_xtquant_request_supports_args_and_optional_timeout():
    request = XtQuantRpcExecuteRequest(
        module="xtdata",
        function="get_full_kline",
        args=[["600000.SH"]],
        kwargs={},
        timeout=120,
    )
    assert request.args == [["600000.SH"]]
    assert request.timeout == 120

    default = XtQuantRpcExecuteRequest(module="xtdata", function="get_period_list")
    assert default.args == []
    assert default.timeout is None


@pytest.mark.parametrize("timeout", [0, 601, -5])
def test_xtquant_request_rejects_out_of_range_timeout(timeout):
    with pytest.raises(ValidationError):
        XtQuantRpcExecuteRequest(
            module="xtdata", function="get_period_list", timeout=timeout
        )


def test_normalize_timeout_none_becomes_default():
    assert normalize_timeout(None) == 30.0


def test_normalize_timeout_clamps_to_api_minimum():
    assert normalize_timeout(0, minimum=API_MIN_TIMEOUT) == API_MIN_TIMEOUT
    assert normalize_timeout(0.05) == 0.05


def test_normalize_timeout_clamps_to_maximum():
    assert normalize_timeout(10_000) == MAX_TIMEOUT


@pytest.mark.parametrize("value", ["abc", float("nan")])
def test_normalize_timeout_rejects_invalid(value):
    with pytest.raises(ValueError):
        normalize_timeout(value)


@pytest.mark.asyncio
async def test_run_module_call_none_timeout_does_not_hang():
    result = await run_module_call("xtdata", lambda: "ok", timeout=None)
    assert result == "ok"


@pytest.mark.asyncio
async def test_run_module_call_subsecond_timeout_still_works():
    started = time.monotonic()
    with pytest.raises(asyncio.TimeoutError):
        await run_module_call("xtdata", lambda: time.sleep(0.2), timeout=0.05)
    assert time.monotonic() - started < 0.5


def test_gm_api_rejects_null_timeout():
    client = TestClient(main_module.app)

    response = client.post(
        "/api/v1/gm/rpc/execute",
        headers=HEADERS,
        json={
            "module": "gmdata",
            "function": "get_cash",
            "kwargs": {},
            "timeout": None,
        },
    )

    assert response.status_code == 422


def test_gm_api_rejects_zero_timeout():
    client = TestClient(main_module.app)

    response = client.post(
        "/api/v1/gm/rpc/execute",
        headers=HEADERS,
        json={
            "module": "gmdata",
            "function": "get_cash",
            "kwargs": {},
            "timeout": 0,
        },
    )

    assert response.status_code == 422
