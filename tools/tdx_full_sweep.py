"""TDX 非交易时段数据 + 交易边界全量扫描。"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY = [
    line.split("=", 1)[1].strip().strip('"').strip("'")
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
    if line.startswith("JINGNI_API_KEY=")
][0]
BASE = "http://127.0.0.1:8010"
OUT = ROOT / "data/itest/20261123/tdx_full_sweep.json"


def request(method: str, path: str, payload: dict | None = None, timeout: float = 60):
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"X-API-Key": KEY, "Content-Type": "application/json"},
        method=method,
    )
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8", "replace")), round((time.time() - start) * 1000)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"raw": body}
        return exc.code, parsed, round((time.time() - start) * 1000)
    except Exception as exc:  # noqa: BLE001
        return 0, {"error": f"{type(exc).__name__}: {exc}"}, round((time.time() - start) * 1000)


def classify(result: dict) -> str:
    if not result.get("success"):
        code = result.get("error_code") or ""
        text = str(result.get("error") or "")
        if code:
            return f"ERROR:{code}"
        if "timed out" in text.lower() or "超时" in text:
            return "TIMEOUT"
        return "ERROR"
    data = result.get("data")
    if isinstance(data, (list, dict)) and len(data) == 0:
        return "EMPTY"
    return "PASS"


DATA_CASES = {
    "get_market_data": {"field_list": ["Open", "Close", "Volume"], "stock_list": ["688318.SH"],
                         "period": "1d", "start_time": "20261101", "end_time": "20261123", "count": -1},
    "get_market_snapshot": {"stock_code": "688318.SH", "field_list": []},
    "get_sector_list": {"list_type": 1},
    "get_stock_list_in_sector": {"block_code": "880201.SH"},
    "get_trading_dates": {"market": "SH", "start_time": "20261101", "end_time": "20261123", "count": -1},
    "get_divid_factors": {"stock_code": "688318.SH", "start_time": "20240101", "end_time": "20261123"},
    "get_stock_info": {"stock_code": "688318.SH", "field_list": []},
    "get_more_info": {"stock_code": "688318.SH", "field_list": []},
    "get_kzz_info": {"stock_code": "113648.SH", "field_list": []},
    "get_financial_data": {"stock_list": ["688318.SH"], "field_list": ["Fn193", "Fn194"],
                            "start_time": "20250101", "end_time": "", "report_type": "announce_time"},
    "get_stock_list": {"market": "SH"},
    "refresh_cache": {"market": "AG", "force": False},
}


def main():
    _, health, _ = request("GET", "/api/v1/tdxquant/health", timeout=30)
    _, methods, _ = request("GET", "/api/v1/tdxquant/rpc/methods", timeout=30)
    declared = [m["function"] for m in methods.get("methods", [])]
    missing = sorted(set(declared) - set(DATA_CASES))
    extra = sorted(set(DATA_CASES) - set(declared))
    if missing or extra:
        raise RuntimeError(f"TDX probe coverage mismatch missing={missing} extra={extra}")

    report = {"provider": "tdxquant", "health": health, "results": [], "trade": []}
    for idx, name in enumerate(declared):
        status, result, elapsed = request(
            "POST", "/api/v1/tdxquant/rpc/execute",
            {"module": "tdxdata", "function": name, "kwargs": DATA_CASES[name], "timeout": 60},
            timeout=80,
        )
        cls = classify(result)
        entry = {"index": idx, "function": name, "status": cls, "execution_time_ms": elapsed,
                 "http_status": status, "error": result.get("error"), "error_code": result.get("error_code"),
                 "data_type": type(result.get("data")).__name__ if result.get("success") else None,
                 "data_len": len(result.get("data")) if isinstance(result.get("data"), (list, dict)) else None}
        report["results"].append(entry)
        print(f"[{idx:02d}] {name}: {cls} {elapsed}ms {str(result.get('error') or '')[:120]}")

    trade_cases = [
        ("asset", "GET", "/api/v1/tdxquant/trade/asset", None),
        ("orders", "GET", "/api/v1/tdxquant/trade/orders", None),
        ("positions", "GET", "/api/v1/tdxquant/trade/positions", None),
        ("order_valid", "POST", "/api/v1/tdxquant/trade/order",
         {"stock_code": "600000.SH", "order_type": 0, "order_volume": 100,
          "price_type": 0, "price": 10.0, "notify": 0}),
        ("order_price_zero", "POST", "/api/v1/tdxquant/trade/order",
         {"stock_code": "600000.SH", "order_type": 0, "order_volume": 100,
          "price_type": 0, "price": 0, "notify": 0}),
        ("order_bad_code", "POST", "/api/v1/tdxquant/trade/order",
         {"stock_code": "600000", "order_type": 0, "order_volume": 100,
          "price_type": 0, "price": 10.0, "notify": 0}),
        ("cancel", "POST", "/api/v1/tdxquant/trade/cancel",
         {"stock_code": "600000.SH", "order_id": "999999"}),
        ("generic_trade_rpc", "POST", "/api/v1/tdxquant/rpc/execute",
         {"module": "tdxtrade", "function": "query_stock_asset", "kwargs": {}}),
    ]
    for name, method, path, payload in trade_cases:
        status, result, elapsed = request(method, path, payload, timeout=60)
        code = result.get("error_code") or ("HTTP_%s" % status if status != 200 else "OK")
        report["trade"].append({"case": name, "http_status": status, "success": result.get("success"),
                                "error_code": code, "error": result.get("error"), "execution_time_ms": elapsed})
        print(f"trade {name}: HTTP {status} success={result.get('success')} code={code}")

    counts: dict[str, int] = {}
    for entry in report["results"]:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    report["counts"] = counts
    report["health_logged_in"] = (
        (health.get("data") or {}).get("logged_in")
        if isinstance(health.get("data"), dict) else health.get("logged_in")
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
