#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JingNiGateway GM (掘金量化) 数据接口测试
测试所有 GM gmdata 模块数据接口

重要说明：
- 本测试文件模拟远程客户端，通过 HTTP RPC 调用测试服务端功能
- 不直接使用本地 gm 模块
- 所有操作都通过 /api/v1/gm/rpc/execute 端点完成
- 测试标的：比亚迪 (SZSE.002594)
"""

import pytest
from fastapi.testclient import TestClient
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from tests.test_config import (
    TEST_HEADERS,
    TEST_GM_SYMBOL,
    _print_result,
    print_test_header,
    print_data_summary
)

client = TestClient(app)

BYD_SYMBOL = TEST_GM_SYMBOL
TODAY = datetime.now().strftime("%Y-%m-%d")
YEAR_START = "2026-01-01"


def call_gm_rpc(function: str, kwargs: dict):
    """Call GM RPC function."""
    response = client.post(
        "/api/v1/gm/rpc/execute",
        json={
            "module": "gmdata",
            "function": function,
            "kwargs": kwargs
        },
        headers=TEST_HEADERS
    )
    return response.json()


class TestGMBasicInfo:
    """GM 基础信息接口测试"""

    def test_get_version(self):
        """测试获取版本信息"""
        print_test_header("test_get_version", "测试获取 GM SDK 版本", "test_gm_data.py")

        data = call_gm_rpc("get_version", {})
        assert "success" in data

        if data.get("success"):
            print_data_summary("GM SDK 版本", data.get("data"))
            _print_result("获取版本信息", True, f"版本: {data.get('data')}", test_file="test_gm_data.py")
        else:
            _print_result("获取版本信息", False, data.get("error", "Unknown error"), test_file="test_gm_data.py")

    def test_get_symbol_infos(self):
        """测试获取标的基本信息"""
        print_test_header("test_get_symbol_infos", "测试获取标的基本信息", "test_gm_data.py")

        data = call_gm_rpc("get_symbol_infos", {
            "sec_type1": 1010,
            "symbols": BYD_SYMBOL,
            "df": True
        })
        assert "success" in data

        if data.get("success"):
            print_data_summary(f"标的基本信息 - {BYD_SYMBOL}", data.get("data"))
            _print_result("获取标的基本信息", True, f"标的: {BYD_SYMBOL}", test_file="test_gm_data.py")
        else:
            error = data.get("error", "")
            if error in ["permission_denied", "service_not_supported"]:
                _print_result("获取标的基本信息", True, f"跳过: {error}", test_file="test_gm_data.py")
            else:
                _print_result("获取标的基本信息", False, error, test_file="test_gm_data.py")

    def test_get_instruments(self):
        """测试获取交易标的信息"""
        print_test_header("test_get_instruments", "测试获取交易标的信息", "test_gm_data.py")

        data = call_gm_rpc("get_instruments", {
            "symbols": BYD_SYMBOL,
            "df": True
        })
        assert "success" in data

        if data.get("success"):
            print_data_summary(f"交易标的信息 - {BYD_SYMBOL}", data.get("data"))
            _print_result("获取交易标的信息", True, f"标的: {BYD_SYMBOL}", test_file="test_gm_data.py")
        else:
            error = data.get("error", "")
            if error in ["permission_denied", "service_not_supported"]:
                _print_result("获取交易标的信息", True, f"跳过: {error}", test_file="test_gm_data.py")
            else:
                _print_result("获取交易标的信息", False, error, test_file="test_gm_data.py")


class TestGMMarketData:
    """GM 行情数据接口测试"""

    def test_history_n(self):
        """测试获取历史行情 (history_n)"""
        print_test_header("test_history_n", "测试获取历史行情 (history_n)", "test_gm_data.py")

        data = call_gm_rpc("history_n", {
            "symbol": BYD_SYMBOL,
            "frequency": "1d",
            "count": 10,
            "end_time": TODAY,
            "df": True
        })
        assert "success" in data

        if data.get("success"):
            print_data_summary(f"历史行情 (最近10天) - {BYD_SYMBOL}", data.get("data"))
            _print_result("获取历史行情 (history_n)", True, f"标的: {BYD_SYMBOL}, 周期: 1d", test_file="test_gm_data.py")
        else:
            error = data.get("error", "")
            if error in ["permission_denied", "service_not_supported"]:
                _print_result("获取历史行情 (history_n)", True, f"跳过: {error}", test_file="test_gm_data.py")
            else:
                _print_result("获取历史行情 (history_n)", False, error, test_file="test_gm_data.py")

    def test_history(self):
        """测试获取历史行情 (history)"""
        print_test_header("test_history", "测试获取历史行情 (history)", "test_gm_data.py")

        data = call_gm_rpc("history", {
            "symbol": BYD_SYMBOL,
            "frequency": "1d",
            "start_time": YEAR_START,
            "end_time": TODAY,
            "df": True
        })
        assert "success" in data

        if data.get("success"):
            print_data_summary(f"历史行情 (2026年) - {BYD_SYMBOL}", data.get("data"))
            _print_result("获取历史行情 (history)", True, f"标的: {BYD_SYMBOL}", test_file="test_gm_data.py")
        else:
            error = data.get("error", "")
            if error in ["permission_denied", "service_not_supported"]:
                _print_result("获取历史行情 (history)", True, f"跳过: {error}", test_file="test_gm_data.py")
            else:
                _print_result("获取历史行情 (history)", False, error, test_file="test_gm_data.py")

    def test_last_tick(self):
        """测试获取最新 Tick"""
        print_test_header("test_last_tick", "测试获取最新 Tick", "test_gm_data.py")

        data = call_gm_rpc("last_tick", {
            "symbols": BYD_SYMBOL
        })
        assert "success" in data

        if data.get("success"):
            print_data_summary(f"最新 Tick - {BYD_SYMBOL}", data.get("data"))
            _print_result("获取最新 Tick", True, f"标的: {BYD_SYMBOL}", test_file="test_gm_data.py")
        else:
            error = data.get("error", "")
            if error in ["permission_denied", "service_not_supported", "mode_not_supported"]:
                _print_result("获取最新 Tick", True, f"跳过: {error}", test_file="test_gm_data.py")
            else:
                _print_result("获取最新 Tick", False, error, test_file="test_gm_data.py")

    def test_current_price(self):
        """测试获取当前价格"""
        print_test_header("test_current_price", "测试获取当前价格", "test_gm_data.py")

        data = call_gm_rpc("current_price", {
            "symbols": BYD_SYMBOL
        })
        assert "success" in data

        if data.get("success"):
            print_data_summary(f"当前价格 - {BYD_SYMBOL}", data.get("data"))
            _print_result("获取当前价格", True, f"标的: {BYD_SYMBOL}", test_file="test_gm_data.py")
        else:
            error = data.get("error", "")
            if error in ["permission_denied", "service_not_supported", "mode_not_supported"]:
                _print_result("获取当前价格", True, f"跳过: {error}", test_file="test_gm_data.py")
            else:
                _print_result("获取当前价格", False, error, test_file="test_gm_data.py")

    def test_current(self):
        """测试获取当前行情快照"""
        print_test_header("test_current", "测试获取当前行情快照", "test_gm_data.py")

        data = call_gm_rpc("current", {
            "symbols": BYD_SYMBOL
        })
        assert "success" in data

        if data.get("success"):
            print_data_summary(f"当前行情快照 - {BYD_SYMBOL}", data.get("data"))
            _print_result("获取当前行情快照", True, f"标的: {BYD_SYMBOL}", test_file="test_gm_data.py")
        else:
            error = data.get("error", "")
            if error in ["permission_denied", "service_not_supported", "mode_not_supported"]:
                _print_result("获取当前行情快照", True, f"跳过: {error}", test_file="test_gm_data.py")
            else:
                _print_result("获取当前行情快照", False, error, test_file="test_gm_data.py")


class TestGMTradingCalendar:
    """GM 交易日历接口测试"""

    def test_get_trading_dates_by_year(self):
        """测试获取年度交易日历"""
        print_test_header("test_get_trading_dates_by_year", "测试获取年度交易日历", "test_gm_data.py")

        data = call_gm_rpc("get_trading_dates_by_year", {
            "exchange": "SZSE",
            "start_year": 2026,
            "end_year": 2026
        })
        assert "success" in data

        if data.get("success"):
            print_data_summary("2026年交易日历 - SZSE", data.get("data"))
            _print_result("获取年度交易日历", True, "交易所: SZSE, 年份: 2026", test_file="test_gm_data.py")
        else:
            error = data.get("error", "")
            if error in ["permission_denied", "service_not_supported"]:
                _print_result("获取年度交易日历", True, f"跳过: {error}", test_file="test_gm_data.py")
            else:
                _print_result("获取年度交易日历", False, error, test_file="test_gm_data.py")

    def test_get_trading_dates(self):
        """测试获取交易日历"""
        print_test_header("test_get_trading_dates", "测试获取交易日历", "test_gm_data.py")

        data = call_gm_rpc("get_trading_dates", {
            "exchange": "SZSE",
            "start_date": YEAR_START,
            "end_date": TODAY
        })
        assert "success" in data

        if data.get("success"):
            print_data_summary("交易日历 - SZSE (2026)", data.get("data"))
            _print_result("获取交易日历", True, "交易所: SZSE", test_file="test_gm_data.py")
        else:
            error = data.get("error", "")
            if error in ["permission_denied", "service_not_supported"]:
                _print_result("获取交易日历", True, f"跳过: {error}", test_file="test_gm_data.py")
            else:
                _print_result("获取交易日历", False, error, test_file="test_gm_data.py")


class TestGMFinancialData:
    """GM 财务数据接口测试"""

    def test_stk_get_fundamentals_income_pt(self):
        """测试获取利润表截面数据"""
        print_test_header("test_stk_get_fundamentals_income_pt", "测试获取利润表截面数据", "test_gm_data.py")

        data = call_gm_rpc("stk_get_fundamentals_income_pt", {
            "symbols": BYD_SYMBOL,
            "fields": "ttl_inc_oper,inc_oper,net_prof,oper_prof",
            "date": TODAY,
            "df": True
        })
        assert "success" in data

        if data.get("success"):
            print_data_summary(f"利润表截面数据 - {BYD_SYMBOL}", data.get("data"))
            _print_result("获取利润表截面数据", True, f"标的: {BYD_SYMBOL}", test_file="test_gm_data.py")
        else:
            error = data.get("error", "")
            if error in ["permission_denied", "service_not_supported"]:
                _print_result("获取利润表截面数据", True, f"跳过: {error}", test_file="test_gm_data.py")
            else:
                _print_result("获取利润表截面数据", False, error, test_file="test_gm_data.py")

    def test_stk_get_fundamentals_balance_pt(self):
        """测试获取资产负债表截面数据"""
        print_test_header("test_stk_get_fundamentals_balance_pt", "测试获取资产负债表截面数据", "test_gm_data.py")

        data = call_gm_rpc("stk_get_fundamentals_balance_pt", {
            "symbols": BYD_SYMBOL,
            "fields": "ttl_ast,ttl_liab,ttl_eqy,mny_cptl",
            "date": TODAY,
            "df": True
        })
        assert "success" in data

        if data.get("success"):
            print_data_summary(f"资产负债表截面数据 - {BYD_SYMBOL}", data.get("data"))
            _print_result("获取资产负债表截面数据", True, f"标的: {BYD_SYMBOL}", test_file="test_gm_data.py")
        else:
            error = data.get("error", "")
            if error in ["permission_denied", "service_not_supported"]:
                _print_result("获取资产负债表截面数据", True, f"跳过: {error}", test_file="test_gm_data.py")
            else:
                _print_result("获取资产负债表截面数据", False, error, test_file="test_gm_data.py")

    def test_stk_get_fundamentals_cashflow_pt(self):
        """测试获取现金流量表截面数据"""
        print_test_header("test_stk_get_fundamentals_cashflow_pt", "测试获取现金流量表截面数据", "test_gm_data.py")

        data = call_gm_rpc("stk_get_fundamentals_cashflow_pt", {
            "symbols": BYD_SYMBOL,
            "fields": "net_cf_oper,net_cf_inv,net_cf_fin",
            "date": TODAY,
            "df": True
        })
        assert "success" in data

        if data.get("success"):
            print_data_summary(f"现金流量表截面数据 - {BYD_SYMBOL}", data.get("data"))
            _print_result("获取现金流量表截面数据", True, f"标的: {BYD_SYMBOL}", test_file="test_gm_data.py")
        else:
            error = data.get("error", "")
            if error in ["permission_denied", "service_not_supported"]:
                _print_result("获取现金流量表截面数据", True, f"跳过: {error}", test_file="test_gm_data.py")
            else:
                _print_result("获取现金流量表截面数据", False, error, test_file="test_gm_data.py")

    def test_stk_get_finance_prime_pt(self):
        """测试获取主要财务指标"""
        print_test_header("test_stk_get_finance_prime_pt", "测试获取主要财务指标", "test_gm_data.py")

        data = call_gm_rpc("stk_get_finance_prime_pt", {
            "symbols": BYD_SYMBOL,
            "fields": "roe,eps_basic",
            "date": TODAY,
            "df": True
        })
        assert "success" in data

        if data.get("success"):
            print_data_summary(f"主要财务指标 - {BYD_SYMBOL}", data.get("data"))
            _print_result("获取主要财务指标", True, f"标的: {BYD_SYMBOL}", test_file="test_gm_data.py")
        else:
            error = data.get("error", "")
            if error in ["permission_denied", "service_not_supported"]:
                _print_result("获取主要财务指标", True, f"跳过: {error}", test_file="test_gm_data.py")
            else:
                _print_result("获取主要财务指标", False, error, test_file="test_gm_data.py")


class TestGMDailyData:
    """GM 每日数据接口测试"""

    def test_stk_get_daily_basic_pt(self):
        """测试获取每日基本面数据"""
        print_test_header("test_stk_get_daily_basic_pt", "测试获取每日基本面数据", "test_gm_data.py")

        data = call_gm_rpc("stk_get_daily_basic_pt", {
            "symbols": BYD_SYMBOL,
            "fields": "a_shr_unl",
            "trade_date": TODAY,
            "df": True
        })
        assert "success" in data

        if data.get("success"):
            print_data_summary(f"每日基本面数据 - {BYD_SYMBOL}", data.get("data"))
            _print_result("获取每日基本面数据", True, f"标的: {BYD_SYMBOL}", test_file="test_gm_data.py")
        else:
            error = data.get("error", "")
            if error in ["permission_denied", "service_not_supported"]:
                _print_result("获取每日基本面数据", True, f"跳过: {error}", test_file="test_gm_data.py")
            else:
                _print_result("获取每日基本面数据", False, error, test_file="test_gm_data.py")

    def test_stk_get_daily_mktvalue_pt(self):
        """测试获取每日市值数据"""
        print_test_header("test_stk_get_daily_mktvalue_pt", "测试获取每日市值数据", "test_gm_data.py")

        data = call_gm_rpc("stk_get_daily_mktvalue_pt", {
            "symbols": BYD_SYMBOL,
            "fields": "tot_mv,a_mv",
            "trade_date": TODAY,
            "df": True
        })
        assert "success" in data

        if data.get("success"):
            print_data_summary(f"每日市值数据 - {BYD_SYMBOL}", data.get("data"))
            _print_result("获取每日市值数据", True, f"标的: {BYD_SYMBOL}", test_file="test_gm_data.py")
        else:
            error = data.get("error", "")
            if error in ["permission_denied", "service_not_supported"]:
                _print_result("获取每日市值数据", True, f"跳过: {error}", test_file="test_gm_data.py")
            else:
                _print_result("获取每日市值数据", False, error, test_file="test_gm_data.py")

    def test_stk_get_daily_valuation_pt(self):
        """测试获取每日估值数据"""
        print_test_header("test_stk_get_daily_valuation_pt", "测试获取每日估值数据", "test_gm_data.py")

        data = call_gm_rpc("stk_get_daily_valuation_pt", {
            "symbols": BYD_SYMBOL,
            "fields": "pe_ttm,pb_mrq,ps_ttm",
            "trade_date": TODAY,
            "df": True
        })
        assert "success" in data

        if data.get("success"):
            print_data_summary(f"每日估值数据 - {BYD_SYMBOL}", data.get("data"))
            _print_result("获取每日估值数据", True, f"标的: {BYD_SYMBOL}", test_file="test_gm_data.py")
        else:
            error = data.get("error", "")
            if error in ["permission_denied", "service_not_supported"]:
                _print_result("获取每日估值数据", True, f"跳过: {error}", test_file="test_gm_data.py")
            else:
                _print_result("获取每日估值数据", False, error, test_file="test_gm_data.py")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
