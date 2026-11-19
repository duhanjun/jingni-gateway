import sys, json
sys.path.append(r"C:\new_tdx_mock\PYPlugins\user")
from tqcenter import tq
tq.initialize(__file__)
acct = tq.stock_account(account="11048389", account_type="stock")
print("ALL:", json.dumps(tq.query_stock_orders(acct), ensure_ascii=False))
print("ASSET:", json.dumps(tq.query_stock_asset(acct), ensure_ascii=False))
tq.close()
