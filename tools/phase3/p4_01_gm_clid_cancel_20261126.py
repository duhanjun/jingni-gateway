"""P4-01：GM 模拟账户按 cl_ord_id 撤单（仅模拟盘，100 股不可成交限价）。

安全边界：
- 账户 ID 前后缀匹配已知 GM 模拟账户；
- nav 基线 99977.8999 ±1，无 open 单、无持仓；
- 600000.SH 100 股限价 9.66 买入，当前价必须显著高于 9.66，确保不可成交；
- 下单后从终端委托中取券商返回的 cl_ord_id，按 cl_ord_id 撤单；
- 终态 status=5/12、持仓=0、无 open 单、nav diff<=1 才 PASS。
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BASE = "http://127.0.0.1:8010"
OUT = ROOT / "data/itest/20261126/gm_clid_cancel_20261126.json"
SYMBOL = "SHSE.600000"
VOLUME = 100
PRICE = 9.66
CLIENT_ID = "itest-gm-clid-20261126"
EXPECTED_ACCOUNT_PREFIX = "7aa03150"
EXPECTED_ACCOUNT_SUFFIX = "2aa6"
EXPECTED_NAV = 99977.89996147156
NAV_TOL = 1.0
OPEN_STATUS = ("1", "2")
FINAL_STATUS = ("5", "12")


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


def unwrap(resp: dict):
    body = resp.get("data") if isinstance(resp, dict) else None
    if isinstance(body, dict) and "data" in body:
        return body.get("data")
    return body


def rows(resp: dict) -> list:
    data = unwrap(resp)
    return data if isinstance(data, list) else []


def find_order(rows_: list, **criteria) -> dict | None:
    for row in rows_:
        if all(str(row.get(key)) == str(value) for key, value in criteria.items()):
            return row
    return None


def asset_values(resp: dict) -> dict:
    data = unwrap(resp)
    if not isinstance(data, dict):
        data = {}
    def f(key):
        try:
            return float(data.get(key))
        except (TypeError, ValueError):
            return None
    return {"nav": f("nav"), "available": f("available"), "balance": f("balance")}


def mask_account(account: str) -> str:
    if len(account) <= 10:
        return "***"
    return f"{account[:8]}...{account[-4:]}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-sim", action="store_true")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    dry_run = not args.confirm_sim

    env = load_env()
    account = env.get("JINGNI_GM_ACCOUNT_ID", "")
    report = {
        "item": "p4_01_gm_clid_cancel",
        "trade_date": "2026-11-26",
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "dry-run" if dry_run else "sim-live",
        "account_scope": "simulated",
        "account_masked": mask_account(account),
        "criteria": [
            "账户 ID 前后缀匹配已知 GM 模拟账户",
            "基线 nav≈99977.8999，无在途委托/持仓",
            "100 股限价买入 600000.SH @9.66 受理，且当前价显著高于 9.66",
            "按券商返回的 cl_ord_id 撤单，cancel_state=confirmed，status=5/12",
            "撤单后 nav diff<=1、持仓=0、无 open 单",
        ],
        "planned_order": {
            "symbol": SYMBOL, "volume": VOLUME, "side": 0,
            "order_type": 0, "price": PRICE, "position_effect": 1,
            "client_order_id": CLIENT_ID,
        },
        "responses": {},
    }

    _, health, _ = request("GET", "/api/v1/gm/health")
    _, asset0, _ = request("GET", "/api/v1/gm/trade/asset")
    _, orders0, _ = request("GET", "/api/v1/gm/trade/orders")
    _, positions0, _ = request("GET", "/api/v1/gm/trade/positions")
    report["responses"].update({"health": health, "asset_before": asset0,
                                "orders_before": orders0, "positions_before": positions0})

    health_data = unwrap(health)
    if not health_data:
        health_data = health
    asset_before = asset_values(asset0)
    open_orders = [o for o in rows(orders0) if str(o.get("status")) in OPEN_STATUS]
    positions = rows(positions0)
    preconditions = {
        "account_prefix_ok": account.startswith(EXPECTED_ACCOUNT_PREFIX),
        "account_suffix_ok": account.endswith(EXPECTED_ACCOUNT_SUFFIX),
        "health_status": health_data.get("status") or health.get("status"),
        "account_configured": bool(health_data.get("account_configured")),
        "token_configured": bool(health_data.get("token_configured")),
        "gmtrade_available": bool(health_data.get("gmtrade_available")),
        "nav_ok": asset_before["nav"] is not None and abs(asset_before["nav"] - EXPECTED_NAV) <= NAV_TOL,
        "no_open_orders": len(open_orders) == 0,
        "no_positions": len(positions) == 0,
    }

    quote_status, quote_resp, quote_elapsed = request(
        "POST", "/api/v1/gm/rpc/execute",
        {"module": "gmdata", "function": "current", "kwargs": {"symbols": [SYMBOL]}, "timeout": 30},
    )
    quote_rows = unwrap(quote_resp) or []
    quote = quote_rows[0] if isinstance(quote_rows, list) and quote_rows else None
    current_price = None
    if isinstance(quote, dict):
        try:
            current_price = float(quote.get("price"))
        except (TypeError, ValueError):
            current_price = None
    price_safe = current_price is not None and current_price > PRICE + 0.05
    preconditions["quote_http_status"] = quote_status
    preconditions["current_price"] = current_price
    preconditions["price_non_marketable"] = price_safe

    report["preconditions"] = preconditions
    report["baseline"] = {
        "nav": asset_before["nav"], "available": asset_before["available"],
        "open_orders": len(open_orders), "positions": len(positions),
        "quote": quote, "quote_elapsed_ms": quote_elapsed,
    }

    ready = all([
        preconditions["account_prefix_ok"], preconditions["account_suffix_ok"],
        preconditions["health_status"] == "healthy", preconditions["account_configured"],
        preconditions["token_configured"], preconditions["gmtrade_available"],
        preconditions["nav_ok"], preconditions["no_open_orders"], preconditions["no_positions"],
        price_safe,
    ])
    if not ready:
        report["verdict"] = "SAFETY_HALT_PRECONDITION"
        out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"evidence: {out}")
        print(f"verdict: {report['verdict']} dry_run={dry_run}")
        return 0

    if dry_run:
        report["verdict"] = "DRY_RUN_READY"
        out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"evidence: {out}")
        print(f"verdict: {report['verdict']} dry_run={dry_run}")
        return 0

    # 1) 下单
    status, placed, elapsed = request("POST", "/api/v1/gm/trade/order", report["planned_order"])
    report["responses"]["place"] = placed
    report["place_http_status"] = status
    report["place_elapsed_ms"] = elapsed
    placed_body = unwrap(placed) if isinstance(placed, dict) else {}
    order_id = placed_body.get("order_id") or (placed.get("order_id") if isinstance(placed, dict) else None)
    returned_cl_ord_id = placed_body.get("cl_ord_id")
    report["order_id"] = order_id
    report["returned_cl_ord_id"] = returned_cl_ord_id
    if not order_id or not placed_body.get("success"):
        report["verdict"] = "PLACE_FAILED"
        out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"evidence: {out}")
        print(f"verdict: {report['verdict']} order_id={order_id}")
        return 0

    # 2) 确认终端委托，并从终端记录取权威 cl_ord_id
    time.sleep(0.5)
    _, orders1, _ = request("GET", "/api/v1/gm/trade/orders")
    report["responses"]["orders_after_place"] = orders1
    matched = find_order(rows(orders1), order_id=str(order_id))
    report["order_after_place"] = matched
    if matched is None:
        report["verdict"] = "ORDER_NOT_FOUND_IN_TERMINAL"
        out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"evidence: {out}")
        print(f"verdict: {report['verdict']} order_id={order_id}")
        return 0

    terminal_cl_ord_id = matched.get("cl_ord_id")
    report["terminal_cl_ord_id"] = terminal_cl_ord_id
    if not terminal_cl_ord_id:
        report["verdict"] = "CL_ORD_ID_MISSING"
        out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"evidence: {out}")
        print(f"verdict: {report['verdict']} order_id={order_id}")
        return 0

    # 3) 按 cl_ord_id 撤单，最多尝试 3 次
    cancel_responses = []
    for attempt in range(1, 4):
        status, cancel, elapsed = request(
            "POST", "/api/v1/gm/trade/cancel", {"cl_ord_id": str(terminal_cl_ord_id)}
        )
        cancel_responses.append({
            "attempt": attempt, "http_status": status, "response": cancel,
            "elapsed_ms": elapsed,
        })
        cancel_body = unwrap(cancel)
        if isinstance(cancel_body, dict) and cancel_body.get("cancel_state") == "confirmed":
            break
        time.sleep(0.5)
    report["responses"]["cancel_by_cl_ord_id"] = cancel_responses

    # 4) 轮询终态
    final_order = None
    final_orders = []
    for _ in range(12):
        time.sleep(0.3)
        _, orders2, _ = request("GET", "/api/v1/gm/trade/orders")
        final_orders = rows(orders2)
        final_order = find_order(final_orders, order_id=str(order_id))
        if final_order is not None and str(final_order.get("status")) in FINAL_STATUS:
            break
    report["responses"]["orders_after_cancel"] = final_orders
    report["order_after_cancel"] = final_order

    # 5) 资产/持仓/在途对账
    _, asset1, _ = request("GET", "/api/v1/gm/trade/asset")
    _, positions1, _ = request("GET", "/api/v1/gm/trade/positions")
    _, orders3, _ = request("GET", "/api/v1/gm/trade/orders")
    report["responses"].update({"asset_after": asset1, "positions_after": positions1,
                                "orders_final": orders3})
    asset_after = asset_values(asset1)
    positions_after = rows(positions1)
    open_after = [o for o in rows(orders3) if str(o.get("status")) in OPEN_STATUS]
    nav_diff = None
    if asset_before["nav"] is not None and asset_after["nav"] is not None:
        nav_diff = round(abs(asset_after["nav"] - asset_before["nav"]), 4)
    report["reconciliation"] = {
        "nav_before": asset_before["nav"], "nav_after": asset_after["nav"],
        "nav_diff": nav_diff, "positions_after": len(positions_after),
        "open_orders_after": len(open_after),
        "final_status": final_order.get("status") if final_order else None,
    }

    cancel_confirmed = any(
        isinstance(unwrap(item["response"]), dict)
        and unwrap(item["response"]).get("cancel_state") == "confirmed"
        for item in cancel_responses
    )
    final_status_ok = final_order is not None and str(final_order.get("status")) in FINAL_STATUS
    nav_ok = nav_diff is not None and nav_diff <= NAV_TOL
    clean = len(positions_after) == 0 and len(open_after) == 0
    if all([cancel_confirmed, final_status_ok, nav_ok, clean]):
        report["verdict"] = "GM_CLID_CANCEL_PASS"
    else:
        report["verdict"] = "GM_CLID_CANCEL_REVIEW"

    report["cancel_used_cl_ord_id"] = True
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"evidence: {out}")
    print(
        f"verdict: {report['verdict']} order_id={order_id} "
        f"cl_ord_id={terminal_cl_ord_id} status={report['reconciliation']['final_status']} "
        f"nav_diff={nav_diff} open={len(open_after)} positions={len(positions_after)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
