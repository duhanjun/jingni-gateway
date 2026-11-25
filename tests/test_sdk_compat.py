# -*- coding: utf-8 -*-
"""xtquant SDK 缺失函数兼容层测试（纯离线，不依赖真实 SDK）。

覆盖：
- 26 项缺口登记表完整性与唯一性；
- 可派生函数的实现语义（委托到当前 SDK 已有 API）；
- 不可派生函数保持 runtime_missing 且给出升级提示；
- 代理层“真实 API 优先、缺失才走兼容”；
- 能力矩阵中的 compat / counts / missing_sdk 输出。
"""

import pytest

from core import sdk_compat
from core.capabilities import build_capability_snapshot
from core.sdk_compat import (
    MISSING_SDK_FUNCTIONS,
    STRATEGY_DERIVED,
    STRATEGY_SDK_ABSENT,
    XtDataCompatModule,
    XtTraderCompat,
    compat_functions,
    describe_missing_sdk,
    is_compat_function,
    missing_entry,
    unwrap,
    wrap_trader,
    wrap_xtdata,
)
from core.whitelist import RPC_WHITELIST


def test_registry_declares_exactly_26_functions():
    assert len(MISSING_SDK_FUNCTIONS) == 26

    xtdata_entries = [e for e in MISSING_SDK_FUNCTIONS if e.module == "xtdata"]
    xttrader_entries = [e for e in MISSING_SDK_FUNCTIONS if e.module == "xttrader"]
    assert len(xtdata_entries) == 16
    assert len(xttrader_entries) == 10

    keys = [(e.module, e.function) for e in MISSING_SDK_FUNCTIONS]
    assert len(keys) == len(set(keys))


def test_registry_entries_are_declared_in_whitelist():
    for entry in MISSING_SDK_FUNCTIONS:
        assert entry.function in RPC_WHITELIST[entry.module], entry.function
        assert entry.reason, entry.function
        if entry.strategy == STRATEGY_DERIVED:
            assert entry.derivation
        else:
            assert entry.strategy == STRATEGY_SDK_ABSENT
            assert entry.derivation is None


def test_derived_and_absent_sets_are_disjoint_and_cover_all():
    derived = {e.function for e in MISSING_SDK_FUNCTIONS if e.strategy == STRATEGY_DERIVED}
    absent = {e.function for e in MISSING_SDK_FUNCTIONS if e.strategy == STRATEGY_SDK_ABSENT}
    blocked = {e.function for e in MISSING_SDK_FUNCTIONS if e.policy_blocked}

    assert derived.isdisjoint(absent)
    assert derived | absent == {e.function for e in MISSING_SDK_FUNCTIONS}
    assert len(derived) == 11
    assert len(absent) == 15
    assert len(blocked) == 7
    assert blocked <= absent


def test_describe_missing_sdk_groups_by_module():
    report = describe_missing_sdk()
    assert set(report) == {"xtdata", "xttrader"}
    assert len(report["xtdata"]) == 16
    assert len(report["xttrader"]) == 10

    for entry in report["xtdata"] + report["xttrader"]:
        assert entry["function"]
        assert entry["strategy"] in (STRATEGY_DERIVED, STRATEGY_SDK_ABSENT)
        if entry["strategy"] == STRATEGY_SDK_ABSENT and not entry["policy_blocked"]:
            assert "升级" in entry["upgrade_hint"]
        if entry["policy_blocked"]:
            assert entry["upgrade_hint"] is None


def test_policy_blocked_functions_never_auto_expose():
    from core.capabilities import evaluate_rpc

    for function in [
        "query_com_fund",
        "query_com_position",
        "query_bank_info",
        "query_bank_amount",
        "query_bank_transfer_stream",
        "smt_query_quoter",
        "smt_query_compact",
    ]:
        status, reason = evaluate_rpc(
            "xtquant", "xttrader", function, probe=lambda _fn: True
        )
        assert status == "unsupported", function
        assert "即使 SDK 恢复也不会开放" in reason


@pytest.mark.parametrize("module", ["xtdata", "xttrader"])
def test_compat_functions_match_derived_entries(module):
    names = set(compat_functions(module))
    derived = {
        e.function for e in MISSING_SDK_FUNCTIONS
        if e.module == module and e.strategy == STRATEGY_DERIVED
    }
    assert names == derived

    for name in names:
        assert is_compat_function(module, name) is True


def test_is_compat_function_rejects_unknown():
    assert is_compat_function("xtdata", "get_market_data") is False
    assert is_compat_function("gmdata", "get_full_kline") is False
    assert missing_entry("xtdata", "get_market_data") is None


class FakeXtData:
    """只实现兼容层依赖的当前 SDK API。"""

    def __init__(self):
        self.calls = []
        self.sectors = {"我的板块": ["600000.SH", "000001.SZ"]}

    def get_market_data_ex(self, **kwargs):
        self.calls.append(("get_market_data_ex", kwargs))
        return {"600000.SH": {"close": [10.0]}}

    def get_holidays(self):
        self.calls.append(("get_holidays", {}))
        return ["20260101"]

    def get_trade_times(self, stock_code):
        self.calls.append(("get_trade_times", {"stock_code": stock_code}))
        return [["09:30", "11:30"], ["13:00", "15:00"]]

    def init_data_dir(self):
        self.calls.append(("init_data_dir", {}))
        return "/qmt/datadir"

    def add_sector(self, sector_name, stock_list):
        self.calls.append(("add_sector", {"name": sector_name, "stocks": list(stock_list)}))
        self.sectors[sector_name] = list(stock_list)
        return len(stock_list)

    def remove_sector(self, sector_name):
        self.calls.append(("remove_sector", {"name": sector_name}))
        self.sectors.pop(sector_name, None)

    def get_stock_list_in_sector(self, sector_name):
        self.calls.append(("get_stock_list_in_sector", {"name": sector_name}))
        return list(self.sectors.get(sector_name, []))


def test_get_full_kline_forces_full_history_and_delegates():
    xt = FakeXtData()
    proxy = wrap_xtdata(xt)

    result = proxy.get_full_kline(stock_list=["600000.SH"], period="1d")

    assert result == {"600000.SH": {"close": [10.0]}}
    call = xt.calls[0]
    assert call[0] == "get_market_data_ex"
    assert call[1]["stock_list"] == ["600000.SH"]
    assert call[1]["count"] == -1
    assert call[1]["dividend_type"] == "none"


def test_trading_time_is_aliased_to_get_trade_times():
    xt = FakeXtData()
    proxy = wrap_xtdata(xt)

    result = proxy.get_trading_time(stock_code="600000.SH")

    assert result == [["09:30", "11:30"], ["13:00", "15:00"]]
    assert xt.calls[0] == ("get_trade_times", {"stock_code": "600000.SH"})


def test_period_list_and_data_dir_are_derived():
    xt = FakeXtData()
    proxy = wrap_xtdata(xt)

    assert proxy.get_period_list() == [
        "tick", "1m", "5m", "15m", "30m", "1h", "1d", "1w", "1M",
    ]
    assert proxy.get_data_dir() == "/qmt/datadir"
    assert ("init_data_dir", {}) in xt.calls


def test_download_holiday_data_delegates_to_get_holidays():
    xt = FakeXtData()
    proxy = wrap_xtdata(xt)

    assert proxy.download_holiday_data() == ["20260101"]
    assert xt.calls[-1][0] == "get_holidays"


def test_sector_operations_are_derived():
    xt = FakeXtData()
    proxy = wrap_xtdata(xt)

    assert proxy.create_sector_folder(folder_name="我的板块") == {
        "folder": "我的板块", "created": True,
    }

    proxy.create_sector(sector_name="我的板块", stock_list=["600000.SH"])
    assert xt.sectors["我的板块"] == ["600000.SH"]

    removed = proxy.remove_stock_from_sector(
        sector_name="我的板块", stock_list=["600000.SH"]
    )
    assert removed == {"sector_name": "我的板块", "removed": 1, "remaining": 0}

    reset = proxy.reset_sector(sector_name="我的板块", stock_list=["000001.SZ"])
    assert reset == {"sector_name": "我的板块", "members": 1}
    assert xt.sectors["我的板块"] == ["000001.SZ"]


def test_create_sector_folder_validates_name():
    with pytest.raises(ValueError):
        sdk_compat.compat_create_sector_folder(None, "")
    with pytest.raises(ValueError):
        sdk_compat.compat_create_sector_folder(None, "a/b")


class FakeTrader:
    def __init__(self):
        self.positions = [
            {"stock_code": "600000.SH", "volume": 100, "open_price": 10.0,
             "market_value": 1010.0},
            {"stock_code": "000001.SZ", "volume": 200, "open_price": 5.0,
             "market_value": 1020.0},
        ]
        self.accounts = [
            {"account_id": "11048389", "account_type": "STOCK"},
            {"account_id": "99999999", "account_type": "STOCK"},
        ]

    def query_stock_positions(self, account=None):
        return list(self.positions)

    def query_account_infos(self):
        return list(self.accounts)


def test_position_statistics_aggregates_positions():
    trader = FakeTrader()
    proxy = wrap_trader(trader)

    stats = proxy.query_position_statistics()

    assert stats["position_count"] == 2
    assert stats["total_volume"] == 300
    assert stats["total_cost"] == pytest.approx(100 * 10.0 + 200 * 5.0)
    assert stats["total_market_value"] == pytest.approx(2030.0)
    assert stats["symbols"] == ["600000.SH", "000001.SZ"]


def test_query_secu_account_filters_by_account():
    trader = FakeTrader()
    proxy = wrap_trader(trader)

    rows = proxy.query_secu_account(account="11048389")

    assert rows == [{"account_id": "11048389", "account_type": "STOCK"}]


def test_proxy_prefers_real_api_over_compat():
    class RealFirst(FakeXtData):
        def get_period_list(self):
            return ["real"]

    proxy = wrap_xtdata(RealFirst())
    assert proxy.get_period_list() == ["real"]
    assert isinstance(proxy, XtDataCompatModule)


def test_proxy_dir_contains_compat_names():
    proxy = wrap_xtdata(FakeXtData())
    assert "get_full_kline" in dir(proxy)
    assert "get_market_data_ex" in dir(proxy)


def test_wrap_is_idempotent_and_can_be_disabled():
    raw = FakeXtData()
    assert wrap_xtdata(None) is None
    assert wrap_xtdata(raw, enabled=False) is raw

    wrapped = wrap_xtdata(raw)
    assert wrap_xtdata(wrapped) is wrapped
    assert unwrap(wrapped) is raw
    assert unwrap(raw) is raw


def test_trader_proxy_prefers_real_api():
    class RealTrader(FakeTrader):
        def query_position_statistics(self, account=None):
            return {"real": True}

    proxy = wrap_trader(RealTrader())
    assert proxy.query_position_statistics() == {"real": True}
    assert isinstance(proxy, XtTraderCompat)


def test_capability_snapshot_exposes_compat_and_missing_sdk():
    proxy = wrap_xtdata(FakeXtData())

    def trader_probe(function):
        if function in ("create_trader", "start", "connect"):
            return True
        return is_compat_function("xttrader", function)

    snapshot = build_capability_snapshot(
        "xtquant",
        module_refs={"xtdata": proxy},
        probes={"xttrader": trader_probe},
        runtime_available=True,
    )

    assert snapshot["rpc"]["counts"]["xtdata"]["declared"] == 48
    assert snapshot["rpc"]["counts"]["xtdata"]["compat"] == 9
    assert set(snapshot["rpc"]["compat"]["xtdata"]) == set(compat_functions("xtdata"))
    assert set(snapshot["rpc"]["compat"]["xttrader"]) == {"query_position_statistics", "query_secu_account"}

    assert len(snapshot["missing_sdk"]["xtdata"]) == 16
    assert len(snapshot["missing_sdk"]["xttrader"]) == 10

    unsupported = {
        item["function"]: item for item in snapshot["rpc"]["unsupported"]["xtdata"]
    }
    assert unsupported["subscribe_formula"]["status"] == "runtime_missing"
    assert "升级" in unsupported["subscribe_formula"]["reason"]


def test_compat_marker_disappears_when_sdk_restores_api():
    class Restored(FakeXtData):
        def get_period_list(self):
            return ["real"]

    proxy = wrap_xtdata(Restored())
    snapshot = build_capability_snapshot(
        "xtquant", module_refs={"xtdata": proxy}, runtime_available=True
    )

    assert proxy.get_period_list() == ["real"]
    assert "get_period_list" not in snapshot["rpc"]["compat"]["xtdata"]
    assert "get_full_kline" in snapshot["rpc"]["compat"]["xtdata"]


def test_compat_disabled_keeps_functions_runtime_missing():
    raw = FakeXtData()
    snapshot = build_capability_snapshot(
        "xtquant", module_refs={"xtdata": raw}, runtime_available=True
    )

    assert snapshot["rpc"]["compat"] == {}
    unsupported = {
        item["function"]: item for item in snapshot["rpc"]["unsupported"]["xtdata"]
    }
    assert unsupported["get_full_kline"]["status"] == "runtime_missing"
    assert "get_market_data_ex" in unsupported["get_full_kline"]["reason"]


def test_http_rpc_exposes_compat_functions():
    """HTTP /rpc/methods 与 /rpc/execute 都能看到并使用兼容实现。"""
    from fastapi.testclient import TestClient

    import api.xtquant as xt_api
    import main as main_module
    from config import config

    class FakeProvider:
        is_available = True
        is_initialized = True

        def __init__(self, ref):
            self._ref = ref

        def get_module_reference(self, module):
            return self._ref if module == "xtdata" else None

    proxy = wrap_xtdata(FakeXtData())
    xt_api.set_xtquant_provider(FakeProvider(proxy))
    headers = {"X-API-Key": config.API_KEY}
    client = TestClient(main_module.app)

    try:
        methods = client.get(
            "/api/v1/xtquant/rpc/methods", headers=headers
        ).json()
        names = {m["function"] for m in methods["methods"]}
        assert "get_period_list" in names
        assert "get_full_kline" in names

        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            headers=headers,
            json={"module": "xtdata", "function": "get_period_list"},
        ).json()
        assert response["success"] is True
        assert response["data"] == [
            "tick", "1m", "5m", "15m", "30m", "1h", "1d", "1w", "1M",
        ]

        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            headers=headers,
            json={
                "module": "xtdata",
                "function": "get_trading_time",
                "args": ["600000.SH"],
            },
        ).json()
        assert response["success"] is True
        assert proxy.wrapped.calls[-1] == (
            "get_trade_times", {"stock_code": "600000.SH"}
        )

        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            headers=headers,
            json={
                "module": "xtdata",
                "function": "get_full_kline",
                "kwargs": {"stock_list": ["600000.SH"], "period": "1d"},
            },
        ).json()
        assert response["success"] is True
        assert response["data"] == {"600000.SH": {"close": [10.0]}}
        assert proxy.wrapped.calls[-1][1]["stock_list"] == ["600000.SH"]
        assert proxy.wrapped.calls[-1][1]["count"] == -1
    finally:
        xt_api.set_xtquant_provider(None)
