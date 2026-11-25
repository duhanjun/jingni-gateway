"""GM/TDX 真实终端非交易时段全量扫描。

通过运行中的网关逐项调用，不直接 import SDK，避免与网关进程争用终端会话。
支持断点续跑：每次调用后立即写 JSON，超时/进程卡死时可从 offset 继续。
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TRADE_DATE = "2026-11-20"
TODAY = "2026-11-23"
STOCK = "SHSE.600000"
STOCK2 = "SZSE.000001"
INDEX = "SHSE.000300"
FUND = "SHSE.510300"
BOND = "SHSE.113648"
FUTURE = "SHFE.zn2710"
FUTURE_PRODUCT = "SHFE.RB"
START = "2026-11-01"
END = "2026-11-23"
LONG_START = "2025-01-01"


def load_api_key(env_path: Path) -> str:
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("JINGNI_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("JINGNI_API_KEY not found")


class Client:
    def __init__(self, base: str, key: str):
        self.base = base.rstrip("/")
        self.key = key

    def request(self, method: str, path: str, payload: dict | None = None, timeout: float = 90):
        data = None
        headers = {"X-API-Key": self.key}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            try:
                return exc.code, json.loads(body)
            except json.JSONDecodeError:
                return exc.code, {"raw": body}
        except Exception as exc:  # noqa: BLE001 - 记录为工具错误
            return 0, {"error": f"{type(exc).__name__}: {exc}"}

    def rpc(self, provider: str, module: str, function: str, kwargs: dict | None = None,
            args: list | None = None, timeout: int = 45):
        return self.request(
            "POST",
            f"/api/v1/{provider}/rpc/execute",
            {
                "module": module,
                "function": function,
                "args": args or [],
                "kwargs": kwargs or {},
                "timeout": timeout,
            },
            timeout=timeout + 20,
        )

    def get(self, path: str, timeout: float = 30):
        return self.request("GET", path, timeout=timeout)


OPTION_ARGS = {"s": 100, "k": 100, "v": 0.2, "t": 0.25, "call_or_put": "C"}

GM_PROBES: dict[str, dict[str, Any]] = {
    "history_n": {"kwargs": {"symbol": STOCK, "frequency": "1d", "count": 5,
                             "end_time": f"{TRADE_DATE} 15:00:00"}},
    "history": {"kwargs": {"symbol": STOCK, "frequency": "1d",
                            "start_time": f"{START} 09:30:00", "end_time": f"{TRADE_DATE} 15:00:00"}},
    "get_fundamentals": {"kwargs": {"table": "trading_derivative_indicator",
                                    "symbols": [STOCK], "start_date": START, "end_date": END,
                                    "fields": "TCLOSE,TOTMKTCAP,TURNRATE", "limit": 10}},
    "get_fundamentals_n": {"kwargs": {"table": "trading_derivative_indicator",
                                      "symbols": [STOCK], "end_date": TRADE_DATE,
                                      "fields": "TCLOSE,TOTMKTCAP,TURNRATE", "count": 3}},
    "get_symbol_infos": {"kwargs": {"sec_type1": 1010, "exchanges": ["SHSE"], "symbols": [STOCK]}},
    "get_symbols": {"kwargs": {"sec_type1": 1010, "exchanges": ["SHSE"], "symbols": [STOCK]}},
    "get_history_symbol": {"kwargs": {"symbol": STOCK, "start_date": START, "end_date": END}},
    "get_trading_dates_by_year": {"kwargs": {"exchange": "SHSE", "start_year": 2025, "end_year": 2026}},
    "get_trading_dates": {"kwargs": {"exchange": "SHSE", "start_date": START, "end_date": END}},
    "get_trading_session": {"kwargs": {"symbols": [STOCK]}},
    "get_instrumentinfos": {"kwargs": {"symbols": [STOCK]}},
    "get_instruments": {"kwargs": {"symbols": [STOCK]}},
    "get_history_instruments": {"kwargs": {"symbols": [STOCK], "start_date": START, "end_date": END}},
    "get_constituents": {"kwargs": {"index": INDEX}},
    "get_history_constituents": {"kwargs": {"index": INDEX, "start_date": "2026-10-01", "end_date": END}},
    "get_industry": {"kwargs": {"code": "C"}},
    "get_sector": {"kwargs": {"code": "007001"}},
    "get_concept": {"kwargs": {"code": "007001"}},
    "stk_get_adj_factor": {"kwargs": {"symbol": STOCK, "start_date": LONG_START, "end_date": END}},
    "stk_get_dividend": {"kwargs": {"symbol": STOCK, "start_date": LONG_START, "end_date": END}},
    "stk_get_daily_basic": {"kwargs": {"symbol": STOCK, "fields": "tclose,turnrate,ttl_shr,circ_shr",
                                       "start_date": START, "end_date": END}},
    "stk_get_daily_basic_pt": {"kwargs": {"symbols": [STOCK, STOCK2],
                                          "fields": "tclose,turnrate,ttl_shr,circ_shr",
                                          "trade_date": TRADE_DATE}},
    "stk_get_daily_mktvalue": {"kwargs": {"symbol": STOCK, "fields": "tot_mv,tot_mv_csrc,a_mv",
                                          "start_date": START, "end_date": END}},
    "stk_get_daily_mktvalue_pt": {"kwargs": {"symbols": [STOCK, STOCK2],
                                             "fields": "tot_mv,tot_mv_csrc,a_mv",
                                             "trade_date": TRADE_DATE}},
    "stk_get_daily_valuation": {"kwargs": {"symbol": STOCK, "fields": "pe_ttm,pe_lyr,pe_mrq",
                                           "start_date": START, "end_date": END}},
    "stk_get_daily_valuation_pt": {"kwargs": {"symbols": [STOCK, STOCK2],
                                              "fields": "pe_ttm,pe_lyr,pe_mrq",
                                              "trade_date": TRADE_DATE}},
    "stk_get_index_constituents": {"kwargs": {"index": INDEX, "trade_date": TRADE_DATE}},
    "stk_get_industry_category": {"kwargs": {"source": "zjh2012", "level": 1}},
    "stk_get_industry_constituents": {"kwargs": {"industry_code": "C", "date": TRADE_DATE}},
    "stk_get_sector_category": {"kwargs": {"sector_type": "1003"}},
    "stk_get_sector_constituents": {"kwargs": {"sector_code": "007001"}},
    "stk_get_money_flow": {"kwargs": {"symbols": [STOCK, STOCK2], "trade_date": TRADE_DATE}},
    "stk_get_share_change": {"kwargs": {"symbol": STOCK, "start_date": LONG_START, "end_date": END}},
    "stk_get_shareholder_num": {"kwargs": {"symbol": STOCK, "start_date": LONG_START, "end_date": END}},
    "stk_get_symbol_industry": {"kwargs": {"symbols": [STOCK, STOCK2], "source": "zjh2012", "level": 1}},
    "stk_get_symbol_sector": {"kwargs": {"symbols": [STOCK, STOCK2], "sector_type": "1003"}},
    "stk_get_top_shareholder": {"kwargs": {"symbol": STOCK, "start_date": LONG_START, "end_date": END}},
    "stk_get_ration": {"kwargs": {"symbol": STOCK, "start_date": LONG_START, "end_date": END}},
    "stk_get_fundamentals_balance": {"kwargs": {"symbol": STOCK, "fields": "mny_cptl,trd_fin_ast,fix_ast",
                                                "start_date": LONG_START, "end_date": END}},
    "stk_get_fundamentals_balance_pt": {"kwargs": {"symbols": [STOCK, STOCK2], "fields": "fix_ast",
                                                   "date": "2026-09-30"}},
    "stk_get_fundamentals_cashflow": {"kwargs": {"symbol": STOCK, "fields": "net_cf_oper",
                                                 "start_date": LONG_START, "end_date": END}},
    "stk_get_fundamentals_cashflow_pt": {"kwargs": {"symbols": [STOCK, STOCK2], "fields": "net_cf_oper",
                                                    "date": "2026-09-30"}},
    "stk_get_fundamentals_income": {"kwargs": {"symbol": STOCK, "fields": "net_prof,oper_prof",
                                               "start_date": LONG_START, "end_date": END}},
    "stk_get_fundamentals_income_pt": {"kwargs": {"symbols": [STOCK, STOCK2], "fields": "net_prof,oper_prof",
                                                  "date": "2026-09-30"}},
    "stk_get_finance_audit": {"kwargs": {"symbols": [STOCK], "date": TODAY}},
    "stk_get_finance_deriv": {"kwargs": {"symbol": STOCK, "fields": "eps_basic,eps_dil2,eps_dil",
                                         "start_date": LONG_START, "end_date": END}},
    "stk_get_finance_deriv_pt": {"kwargs": {"symbols": [STOCK, STOCK2], "fields": "eps_basic,eps_dil2",
                                            "date": "2026-09-30"}},
    "stk_get_finance_forecast": {"kwargs": {"symbols": [STOCK, STOCK2], "date": TODAY}},
    "stk_get_finance_prime": {"kwargs": {"symbol": STOCK, "fields": "eps_basic,eps_dil",
                                         "start_date": LONG_START, "end_date": END}},
    "stk_get_finance_prime_pt": {"kwargs": {"symbols": [STOCK, STOCK2], "fields": "eps_basic,eps_dil",
                                            "date": "2026-09-30"}},
    "fut_get_continuous_contracts": {"kwargs": {"csymbol": FUTURE_PRODUCT, "start_date": START, "end_date": END}},
    "fut_get_contract_info": {"kwargs": {"product_codes": [FUTURE_PRODUCT]}},
    "fut_get_transaction_ranking": {"kwargs": {"symbol": FUTURE, "trade_date": TRADE_DATE}},
    "fut_get_transaction_rankings": {"kwargs": {"symbols": [FUTURE], "trade_date": TRADE_DATE,
                                                "indicators": "volume"}},
    "fut_get_warehouse_receipt": {"kwargs": {"product_code": "RB", "start_date": START, "end_date": END}},
    "get_continuous_contracts": {"kwargs": {"csymbol": FUTURE_PRODUCT, "start_date": START, "end_date": END}},
    "get_contract_expire_rest_days": {"kwargs": {"symbols": [FUTURE], "start_date": TODAY, "end_date": TODAY}},
    "get_expire_rest_days": {"kwargs": {"symbols": [FUTURE], "trade_date": TODAY}},
    "fnd_get_adj_factor": {"kwargs": {"fund": FUND, "start_date": LONG_START, "end_date": END}},
    "fnd_get_dividend": {"kwargs": {"fund": FUND, "start_date": LONG_START, "end_date": END}},
    "fnd_get_etf_constituents": {"kwargs": {"etf": FUND}},
    "fnd_get_net_value": {"kwargs": {"fund": FUND, "start_date": LONG_START, "end_date": END}},
    "fnd_get_portfolio": {"kwargs": {"fund": FUND, "report_type": 4, "portfolio_type": "stk",
                                     "start_date": LONG_START, "end_date": END}},
    "fnd_get_share": {"kwargs": {"fund": FUND, "start_date": LONG_START, "end_date": END}},
    "fnd_get_split": {"kwargs": {"fund": FUND, "start_date": LONG_START, "end_date": END}},
    "bnd_get_amount_change": {"kwargs": {"symbol": BOND, "start_date": LONG_START, "end_date": END}},
    "bnd_get_analysis": {"kwargs": {"symbol": BOND, "start_date": LONG_START, "end_date": END}},
    "bnd_get_call_info": {"kwargs": {"symbol": BOND, "start_date": LONG_START, "end_date": END}},
    "bnd_get_conversion_price": {"kwargs": {"symbol": BOND, "start_date": LONG_START, "end_date": END}},
    "bnd_get_put_info": {"kwargs": {"symbol": BOND, "start_date": LONG_START, "end_date": END}},
    "option_calculate_delta": {"kwargs": OPTION_ARGS},
    "option_calculate_gamma": {"kwargs": OPTION_ARGS},
    "option_calculate_greeks": {"kwargs": OPTION_ARGS},
    "option_calculate_hv": {"kwargs": {"price": [100 + (i % 7) * 0.3 for i in range(60)], "frequency": "1d"}},
    "option_calculate_iv": {"kwargs": {"p": 10, "s": 100, "k": 100, "t": 0.25, "call_or_put": "C"}},
    "option_calculate_ivsurface": {"kwargs": {"underlying_symbol": "DCE.V", "call_or_put": "C",
                                              "trade_date": TRADE_DATE}, "timeout": 30, "sdk_bug": True},
    "option_calculate_price": {"kwargs": OPTION_ARGS},
    "option_calculate_rho": {"kwargs": OPTION_ARGS},
    "option_calculate_t": {"kwargs": {"start_time": TODAY, "end_time": "2027-03-01"}},
    "option_calculate_theta": {"kwargs": OPTION_ARGS},
    "option_calculate_vega": {"kwargs": OPTION_ARGS},
    "option_get_comb_info": {"kwargs": {"exchange": "SHFE", "optcomb_code": ""}, "timeout": 45},
    "option_get_comb_pos": {"kwargs": {"optcomb_code": ""}, "timeout": 45},
    "option_get_delisted_dates": {"skip": "SDK_HANG: 期权链查询在当前终端 >60s 无响应"},
    "option_get_exercise_prices": {"skip": "SDK_HANG: 期权链查询在当前终端 >60s 无响应"},
    "option_get_symbols_by_exchange": {"skip": "SDK_HANG: 期权链查询在当前终端 >60s 无响应"},
    "option_get_symbols_by_in_at_out": {"kwargs": {"underlying_symbol": "DCE.V",
                                                    "trade_date": TRADE_DATE, "execute_month": 1,
                                                    "call_or_put": "C", "in_at_out": "at", "s": 5000},
                                          "timeout": 30, "sdk_bug": True},
    "get_history_bars_l2": {"kwargs": {"symbols": [STOCK], "frequency": "60s",
                                       "start_time": f"{TRADE_DATE} 09:30:00", "end_time": f"{TRADE_DATE} 15:00:00"}},
    "get_history_l2bars": {"kwargs": {"symbols": [STOCK], "frequency": "60s",
                                      "start_time": f"{TRADE_DATE} 09:30:00", "end_time": f"{TRADE_DATE} 15:00:00"}},
    "get_history_l2orders": {"kwargs": {"symbols": [STOCK],
                                        "start_time": f"{TRADE_DATE} 09:30:00", "end_time": f"{TRADE_DATE} 15:00:00"}},
    "get_history_l2orders_queue": {"kwargs": {"symbols": [STOCK],
                                              "start_time": f"{TRADE_DATE} 09:30:00", "end_time": f"{TRADE_DATE} 15:00:00"}},
    "get_history_l2ticks": {"kwargs": {"symbols": [STOCK],
                                       "start_time": f"{TRADE_DATE} 09:30:00", "end_time": f"{TRADE_DATE} 15:00:00"}},
    "get_history_l2transactions": {"kwargs": {"symbols": [STOCK],
                                              "start_time": f"{TRADE_DATE} 09:30:00", "end_time": f"{TRADE_DATE} 15:00:00"}},
    "get_history_ticks_l2": {"kwargs": {"symbols": [STOCK],
                                        "start_time": f"{TRADE_DATE} 09:30:00", "end_time": f"{TRADE_DATE} 15:00:00"}},
    "get_history_transaction_l2": {"kwargs": {"symbols": [STOCK],
                                              "start_time": f"{TRADE_DATE} 09:30:00", "end_time": f"{TRADE_DATE} 15:00:00"}},
    "get_version": {"kwargs": {}},
    "get_strerror": {"kwargs": {"error_code": 0}},
    "last_tick": {"kwargs": {"symbols": [STOCK]}},
    "current_price": {"kwargs": {"symbols": [STOCK]}},
    "current": {"kwargs": {"symbols": [STOCK]}},
    "stk_hk_inst_holding_detail_info": {"kwargs": {"symbols": [STOCK], "trade_date": TRADE_DATE}},
    "stk_hk_inst_holding_info": {"kwargs": {"symbols": [STOCK], "trade_date": TRADE_DATE}},
    "stk_quota_shszhk_infos": {"kwargs": {"count": 20}},
    "stk_active_stock_top10_shszhk_info": {"kwargs": {"trade_date": TRADE_DATE}},
    "stk_abnor_change_detail": {"kwargs": {"trade_date": TRADE_DATE}},
    "stk_abnor_change_stocks": {"kwargs": {"trade_date": TRADE_DATE}},
    "ipo_get_instruments": {"kwargs": {"sec_type": 1}},
    "ipo_get_lot_info": {"kwargs": {"start_time": "2026-01-01", "end_time": END}},
    "ipo_get_match_number": {"kwargs": {"start_time": "2026-01-01", "end_time": END}},
    "ipo_get_quota": {"kwargs": {}},
}


def summarize(value: Any) -> dict:
    if isinstance(value, list):
        return {"type": "list", "count": len(value), "sample": value[:1]}
    if isinstance(value, dict):
        if value.get("__type__") == "DataFrame":
            rows = value.get("data") or []
            return {"type": "DataFrame", "count": len(rows), "columns": value.get("columns"),
                    "sample": rows[:1]}
        return {"type": "dict", "keys": list(value)[:10], "sample": value}
    if value is None:
        return {"type": "null"}
    return {"type": type(value).__name__, "value": value}


def classify(result: dict) -> str:
    if not result.get("success"):
        code = str(result.get("error_code") or "")
        text = str(result.get("error") or "")
        low = text.lower()
        if "无此数据接口权限" in text or '"status": 2001' in text or "权限" in text:
            return "SDK_NO_PERMISSION"
        if '"status": 1013' in text or "交易服务调用错误" in text:
            return "SDK_TRADE_ERROR"
        if "字段不能为空" in text or "无效的 fields" in text or '"status": 1027' in text:
            return "PARAM_INVALID"
        if "1030" in text or "不支持" in text or "not support" in low:
            return "MODE_LIMITED"
        if "timed out" in low or "超时" in text:
            return "TIMEOUT"
        if "No module named" in text or "ModuleNotFound" in text:
            return "DEPENDENCY_MISSING"
        if code:
            return f"ERROR:{code}"
        return "ERROR"
    data = result.get("data")
    if isinstance(data, dict) and data.get("__type__") == "DataFrame":
        return "PASS" if data.get("data") else "EMPTY"
    if isinstance(data, (list, dict)) and len(data) == 0:
        return "EMPTY"
    return "PASS"


def run_gm(client: Client, out_path: Path, offset: int = 0):
    _, methods = client.get("/api/v1/gm/rpc/methods", timeout=30)
    all_methods = [m for m in methods.get("methods", []) if m["module"] == "gmdata"]
    names = [m["name"] for m in all_methods]
    missing = sorted(set(names) - set(GM_PROBES))
    extra = sorted(set(GM_PROBES) - set(names))
    if missing or extra:
        raise RuntimeError(f"probe coverage mismatch missing={missing} extra={extra}")

    report = {
        "provider": "gm",
        "module": "gmdata",
        "method_count": len(names),
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": [],
        "counts": {},
    }
    for idx, name in enumerate(names):
        if idx < offset:
            continue
        spec = GM_PROBES[name]
        timed_out = False
        if "skip" in spec:
            report["results"].append({
                "index": idx, "function": name, "status": "SKIP", "detail": spec["skip"],
                "execution_time_ms": 0,
            })
            print(f"[{idx:03d}] {name}: SKIP {spec['skip']}", flush=True)
        else:
            timeout = int(spec.get("timeout", 60))
            t0 = time.time()
            status, result = client.rpc("gm", "gmdata", name, spec.get("kwargs", {}), timeout=timeout)
            elapsed = round((time.time() - t0) * 1000)
            cls = classify(result)
            if spec.get("sdk_bug") and cls.startswith("ERROR"):
                cls = "SDK_BUG"
            timed_out = cls == "TIMEOUT" or status == 0
            entry = {
                "index": idx, "function": name, "status": cls,
                "http_status": status, "execution_time_ms": elapsed,
                "kwargs": spec.get("kwargs", {}),
                "error_code": result.get("error_code"),
                "error": result.get("error"),
                "data_summary": summarize(result.get("data")) if result.get("success") else None,
            }
            report["results"].append(entry)
            print(f"[{idx:03d}] {name}: {cls} {elapsed}ms "
                  f"{str(result.get('error') or '')[:120]}", flush=True)
        counts: dict[str, int] = {}
        for entry in report["results"]:
            counts[entry["status"]] = counts.get(entry["status"], 0) + 1
        report["counts"] = counts
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if timed_out:
            print("TIMEOUT: GM data lane may be stuck; stop here and restart gateway.", flush=True)
            break
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    parser.add_argument("--out", default="data/itest/20261123/gm_full_sweep.json")
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    client = Client(args.base, load_api_key(ROOT / ".env"))
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report = run_gm(client, out_path, args.offset)
    print(json.dumps(report["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
