# -*- coding: utf-8 -*-
"""Phase 3 / QMT-06：复核 QMT（xtquant）撤单 NO-GO 结论是否仍成立（仅模拟盘）。

背景：
- 网关 QMT 撤单端点为 POST /api/v1/xtquant/trade/cancel，后端 SDK 函数为
  ``cancel_order_stock``（任务语境中的 "QMT order_cancel"）；
- 现状登记为 NO-GO：SDK 已复制到 .venv，但本机未启动 MiniQMT、未配置资金账号，
  撤单终态对账未做真实联调（见 README 能力矩阵、真实环境联调清单 QMT-06）。

本脚本 dry-run（默认）只读取：
1. GET /api/v1/xtquant/health：provider / xttrader 可用性、账号是否配置；
2. GET /api/v1/xtquant/rpc/capabilities：撤单是否仍登记为类型化交易端点。
不发送任何下单 / 撤单写请求。

结论口径：
- 网关不可达            -> SKIPPED_GATEWAY_UNREACHABLE（NO-GO 暂维持）
- provider 不可用 / 未配账号 -> NO_GO_STILL_HOLDS
- provider 可用且已配账号，但未确认交易会话 -> CONDITIONAL_READY（待模拟盘往返）
- 仅模拟盘往返 confirmed 后，才可在联调记录里把 QMT-06 从 NO-GO 升级为通过。
"""
from __future__ import annotations

import sys
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


def main() -> int:
    args = base_parser("QMT 撤单 NO-GO 复核").parse_args()
    dry_run = not args.confirm_sim
    report = new_report("03_qmt_cancel_recheck", args.date, dry_run)
    report["criteria"] = [
        "health: available=true、xttrader_available=true、account_configured=true",
        "capabilities: cancel_order_stock 仅出现在 typed_trade，不开放通用 RPC",
        "升级条件（模拟盘）：先有一笔 accepted 模拟委托，再调 /trade/cancel，"
        "cancel_state=confirmed、status 为 53/54/57、polls>=1、request_accepted=true",
        "未启动 MiniQMT 或未配账号时，NO-GO 结论维持，不得据离线单测判定撤单已通",
    ]

    client = GatewayClient(build_base(args.base), load_env().get("JINGNI_API_KEY", ""))
    health = client.request("GET", "/api/v1/xtquant/health")
    caps = client.request("GET", "/api/v1/xtquant/rpc/capabilities")
    report["read_only"]["health"] = health
    report["read_only"]["capabilities_excerpt"] = {
        "typed_trade": (caps.get("data") or caps).get("typed_trade"),
        "unsupported_xttrader": [
            item for item in (caps.get("data") or caps).get("rpc", {})
            .get("unsupported", {})
            .get("xttrader", [])
            if item.get("function") == "cancel_order_stock"
        ],
    }

    report["planned_writes"] = [
        {
            "step": "模拟盘：发一笔不可成交限价买单，取真实 order_id（仅 sim-live）",
            "method": "POST",
            "path": "/api/v1/xtquant/trade/order",
            "payload": {
                "stock_code": "600000.SH",
                "order_type": 0,
                "order_volume": 100,
                "price_type": 0,
                "price": 10.00,
                "client_order_id": f"itest-qmt-cancel-{args.date.replace('-', '')}",
            },
            "dry_run_blocked": dry_run,
        },
        {
            "step": "模拟盘：按 order_id 撤单并做终态对账（仅 sim-live）",
            "method": "POST",
            "path": "/api/v1/xtquant/trade/cancel",
            "payload": {"order_id": "<上一步返回 order_id>"},
            "dry_run_blocked": dry_run,
        },
    ]

    if health.get("client_error"):
        report["verdict"] = "SKIPPED_GATEWAY_UNREACHABLE"
        report["notes"].append("网关不可达；NO-GO 结论暂维持，待 MiniQMT 与网关在线后复核。")
    else:
        data = health.get("data") or health
        available = bool(data.get("available"))
        xttrader = bool(data.get("xttrader_available"))
        acct = bool(data.get("account_configured"))
        report["read_only"]["checks"] = {
            "provider_available": available,
            "xttrader_available": xttrader,
            "account_configured": acct,
        }
        if not available or not acct:
            report["verdict"] = "NO_GO_STILL_HOLDS"
            report["notes"].append("MiniQMT 未就绪或账号未配置；撤单仍属 NO-GO。")
        elif not xttrader:
            report["verdict"] = "NO_GO_STILL_HOLDS"
            report["notes"].append("xtdata 可用但 xttrader 实例不可用；撤单链路未就绪。")
        else:
            report["verdict"] = "CONDITIONAL_READY"
            report["notes"].append(
                "provider 与账号就绪；dry-run 未做撤单往返，需模拟盘 order→cancel 对账后再升级结论。"
            )

    dest = finalize(report, args.out)
    print(f"evidence: {dest}")
    print(f"verdict: {report['verdict']}  dry_run={dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
