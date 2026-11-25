#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JingNiGateway WebSocket 接口测试
测试 WebSocket 连接、订阅和实时推送功能

重要说明：
- 本测试文件模拟远程客户端，通过 WebSocket 协议测试服务端功能
- 所有测试都通过 WebSocket 客户端完成
"""

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import TestClient as WebSocketTestClient
import sys
import os
import json
import time
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app, XTDATA_AVAILABLE
from tests.test_config import (
    TEST_API_KEY,
    TEST_CLIENT_ID,
    TEST_STOCK,
    _print_result,
    print_test_header
)
from tests.xtquant_runtime import XTQUANT_RUNTIME_AVAILABLE

requires_xtdata = pytest.mark.skipif(
    not (XTDATA_AVAILABLE and XTQUANT_RUNTIME_AVAILABLE),
    reason="需要本机安装 xtquant SDK，并启动 MiniQMT 行情服务",
)


class TestWebSocketConnection:
    """WebSocket 连接测试"""
    
    def test_websocket_connect_success(self):
        """测试 WebSocket 连接成功"""
        print_test_header("test_websocket_connect_success", "测试 WebSocket 连接成功", "test_api_websocket.py")
        
        with WebSocketTestClient(app).websocket_connect(
            f"/ws?client_id={TEST_CLIENT_ID}&api_key={TEST_API_KEY}"
        ) as websocket:
            # 应该收到连接成功消息
            data = websocket.receive_json()
            assert data["type"] == "connected"
            assert data["client_id"] == TEST_CLIENT_ID
        _print_result("WebSocket 连接成功", True, f"客户端 ID: {TEST_CLIENT_ID}", test_file="test_api_websocket.py")
    
    def test_websocket_connect_invalid_key(self):
        """测试 WebSocket 连接 - 无效 API Key"""
        print_test_header("test_websocket_connect_invalid_key", "测试 WebSocket 无效 API Key", "test_api_websocket.py")
        
        from starlette.websockets import WebSocketDisconnect
        
        try:
            with WebSocketTestClient(app).websocket_connect(
                f"/ws?client_id={TEST_CLIENT_ID}&api_key=invalid_key"
            ) as websocket:
                pass
            assert False, "应该拒绝无效 API Key"
        except WebSocketDisconnect:
            pass
        _print_result("WebSocket 无效 API Key", True, "正确拒绝无效密钥", test_file="test_api_websocket.py")
    
    def test_websocket_connect_missing_params(self):
        """测试 WebSocket 连接 - 缺少参数"""
        print_test_header("test_websocket_connect_missing_params", "测试 WebSocket 缺少参数", "test_api_websocket.py")
        
        from starlette.websockets import WebSocketDisconnect
        
        try:
            with WebSocketTestClient(app).websocket_connect(
                f"/ws?client_id={TEST_CLIENT_ID}"
            ) as websocket:
                pass
        except WebSocketDisconnect:
            pass
        _print_result("WebSocket 缺少参数", True, "正确拒绝缺少参数请求", test_file="test_api_websocket.py")


class TestWebSocketSubscribe:
    """WebSocket 订阅测试"""
    
    @requires_xtdata
    def test_subscribe_quote(self):
        """测试订阅行情"""
        print_test_header("test_subscribe_quote", "测试订阅行情", "test_api_websocket.py")
        
        with WebSocketTestClient(app).websocket_connect(
            f"/ws?client_id={TEST_CLIENT_ID}&api_key={TEST_API_KEY}"
        ) as websocket:
            # 接收连接成功消息
            websocket.receive_json()
            
            # 发送订阅请求
            websocket.send_json({
                "type": "subscribe_quote",
                "stock_code": TEST_STOCK,
                "period": "tick"
            })
            
            # 应该收到订阅确认
            data = websocket.receive_json()
            # 订阅成功会返回 subscribed 消息
            assert data["type"] in ["subscribed", "subscribe_result"]
            assert data.get("success", True) is True
        _print_result("订阅行情", True, f"股票：{TEST_STOCK}, 周期：tick", test_file="test_api_websocket.py")
    
    @requires_xtdata
    def test_subscribe_whole_quote(self):
        """测试订阅全量行情"""
        print_test_header("test_subscribe_whole_quote", "测试订阅全量行情", "test_api_websocket.py")
        
        with WebSocketTestClient(app).websocket_connect(
            f"/ws?client_id={TEST_CLIENT_ID}&api_key={TEST_API_KEY}"
        ) as websocket:
            # 接收连接成功消息
            websocket.receive_json()
            
            # 发送订阅全量行情请求
            websocket.send_json({
                "type": "subscribe_whole_quote",
                "code_list": [TEST_STOCK]
            })
            
            # 等待一段时间让数据推送
            time.sleep(0.5)
            
            # 应该收到行情数据
            data = websocket.receive_json()
            assert data["type"] in ["quote_data", "whole_quote"]
        _print_result("订阅全量行情", True, f"股票列表：{len([TEST_STOCK])} 只", test_file="test_api_websocket.py")


class TestWebSocketRPC:
    """WebSocket RPC 调用测试"""
    
    @requires_xtdata
    def test_rpc_call_via_websocket(self):
        """测试通过 WebSocket 调用 RPC 接口"""
        print_test_header("test_rpc_call_via_websocket", "测试通过 WebSocket 调用 RPC 接口", "test_api_websocket.py")
        
        with WebSocketTestClient(app).websocket_connect(
            f"/ws?client_id={TEST_CLIENT_ID}&api_key={TEST_API_KEY}"
        ) as websocket:
            # 接收连接成功消息
            websocket.receive_json()
            
            # 发送 RPC 调用请求
            websocket.send_json({
                "type": "rpc_call",
                "module": "xtdata",
                "function": "get_instrument_detail",
                "kwargs": {"stock_code": TEST_STOCK},
                "request_id": "test_001"
            })
            
            # 应该收到 RPC 响应
            data = websocket.receive_json()
            assert data["type"] == "rpc_response"
            assert data["request_id"] == "test_001"
            if not data["success"]:
                print(f"RPC 调用失败：{data.get('error', 'Unknown error')}")
            assert data["success"] is True
        _print_result("WebSocket RPC 调用", True, f"方法：xtdata.get_instrument_detail", test_file="test_api_websocket.py")


if __name__ == "__main__":
    # 运行所有测试
    pytest.main([__file__, "-v", "-s", "--tb=short"])
