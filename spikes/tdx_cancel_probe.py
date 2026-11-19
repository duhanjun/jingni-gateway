# -*- coding: utf-8 -*-
"""受控撤单实验：下单 → 立即撤单 → 轮询状态 60 秒。

目的：判断 cancel_order_stock 是同步失败，还是"返回失败但异步生效"。
"""

import json
import os
import sys
import time

TDX_HOME = r"C:\new_tdx_mock"
sys.path.append(os.path.join(TDX_HOME, "PYPlugins", "user"))

from tqcenter import tq, tqconst  # noqa: E402


def j(obj):
    return json.dumps(obj, ensure_ascii=False, default=str)


def last_close(code):
    try:
        data = tq.get_market_data(
            field_list=["Close"],
            stock_list=[code],
            period="1d",
            count=1,
        )
        print("market data:", j(data)[:500])
        close = data["Close"][code].iloc[-1]
        return float(close)
    except Exception as e:
        print("last_close failed:", e)
        return None


def main():
    tq.initialize(__file__)
    acct = tq.stock_account(account="11048389", account_type="stock")

    code = "600000.SH"
    close = last_close(code)
    price = round(close * 0.95, 2) if close else 9.70
    print(f"last_close={close}, order_price={price}")

    res = tq.order_stock(
        account_id=acct,
        stock_code=code,
        order_type=tqconst.STOCK_BUY,
        order_volume=100,
        price_type=tqconst.PRICE_MY,
        price=price,
        notify=0,
    )
    print("order ->", j(res))
    wtbh = res.get("Wtbh") if isinstance(res, dict) else None
    if not wtbh:
        print("no Wtbh, abort")
        tq.close()
        return

    def status_of():
        for o in tq.query_stock_orders(acct, stock_code=code):
            if str(o.get("Wtbh")) == str(wtbh):
                return o.get("Status"), o.get("BSFlag"), o.get("CjVol")
        return None, None, None

    print("status before cancel:", status_of())
    cancel = tq.cancel_order_stock(acct, code, str(wtbh))
    print("cancel ->", j(cancel))

    for i in range(1, 31):
        time.sleep(2)
        s = status_of()
        print(f"poll {i * 2:>3}s: Status={s[0]} BSFlag={s[1]} CjVol={s[2]}")
        if s[0] in (0, 4, 5):
            print("terminal state reached")
            break

    tq.close()


if __name__ == "__main__":
    main()
