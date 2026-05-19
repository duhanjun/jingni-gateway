#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JingNiGateway 主服务测试模块

重要说明：
- 本测试文件模拟远程客户端，通过 HTTP 请求测试服务端功能
- 所有测试都通过 HTTP 客户端完成
"""

import pytest
from fastapi.testclient import TestClient
import sys
import os
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from tests.test_config import (
    _print_result,
    print_test_header
)

client = TestClient(app)


class TestHealthCheck:
    """健康检查测试"""
    
    def test_root(self):
        """测试根路径"""
        print_test_header("test_root", "测试根路径", "test_api_health.py")
        
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "quant-data-gateway"
        assert data["status"] == "running"
        assert "websocket_support" in data
        assert "providers" in data
        assert "xtquant" in data["providers"]
        assert "gm" in data["providers"]
        _print_result("根路径访问", True, f"服务：{data['service']}", test_file="test_api_health.py")
    
    def test_health(self):
        """测试健康检查"""
        print_test_header("test_health", "测试健康检查", "test_api_health.py")
        
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "xtdata_available" in data
        assert "xttrader_available" in data
        _print_result("健康检查", True, f"状态：{data['status']}", test_file="test_api_health.py")
    
    def test_xtdata_availability(self):
        """测试 xtdata 模块可用性"""
        print_test_header("test_xtdata_availability", "测试 xtdata 模块可用性", "test_api_health.py")
        
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["xtdata_available"], bool)
        _print_result("xtdata 模块可用", True, f"可用：{data['xtdata_available']}", test_file="test_api_health.py")
    
    def test_xttrader_availability(self):
        """测试 xttrader 模块可用性"""
        print_test_header("test_xttrader_availability", "测试 xttrader 模块可用性", "test_api_health.py")
        
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["xttrader_available"], bool)
        _print_result("xttrader 模块可用", True, f"可用：{data['xttrader_available']}", test_file="test_api_health.py")


class TestAPIKeyAuth:
    """API Key 认证测试"""
    
    def test_stats_without_auth(self):
        """测试无认证访问 stats 接口"""
        print_test_header("test_stats_without_auth", "测试无认证访问 stats 接口", "test_api_health.py")
        
        response = client.get("/api/v1/stats")
        assert response.status_code in [401, 403]
        _print_result("无认证访问", True, f"正确拒绝 (状态码：{response.status_code})", test_file="test_api_health.py")
    
    def test_stats_with_invalid_auth(self):
        """测试无效 API Key"""
        print_test_header("test_stats_with_invalid_auth", "测试无效 API Key", "test_api_health.py")
        
        response = client.get(
            "/api/v1/stats",
            headers={"X-API-Key": "invalid_key"}
        )
        assert response.status_code == 401
        _print_result("无效 API Key", True, "正确拒绝无效密钥", test_file="test_api_health.py")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
