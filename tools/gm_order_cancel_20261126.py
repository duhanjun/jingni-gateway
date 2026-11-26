"""GM 模拟账户限价买入 -> 撤单 -> 幂等重放 -> 资产/持仓对账。

仅允许在已确认的 GM 模拟账户上运行；需要 --confirm-sim 才发送写请求。
安全前置：账户 ID 前后缀匹配、nav 基线匹配、无在途委托、无持仓。
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8010"
OUT = ROOT / "data/itest/20261126/gm_order_cancel.json"
SYMBOL = "SHSE.600000"
VOLUME = 100
PRICE = 9.66
CLIENT_ID = "itest-gm-cash-20261126"
DEFAULT_CLIENT_ID = CLIENT_ID
EXPECTED_ACCOUNT_PREFIX = "7aa03150"
EXPECTED_ACCOUNT_SUFFIX = "2aa6"
EXPECTED_NAV = 99977.89996147156
NAV_TOL = 1.0
OPEN_STATUS = ("1", "2")


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
    """兼容 {"success":true,"data":...} / 扁平健康对象 / data 为 list。"""
    body = resp.get("data") if isinstance(resp, dict) else None
    if isinstance(body, dict) and "data" in body:
        return body.get("data")
    return body


def mask_account(account: str) -> str:
    if len(account) <= 10:
        return "***"
    return f"{account[:8]}...{account[-4:]}"


def asset_values(resp: dict) -> dict:
    data = unwrap(resp)
    if not isinstance(data, dict):
        data = {}
    def f(key):
        try:
            return float(data.get(key))
        except (TypeError, ValueError):
            return None
    return {"nav": f("nav"), "available": f("available"), "balance": f("balance"), "raw": data}


def order_rows(resp: dict) -> list:
    data = unwrap(resp)
    return data if isinstance(data, list) else []


def find_order(rows: list, order_id: str) -> dict | None:
    for row in rows:
        if str(row.get("order_id")) == str(order_id):
            return row
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-sim", action="store_true")
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--client-id", default=DEFAULT_CLIENT_ID)
    args = parser.parse_args()
    dry_run = not args.confirm_sim

    env = load_env()
    account = env.get("JINGNI_GM_ACCOUNT_ID", "")
    report = {
        "item": "gm_order_cancel",
        "trade_date": "2026-11-26",
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "dry-run" if dry_run else "sim-live",
        "account_scope": "simulated",
        "account_masked": mask_account(account),
        "criteria": [
            "账户 ID 前后缀匹配已知 GM 模拟账户",
            "基线 nav≈99977.8999，无在途委托/持仓",
            "100 股限价买入 600000.SH @9.66 受理，status=1",
            "按 order_id 撤单，cancel_state=confirmed，status=5/12",
            "撤单后 nav/available 与基线一致，持仓仍为 0",
            "同 client_order_id 重放不新增委托",
        ],
        "planned_order": {
            "symbol": SYMBOL, "volume": VOLUME, "side": 0,
            "order_type": 0, "price": PRICE, "position_effect": 1,
            "client_order_id": args.client_id,
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
        # /api/v1/gm/health 直接返回扁平健康对象，没有 success/data 信封
        health_data = health
    asset_before = asset_values(asset0)
    open_orders = [o for o in order_rows(orders0) if str(o.get("status")) in OPEN_STATUS]
    positions = order_rows(positions0)
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
    report["preconditions"] = preconditions
    report["baseline"] = {"nav": asset_before["nav"], "available": asset_before["available"],
                          "open_orders": len(open_orders), "positions": len(positions)}

    ready = all([
        preconditions["account_prefix_ok"], preconditions["account_suffix_ok"],
        preconditions["health_status"] == "healthy", preconditions["account_configured"],
        preconditions["token_configured"], preconditions["gmtrade_available"],
        preconditions["nav_ok"], preconditions["no_open_orders"], preconditions["no_positions"],
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
    report["order_id"] = order_id
    if not order_id or not placed_body.get("success"):
        report["verdict"] = "PLACE_FAILED"
        out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"evidence: {out}")
        print(f"verdict: {report['verdict']} order_id={order_id}")
        return 0

    # 2) 查询并确认 open
    time.sleep(0.5)
    _, orders1, _ = request("GET", "/api/v1/gm/trade/orders")
    report["responses"]["orders_after_place"] = orders1
    matched = find_order(order_rows(orders1), str(order_id))
    report["order_after_place"] = matched
    if matched is None:
        report["verdict"] = "ORDER_NOT_FOUND_IN_TERMINAL"
        out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"evidence: {out}")
        print(f"verdict: {report['verdict']} order_id={order_id}")
        return 0

    # 3) 撤单，最多尝试 3 次
    cancel_responses = []
    for attempt in range(1, 4):
        status, cancel, elapsed = request("POST", "/api/v1/gm/trade/cancel", {"order_id": str(order_id)})
        cancel_responses.append({"attempt": attempt, "http_status": status, "response": cancel,
                                 "elapsed_ms": elapsed})
        cancel_body = unwrap(cancel)
        if cancel_body.get("cancel_state") == "confirmed":
            break
        time.sleep(0.5)
    report["responses"]["cancel"] = cancel_responses

    # 4) 轮询终态
    final_order = None
    final_orders = []
    for _ in range(10):
        time.sleep(0.3)
        _, orders2, _ = request("GET", "/api/v1/gm/trade/orders")
        final_orders = order_rows(orders2)
        final_order = find_order(final_orders, str(order_id))
        if final_order is not None and str(final_order.get("status")) in ("5", "12"):
            break
    report["responses"]["orders_after_cancel"] = final_orders
    report["order_after_cancel"] = final_order

    # 5) 资产/持仓对账
    _, asset1, _ = request("GET", "/api/v1/gm/trade/asset")
    _, positions1, _ = request("GET", "/api/v1/gm/trade/positions")
    report["responses"]["asset_after"] = asset1
    report["responses"]["positions_after"] = positions1
    asset_after = asset_values(asset1)
    positions_after = order_rows(positions1)
    nav_diff = None
    if asset_before["nav"] is not None and asset_after["nav"] is not None:
        nav_diff = round(abs(asset_after["nav"] - asset_before["nav"]), 4)
    report["reconciliation"] = {
        "nav_before": asset_before["nav"], "nav_after": asset_after["nav"],
        "nav_diff": nav_diff, "positions_after": len(positions_after),
        "final_status": final_order.get("status") if final_order else None,
    }

    # 6) 幂等重放
    status, replay, elapsed = request("POST", "/api/v1/gm/trade/order", report["planned_order"])
    report["responses"]["replay"] = replay
    report["replay_http_status"] = status
    report["replay_elapsed_ms"] = elapsed
    replay_body = unwrap(replay) if isinstance(replay, dict) else {}
    replay_id = replay_body.get("order_id") or (replay.get("order_id") if isinstance(replay, dict) else None)
    _, orders3, _ = request("GET", "/api/v1/gm/trade/orders")
    replay_orders = order_rows(orders3)
    report["responses"]["orders_after_replay"] = replay_orders
    report["idempotency"] = {
        "idempotent_replay": bool(replay_body.get("idempotent_replay")),
        "same_order_id": str(replay_id) == str(order_id) if replay_id else False,
        "order_count_before": len(final_orders), "order_count_after": len(replay_orders),
        "no_new_order": len(replay_orders) == len(final_orders),
    }

    cancel_confirmed = any(
        (unwrap(item["response"]).get("cancel_state") == "confirmed") for item in cancel_responses
    )
    final_status_ok = final_order is not None and str(final_order.get("status")) in ("5", "12")
    nav_ok = nav_diff is not None and nav_diff <= NAV_TOL
    no_position = len(positions_after) == 0
    idem_ok = report["idempotency"]["idempotent_replay"] and report["idempotency"]["same_order_id"] and report["idempotency"]["no_new_order"]
    if all([cancel_confirmed, final_status_ok, nav_ok, no_position, idem_ok]):
        report["verdict"] = "GM_ORDER_CANCEL_PASS"
    else:
        report["verdict"] = "GM_ORDER_CANCEL_REVIEW"

    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"evidence: {out}")
    print(f"verdict: {report['verdict']} order_id={order_id} status={report['reconciliation']['final_status']} nav_diff={nav_diff}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
