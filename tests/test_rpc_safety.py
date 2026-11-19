#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RPC 安全回归测试：阻塞函数、参数校验、超时不阻塞事件循环。"""

import asyncio
import time

import pytest

from core.executor import get_executor, run_module_call, shutdown_executors
from core.rpc import InvalidRpcArguments, validate_kwargs
from core.whitelist import BLOCKED_RPC_FUNCTIONS, RPC_WHITELIST, is_function_whitelisted


def test_lanes_are_isolated_but_tdx_is_single_serial():
    assert get_executor("xtdata", "data") is not get_executor("xtdata", "trade")
    # tqcenter 是进程级单客户端，data/trade 必须收敛到同一串行执行器
    assert get_executor("tdxquant", "data") is get_executor("tdxquant", "trade")


def test_blocked_functions_are_not_whitelisted():
    for module, function in BLOCKED_RPC_FUNCTIONS:
        assert function not in RPC_WHITELIST.get(module, []), f"{module}.{function} 不应在白名单中"
        assert is_function_whitelisted(module, function) is False


def test_known_blocking_functions_removed():
    assert "run" not in RPC_WHITELIST["xtdata"]
    assert "run_forever" not in RPC_WHITELIST["xttrader"]
    assert "run" not in RPC_WHITELIST["gmtrade"]


def test_validate_kwargs_rejects_unknown():
    def sample(a, b=2):
        return a + b

    with pytest.raises(InvalidRpcArguments) as exc:
        validate_kwargs(sample, {"a": 1, "c": 3})

    assert exc.value.unknown == ["c"]
    assert "未知参数" in str(exc.value)


def test_validate_kwargs_rejects_missing():
    def sample(a, b=2):
        return a + b

    with pytest.raises(InvalidRpcArguments) as exc:
        validate_kwargs(sample, {"b": 3})

    assert exc.value.missing == ["a"]
    assert "缺少必填参数" in str(exc.value)


def test_validate_kwargs_allows_var_keyword():
    def sample(a, **extra):
        return a, extra

    validate_kwargs(sample, {"a": 1, "anything": 2})


def test_validate_kwargs_ignores_uninspectable_callable():
    class NoSignature:
        @property
        def __signature__(self):
            raise ValueError("no signature available")

        def __call__(self, **kwargs):
            return kwargs

    # 没有可用签名时不应误报，交给底层自行报错
    validate_kwargs(NoSignature(), {"anything": 1})


@pytest.mark.asyncio
async def test_run_module_call_returns_value():
    result = await run_module_call("test_value", lambda x: x * 2, (21,), timeout=5)
    assert result == 42


@pytest.mark.asyncio
async def test_timeout_does_not_block_event_loop():
    started = time.monotonic()
    with pytest.raises(asyncio.TimeoutError):
        await run_module_call("test_timeout", time.sleep, (0.6,), timeout=0.05)
    elapsed = time.monotonic() - started

    # 超时后应立即返回，而不是等线程睡完
    assert elapsed < 0.4, f"超时未生效，耗时 {elapsed:.2f}s"


def teardown_module(module):
    shutdown_executors(wait=False)
