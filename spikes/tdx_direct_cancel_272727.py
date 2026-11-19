# -*- coding: utf-8 -*-
"""独立进程直接撤单 272727，对照网关结果。"""

import sys
import time

sys.path.append(r"C:\new_tdx_mock\PYPlugins\user")

from tqcenter import tq

tq.initialize(__file__)
handle = tq.stock_account(account="11048389", account_type="stock")
print("handle:", handle)

orders = tq.query_stock_orders(handle)
for o in orders:
    if str(o.get("Wtbh")) == "272727":
        print("before:", o)

res = tq.cancel_order_stock(handle, "600000.SH", "272727")
print("cancel:", res)

for i in range(10):
    time.sleep(1)
    orders = tq.query_stock_orders(handle)
    row = next((o for o in orders if str(o.get("Wtbh")) == "272727"), None)
    print(i + 1, "status:", row.get("Status") if row else None)
    if row and int(row.get("Status")) in (0, 4, 5):
        break

asset = tq.query_stock_asset(handle)
print("cash:", asset.get("Cash"))

tq.close()
