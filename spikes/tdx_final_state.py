import sys, json
sys.path.append(r"C:\new_tdx_mock\PYPlugins\user")
from tqcenter import tq
tq.initialize(__file__)
acct = tq.stock_account(account="11048389", account_type="stock")
print("ASSET   :", json.dumps(tq.query_stock_asset(acct), ensure_ascii=False))
print("POSITION:", json.dumps(tq.query_stock_positions(acct), ensure_ascii=False))
print("ORDERS  :", json.dumps(tq.query_stock_orders(acct), ensure_ascii=False))
print("CANCELABLE:", json.dumps(tq.query_stock_orders(acct, cancelable_only=True), ensure_ascii=False))
tq.close()
