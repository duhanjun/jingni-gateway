# -*- coding: utf-8 -*-
"""TQCenter 交易闭环：下单 → 查委托 → 撤单 → 查委托。

安全：模拟账户 11048389；600000.SH 限价 9.70（远低于现价），100 股；验证后立即撤单。
"""

import json
import os
import sys
import time

TDX_HOME = r"C:\new_tdx_mock"
sys.path.append(os.path.join(TDX_HOME, "PYPlugins", "user"))

from tqcenter import tq, tqconst  # noqa: E402


def show(title, obj):
    print(f"\n=== {title} ===")
    try:
        print(json.dumps(obj, ensure_ascii=False, default=str, indent=2))
    except Exception:
        print(repr(obj))


def main():
    tq.initialize(__file__)
    acct = tq.stock_account(account="11048389", account_type="stock")
    print(f"account handle = {acct}")

    asset = tq.query_stock_asset(acct)
    print(f"asset = {asset.get('Asset')} / cash = {asset.get('Cash')}")

    show("orders before", tq.query_stock_orders(acct))

    result = tq.order_stock(
        account_id=acct,
        stock_code="600000.SH",
        order_type=tqconst.STOCK_BUY,
        order_volume=100,
        price_type=tqconst.PRICE_MY,
        price=9.70,
        notify=0,
    )
    show("order result", result)

    time.sleep(2)
    show("orders after place", tq.query_stock_orders(acct))
    show("cancelable only", tq.query_stock_orders(acct, cancelable_only=True))

    wtbh = result.get("Wtbh") if isinstance(result, dict) else None
    if wtbh:
        cancel_result = tq.cancel_order_stock(acct, "600000.SH", str(wtbh))
        show(f"cancel {wtbh}", cancel_result)
        time.sleep(2)
        show("orders after cancel", tq.query_stock_orders(acct))
    else:
        print("no Wtbh returned, skip cancel")

    tq.close()


if __name__ == "__main__":
    main()
