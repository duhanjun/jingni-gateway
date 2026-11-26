"""P4-02：GM 模拟账户市价往返 + position_effect=3（T+0 QDII ETF，100 股）。

标的：SHSE.513100（国泰纳斯达克100 QDII-ETF，sec_type=2，T+0）。
安全边界：
- 仅 GM 模拟账户；nav 基线 99977.8999 ±5；无 open 单、无持仓；
- 只做 100 股；先市价买入，成交后立即市价/限价卖出，必须当日归零；
- 卖出优先 position_effect=3（平今）；若被柜台明确拒绝，回退 position_effect=2 平仓；
- 任何一步异常、买入后无法卖出、收盘前仍有持仓，立即记录并停止。
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
OUT = ROOT / "data/itest/20261126/gm_market_roundtrip_20261126.json"
SYMBOL = "SHSE.513100"
VOLUME = 100
BUY_CLIENT_ID = "itest-gm-etf-20261126-buy"
SELL_CLIENT_ID = "itest-gm-etf-20261126-sell"
EXPECTED_ACCOUNT_PREFIX = "7aa03150"
EXPECTED_ACCOUNT_SUFFIX = "2aa6"
EXPECTED_NAV = 99977.89996147156
NAV_TOL = 5.0
OPEN_STATUS = ("1", "2")
FILLED_STATUS = "3"


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


def find_order(rows_: list, order_id: str) -> dict | None:
    for row in rows_:
        if str(row.get("order_id")) == str(order_id):
            return row
    return None


def find_position(rows_: list, symbol: str) -> dict | None:
    for row in rows_:
        if str(row.get("symbol")) == symbol:
            return row
    return None


def position_volume(row: dict | None) -> int:
    if not row:
        return 0
    for key in ("volume", "position", "total_volume"):
        try:
            return int(float(row.get(key) or 0))
        except (TypeError, ValueError):
            continue
    return 0


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


def quote() -> dict | None:
    _, resp, _ = request(
        "POST", "/api/v1/gm/rpc/execute",
        {"module": "gmdata", "function": "current", "kwargs": {"symbols": [SYMBOL]}, "timeout": 30},
    )
    data = unwrap(resp)
    if isinstance(data, list) and data:
        return data[0]
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-sim", action="store_true")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    dry_run = not args.confirm_sim

    env = load_env()
    account = env.get("JINGNI_GM_ACCOUNT_ID", "")
    report = {
        "item": "p4_02_gm_market_roundtrip",
        "trade_date": "2026-11-26",
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "dry-run" if dry_run else "sim-live",
        "account_scope": "simulated",
        "account_masked": mask_account(account),
        "symbol": SYMBOL,
        "symbol_reason": "QDII ETF，sec_type=2，T+0；100 股名义约 200 元，流动性足够",
        "criteria": [
            "账户 ID 前后缀匹配已知 GM 模拟账户",
            "基线 nav≈99977.8999，无在途委托/持仓",
            "市价买入 100 股成交；市价卖出 100 股成交",
            "卖出优先 position_effect=3（平今），若明确拒绝则用 position_effect=2 平仓",
            "收盘前持仓归零、无 open 单；资产对账",
        ],
        "planned_writes": [],
        "responses": {},
    }

    _, health, _ = request("GET", "/api/v1/gm/health")
    _, asset0, _ = request("GET", "/api/v1/gm/trade/asset")
    _, orders0, _ = request("GET", "/api/v1/gm/trade/orders")
    _, positions0, _ = request("GET", "/api/v1/gm/trade/positions")
    report["responses"].update({"health": health, "asset_before": asset0,
                                "orders_before": orders0, "positions_before": positions0})

    health_data = unwrap(health) or health
    asset_before = asset_values(asset0)
    open_orders = [o for o in rows(orders0) if str(o.get("status")) in OPEN_STATUS]
    positions = rows(positions0)
    q = quote()
    current_price = None
    bid = None
    if isinstance(q, dict):
        try:
            current_price = float(q.get("price"))
            bid = float((q.get("quotes") or [{}])[0].get("bid_p"))
        except (TypeError, ValueError, IndexError):
            pass

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
        "quote_ok": current_price is not None and bid is not None and current_price > 0,
        "price_tick_ok": abs(current_price - bid) < 0.02 if current_price and bid else False,
    }
    report["preconditions"] = preconditions
    report["baseline"] = {
        "nav": asset_before["nav"], "available": asset_before["available"],
        "open_orders": len(open_orders), "positions": len(positions),
        "quote": q,
    }
    ready = all(preconditions.values())
    if not ready:
        report["verdict"] = "SAFETY_HALT_PRECONDITION"
        out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"evidence: {out}")
        print(f"verdict: {report['verdict']} dry_run={dry_run}")
        return 0

    if dry_run:
        report["planned_writes"] = [
            {"step": "market buy", "symbol": SYMBOL, "volume": VOLUME,
             "order_type": 1, "price": 0.0, "position_effect": 1,
             "client_order_id": BUY_CLIENT_ID},
            {"step": "market sell / position_effect=3", "symbol": SYMBOL, "volume": VOLUME,
             "order_type": 1, "price": 0.0, "position_effect": 3,
             "client_order_id": SELL_CLIENT_ID},
        ]
        report["verdict"] = "DRY_RUN_READY"
        out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"evidence: {out}")
        print(f"verdict: {report['verdict']} dry_run={dry_run}")
        return 0

    # 1) 市价买入 100 股
    buy_payload = {
        "symbol": SYMBOL, "volume": VOLUME, "side": 0, "order_type": 1,
        "price": 0.0, "position_effect": 1, "client_order_id": BUY_CLIENT_ID,
    }
    report["planned_writes"].append({"step": "market_buy", **buy_payload})
    status, buy_resp, elapsed = request("POST", "/api/v1/gm/trade/order", buy_payload)
    report["responses"]["buy"] = {"http_status": status, "response": buy_resp, "elapsed_ms": elapsed}
    buy_body = unwrap(buy_resp) or {}
    buy_order_id = buy_body.get("order_id")
    report["buy_order_id"] = buy_order_id
    report["buy_state"] = buy_body.get("state")
    report["buy_status"] = buy_body.get("status")
    if not buy_order_id or not buy_body.get("success"):
        report["verdict"] = "MARKET_BUY_REJECTED"
        out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"evidence: {out}")
        print(f"verdict: {report['verdict']} response={buy_resp}")
        return 0

    # 2) 等买入成交
    buy_order = None
    buy_orders = []
    for _ in range(20):
        time.sleep(0.3)
        _, orders1, _ = request("GET", "/api/v1/gm/trade/orders")
        buy_orders = rows(orders1)
        buy_order = find_order(buy_orders, buy_order_id)
        if buy_order is not None and str(buy_order.get("status")) in (FILLED_STATUS, "8"):
            break
    report["responses"]["orders_after_buy"] = buy_orders
    report["buy_order_after"] = buy_order
    if buy_order is None or str(buy_order.get("status")) != FILLED_STATUS:
        # 未成交/部分成交：撤单，避免留 open 单
        cancel_resp = None
        if buy_order is not None and str(buy_order.get("status")) in OPEN_STATUS:
            _, cancel_resp, _ = request("POST", "/api/v1/gm/trade/cancel", {"order_id": str(buy_order_id)})
        report["responses"]["buy_cancel"] = cancel_resp
        _, positions_after_buy, _ = request("GET", "/api/v1/gm/trade/positions")
        report["responses"]["positions_after_buy"] = positions_after_buy
        pos = find_position(rows(positions_after_buy), SYMBOL)
        report["reconciliation"] = {"buy_order_status": buy_order.get("status") if buy_order else None,
                                    "position_after_buy": position_volume(pos)}
        report["verdict"] = "MARKET_BUY_NOT_FILLED"
        out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"evidence: {out}")
        print(f"verdict: {report['verdict']} status={report['reconciliation']['buy_order_status']}")
        return 0

    _, positions_after_buy, _ = request("GET", "/api/v1/gm/trade/positions")
    report["responses"]["positions_after_buy"] = positions_after_buy
    pos = find_position(rows(positions_after_buy), SYMBOL)
    held = position_volume(pos)
    report["position_after_buy"] = pos
    report["held_volume"] = held
    if held <= 0:
        report["verdict"] = "BUY_FILLED_BUT_NO_POSITION"
        out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"evidence: {out}")
        print(f"verdict: {report['verdict']}")
        return 0

    # 3) 先测 position_effect=3 市价卖出
    sell_payload = {
        "symbol": SYMBOL, "volume": held, "side": 1, "order_type": 1,
        "price": 0.0, "position_effect": 3, "client_order_id": SELL_CLIENT_ID,
    }
    report["planned_writes"].append({"step": "market_sell_pe3", **sell_payload})
    status, sell_resp, elapsed = request("POST", "/api/v1/gm/trade/order", sell_payload)
    sell_body = unwrap(sell_resp) or {}
    report["responses"]["sell_pe3"] = {"http_status": status, "response": sell_resp, "elapsed_ms": elapsed}
    sell_order_id = sell_body.get("order_id")
    report["sell_order_id"] = sell_order_id
    report["sell_pe3_state"] = sell_body.get("state")
    report["sell_pe3_status"] = sell_body.get("status")
    report["sell_pe3_reject_reason"] = sell_body.get("reject_reason")
    pe3_rejected = not (sell_order_id and sell_body.get("success"))

    sell_order = None
    if sell_order_id:
        for _ in range(20):
            time.sleep(0.3)
            _, orders2, _ = request("GET", "/api/v1/gm/trade/orders")
            sell_order = find_order(rows(orders2), sell_order_id)
            if sell_order is not None and str(sell_order.get("status")) in (FILLED_STATUS, "8"):
                break

    if sell_order is not None and str(sell_order.get("status")) == "8":
        pe3_rejected = True

    # 4) 若 PE3 未受理/未成交，回退 position_effect=2 限价卖出
    fallback_order_id = None
    fallback_filled = False
    if pe3_rejected or sell_order is None or str(sell_order.get("status")) != FILLED_STATUS:
        if sell_order is not None and str(sell_order.get("status")) in OPEN_STATUS:
            _, cancel_resp, _ = request("POST", "/api/v1/gm/trade/cancel", {"order_id": str(sell_order_id)})
            report["responses"]["sell_pe3_cancel"] = cancel_resp
            # 撤单必须落地为终态，避免 PE3 卖单仍挂在柜台时又发 fallback 卖单造成超卖
            sell_after_cancel = None
            for _ in range(12):
                time.sleep(0.3)
                _, orders2b, _ = request("GET", "/api/v1/gm/trade/orders")
                sell_after_cancel = find_order(rows(orders2b), sell_order_id)
                if sell_after_cancel is not None and str(sell_after_cancel.get("status")) not in OPEN_STATUS:
                    break
            report["sell_pe3_after_cancel"] = sell_after_cancel
            if sell_after_cancel is not None and str(sell_after_cancel.get("status")) in OPEN_STATUS:
                report["verdict"] = "SELL_PE3_STILL_OPEN"
                out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"evidence: {out}")
                print(f"verdict: {report['verdict']} sell_order_id={sell_order_id}")
                return 0
        # fallback 前再次确认没有同标的在途卖单
        _, orders_guard, _ = request("GET", "/api/v1/gm/trade/orders")
        open_sell = [
            o for o in rows(orders_guard)
            if str(o.get("symbol")) == SYMBOL and str(o.get("side")) in ("sell", "2")
            and str(o.get("status")) in OPEN_STATUS
        ]
        report["open_sell_before_fallback"] = open_sell
        if open_sell:
            report["verdict"] = "OPEN_SELL_BEFORE_FALLBACK"
            out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"evidence: {out}")
            print(f"verdict: {report['verdict']} open_sell={len(open_sell)}")
            return 0
        _, positions_now_resp, _ = request("GET", "/api/v1/gm/trade/positions")
        pos_now = find_position(rows(positions_now_resp), SYMBOL)
        held = position_volume(pos_now)
        report["held_after_pe3"] = held
        if held > 0:
            q2 = quote()
            try:
                bid2 = float((q2.get("quotes") or [{}])[0].get("bid_p")) if isinstance(q2, dict) else None
            except (TypeError, ValueError, IndexError):
                bid2 = None
            if bid2 is None:
                report["verdict"] = "SELL_PE3_FAILED_NO_BID"
                out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"evidence: {out}")
                print(f"verdict: {report['verdict']} held={held}")
                return 0
            fallback_payload = {
                "symbol": SYMBOL, "volume": held, "side": 1, "order_type": 0,
                "price": round(bid2, 3), "position_effect": 2,
                "client_order_id": f"{SELL_CLIENT_ID}-fallback2",
            }
            report["planned_writes"].append({"step": "limit_sell_pe2_fallback", **fallback_payload})
            status, fallback_resp, elapsed = request("POST", "/api/v1/gm/trade/order", fallback_payload)
            fallback_body = unwrap(fallback_resp) or {}
            report["responses"]["sell_pe2_fallback"] = {
                "http_status": status, "response": fallback_resp, "elapsed_ms": elapsed,
            }
            fallback_order_id = fallback_body.get("order_id")
            report["fallback_order_id"] = fallback_order_id
            if fallback_order_id and fallback_body.get("success"):
                for _ in range(20):
                    time.sleep(0.3)
                    _, orders3, _ = request("GET", "/api/v1/gm/trade/orders")
                    fb_order = find_order(rows(orders3), fallback_order_id)
                    if fb_order is not None and str(fb_order.get("status")) == FILLED_STATUS:
                        fallback_filled = True
                        break
    else:
        fallback_filled = True  # PE3 market sell filled; 不需要 fallback

    # 5) 终态对账
    _, positions_final, _ = request("GET", "/api/v1/gm/trade/positions")
    _, orders_final, _ = request("GET", "/api/v1/gm/trade/orders")
    _, asset_final, _ = request("GET", "/api/v1/gm/trade/asset")
    report["responses"].update({"positions_final": positions_final,
                                "orders_final": orders_final, "asset_final": asset_final})
    pos_final = find_position(rows(positions_final), SYMBOL)
    held_final = position_volume(pos_final)
    open_final = [o for o in rows(orders_final) if str(o.get("status")) in OPEN_STATUS]
    asset_after = asset_values(asset_final)
    nav_diff = None
    if asset_before["nav"] is not None and asset_after["nav"] is not None:
        nav_diff = round(abs(asset_after["nav"] - asset_before["nav"]), 4)
    report["reconciliation"] = {
        "nav_before": asset_before["nav"], "nav_after": asset_after["nav"],
        "nav_diff": nav_diff, "held_volume": held_final,
        "open_orders": len(open_final),
        "buy_status": buy_order.get("status") if buy_order else None,
        "sell_pe3_status": sell_order.get("status") if sell_order else None,
        "sell_pe3_rejected": pe3_rejected,
        "fallback_pe2_order_id": fallback_order_id,
        "fallback_pe2_filled": fallback_filled,
    }

    if held_final > 0:
        # 先确认没有仍挂在柜台的卖单，避免紧急平仓与在途卖单叠加造成超卖
        _, orders_guard2, _ = request("GET", "/api/v1/gm/trade/orders")
        open_sell2 = [
            o for o in rows(orders_guard2)
            if str(o.get("symbol")) == SYMBOL and str(o.get("side")) in ("sell", "2")
            and str(o.get("status")) in OPEN_STATUS
        ]
        if open_sell2:
            report["emergency_blocked_by_open_sell"] = open_sell2
            report["verdict"] = "EMERGENCY_BLOCKED_BY_OPEN_SELL"
            out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"evidence: {out}")
            print(f"verdict: {report['verdict']} open_sell={len(open_sell2)}")
            return 0
        # 最后一次紧急平仓，仍用 position_effect=2 市价/限价，避免留隔夜仓
        q3 = quote()
        try:
            bid3 = float((q3.get("quotes") or [{}])[0].get("bid_p")) if isinstance(q3, dict) else None
        except (TypeError, ValueError, IndexError):
            bid3 = None
        if bid3 is not None:
            emergency = {
                "symbol": SYMBOL, "volume": held_final, "side": 1, "order_type": 0,
                "price": round(bid3 - 0.002, 3), "position_effect": 2,
                "client_order_id": f"{SELL_CLIENT_ID}-emergency",
            }
            report["planned_writes"].append({"step": "emergency_limit_sell_pe2", **emergency})
            status, em_resp, elapsed = request("POST", "/api/v1/gm/trade/order", emergency)
            report["responses"]["emergency_sell"] = {
                "http_status": status, "response": em_resp, "elapsed_ms": elapsed,
            }
            em_body = unwrap(em_resp) or {}
            em_id = em_body.get("order_id")
            report["emergency_order_id"] = em_id
            if em_id and em_body.get("success"):
                for _ in range(20):
                    time.sleep(0.3)
                    _, orders4, _ = request("GET", "/api/v1/gm/trade/orders")
                    if find_order(rows(orders4), em_id) and str(find_order(rows(orders4), em_id).get("status")) == FILLED_STATUS:
                        break
        _, positions_final2, _ = request("GET", "/api/v1/gm/trade/positions")
        report["responses"]["positions_final2"] = positions_final2
        held_final = position_volume(find_position(rows(positions_final2), SYMBOL))
        report["reconciliation"]["held_volume_after_emergency"] = held_final

    pe3_ok = (not pe3_rejected) and sell_order is not None and str(sell_order.get("status")) == FILLED_STATUS
    flat = held_final == 0 and len(open_final) == 0
    nav_ok = nav_diff is not None and nav_diff <= NAV_TOL
    if flat and nav_ok and pe3_ok:
        report["verdict"] = "GM_MARKET_ROUNDTRIP_PASS"
    elif flat and nav_ok and pe3_rejected and fallback_filled:
        report["verdict"] = "GM_MARKET_ROUNDTRIP_PASS_PE3_REJECTED"
    elif flat:
        report["verdict"] = "GM_MARKET_ROUNDTRIP_FLAT_REVIEW"
    else:
        report["verdict"] = "GM_MARKET_ROUNDTRIP_REVIEW"

    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"evidence: {out}")
    print(
        f"verdict: {report['verdict']} buy={buy_order.get('status') if buy_order else None} "
        f"sell_pe3={sell_order.get('status') if sell_order else None} "
        f"pe3_rejected={pe3_rejected} fallback_filled={fallback_filled} "
        f"held={held_final} open={len(open_final)} nav_diff={nav_diff}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
