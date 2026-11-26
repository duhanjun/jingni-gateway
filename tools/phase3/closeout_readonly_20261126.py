"""15:00 收盘只读对账（GM/TDX）。

只做查询，不发送任何下单/撤单请求。输出：
- GM/TDX health、资产、委托、持仓
- open 委托计数与 order_id 列表
- 与今日基线（GM nav≈99967.7999，已扣除 P4-02 两笔 ETF 佣金及价差；TDX cash/asset≈1000147.22）的差异
- D 盘剩余空间、网关 err 日志尾部异常行
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:8010"
OUT = ROOT / "data/itest/20261126/phase3_closeout_reconciliation.json"
GM_NAV_BASELINE = 99967.79994487762
TDX_CASH_BASELINE = 1000147.22
ASSET_TOL = 1.0
OPEN_STATUS = {1, 2, 4}


def load_env() -> dict[str, str]:
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def request(method: str, path: str, payload: dict | None = None, timeout: float = 45):
    key = load_env().get("JINGNI_API_KEY", "")
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"X-API-Key": key, "Content-Type": "application/json"},
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


def unwrap(resp):
    body = resp.get("data") if isinstance(resp, dict) else None
    if isinstance(body, dict) and "data" in body:
        return body.get("data")
    return body


def as_dict(resp) -> dict:
    data = unwrap(resp)
    return data if isinstance(data, dict) else {}


def as_list(resp) -> list:
    data = unwrap(resp)
    return data if isinstance(data, list) else []


def float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def mask(account: str) -> str:
    return f"{account[:8]}...{account[-4:]}" if len(account) > 10 else "***"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    env = load_env()
    gm_account = env.get("JINGNI_GM_ACCOUNT_ID", "")
    report = {
        "item": "phase3_closeout_reconciliation",
        "trade_date": "2026-11-26",
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "read-only",
        "scope": "GM/TDX simulated accounts",
        "account_masked": mask(gm_account),
        "criteria": [
            "GM/TDX health=healthy",
            "open 委托=0、持仓=0",
            "GM nav≈99967.7999（P4-02 佣金/价差后）；TDX cash=asset≈1000147.22、TotalFreeze=0",
            "无新增 Traceback/5xx；D 盘空间可用",
        ],
        "responses": {},
    }

    _, agg, _ = request("GET", "/health", timeout=15)
    _, gm_h, _ = request("GET", "/api/v1/gm/health", timeout=30)
    _, gm_a, _ = request("GET", "/api/v1/gm/trade/asset", timeout=30)
    _, gm_o, _ = request("GET", "/api/v1/gm/trade/orders", timeout=30)
    _, gm_p, _ = request("GET", "/api/v1/gm/trade/positions", timeout=30)
    _, tdx_h, _ = request("GET", "/api/v1/tdxquant/health", timeout=30)
    _, tdx_a, _ = request("GET", "/api/v1/tdxquant/trade/asset", timeout=30)
    _, tdx_o, _ = request("GET", "/api/v1/tdxquant/trade/orders", timeout=30)
    _, tdx_p, _ = request("GET", "/api/v1/tdxquant/trade/positions", timeout=30)
    report["responses"].update({
        "aggregate_health": agg, "gm_health": gm_h, "gm_asset": gm_a,
        "gm_orders": gm_o, "gm_positions": gm_p, "tdx_health": tdx_h,
        "tdx_asset": tdx_a, "tdx_orders": tdx_o, "tdx_positions": tdx_p,
    })

    gm_health = as_dict(gm_h) or gm_h
    tdx_health = as_dict(tdx_h) or tdx_h
    gm_asset = as_dict(gm_a)
    tdx_asset = as_dict(tdx_a)
    gm_orders = as_list(gm_o)
    tdx_orders = as_list(tdx_o)
    gm_positions = as_list(gm_p)
    tdx_positions = as_list(tdx_p)

    def status_int(row):
        try:
            return int(row.get("status"))
        except (TypeError, ValueError):
            return None

    gm_open = [o for o in gm_orders if status_int(o) in OPEN_STATUS]
    tdx_open = [o for o in tdx_orders if status_int(o) in OPEN_STATUS]

    gm_nav = float_or_none(gm_asset.get("nav"))
    gm_available = float_or_none(gm_asset.get("available"))
    tdx_cash = float_or_none(tdx_asset.get("cash"))
    tdx_asset_value = float_or_none(tdx_asset.get("asset"))
    tdx_freeze = float_or_none((tdx_asset.get("raw") or {}).get("TotalFreeze"))
    gm_nav_diff = round(abs(gm_nav - GM_NAV_BASELINE), 4) if gm_nav is not None else None
    tdx_cash_diff = round(abs(tdx_cash - TDX_CASH_BASELINE), 4) if tdx_cash is not None else None

    err_path = ROOT / "data/itest/20261126/gateway_20261126.err.log"
    err_lines = []
    if err_path.exists():
        tail = err_path.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]
        err_lines = [line for line in tail if "ERROR" in line or "Traceback" in line or "Exception" in line]

    disk_free_gb = round(shutil.disk_usage("D:\\").free / (1024 ** 3), 2)
    report["state"] = {
        "aggregate_status": agg.get("status") if isinstance(agg, dict) else None,
        "providers": list((agg.get("providers") or {}).keys()) if isinstance(agg, dict) else [],
        "gm": {
            "health_status": gm_health.get("status") if isinstance(gm_health, dict) else None,
            "orders_total": len(gm_orders), "open_orders": len(gm_open),
            "open_order_ids": [str(o.get("order_id")) for o in gm_open],
            "positions": len(gm_positions), "nav": gm_nav, "available": gm_available,
            "nav_diff": gm_nav_diff,
        },
        "tdx": {
            "health_status": tdx_health.get("status") if isinstance(tdx_health, dict) else None,
            "orders_total": len(tdx_orders), "open_orders": len(tdx_open),
            "open_order_ids": [str(o.get("order_id")) for o in tdx_open],
            "positions": len(tdx_positions), "cash": tdx_cash, "asset": tdx_asset_value,
            "total_freeze": tdx_freeze, "cash_diff": tdx_cash_diff,
        },
        "disk_d_free_gb": disk_free_gb,
        "err_log_tail_error_lines": err_lines,
    }

    checks = {
        "aggregate_healthy": (agg.get("status") if isinstance(agg, dict) else None) == "healthy",
        "gm_healthy": (gm_health.get("status") if isinstance(gm_health, dict) else None) == "healthy",
        "tdx_healthy": (tdx_health.get("status") if isinstance(tdx_health, dict) else None) == "healthy",
        "gm_no_open_orders": len(gm_open) == 0,
        "tdx_no_open_orders": len(tdx_open) == 0,
        "gm_no_positions": len(gm_positions) == 0,
        "tdx_no_positions": len(tdx_positions) == 0,
        "gm_nav_matches": gm_nav_diff is not None and gm_nav_diff <= ASSET_TOL,
        "tdx_cash_matches": tdx_cash_diff is not None and tdx_cash_diff <= ASSET_TOL,
        "tdx_freeze_zero": tdx_freeze is not None and abs(tdx_freeze) <= 0.01,
    }
    report["checks"] = checks
    report["verdict"] = "CLOSEOUT_CLEAN" if all(checks.values()) else "CLOSEOUT_REVIEW"

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"evidence: {out}")
    print(
        f"verdict: {report['verdict']} "
        f"gm_open={len(gm_open)} tdx_open={len(tdx_open)} "
        f"gm_nav_diff={gm_nav_diff} tdx_cash_diff={tdx_cash_diff} "
        f"disk_free_gb={disk_free_gb} err_lines={len(err_lines)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
