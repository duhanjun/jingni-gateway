# -*- coding: utf-8 -*-
"""对照实验：下单后 3 分钟不撤单，观察是否自动失效；随后再撤单观察时序。

用于区分：
A. 撤单异步生效但返回 Value=0（假失败）
B. 模拟柜台到时间自动失效（与撤单无关）
"""

import json
import os
import sys
import time

TDX_HOME = r"C:\new_tdx_mock"
sys.path.append(os.path.join(TDX_HOME, "PYPlugins", "user"))

from tqcenter import tq, tqconst  # noqa: E402

CODE = "600000.SH"


def j(o):
    return json.dumps(o, ensure_ascii=False, default=str)


def find(acct, wtbh):
    for o in tq.query_stock_orders(acct):
        if str(o.get("Wtbh")) == str(wtbh):
            return o
    return None


def snap(acct, wtbh):
    o = find(acct, wtbh)
    a = tq.query_stock_asset(acct)
    return (
        o.get("Status") if o else None,
        o.get("BSFlag") if o else None,
        a.get("Cash"),
        a.get("TotalFreeze"),
    )


def main():
    tq.initialize(__file__)
    acct = tq.stock_account(account="11048389", account_type="stock")

    res = tq.order_stock(
        account_id=acct,
        stock_code=CODE,
        order_type=tqconst.STOCK_BUY,
        order_volume=100,
        price_type=tqconst.PRICE_MY,
        price=10.13,
        notify=0,
    )
    print("order ->", j(res))
    wtbh = res.get("Wtbh")
    if not wtbh:
        tq.close()
        return

    print("t=0   ", snap(acct, wtbh))
    for i in range(1, 19):
        time.sleep(10)
        print(f"t={i * 10:<3}s", snap(acct, wtbh))

    print("\n--- now cancel ---")
    c = tq.cancel_order_stock(acct, CODE, str(wtbh))
    print("cancel ->", j(c))
    for i in range(1, 13):
        time.sleep(5)
        print(f"t+{i * 5:<3}s", snap(acct, wtbh))

    print("final order:", j(find(acct, wtbh)))
    tq.close()


if __name__ == "__main__":
    main()
