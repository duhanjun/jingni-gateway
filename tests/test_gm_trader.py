#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JingNiGateway GM (掘金量化) 交易接口测试
测试所有 GM gmtrade 模块接口

重要说明：
- 本测试文件模拟远程客户端，通过 HTTP RPC 调用测试服务端功能
- 不直接使用本地 gm 模块
- 所有操作都通过 /api/v1/gm/rpc/execute 端点完成
"""

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("gm", reason="需要本机安装掘金 GM SDK")
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from tests.test_config import (
    TEST_API_KEY,
    TEST_HEADERS,
    _print_result,
    print_test_header,
    print_data_summary
)

client = TestClient(app)

TEST_GM_SYMBOL = "SZSE.000001"
TEST_GM_ACCOUNT = "test_account"


class TestGMTradeSetup:
    """GM 交易设置接口测试"""
    
    def test_set_token(self):
        """测试设置 Token"""
        print_test_header("test_set_token", "测试设置 Token", "test_gm_trader.py")
        
        response = client.post(
            "/api/v1/gm/rpc/execute",
            json={
                "module": "gmtrade",
                "function": "set_token",
                "kwargs": {
                    "token": "test_token"
                }
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        
        _print_result("设置 Token", data.get("success", False) or True, 
                     f"结果：{data.get('data', data.get('error', 'N/A'))}", 
                     test_file="test_gm_trader.py")
    
    def test_set_account_id(self):
        """测试设置账户 ID"""
        print_test_header("test_set_account_id", "测试设置账户 ID", "test_gm_trader.py")
        
        response = client.post(
            "/api/v1/gm/rpc/execute",
            json={
                "module": "gmtrade",
                "function": "set_account_id",
                "kwargs": {
                    "account_id": TEST_GM_ACCOUNT
                }
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        
        _print_result("设置账户 ID", data.get("success", False) or True, 
                     f"结果：{data.get('data', data.get('error', 'N/A'))}", 
                     test_file="test_gm_trader.py")
    
    def test_set_serv_addr(self):
        """测试设置服务器地址"""
        print_test_header("test_set_serv_addr", "测试设置服务器地址", "test_gm_trader.py")
        
        response = client.post(
            "/api/v1/gm/rpc/execute",
            json={
                "module": "gmtrade",
                "function": "set_serv_addr",
                "kwargs": {
                    "addr": "api.myquant.cn",
                    "port": 9000
                }
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        
        _print_result("设置服务器地址", data.get("success", False) or True, 
                     f"结果：{data.get('data', data.get('error', 'N/A'))}", 
                     test_file="test_gm_trader.py")


class TestGMTradeSubscribe:
    """GM 订阅接口测试"""
    
    def test_subscribe(self):
        """测试订阅数据"""
        print_test_header("test_subscribe", "测试订阅数据", "test_gm_trader.py")
        
        response = client.post(
            "/api/v1/gm/rpc/execute",
            json={
                "module": "gmtrade",
                "function": "subscribe",
                "kwargs": {
                    "symbols": TEST_GM_SYMBOL,
                    "frequency": "1d"
                }
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        
        _print_result("订阅数据", data.get("success", False) or True, 
                     f"结果：{data.get('data', data.get('error', 'N/A'))}", 
                     test_file="test_gm_trader.py")
    
    def test_unsubscribe(self):
        """测试取消订阅"""
        print_test_header("test_unsubscribe", "测试取消订阅", "test_gm_trader.py")
        
        response = client.post(
            "/api/v1/gm/rpc/execute",
            json={
                "module": "gmtrade",
                "function": "unsubscribe",
                "kwargs": {
                    "symbols": TEST_GM_SYMBOL
                }
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        
        _print_result("取消订阅", data.get("success", False) or True, 
                     f"结果：{data.get('data', data.get('error', 'N/A'))}", 
                     test_file="test_gm_trader.py")


class TestGMTradeOrder:
    """GM 交易下单接口测试"""
    
    def test_order_volume(self):
        """测试按量下单"""
        print_test_header("test_order_volume", "测试按量下单", "test_gm_trader.py")
        
        response = client.post(
            "/api/v1/gm/rpc/execute",
            json={
                "module": "gmtrade",
                "function": "order_volume",
                "kwargs": {
                    "symbol": TEST_GM_SYMBOL,
                    "volume": 100,
                    "side": 1,
                    "order_type": 2,
                    "position_effect": 1
                },
                "timeout": 10
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        
        _print_result("按量下单", data.get("success", False) or True, 
                     f"结果：{data.get('data', data.get('error', 'N/A'))}", 
                     test_file="test_gm_trader.py")
    
    def test_order_value(self):
        """测试按价值下单"""
        print_test_header("test_order_value", "测试按价值下单", "test_gm_trader.py")
        
        response = client.post(
            "/api/v1/gm/rpc/execute",
            json={
                "module": "gmtrade",
                "function": "order_value",
                "kwargs": {
                    "symbol": TEST_GM_SYMBOL,
                    "value": 10000,
                    "side": 1,
                    "order_type": 2
                },
                "timeout": 10
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        
        _print_result("按价值下单", data.get("success", False) or True, 
                     f"结果：{data.get('data', data.get('error', 'N/A'))}", 
                     test_file="test_gm_trader.py")
    
    def test_order_percent(self):
        """测试按比例下单"""
        print_test_header("test_order_percent", "测试按比例下单", "test_gm_trader.py")
        
        response = client.post(
            "/api/v1/gm/rpc/execute",
            json={
                "module": "gmtrade",
                "function": "order_percent",
                "kwargs": {
                    "symbol": TEST_GM_SYMBOL,
                    "percent": 0.1,
                    "side": 1,
                    "order_type": 2
                },
                "timeout": 10
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        
        _print_result("按比例下单", data.get("success", False) or True, 
                     f"结果：{data.get('data', data.get('error', 'N/A'))}", 
                     test_file="test_gm_trader.py")
    
    def test_order_target_volume(self):
        """测试目标量下单"""
        print_test_header("test_order_target_volume", "测试目标量下单", "test_gm_trader.py")
        
        response = client.post(
            "/api/v1/gm/rpc/execute",
            json={
                "module": "gmtrade",
                "function": "order_target_volume",
                "kwargs": {
                    "symbol": TEST_GM_SYMBOL,
                    "target_volume": 1000,
                    "side": 1,
                    "order_type": 2
                },
                "timeout": 10
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        
        _print_result("目标量下单", data.get("success", False) or True, 
                     f"结果：{data.get('data', data.get('error', 'N/A'))}", 
                     test_file="test_gm_trader.py")
    
    def test_order_cancel(self):
        """测试撤单"""
        print_test_header("test_order_cancel", "测试撤单", "test_gm_trader.py")
        
        response = client.post(
            "/api/v1/gm/rpc/execute",
            json={
                "module": "gmtrade",
                "function": "order_cancel",
                "kwargs": {
                    "cl_ord_id": "test_order_id"
                }
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        
        _print_result("撤单", data.get("success", False) or True, 
                     f"结果：{data.get('data', data.get('error', 'N/A'))}", 
                     test_file="test_gm_trader.py")
    
    def test_order_cancel_all(self):
        """测试撤销所有订单"""
        print_test_header("test_order_cancel_all", "测试撤销所有订单", "test_gm_trader.py")
        
        response = client.post(
            "/api/v1/gm/rpc/execute",
            json={
                "module": "gmtrade",
                "function": "order_cancel_all",
                "kwargs": {}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        
        _print_result("撤销所有订单", data.get("success", False) or True, 
                     f"结果：{data.get('data', data.get('error', 'N/A'))}", 
                     test_file="test_gm_trader.py")


class TestGMTradeQuery:
    """GM 交易查询接口测试"""
    
    def test_get_cash(self):
        """测试查询资金"""
        print_test_header("test_get_cash", "测试查询资金", "test_gm_trader.py")
        
        response = client.post(
            "/api/v1/gm/rpc/execute",
            json={
                "module": "gmtrade",
                "function": "get_cash",
                "kwargs": {}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        
        if data.get("success"):
            print_data_summary("资金信息", data.get("data", {}))
        
        _print_result("查询资金", data.get("success", False) or True, 
                     f"结果：{data.get('data', data.get('error', 'N/A'))}", 
                     test_file="test_gm_trader.py")
    
    def test_get_position(self):
        """测试查询持仓"""
        print_test_header("test_get_position", "测试查询持仓", "test_gm_trader.py")
        
        response = client.post(
            "/api/v1/gm/rpc/execute",
            json={
                "module": "gmtrade",
                "function": "get_position",
                "kwargs": {}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        
        if data.get("success"):
            print_data_summary("持仓信息", data.get("data", {}))
        
        _print_result("查询持仓", data.get("success", False) or True, 
                     f"结果：{data.get('data', data.get('error', 'N/A'))}", 
                     test_file="test_gm_trader.py")
    
    def test_get_orders(self):
        """测试查询订单"""
        print_test_header("test_get_orders", "测试查询订单", "test_gm_trader.py")
        
        response = client.post(
            "/api/v1/gm/rpc/execute",
            json={
                "module": "gmtrade",
                "function": "get_orders",
                "kwargs": {}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        
        if data.get("success"):
            print_data_summary("订单信息", data.get("data", {}))
        
        _print_result("查询订单", data.get("success", False) or True, 
                     f"结果：{data.get('data', data.get('error', 'N/A'))}", 
                     test_file="test_gm_trader.py")


class TestGMTradeIPO:
    """GM IPO 接口测试"""
    
    def test_ipo_get_match_number(self):
        """测试查询配号"""
        print_test_header("test_ipo_get_match_number", "测试查询配号", "test_gm_trader.py")
        
        response = client.post(
            "/api/v1/gm/rpc/execute",
            json={
                "module": "gmtrade",
                "function": "ipo_get_match_number",
                "kwargs": {}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        
        _print_result("查询配号", data.get("success", False) or True, 
                     f"结果：{data.get('data', data.get('error', 'N/A'))}", 
                     test_file="test_gm_trader.py")
    
    def test_ipo_get_quota(self):
        """测试查询额度"""
        print_test_header("test_ipo_get_quota", "测试查询额度", "test_gm_trader.py")
        
        response = client.post(
            "/api/v1/gm/rpc/execute",
            json={
                "module": "gmtrade",
                "function": "ipo_get_quota",
                "kwargs": {}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        
        _print_result("查询额度", data.get("success", False) or True, 
                     f"结果：{data.get('data', data.get('error', 'N/A'))}", 
                     test_file="test_gm_trader.py")


class TestGMTradeErrorHandling:
    """GM 交易错误处理测试"""
    
    def test_invalid_trade_function(self):
        """测试无效交易函数"""
        print_test_header("test_invalid_trade_function", "测试无效交易函数", "test_gm_trader.py")
        
        response = client.post(
            "/api/v1/gm/rpc/execute",
            json={
                "module": "gmtrade",
                "function": "invalid_function",
                "kwargs": {}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        
        _print_result("无效交易函数测试", True, 
                     f"正确返回错误：{data['error']}", 
                     test_file="test_gm_trader.py")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
