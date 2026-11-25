"""2026-11-24 开盘期只读状态采集与边界复核。

不主动下单；只读取现有委托、持仓、资产，并复核 TDX 分钟数据、
快照新鲜度、GM last_tick/current_price 与错误载荷。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8010"
KEY = [
    line.split("=", 1)[1].strip().strip('"').strip("'")
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
    if line.startswith("JINGNI_API_KEY=")
][0]


def request(method: str, path: str, payload: dict | None = None, timeout: float = 60):
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=body,
        headers={"X-API-Key": KEY, "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return {"http_status": exc.code, **json.loads(raw)}
        except json.JSONDecodeError:
            return {"http_status": exc.code, "raw": raw}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"{type(exc).__name__}: {exc}", "client_error": True}


def main():
    out = {"date": "2026-11-24", "captured_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    out["gm_health"] = request("GET", "/api/v1/gm/health")
    out["tdx_health"] = request("GET", "/api/v1/tdxquant/health")
    out["gm_asset"] = request("GET", "/api/v1/gm/trade/asset")
    out["gm_positions"] = request("GET", "/api/v1/gm/trade/positions")
    out["gm_orders"] = request("GET", "/api/v1/gm/trade/orders")
    out["tdx_asset"] = request("GET", "/api/v1/tdxquant/trade/asset")
    out["tdx_positions"] = request("GET", "/api/v1/tdxquant/trade/positions")
    out["tdx_orders"] = request("GET", "/api/v1/tdxquant/trade/orders")

    td = {"module": "tdxdata", "args": [], "timeout": 30}
    data = {}
    for period in ("1m", "5m", "15m", "30m", "1h", "1d"):
        payload = {
            "module": "tdxdata",
            "function": "get_market_data",
            "args": [],
            "kwargs": {
                "field_list": ["Open", "High", "Low", "Close", "Volume"],
                "stock_list": ["600000.SH"],
                "period": period,
                "count": 10,
            },
            "timeout": 30,
        }
        data[period] = request("POST", "/api/v1/tdxquant/rpc/execute", payload)
    out["tdx_minute_data"] = data

    snapshot_payload = {
        "module": "tdxdata",
        "function": "get_market_snapshot",
        "args": [],
        "kwargs": {"stock_code": "600000.SH"},
        "timeout": 20,
    }
    s1 = request("POST", "/api/v1/tdxquant/rpc/execute", snapshot_payload)
    time.sleep(5)
    s2 = request("POST", "/api/v1/tdxquant/rpc/execute", snapshot_payload)
    out["tdx_snapshot_t1"] = s1
    out["tdx_snapshot_t2"] = s2

    out["tdx_invalid_period"] = request(
        "POST",
        "/api/v1/tdxquant/rpc/execute",
        {
            "module": "tdxdata",
            "function": "get_market_data",
            "args": [],
            "kwargs": {"field_list": ["Close"], "stock_list": ["600000.SH"], "period": "1min"},
            "timeout": 20,
        },
    )

    out["gm_current_price"] = request(
        "POST",
        "/api/v1/gm/rpc/execute",
        {
            "module": "gmdata",
            "function": "current_price",
            "args": [],
            "kwargs": {"symbols": ["SHSE.600000", "SHSE.601398", "SHSE.510300"]},
            "timeout": 20,
        },
    )
    # last_tick 当前会返回 1030/UnicodeDecodeError 并短时占用 GM 数据 lane，
    # 放在 current_price 之后，避免采集脚本自己造成后续请求超时。
    out["gm_last_tick"] = request(
        "POST",
        "/api/v1/gm/rpc/execute",
        {
            "module": "gmdata",
            "function": "last_tick",
            "args": [],
            "kwargs": {"symbols": ["SHSE.600000"]},
            "timeout": 20,
        },
    )
    out["tdx_refresh_cache"] = request(
        "POST",
        "/api/v1/tdxquant/rpc/execute",
        {
            "module": "tdxdata",
            "function": "refresh_cache",
            "args": [],
            "kwargs": {"market": "AG", "force": False},
            "timeout": 30,
        },
    )

    dest = ROOT / "data/itest/20261124/open_session_state.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(dest)
    print(json.dumps({
        "gm_asset": (out["gm_asset"].get("data") or {}) if out["gm_asset"].get("success") else out["gm_asset"],
        "gm_positions_count": len((out["gm_positions"].get("data") or [])),
        "gm_orders_count": len((out["gm_orders"].get("data") or [])),
        "tdx_asset": (out["tdx_asset"].get("data") or {}) if out["tdx_asset"].get("success") else out["tdx_asset"],
        "tdx_positions_count": len((out["tdx_positions"].get("data") or [])),
        "tdx_orders_count": len((out["tdx_orders"].get("data") or [])),
        "minute_periods": {
            k: ("DATA" if v.get("success") and (v.get("data") or {}) else "EMPTY" if v.get("success") else "ERROR")
            for k, v in data.items()
        },
        "snapshot_t1": {k: (s1.get("data") or {}).get(k) for k in ("Now", "Volume", "Amount", "NowVol")},
        "snapshot_t2": {k: (s2.get("data") or {}).get(k) for k in ("Now", "Volume", "Amount", "NowVol")},
        "gm_last_tick": out["gm_last_tick"],
        "gm_current_price": out["gm_current_price"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
