# -*- coding: utf-8 -*-
"""API Key 认证加固测试：未配置、缺失、错误、正确四种路径。"""

from fastapi.testclient import TestClient

from config import config
from main import app

client = TestClient(app)


def test_unconfigured_key_returns_503(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "")
    response = client.get("/api/v1/stats")
    assert response.status_code == 503


def test_missing_key_returns_401():
    response = client.get("/api/v1/stats")
    assert response.status_code == 401


def test_invalid_key_returns_401():
    response = client.get("/api/v1/stats", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401


def test_valid_key_returns_200():
    if not config.API_KEY:
        import pytest
        pytest.skip("当前环境未配置 JINGNI_API_KEY")
    response = client.get("/api/v1/stats", headers={"X-API-Key": config.API_KEY})
    assert response.status_code == 200
