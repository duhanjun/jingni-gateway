# -*- coding: utf-8 -*-
"""GM RPC 异常归一化测试。"""

import asyncio

import api.gm as gm_api


class FakeModule:
    def get_version(self):
        raise ValueError("sdk boom")


class FakeProvider:
    is_available = True

    def get_module_reference(self, module):
        return FakeModule()


def test_sdk_exception_returns_gm_sdk_error(monkeypatch):
    monkeypatch.setattr(gm_api, "get_gm_provider", lambda: FakeProvider())

    result = asyncio.run(gm_api._execute_gm_rpc_call("gmdata", "get_version", [], {}, 10))

    assert result["success"] is False
    assert result["error_code"] == "GM_SDK_ERROR"
    assert result["exception_type"] == "ValueError"
    assert "ValueError: sdk boom" in result["error"]
