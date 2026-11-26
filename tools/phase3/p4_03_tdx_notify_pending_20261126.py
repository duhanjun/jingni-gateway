"""P4-03：TDX 模拟账户 notify=1 pending 确认 -> 撤单 -> 现金恢复。

分两步，避免脚本盲等人工确认：
1) `--send --confirm-sim`：预检后发 notify=1 不可成交限价买单，保存 pending 证据；
2) 用户在 TDX 量化模拟终端点击确认后，运行 `--reconcile`：
   - 轮询终端找到确认后的委托，按 client_order_id 幂等重放对账；
   - 按 order_id 撤单，采样 cash/asset/TotalFreeze 0–360 秒；
   - 只有撤单 confirmed、cash=asset、TotalFreeze=0 才 PASS。

安全边界：仅模拟账户、100 股、限价 10.00（当前价约 10.68，显著低于市价）、异常即停。
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
OUT = ROOT / "data/itest/20261126/tdx_notify_pending_20261126.json"
STOCK = "600000.SH"
VOLUME = 100
PRICE = 10.00
CLIENT_ID = "itest-tdx-notify-20261126"
EXPECTED_CASH = 1000147.22
CASH_TOL = 1.0
OPEN_STATUS = (1, 2, 3, 4)
TERMINAL_CANCEL_STATUS = (0, 4, 5)
SAMPLE_SECONDS = (0, 30, 60, 120, 180, 240, 300, 360)


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


def asset_values(resp: dict) -> dict:
    data = unwrap(resp)
    if not isinstance(data, dict):
        data = {}
    raw = data.get("raw") if isinstance(data.get("raw"), dict) else {}
    def f(key):
        for source in (data, raw):
            try:
                return float(source.get(key))
            except (TypeError, ValueError, AttributeError):
                continue
        return None
    return {"cash": f("cash") if f("cash") is not None else f("Cash"),
            "asset": f("asset") if f("asset") is not None else f("Asset"),
            "freeze": f("TotalFreeze"),
            "market_value": f("market_value") if f("market_value") is not None else f("MarketValue")}


def order_ids(resp: dict) -> set[str]:
    return {str(o.get("order_id")) for o in rows(resp) if o.get("order_id")}


def open_orders(resp: dict) -> list:
    return [o for o in rows(resp) if int(o.get("status", -1)) in OPEN_STATUS]


def find_confirmed_order(before_ids: set[str], pending_since: str) -> dict | None:
    _, orders_resp, _ = request("GET", "/api/v1/tdxquant/trade/orders")
    candidates = []
    for order in rows(orders_resp):
        oid = order.get("order_id")
        if not oid or str(oid) in before_ids:
            continue
        if str(order.get("stock_code")) != STOCK:
            continue
        try:
            if int(float(order.get("order_volume") or 0)) != VOLUME:
                continue
            if abs(float(order.get("order_price") or 0) - PRICE) > 1e-6:
                continue
        except (TypeError, ValueError):
            continue
        order_time = str(order.get("time") or "")
        if pending_since and order_time and order_time < pending_since:
            continue
        candidates.append(order)
    if not candidates:
        return None
    return max(candidates, key=lambda o: str(o.get("time") or ""))


def preflight() -> tuple[dict, dict, dict, dict]:
    _, health, _ = request("GET", "/api/v1/tdxquant/health")
    _, asset, _ = request("GET", "/api/v1/tdxquant/trade/asset")
    _, orders, _ = request("GET", "/api/v1/tdxquant/trade/orders")
    _, positions, _ = request("GET", "/api/v1/tdxquant/trade/positions")
    return health, asset, orders, positions


def build_report(mode: str) -> dict:
    return {
        "item": "p4_03_tdx_notify_pending",
        "trade_date": "2026-11-26",
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
        "account_scope": "simulated",
        "criteria": [
            "TDX health logged_in=true、cash≈1000147.22、TotalFreeze=0、无 open 单/持仓",
            "notify=1 发出后 state=pending_confirm、raw_value=1、无 order_id",
            "终端确认后出现真实委托，按 client_order_id 重放 pending_reconciled=true",
            "按 order_id 撤单，cancel_state=confirmed、status=0/4/5",
            "0–360 秒 cash=asset、TotalFreeze=0",
        ],
        "planned_order": {
            "stock_code": STOCK, "order_type": 0, "order_volume": VOLUME,
            "price_type": 0, "price": PRICE, "notify": 1,
            "client_order_id": CLIENT_ID,
        },
        "responses": {},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--reconcile", action="store_true")
    parser.add_argument("--confirm-sim", action="store_true")
    parser.add_argument("--wait-confirm", type=int, default=180)
    parser.add_argument("--sample-seconds", type=int, default=0,
                        help="调试用；0 表示按默认 0..360 全采样")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    if not args.send and not args.reconcile:
        parser.error("需要 --send 或 --reconcile")
    if args.send and args.reconcile:
        parser.error("--send 与 --reconcile 只能二选一")

    # ---------- SEND ----------
    if args.send:
        if not args.confirm_sim:
            parser.error("--send 必须同时传 --confirm-sim")
        report = build_report("sim-live-send")
        health, asset, orders, positions = preflight()
        report["responses"].update({"health": health, "asset_before": asset,
                                    "orders_before": orders, "positions_before": positions})
        health_data = unwrap(health) or health
        av = asset_values(asset)
        oo = open_orders(orders)
        pos = rows(positions)
        pre = {
            "health_status": health_data.get("status"),
            "available": bool(health_data.get("available")),
            "logged_in": bool(health_data.get("logged_in")),
            "cash_ok": av["cash"] is not None and abs(av["cash"] - EXPECTED_CASH) <= CASH_TOL,
            "freeze_zero": av["freeze"] == 0,
            "no_open_orders": len(oo) == 0,
            "no_positions": len(pos) == 0,
        }
        report["preconditions"] = pre
        report["baseline"] = {"cash": av["cash"], "asset": av["asset"],
                              "freeze": av["freeze"], "open_orders": len(oo),
                              "positions": len(pos)}
        if not all([pre["health_status"] == "healthy", pre["available"], pre["logged_in"],
                    pre["cash_ok"], pre["freeze_zero"], pre["no_open_orders"], pre["no_positions"]]):
            report["verdict"] = "SAFETY_HALT_PRECONDITION"
            out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"evidence: {out}")
            print(f"verdict: {report['verdict']}")
            return 0

        report["before_order_ids"] = sorted(order_ids(orders))
        payload = report["planned_order"]
        status, placed, elapsed = request("POST", "/api/v1/tdxquant/trade/order", payload)
        report["responses"]["place"] = {"http_status": status, "response": placed, "elapsed_ms": elapsed}
        body = unwrap(placed) or {}
        report["place_state"] = body.get("state")
        report["place_raw_value"] = body.get("raw_value")
        report["place_message"] = body.get("message")
        report["place_order_id"] = body.get("order_id")
        report["pending_since"] = body.get("pending_since") or time.strftime("%H%M%S")
        report["pending_sent_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if body.get("state") != "pending_confirm" or body.get("order_id"):
            report["verdict"] = "NOT_PENDING_CONFIRM"
        else:
            report["verdict"] = "PENDING_SENT_WAITING_USER_CONFIRM"
        out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"evidence: {out}")
        print(f"verdict: {report['verdict']} state={report['place_state']} raw={report['place_raw_value']} pending_since={report['pending_since']}")
        return 0

    # ---------- RECONCILE ----------
    out = Path(args.out)
    if not out.exists():
        print(f"missing evidence: {out}", file=__import__("sys").stderr)
        return 2
    report = json.loads(out.read_text(encoding="utf-8"))
    if report.get("verdict") != "PENDING_SENT_WAITING_USER_CONFIRM":
        print(f"unexpected prior verdict: {report.get('verdict')}")
        return 2

    before_ids = set(report.get("before_order_ids") or [])
    pending_since = str(report.get("pending_since") or "")
    confirmed = None
    deadline = time.monotonic() + max(10, args.wait_confirm)
    while time.monotonic() < deadline:
        confirmed = find_confirmed_order(before_ids, pending_since)
        if confirmed is not None:
            break
        time.sleep(2)

    report["reconcile_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    report["confirmed_order"] = confirmed
    if confirmed is None:
        report["verdict"] = "PENDING_TIMEOUT"
        report["notes"] = ["在等待窗口内未在终端看到确认后的委托；未发送新委托。请在终端取消/关闭确认框后重试。"]
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"evidence: {out}")
        print(f"verdict: {report['verdict']} waited={args.wait_confirm}s")
        return 0

    order_id = str(confirmed.get("order_id"))
    report["confirmed_order_id"] = order_id
    report["confirmed_status"] = confirmed.get("status")
    # 幂等重放对账：不应新增委托
    status, replay, elapsed = request("POST", "/api/v1/tdxquant/trade/order", report["planned_order"])
    report["responses"]["replay"] = {"http_status": status, "response": replay, "elapsed_ms": elapsed}
    replay_body = unwrap(replay) or {}
    report["replay_state"] = replay_body.get("state")
    report["replay_order_id"] = replay_body.get("order_id")
    report["replay_idempotent"] = bool(replay_body.get("idempotent_replay"))
    report["replay_pending_reconciled"] = bool(replay_body.get("pending_reconciled"))
    _, orders_after_replay, _ = request("GET", "/api/v1/tdxquant/trade/orders")
    report["responses"]["orders_after_replay"] = orders_after_replay
    if len(order_ids(orders_after_replay)) != len(before_ids) + 1:
        report["verdict"] = "REPLAY_CREATED_EXTRA_ORDER"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"evidence: {out}")
        print(f"verdict: {report['verdict']} orders={len(order_ids(orders_after_replay))}")
        return 0

    # 撤单 + 轮询
    cancel_attempts = []
    cancel_confirmed = False
    final_order = None
    for attempt in range(1, 4):
        status, cancel, elapsed = request(
            "POST", "/api/v1/tdxquant/trade/cancel",
            {"stock_code": STOCK, "order_id": order_id},
        )
        cancel_attempts.append({"attempt": attempt, "http_status": status,
                                "response": cancel, "elapsed_ms": elapsed})
        cancel_body = unwrap(cancel) or {}
        if cancel_body.get("cancel_state") == "confirmed":
            cancel_confirmed = True
            final_order = cancel_body
            break
        time.sleep(1)
    report["responses"]["cancel"] = cancel_attempts
    report["cancel_confirmed"] = cancel_confirmed
    report["final_order"] = final_order

    # 终态复核
    for _ in range(8):
        _, orders_final_resp, _ = request("GET", "/api/v1/tdxquant/trade/orders")
        for o in rows(orders_final_resp):
            if str(o.get("order_id")) == order_id:
                final_order = o
                break
        if final_order is not None and int(final_order.get("status", -1)) in TERMINAL_CANCEL_STATUS:
            break
        time.sleep(1)
    report["final_order_after_poll"] = final_order

    # 现金/资产/冻结采样
    samples = []
    start = time.monotonic()
    for offset in SAMPLE_SECONDS:
        if args.sample_seconds and offset > args.sample_seconds:
            continue
        target = start + offset
        remain = target - time.monotonic()
        if remain > 0:
            time.sleep(remain)
        _, asset_resp, _ = request("GET", "/api/v1/tdxquant/trade/asset")
        av = asset_values(asset_resp)
        _, positions_resp, _ = request("GET", "/api/v1/tdxquant/trade/positions")
        pos = rows(positions_resp)
        _, orders_resp, _ = request("GET", "/api/v1/tdxquant/trade/orders")
        oo = open_orders(orders_resp)
        samples.append({
            "offset_s": offset,
            "cash": av["cash"], "asset": av["asset"], "freeze": av["freeze"],
            "market_value": av["market_value"], "positions": len(pos),
            "open_orders": len(oo),
            "raw": asset_resp,
        })
    report["cash_samples"] = samples

    cash_asset_ok = all(
        s["cash"] is not None and s["asset"] is not None and abs(s["cash"] - s["asset"]) <= CASH_TOL
        for s in samples
    )
    freeze_ok = all(s["freeze"] == 0 for s in samples)
    no_position = all(s["positions"] == 0 for s in samples)
    no_open = all(s["open_orders"] == 0 for s in samples)
    final_status_ok = final_order is not None and int(final_order.get("status", -1)) in TERMINAL_CANCEL_STATUS
    if cancel_confirmed and final_status_ok and cash_asset_ok and freeze_ok and no_position and no_open:
        report["verdict"] = "TDX_NOTIFY_PENDING_PASS"
    else:
        report["verdict"] = "TDX_NOTIFY_PENDING_REVIEW"

    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"evidence: {out}")
    print(
        f"verdict: {report['verdict']} order_id={order_id} "
        f"cancel_confirmed={cancel_confirmed} status={(final_order or {}).get('status')} "
        f"cash_asset_ok={cash_asset_ok} freeze_ok={freeze_ok} "
        f"positions={samples[-1]['positions'] if samples else 'n/a'} open={samples[-1]['open_orders'] if samples else 'n/a'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
