import sys, json
sys.path.append(r"C:\new_tdx_mock\PYPlugins\user")
from tqcenter import tq
tq.initialize(__file__)
acct = tq.stock_account(account="11048389", account_type="stock")
print("ALL ORDERS:", json.dumps(tq.query_stock_orders(acct), ensure_ascii=False))
print("FILTER 600000.SH:", json.dumps(tq.query_stock_orders(acct, stock_code="600000.SH"), ensure_ascii=False))
print("CANCELABLE:", json.dumps(tq.query_stock_orders(acct, cancelable_only=True), ensure_ascii=False))
print("ASSET:", json.dumps(tq.query_stock_asset(acct), ensure_ascii=False))
tq.close()
