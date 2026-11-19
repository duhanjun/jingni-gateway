# -*- coding: utf-8 -*-
"""通过网关类型化端点完成一次真实下单-撤单闭环（模拟账户）。"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from config import config
from main import app

HEADERS = {"X-API-Key": config.API_KEY}


def show(title, response):
    print(f"\n=== {title} (HTTP {response.status_code}) ===")
    print(json.dumps(response.json(), ensure_ascii=False, indent=2)[:3000])


def main():
    with TestClient(app) as client:
        before = client.get("/api/v1/tdxquant/trade/asset", headers=HEADERS)
        print("cash_before:", before.json().get("data", {}).get("cash"))

        placed = client.post(
            "/api/v1/tdxquant/trade/order",
            headers=HEADERS,
            json={
                "stock_code": "600000.SH",
                "order_type": 0,
                "order_volume": 100,
                "price_type": 0,
                "price": 10.13,
                "notify": 0,
            },
        )
        show("place_order", placed)
        data = placed.json().get("data") or {}
        order_id = data.get("order_id")
        print("order_id:", order_id)

        if order_id:
            time.sleep(0.5)
            cancelled = client.post(
                "/api/v1/tdxquant/trade/cancel",
                headers=HEADERS,
                json={"stock_code": "600000.SH", "order_id": order_id},
            )
            show("cancel_order", cancelled)

        show("orders_after", client.get("/api/v1/tdxquant/trade/orders", headers=HEADERS))
        after = client.get("/api/v1/tdxquant/trade/asset", headers=HEADERS)
        print("cash_after:", after.json().get("data", {}).get("cash"))


if __name__ == "__main__":
    main()
