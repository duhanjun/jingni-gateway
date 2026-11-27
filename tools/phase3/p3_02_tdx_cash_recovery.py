# -*- coding: utf-8 -*-
"""Phase 3 / TDX-02：撤单后约 5 分钟现金恢复采样（仅模拟盘）。

背景（见 真实环境联调记录-GM-TDX-20261125.md 第 2.5 节）：
- TDX 撤单瞬间 cash 比 asset 少约冻结金额，TotalFreeze=0；约 5 分钟后
  cash 才恢复到 asset；这是终端 / 资金字段异步行为，网关不做现金缓存。
- 对账必须轮询 cash/asset/TotalFreeze，不能以撤单响应里的 cash_after 断定资金已释放。

dry-run（默认）：只读 health / asset / orders / positions，生成拟发送的
下单、撤单与采样时间表，写入证据 JSON，不真正下单或撤单。

--confirm-sim（仅模拟账户，盘中连续竞价时段）：
1. 只读复核 TDX 终端标题含「模拟」、账户资金与预检一致（cash≈asset≈1000147.22、
   TotalFreeze=0）；出现任一真实 / 非模拟标识立即停止，不写单。
2. 报 100 股不可成交限价买单（600000.SH @10.00，notify=0），定位委托后立即撤单。
3. 撤单后按 0–6 分钟采样 cash/asset/TotalFreeze，给出恢复 / 终端异步结论。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    build_base,
    base_parser,
    GatewayClient,
    load_env,
    new_report,
    finalize,
)

STOCK = "600000.SH"
ORDER_VOLUME = 100
ORDER_PRICE = 10.00
EXPECTED_CASH = 1000147.22
CASH_TOL = 1.0          # 基线资金容差（元）
FREEZE_TOL = 0.01       # 冻结容差（元）
RECOVER_TOL = 0.01      # 现金恢复 cash-asset 容差（元）
# 采样时点（秒）：撤单后 0s 起，覆盖 6 分钟。
SAMPLE_SECONDS = [0, 30, 60, 120, 180, 240, 300, 360]
FORBIDDEN_MARKERS = ["实盘", "真实账户", "regular account", "live account"]
SIM_MARKER = "模拟"


def _unwrap(resp: dict) -> dict:
    """网关响应：{http_status, data: {success, data|error}} -> 内层 data。"""
    if not isinstance(resp, dict):
        return {}
    body = resp.get("data") or {}
    if isinstance(body, dict) and "data" in body:
        return body.get("data") or {}
    return body


def _asset_values(asset_resp: dict) -> dict:
    data = _unwrap(asset_resp)
    raw = data.get("raw") or data or {}

    def _f(key: str):
        try:
            return float(raw.get(key))
        except (TypeError, ValueError):
            return None

    return {
        "cash": _f("Cash"),
        "asset": _f("Asset"),
        "market_value": _f("MarketValue"),
        "total_freeze": _f("TotalFreeze"),
        "raw": raw,
    }


def _probe_tdx_titles() -> list:
    """读取本机 TDX 终端窗口标题（只读进程枚举）。"""
    ps = (
        "Get-Process TdxW -ErrorAction SilentlyContinue | "
        "Select-Object Id,ProcessName,MainWindowTitle | ConvertTo-Json -Compress"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=20,
        ).stdout
        rows = json.loads(out) if out.strip() else []
        if isinstance(rows, dict):
            rows = [rows]
        return [
            {"pid": r.get("Id"), "name": r.get("ProcessName"), "title": r.get("MainWindowTitle") or ""}
            for r in rows
        ]
    except Exception as exc:  # noqa: BLE001 - 探测失败不阻断，记录即可
        return [{"error": f"{type(exc).__name__}: {exc}"}]


def _safety_scan(*blobs: object) -> list:
    """扫描文本中是否出现真实 / 非模拟标识，命中即返回标记列表。"""
    text = json.dumps(blobs, ensure_ascii=False, default=str)
    return [m for m in FORBIDDEN_MARKERS if m in text]


def _asset_row(elapsed: float, vals: dict) -> dict:
    return {
        "elapsed_seconds": round(elapsed, 1),
        "cash": vals["cash"],
        "asset": vals["asset"],
        "total_freeze": vals["total_freeze"],
        "market_value": vals["market_value"],
    }


def main() -> int:
    parser = base_parser("TDX 撤单现金恢复采样")
    parser.add_argument(
        "--run-tag", default="01",
        help="同一交易日内多次采样的唯一后缀，避免 client_order_id 幂等冲突",
    )
    args = parser.parse_args()
    dry_run = not args.confirm_sim
    report = new_report("02_tdx_cash_recovery", args.date, dry_run)
    report["criteria"] = [
        "撤单 cancel_state=confirmed、status=0（以委托状态对账，不信撤单返回值）",
        "撤单瞬间记录 cash/asset/TotalFreeze；随后按 0–6 分钟轮询 asset",
        "现金恢复判据：cash 回升至与 asset 一致（差额≈0），TotalFreeze=0",
        "若 6 分钟仍未恢复，保留采样曲线并标注为终端异步行为，不误判网关缺陷",
    ]

    client = GatewayClient(build_base(args.base), load_env().get("JINGNI_API_KEY", ""))
    report["read_only"]["health"] = client.request("GET", "/api/v1/tdxquant/health")
    report["read_only"]["asset"] = client.request("GET", "/api/v1/tdxquant/trade/asset")
    report["read_only"]["orders"] = client.request("GET", "/api/v1/tdxquant/trade/orders")
    report["read_only"]["positions"] = client.request("GET", "/api/v1/tdxquant/trade/positions")
    report["read_only"]["terminal_probe"] = {"processes": _probe_tdx_titles()}

    client_order_id = (
        f"itest-tdx-cash-{args.date.replace('-', '')}-{args.run_tag}"
    )
    report["planned_writes"] = [
        {
            "step": "模拟盘不可成交限价买入 100 股（notify=0）",
            "method": "POST",
            "path": "/api/v1/tdxquant/trade/order",
            "payload": {
                "stock_code": STOCK,
                "order_type": 0,
                "order_volume": ORDER_VOLUME,
                "price_type": 0,
                "price": ORDER_PRICE,
                "notify": 0,
                "client_order_id": client_order_id,
            },
            "dry_run_blocked": dry_run,
        },
        {
            "step": "按返回 order_id 撤单（模拟盘）",
            "method": "POST",
            "path": "/api/v1/tdxquant/trade/cancel",
            "payload": {"stock_code": STOCK, "order_id": "<上一步返回 order_id>"},
            "dry_run_blocked": dry_run,
        },
    ]
    report["sampling_schedule_seconds"] = SAMPLE_SECONDS
    report["sampling_slots"] = [
        {"elapsed_seconds": s, "cash": None, "asset": None, "total_freeze": None,
         "note": "sim-live 模式下在此时点轮询 /trade/asset 填值"}
        for s in SAMPLE_SECONDS
    ]

    health = report["read_only"]["health"]
    if health.get("client_error"):
        report["verdict"] = "SKIPPED_GATEWAY_UNREACHABLE"
        report["notes"].append("网关不可达；dry-run 仅生成采样计划。")
        dest = finalize(report, args.out)
        print(f"evidence: {dest}")
        print(f"verdict: {report['verdict']}  dry_run={dry_run}")
        return 0

    if dry_run:
        report["verdict"] = "DRY_RUN_READY"
        report["notes"].append(
            "下一交易日模拟盘：下单→撤单确认→按 0–6 分钟轮询 asset，现金恢复曲线写入本 JSON。"
        )
        dest = finalize(report, args.out)
        print(f"evidence: {dest}")
        print(f"verdict: {report['verdict']}  dry_run={dry_run}")
        return 0

    # ---- confirm-sim 活单分支：仅 TDX 模拟账户，唯一授权写操作 ----
    health_body = health.get("data") or {}
    health_data = health_body.get("data") or health_body
    baseline = _asset_values(report["read_only"]["asset"])
    titles = [p.get("title", "") for p in report["read_only"]["terminal_probe"]["processes"]]
    sim_title = any(SIM_MARKER in t for t in titles)
    forbidden = _safety_scan(health_data, baseline,
                             report["read_only"]["orders"],
                             report["read_only"]["positions"])

    preconditions = {
        "logged_in": bool(health_data.get("logged_in")),
        "available": bool(health_data.get("available")),
        "initialized": bool(health_data.get("initialized")),
        "sim_terminal_title": sim_title,
        "baseline_cash_ok": baseline["cash"] is not None and
            abs(baseline["cash"] - EXPECTED_CASH) <= CASH_TOL,
        "baseline_freeze_ok": baseline["total_freeze"] is not None and
            abs(baseline["total_freeze"]) <= FREEZE_TOL,
        "forbidden_markers": forbidden,
    }
    report["preconditions"] = preconditions
    report["baseline_asset"] = _asset_row(0.0, baseline)

    open_orders = [
        o for o in (_unwrap(report["read_only"]["orders"]) or [])
        if str(o.get("status")) in ("1", "2")
    ]
    preconditions["no_existing_open_order"] = len(open_orders) == 0

    ready = (
        preconditions["logged_in"] and preconditions["available"] and
        preconditions["initialized"] and preconditions["sim_terminal_title"] and
        preconditions["baseline_cash_ok"] and preconditions["baseline_freeze_ok"] and
        preconditions["no_existing_open_order"] and not forbidden
    )

    if not ready:
        report["verdict"] = "SAFETY_HALT_PRECONDITION"
        report["notes"].append(
            "前置条件未满足，未发送任何写请求："
            + json.dumps(preconditions, ensure_ascii=False)
        )
        dest = finalize(report, args.out)
        print(f"evidence: {dest}")
        print(f"verdict: {report['verdict']}  dry_run={dry_run}")
        return 0

    # 1) 报 100 股不可成交限价买单
    order_payload = {
        "stock_code": STOCK,
        "order_type": 0,
        "order_volume": ORDER_VOLUME,
        "price_type": 0,
        "price": ORDER_PRICE,
        "notify": 0,
        "client_order_id": client_order_id,
    }
    order_resp = client.request("POST", "/api/v1/tdxquant/trade/order", order_payload, timeout=30)
    report["order_response"] = order_resp
    order_body = order_resp.get("data") or {}
    order_data = order_body.get("data") or {}

    if not order_body.get("success", False):
        report["verdict"] = "ORDER_REJECTED"
        report["notes"].append(f"下单被拒，未撤单：{order_body.get('error') or order_data}")
        # 复核是否留下游离委托
        report["read_only"]["orders_after_order"] = client.request(
            "GET", "/api/v1/tdxquant/trade/orders")
        dest = finalize(report, args.out)
        print(f"evidence: {dest}")
        print(f"verdict: {report['verdict']}  dry_run={dry_run}")
        return 0

    order_id = str(order_data.get("order_id") or "")
    report["order"] = order_data

    # 定位委托（order_id 优先；pending_confirm 无 id 时按标的/数量/价格匹配最新一笔）
    time.sleep(1.0)
    orders_now = _unwrap(client.request("GET", "/api/v1/tdxquant/trade/orders")) or []
    matched = None
    if order_id:
        matched = next((o for o in orders_now if str(o.get("order_id")) == order_id), None)
    if matched is None:
        candidates = [
            o for o in orders_now
            if o.get("stock_code") == STOCK
            and int(o.get("order_volume") or 0) == ORDER_VOLUME
            and abs(float(o.get("order_price") or 0) - ORDER_PRICE) < 1e-6
        ]
        matched = max(candidates, key=lambda o: str(o.get("time") or ""), default=None)
    report["located_order"] = matched

    if matched is None:
        report["verdict"] = "ORDER_NOT_FOUND_IN_TERMINAL"
        report["notes"].append("下单成功但终端委托列表查不到该委托，停止撤单流程并人工核查。")
        dest = finalize(report, args.out)
        print(f"evidence: {dest}")
        print(f"verdict: {report['verdict']}  dry_run={dry_run}")
        return 0

    target_order_id = str(matched.get("order_id"))
    order_id_for_cancel = target_order_id or order_id

    # 2) 立即撤单
    cancel_resp = client.request(
        "POST", "/api/v1/tdxquant/trade/cancel",
        {"stock_code": STOCK, "order_id": order_id_for_cancel}, timeout=45,
    )
    report["cancel_response"] = cancel_resp

    # 3) 0–6 分钟现金恢复采样
    start = time.monotonic()
    slots = []
    for idx, target in enumerate(SAMPLE_SECONDS):
        elapsed = time.monotonic() - start
        if elapsed < target:
            time.sleep(max(0.0, target - elapsed))
        vals = _asset_values(client.request("GET", "/api/v1/tdxquant/trade/asset"))
        slots.append(_asset_row(time.monotonic() - start, vals))
    report["sampling_slots"] = slots

    cancel_body = cancel_resp.get("data") or {}
    cancel_data = cancel_body.get("data") or {}
    final = slots[-1] if slots else {}
    cash_diff = None
    if final.get("cash") is not None and final.get("asset") is not None:
        cash_diff = round(abs(final["cash"] - final["asset"]), 4)
    report["recovery"] = {
        "cancel_state": cancel_data.get("cancel_state"),
        "cancel_status": cancel_data.get("status"),
        "final_cash": final.get("cash"),
        "final_asset": final.get("asset"),
        "final_total_freeze": final.get("total_freeze"),
        "cash_asset_diff": cash_diff,
    }

    recovered = (
        cancel_data.get("cancel_state") == "confirmed"
        and cash_diff is not None and cash_diff <= RECOVER_TOL
        and final.get("total_freeze") is not None
        and abs(final["total_freeze"]) <= FREEZE_TOL
    )
    if recovered:
        report["verdict"] = "CASH_RECOVERED"
        report["notes"].append("撤单确认，6 分钟内 cash 与 asset 一致、TotalFreeze=0。")
    else:
        report["verdict"] = "CASH_NOT_RECOVERED_ASYNC"
        report["notes"].append(
            "6 分钟内现金未完全恢复或撤单未确认；保留采样曲线，按终端异步行为处理，需人工复核。"
        )

    dest = finalize(report, args.out)
    print(f"evidence: {dest}")
    print(f"verdict: {report['verdict']}  dry_run={dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
