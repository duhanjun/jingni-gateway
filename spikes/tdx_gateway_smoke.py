# -*- coding: utf-8 -*-
"""TdxQuant 网关冒烟：走 FastAPI 端点验证 provider + 交易查询 + 数据 RPC。"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from config import config
from main import app

HEADERS = {"X-API-Key": config.API_KEY}


def show(title, response):
    print(f"\n=== {title} (HTTP {response.status_code}) ===")
    try:
        print(json.dumps(response.json(), ensure_ascii=False, indent=2)[:2500])
    except Exception:
        print(response.text[:2500])


def main():
    with TestClient(app) as client:
        show("health", client.get("/api/v1/tdxquant/health", headers=HEADERS))
        show("asset", client.get("/api/v1/tdxquant/trade/asset", headers=HEADERS))
        show("positions", client.get("/api/v1/tdxquant/trade/positions", headers=HEADERS))
        show("orders", client.get("/api/v1/tdxquant/trade/orders", headers=HEADERS))

        show(
            "data get_market_data 1d",
            client.post(
                "/api/v1/tdxquant/rpc/execute",
                headers=HEADERS,
                json={
                    "module": "tdxdata",
                    "function": "get_market_data",
                    "kwargs": {
                        "stock_list": ["600000.SH"],
                        "period": "1d",
                        "count": 3,
                    },
                },
            ),
        )

        show(
            "trade rpc blocked",
            client.post(
                "/api/v1/tdxquant/rpc/execute",
                headers=HEADERS,
                json={
                    "module": "tdxtrade",
                    "function": "order_stock",
                    "kwargs": {"stock_code": "600000.SH"},
                },
            ),
        )


if __name__ == "__main__":
    main()
