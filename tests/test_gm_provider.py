# -*- coding: utf-8 -*-
"""GMProvider 初始化参数回归测试。"""

import sys
import types
from types import SimpleNamespace

from providers.gm_provider import GMProvider


def test_gm_provider_does_not_call_set_account_id(monkeypatch):
    called = []

    fake_api = types.ModuleType("gm.api")
    fake_api.set_token = lambda token: None
    fake_api.set_account_id = lambda account_id: called.append(account_id)

    fake_pkg = types.ModuleType("gm")
    fake_pkg.__path__ = []
    fake_pkg.api = fake_api

    monkeypatch.setitem(sys.modules, "gm", fake_pkg)
    monkeypatch.setitem(sys.modules, "gm.api", fake_api)

    config = SimpleNamespace(
        GM=SimpleNamespace(token="test-token", account_id="test-account", mode=None)
    )
    provider = GMProvider(config)

    assert provider.initialize() is True
    assert called == []
