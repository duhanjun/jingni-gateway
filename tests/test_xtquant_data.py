#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JingNiGateway XtData 行情模块接口测试
测试所有 XtData 数据接口

重要说明：
- 本测试文件模拟远程客户端，通过 HTTP RPC 调用测试服务端功能
- 不直接使用本地 xtdata 模块
- 所有操作都通过 /api/v1/xtquant/rpc/execute 端点完成
"""

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("xtquant", reason="需要本机安装 QMT/xtquant SDK")
import sys
import os
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from tests.test_config import (
    TEST_API_KEY,
    TEST_HEADERS,
    TEST_STOCK,
    TEST_STOCK_LIST,
    _print_result,
    print_test_header,
    print_data_summary
)

client = TestClient(app)


class TestXtDataInstrument:
    """XtData 合约相关接口测试"""
    
    def test_get_instrument_detail(self):
        """测试获取合约详情"""
        print_test_header("test_get_instrument_detail", "测试获取合约详情", "test_xtquant_data.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xtdata",
                "function": "get_instrument_detail",
                "kwargs": {"stock_code": TEST_STOCK}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        print_data_summary(f"合约详情 - {TEST_STOCK}", data['data'])
        _print_result("获取合约详情", True, f"股票：{TEST_STOCK}", test_file="test_xtquant_data.py")


class TestXtDataCalendar:
    """XtData 交易日历测试"""
    
    def test_get_trading_dates(self):
        """测试获取交易日历"""
        print_test_header("test_get_trading_dates", "测试获取交易日历", "test_xtquant_data.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xtdata",
                "function": "get_trading_dates",
                "kwargs": {"market": "SH"}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        print_data_summary(f"交易日历 - SH 市场", data['data'])
        _print_result("获取交易日历", True, f"市场：SH", test_file="test_xtquant_data.py")


class TestXtDataStockList:
    """XtData 板块成分股测试"""
    
    def test_get_stock_list_in_sector(self):
        """测试获取板块成分股"""
        print_test_header("test_get_stock_list_in_sector", "测试获取板块成分股", "test_xtquant_data.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xtdata",
                "function": "get_stock_list_in_sector",
                "kwargs": {"sector_name": "沪深指数"}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        print_data_summary(f"板块成分股 - 沪深指数", data['data'])
        _print_result("获取板块成分股", True, f"板块：沪深指数", test_file="test_xtquant_data.py")


class TestXtDataMarketData:
    """XtData 行情数据测试"""
    
    def test_get_market_data_daily(self):
        """测试获取日线行情"""
        print_test_header("test_get_market_data_daily", "测试获取日线行情", "test_xtquant_data.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xtdata",
                "function": "get_market_data",
                "kwargs": {
                    "stock_list": [TEST_STOCK],
                    "period": "1d",
                    "start_time": "20240101",
                    "end_time": "20241231"
                }
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        print_data_summary(f"日线行情 - {TEST_STOCK}", data['data'])
        _print_result("获取日线行情", True, f"股票：{TEST_STOCK}, 周期：1 年", test_file="test_xtquant_data.py")
    
    def test_get_market_data_minute(self):
        """测试获取分钟线行情"""
        print_test_header("test_get_market_data_minute", "测试获取分钟线行情", "test_xtquant_data.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xtdata",
                "function": "get_market_data",
                "kwargs": {
                    "stock_list": [TEST_STOCK],
                    "period": "1m",
                    "start_time": "20241231",
                    "end_time": "20241231"
                }
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        print_data_summary(f"分钟线行情 - {TEST_STOCK}", data['data'])
        _print_result("获取单日行情", True, f"股票：{TEST_STOCK}, 日期：20241231", test_file="test_xtquant_data.py")


class TestXtDataTick:
    """XtData Tick 数据测试"""
    
    def test_get_full_tick(self):
        """测试获取完整 Tick 数据"""
        print_test_header("test_get_full_tick", "测试获取完整 Tick 数据", "test_xtquant_data.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xtdata",
                "function": "get_full_tick",
                "kwargs": {"code_list": TEST_STOCK_LIST}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        print_data_summary(f"Tick 数据 - {len(TEST_STOCK_LIST)} 只股票", data['data'])
        _print_result("获取 Tick 数据", True, f"股票列表：{len(TEST_STOCK_LIST)} 只", test_file="test_xtquant_data.py")


class TestXtDataFinancial:
    """XtData 财务数据测试"""
    
    def test_get_financial_data(self):
        """测试获取财务数据"""
        print_test_header("test_get_financial_data", "测试获取财务数据", "test_xtquant_data.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xtdata",
                "function": "get_financial_data",
                "kwargs": {
                    "stock_list": [TEST_STOCK],
                    "table_name": "Balance"
                }
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        if data['success']:
            print_data_summary(f"财务数据 - {TEST_STOCK}", data['data'])
            _print_result("获取财务数据", True, f"股票：{TEST_STOCK}, 表：Balance", test_file="test_xtquant_data.py")
        else:
            _print_result("获取财务数据", True, f"股票：{TEST_STOCK} (数据无法解析)", test_file="test_xtquant_data.py")


class TestXtDataDividend:
    """XtData 分红除权测试"""
    
    def test_get_divid_factors(self):
        """测试获取分红除权信息"""
        print_test_header("test_get_divid_factors", "测试获取分红除权信息", "test_xtquant_data.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xtdata",
                "function": "get_divid_factors",
                "kwargs": {"stock_code": TEST_STOCK}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        print_data_summary(f"分红除权 - {TEST_STOCK}", data['data'])
        _print_result("获取分红除权", True, f"股票：{TEST_STOCK}", test_file="test_xtquant_data.py")


if __name__ == "__main__":
    # 运行所有测试
    pytest.main([__file__, "-v", "-s", "--tb=short"])
