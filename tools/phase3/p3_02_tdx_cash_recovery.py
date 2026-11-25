# -*- coding: utf-8 -*-
"""Phase 3 / TDX-02：撤单后约 5 分钟现金恢复采样（仅模拟盘）。

背景（见 真实环境联调记录-GM-TDX-20261125.md 第 2.5 节）：
- TDX 撤单瞬间 cash 比 asset 少约冻结金额，TotalFreeze=0；约 5 分钟后
  cash 才恢复到 asset；这是终端 / 资金字段异步行为，网关不做现金缓存。
- 对账必须轮询 cash/asset/TotalFreeze，不能以撤单响应里的 cash_after 断定资金已释放。

dry-run（默认）：只读 health / asset / orders / positions，生成拟发送的
下单、撤单与采样时间表，写入证据 JSON，不真正下单或撤单。
"""
from __future__ import annotations

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
SAMPLE_MINUTES = [0, 1, 2, 3, 4, 5, 6]


def main() -> int:
    args = base_parser("TDX 撤单现金恢复采样").parse_args()
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

    client_order_id = f"itest-tdx-cash-{args.date.replace('-', '')}"
    report["planned_writes"] = [
        {
            "step": "模拟盘不可成交限价买入 100 股（notify=0）",
            "method": "POST",
            "path": "/api/v1/tdxquant/trade/order",
            "payload": {
                "stock_code": STOCK,
                "order_type": 0,
                "order_volume": 100,
                "price_type": 0,
                "price": 10.00,
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
    report["sampling_schedule_minutes"] = SAMPLE_MINUTES
    report["sampling_slots"] = [
        {"minute": m, "cash": None, "asset": None, "total_freeze": None,
         "note": "sim-live 模式下在此时点轮询 /trade/asset 填值"}
        for m in SAMPLE_MINUTES
    ]

    if report["read_only"]["health"].get("client_error"):
        report["verdict"] = "SKIPPED_GATEWAY_UNREACHABLE"
        report["notes"].append("网关不可达；dry-run 仅生成采样计划。")
    else:
        report["verdict"] = "DRY_RUN_READY"
        report["notes"].append(
            "下一交易日模拟盘：下单→撤单确认→按 0–6 分钟轮询 asset，现金恢复曲线写入本 JSON。"
        )

    dest = finalize(report, args.out)
    print(f"evidence: {dest}")
    print(f"verdict: {report['verdict']}  dry_run={dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
