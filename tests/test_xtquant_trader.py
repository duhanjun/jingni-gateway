#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JingNiGateway XtTrader 交易模块接口测试
测试所有 XtTrader 交易接口

重要说明：
- 本测试文件模拟远程客户端，通过 HTTP RPC 调用测试服务端功能
- 不直接创建或使用本地 XtTrader 实例
- 所有操作都通过 /api/v1/xtquant/rpc/execute 端点完成
"""

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("xtquant", reason="需要本机安装 QMT/xtquant SDK")
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from tests.test_config import (
    TEST_API_KEY,
    TEST_HEADERS,
    TEST_ACCOUNT,
    TEST_STOCK,
    TEST_PRICE,
    TEST_VOLUME,
    _print_result,
    print_test_header,
    print_data_summary
)


@pytest.fixture(scope="module")
def client():
    """创建测试客户端，确保 lifespan 被正确触发"""
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


class TestXtTraderSystem:
    """XtTrader 系统接口测试"""
    
    def test_create_trader(self, client):
        """测试创建交易实例"""
        print_test_header("test_create_trader", "测试创建交易实例", "test_xtquant_trader.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xttrader",
                "function": "create_trader",
                "kwargs": {
                    "account": TEST_ACCOUNT,
                    "account_type": "STOCK"
                }
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        _print_result("创建交易实例", True, f"账户：{TEST_ACCOUNT}", test_file="test_xtquant_trader.py")
    
    def test_start(self, client):
        """测试启动交易服务"""
        print_test_header("test_start", "测试启动交易服务", "test_xtquant_trader.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xttrader",
                "function": "start",
                "kwargs": {}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        _print_result("启动交易服务", True, test_file="test_xtquant_trader.py")
    
    def test_connect(self, client):
        """测试连接交易服务器"""
        print_test_header("test_connect", "测试连接交易服务器", "test_xtquant_trader.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xttrader",
                "function": "connect",
                "kwargs": {}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        _print_result("连接交易服务器", True, f"返回值：{data['data']}", test_file="test_xtquant_trader.py")


class TestXtTraderQuery:
    """XtTrader 查询接口测试"""
    
    def test_query_stock_asset(self, client):
        """测试查询资金（真实数据）"""
        print_test_header("test_query_stock_asset", "测试查询资金", "test_xtquant_trader.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xttrader",
                "function": "query_stock_asset",
                "kwargs": {"account": TEST_ACCOUNT}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True, f"查询失败：{data.get('error', 'Unknown')}"
        
        # 验证返回数据格式
        result_data = data['data']
        assert isinstance(result_data, dict), "返回数据应该是字典"
        
        # 检查是否包含 XtAsset 对象或状态信息
        if 'status' in result_data:
            assert result_data['status'] == 'success', f"查询状态失败：{result_data.get('message', '')}"
            assert 'data' in result_data, "成功响应应包含 data 字段"
            asset_data = result_data['data']
        else:
            asset_data = result_data
        
        print_data_summary(f"资金账户 - {TEST_ACCOUNT}", asset_data)
        _print_result("查询资金", True, f"账户：{TEST_ACCOUNT}", test_file="test_xtquant_trader.py")
        
        # 验证资金对象有基本属性
        if isinstance(asset_data, dict) and 'attributes' in asset_data:
            attrs = asset_data['attributes']
            assert 'cash' in attrs or 'total_asset' in attrs, "资金对象应包含 cash 或 total_asset 属性"
    
    def test_query_stock_positions(self, client):
        """测试查询持仓（真实数据）"""
        print_test_header("test_query_stock_positions", "测试查询持仓", "test_xtquant_trader.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xttrader",
                "function": "query_stock_positions",
                "kwargs": {"account": TEST_ACCOUNT}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True, f"查询失败：{data.get('error', 'Unknown')}"
        
        result_data = data['data']
        if isinstance(result_data, dict) and 'status' in result_data:
            assert result_data['status'] == 'success', f"查询状态失败：{result_data.get('message', '')}"
            positions_data = result_data.get('data', [])
        else:
            positions_data = result_data
        
        print_data_summary(f"持仓信息 - {TEST_ACCOUNT}", positions_data)
        _print_result("查询持仓", True, f"账户：{TEST_ACCOUNT}", test_file="test_xtquant_trader.py")
        
        # 验证返回数据
        assert positions_data is not None, "持仓查询返回 None"
        # positions 应该是列表
        assert isinstance(positions_data, list), "持仓应该返回列表"
    
    def test_query_orders(self, client):
        """测试查询订单（真实数据）"""
        print_test_header("test_query_orders", "测试查询订单", "test_xtquant_trader.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xttrader",
                "function": "query_stock_orders",
                "kwargs": {"account": TEST_ACCOUNT}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True, f"查询失败：{data.get('error', 'Unknown')}"
        
        result_data = data['data']
        if isinstance(result_data, dict) and 'status' in result_data:
            assert result_data['status'] == 'success', f"查询状态失败：{result_data.get('message', '')}"
            orders_data = result_data.get('data', [])
        else:
            orders_data = result_data
        
        print_data_summary(f"订单列表 - {TEST_ACCOUNT}", orders_data)
        _print_result("查询订单", True, f"账户：{TEST_ACCOUNT}", test_file="test_xtquant_trader.py")
        
        # 验证返回数据
        assert orders_data is not None, "订单查询返回 None"
        # orders 应该是列表
        assert isinstance(orders_data, list), "订单应该返回列表"


class TestXtTraderOrder:
    """XtTrader 交易操作测试"""
    
    def test_order_stock_buy(self, client):
        """测试股票买入委托"""
        print_test_header("test_order_stock_buy", "测试股票买入委托", "test_xtquant_trader.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xttrader",
                "function": "order_stock",
                "kwargs": {
                    "account": TEST_ACCOUNT,
                    "stock_code": TEST_STOCK,
                    "order_type": 1,  # 买入
                    "order_volume": TEST_VOLUME,
                    "price": TEST_PRICE,
                    "strategy_name": "测试策略",
                    "order_remark": "测试买单"
                }
            },
            headers=TEST_HEADERS
        )
        # 实际交易可能失败（资金不足等），但接口应该正常响应
        assert response.status_code == 200
        data = response.json()
        _print_result("股票买入委托", True, f"股票：{TEST_STOCK}, 数量：{TEST_VOLUME}", test_file="test_xtquant_trader.py")
    
    def test_order_stock_sell(self, client):
        """测试股票卖出委托"""
        print_test_header("test_order_stock_sell", "测试股票卖出委托", "test_xtquant_trader.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xttrader",
                "function": "order_stock",
                "kwargs": {
                    "account": TEST_ACCOUNT,
                    "stock_code": TEST_STOCK,
                    "order_type": 2,  # 卖出
                    "order_volume": TEST_VOLUME,
                    "price": TEST_PRICE,
                    "strategy_name": "测试策略",
                    "order_remark": "测试卖单"
                }
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        _print_result("股票卖出委托", True, f"股票：{TEST_STOCK}, 数量：{TEST_VOLUME}", test_file="test_xtquant_trader.py")
    
    def test_cancel_order_stock(self, client):
        """测试撤销委托"""
        print_test_header("test_cancel_order_stock", "测试撤销委托", "test_xtquant_trader.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xttrader",
                "function": "cancel_order_stock",
                "kwargs": {
                    "account": TEST_ACCOUNT,
                    "order_id": "12345"  # 测试订单 ID
                }
            },
            headers=TEST_HEADERS
        )
        # 撤销可能失败（订单不存在），但接口应该正常响应
        assert response.status_code == 200
        data = response.json()
        _print_result("撤销委托", True, f"订单 ID: 12345", test_file="test_xtquant_trader.py")


class TestXtTraderFund:
    """XtTrader 资金划拨测试"""
    
    def test_fund_transfer(self, client):
        """测试资金转账"""
        print_test_header("test_fund_transfer", "测试资金转账", "test_xtquant_trader.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xttrader",
                "function": "fund_transfer",
                "kwargs": {
                    "account": TEST_ACCOUNT,
                    "amount": 1000,
                    "transfer_type": 1  # 转入
                }
            },
            headers=TEST_HEADERS
        )
        # 实际转账可能失败，但接口应该正常响应
        assert response.status_code == 200
        data = response.json()
        _print_result("资金转账", True, f"金额：1000", test_file="test_xtquant_trader.py")
    
    def test_bank_transfer(self, client):
        """测试银证转账"""
        print_test_header("test_bank_transfer", "测试银证转账", "test_xtquant_trader.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xttrader",
                "function": "bank_transfer_in",
                "kwargs": {
                    "account": TEST_ACCOUNT,
                    "amount": 1000,
                    "bank_id": "测试银行"
                }
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        _print_result("银证转账", True, f"金额：1000, 银行：测试银行", test_file="test_xtquant_trader.py")


class TestXtTraderCredit:
    """XtTrader 信用交易测试"""
    
    def test_query_credit_detail(self, client):
        """测试查询信用账户（真实数据）"""
        print_test_header("test_query_credit_detail", "测试查询信用账户", "test_xtquant_trader.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xttrader",
                "function": "query_credit_detail",
                "kwargs": {"account": TEST_ACCOUNT}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True, f"查询失败：{data.get('error', 'Unknown')}"
        
        result_data = data['data']
        if isinstance(result_data, dict) and 'status' in result_data:
            assert result_data['status'] == 'success', f"查询状态失败：{result_data.get('message', '')}"
            credit_data = result_data.get('data')
        else:
            credit_data = result_data
        
        print_data_summary(f"信用账户 - {TEST_ACCOUNT}", credit_data)
        _print_result("查询信用账户", True, f"账户：{TEST_ACCOUNT}", test_file="test_xtquant_trader.py")
    
    def test_query_stk_compacts(self, client):
        """测试查询合约（真实数据）"""
        print_test_header("test_query_stk_compacts", "测试查询合约", "test_xtquant_trader.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xttrader",
                "function": "query_stk_compacts",
                "kwargs": {"account": TEST_ACCOUNT}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True, f"查询失败：{data.get('error', 'Unknown')}"
        
        result_data = data['data']
        if isinstance(result_data, dict) and 'status' in result_data:
            assert result_data['status'] == 'success', f"查询状态失败：{result_data.get('message', '')}"
            compacts_data = result_data.get('data', [])
        else:
            compacts_data = result_data
        
        print_data_summary(f"合约列表 - {TEST_ACCOUNT}", compacts_data)
        _print_result("查询合约", True, f"账户：{TEST_ACCOUNT}", test_file="test_xtquant_trader.py")


class TestXtTraderSmt:
    """XtTrader 约券业务测试"""
    
    def test_smt_query_quoter(self, client):
        """测试查询报价（真实数据）"""
        print_test_header("test_smt_query_quoter", "测试查询约券报价", "test_xtquant_trader.py")
        
        # 注意：smt_query_quoter 的第一个参数是 account 对象，其他参数是可选的
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xttrader",
                "function": "smt_query_quoter",
                "kwargs": {
                    "account": TEST_ACCOUNT,
                    "stock_code": TEST_STOCK
                    # 其他参数使用默认值，避免参数过多导致错误
                }
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        # 这个方法可能返回错误（如果股票不支持约券），但接口应该正常响应
        _print_result("查询约券报价", True, f"股票：{TEST_STOCK}", test_file="test_xtquant_trader.py")
    
    def test_smt_negotiate_order_async(self, client):
        """测试协商委托"""
        print_test_header("test_smt_negotiate_order_async", "测试协商委托", "test_xtquant_trader.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xttrader",
                "function": "smt_negotiate_order_async",
                "kwargs": {
                    "account": TEST_ACCOUNT,
                    "stock_code": TEST_STOCK,
                    "order_volume": TEST_VOLUME
                }
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        _print_result("约券协商委托", True, f"股票：{TEST_STOCK}, 数量：{TEST_VOLUME}", test_file="test_xtquant_trader.py")


class TestXtTraderAsync:
    """XtTrader 异步操作测试"""
    
    def test_order_stock_async(self, client):
        """测试异步委托"""
        print_test_header("test_order_stock_async", "测试异步委托", "test_xtquant_trader.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xttrader",
                "function": "order_stock_async",
                "kwargs": {
                    "account": TEST_ACCOUNT,
                    "stock_code": TEST_STOCK,
                    "order_type": 1,
                    "order_volume": TEST_VOLUME,
                    "price": TEST_PRICE
                }
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        _print_result("异步委托", True, f"股票：{TEST_STOCK}, 类型：买入", test_file="test_xtquant_trader.py")
    
    def test_cancel_order_stock_async(self, client):
        """测试异步撤销委托"""
        print_test_header("test_cancel_order_stock_async", "测试异步撤销委托", "test_xtquant_trader.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xttrader",
                "function": "cancel_order_stock_async",
                "kwargs": {
                    "account": TEST_ACCOUNT,
                    "order_id": "12345"
                }
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        _print_result("异步撤销委托", True, f"订单 ID: 12345", test_file="test_xtquant_trader.py")


class TestXtTraderAccount:
    """XtTrader 账户管理测试"""
    
    def test_query_account_infos(self, client):
        """测试查询账户信息"""
        print_test_header("test_query_account_infos", "测试查询账户信息", "test_xtquant_trader.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xttrader",
                "function": "query_account_infos",
                "kwargs": {"account": TEST_ACCOUNT}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        _print_result("查询账户信息", True, f"账户：{TEST_ACCOUNT}", test_file="test_xtquant_trader.py")
    
    def test_query_bank_info(self, client):
        """测试查询银行信息"""
        print_test_header("test_query_bank_info", "测试查询银行信息", "test_xtquant_trader.py")
        
        response = client.post(
            "/api/v1/xtquant/rpc/execute",
            json={
                "module": "xttrader",
                "function": "query_bank_info",
                "kwargs": {"account": TEST_ACCOUNT}
            },
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        _print_result("查询银行信息", True, f"账户：{TEST_ACCOUNT}", test_file="test_xtquant_trader.py")


class TestXtTraderRPC:
    """XtTrader RPC 方法测试"""
    
    def test_get_rpc_methods(self, client):
        """测试获取 RPC 方法列表"""
        print_test_header("test_get_rpc_methods", "测试获取 RPC 方法列表", "test_xtquant_trader.py")
        
        response = client.get(
            "/api/v1/xtquant/rpc/methods",
            headers=TEST_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        _print_result("获取 RPC 方法列表", True, f"共 {data['total']} 个方法", test_file="test_xtquant_trader.py")


if __name__ == "__main__":
    # 运行所有测试
    pytest.main([__file__, "-v", "-s", "--tb=short"])
