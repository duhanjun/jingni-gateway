import sys, json, time
sys.path.append(r"C:\new_tdx_mock\PYPlugins\user")
from tqcenter import tq

tq.initialize(__file__)
acct = tq.stock_account(account="11048389", account_type="stock")
print("handle:", acct)

variants = [
    ("baseline", acct, "600000.SH", "229869"),
    ("no_suffix", acct, "600000", "229869"),
    ("empty_code", acct, "", "229869"),
    ("acct_number", 11048389, "600000.SH", "229869"),
]
for name, aid, code, oid in variants:
    try:
        r = tq.cancel_order_stock(aid, code, oid)
        print(f"{name}: {json.dumps(r, ensure_ascii=False)}")
    except Exception as e:
        print(f"{name}: EXCEPTION {e}")
    time.sleep(1)

print("cancelable:", json.dumps(tq.query_stock_orders(acct, cancelable_only=True), ensure_ascii=False))
tq.close()
