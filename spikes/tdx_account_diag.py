# -*- coding: utf-8 -*-
import sys, os, json
sys.path.append(r"C:\new_tdx_mock\PYPlugins\user")
from tqcenter import tq

def show(t, o):
    print("---", t, "---")
    print(json.dumps(o, ensure_ascii=False, default=str, indent=2))

tq.initialize(__file__)
for at in ("stock", "STOCK"):
    try:
        h = tq.stock_account(account="11048389", account_type=at)
        print(f"account_type={at} -> handle={h!r}")
        show(f"asset(type={at})", tq.query_stock_asset(h))
    except Exception as e:
        print(f"account_type={at} ERROR: {e}")

show("asset(handle=1)", tq.query_stock_asset(1))
tq.close()
