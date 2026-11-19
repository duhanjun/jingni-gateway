# -*- coding: utf-8 -*-
import sys, os, json, time
sys.path.append(r"C:\new_tdx_mock\PYPlugins\user")
from tqcenter import tq

tq.initialize(__file__)
acct = tq.stock_account(account="11048389", account_type="stock")
for i in range(1, 4):
    orders = tq.query_stock_orders(acct)
    target = [o for o in orders if o.get("Wtbh") == "227988"]
    print(f"try {i}: orders={len(orders)}, target={json.dumps(target, ensure_ascii=False)}")
    if target:
        res = tq.cancel_order_stock(acct, target[0]["Code"], str(target[0]["Wtbh"]))
        print("  cancel ->", json.dumps(res, ensure_ascii=False))
    else:
        print("  target gone")
        break
    time.sleep(5)
orders = tq.query_stock_orders(acct)
print("final:", json.dumps(orders, ensure_ascii=False))
tq.close()
