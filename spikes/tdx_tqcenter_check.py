# -*- coding: utf-8 -*-
"""TQCenter 直连冒烟测试：账户、资产、持仓、委托、撤单。

用途：验证 tqcenter 直连路径（不依赖 17709 HTTP）能否覆盖交易查询与撤单。
安全：只操作模拟账户 11048389，只撤单，不新开仓。
"""

import json
import os
import sys

TDX_HOME = r"C:\new_tdx_mock"
sys.path.append(os.path.join(TDX_HOME, "PYPlugins", "user"))

from tqcenter import tq  # noqa: E402


def show(title, obj):
    print(f"\n=== {title} ===")
    try:
        print(json.dumps(obj, ensure_ascii=False, default=str, indent=2))
    except Exception:
        print(repr(obj))


def main():
    tq.initialize(__file__)

    acct = tq.stock_account(account="11048389", account_type="stock")
    show("account handle", acct)

    asset = tq.query_stock_asset(acct)
    show("asset", asset)

    positions = tq.query_stock_positions(acct)
    show("positions", positions)

    orders_before = tq.query_stock_orders(acct)
    show("orders before cancel", orders_before)

    result = tq.cancel_order_stock(acct, "600000.SH", "211428")
    show("cancel 211428", result)

    orders_after = tq.query_stock_orders(acct)
    show("orders after cancel", orders_after)

    tq.close()


if __name__ == "__main__":
    main()
