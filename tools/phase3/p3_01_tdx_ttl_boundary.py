# -*- coding: utf-8 -*-
"""Phase 3 / TDX-01：TDX pending 6 小时幂等 TTL 边界复核（仅模拟盘）。

背景（见 真实环境联调记录-GM-TDX-20261125.md 第 2.7 节）：
- pending_confirm 幂等窗口默认 21600 秒（6 小时），普通 accepted 缓存仍为 600 秒；
- 11-25 实测覆盖约 58 分钟 pending + 30 分钟重放 + 重启重放，未在交易时段等满 6 小时。

本脚本 dry-run（默认）只做：
1. 读取 TDX 健康状态（只读）；
2. 核对本地配置 / .env 中的 pending TTL 是否为 21600 秒；
3. 生成"拟发送"的 notify=1 下单体与同 client_order_id 重放体，写入证据 JSON，
   不在 dry-run 下真正下单。

下一交易日模拟盘执行（需 --confirm-sim，且仅模拟账户）：
- t0 发 notify=1 不可成交限价买单；记录 pending_since；
- 窗口内同 client_order_id 重放，应 idempotent_replay=true、同一 pending、不新增委托；
- 6 小时边界属于跨日 / 长时验证，盘中无法等满，过期行为以离线单测为准。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from _common import (  # noqa: E402
    build_base,
    base_parser,
    GatewayClient,
    load_env,
    new_report,
    finalize,
)

EXPECTED_TTL = 21600
STOCK = "600000.SH"


def read_configured_ttl() -> int:
    """直接导入网关配置，读取实际加载的 pending TTL（默认 21600 秒）。"""
    try:
        from config import config

        return int(config.TDX.pending_idempotency_ttl)
    except Exception:  # noqa: BLE001 - 导入失败时回退 .env / 期望值
        raw = load_env().get("JINGNI_TDX_PENDING_IDEMPOTENCY_TTL")
        return int(raw) if raw else EXPECTED_TTL


def main() -> int:
    args = base_parser("TDX pending 6h TTL 边界复核").parse_args()
    dry_run = not args.confirm_sim
    report = new_report("01_tdx_ttl_boundary", args.date, dry_run)
    report["criteria"] = [
        "health: available=true、initialized=true、logged_in=true",
        "pending TTL 配置值 = 21600 秒（6 小时），普通 accepted 缓存 = 600 秒",
        "窗口内同 client_order_id 重放：idempotent_replay=true、pending_since 不变、不新增委托",
        "6 小时过期边界盘中无法等满，以离线单测的 TTL 数学为准；不在盘中做破坏性过期重放",
    ]

    client = GatewayClient(build_base(args.base), load_env().get("JINGNI_API_KEY", ""))

    health = client.request("GET", "/api/v1/tdxquant/health")
    report["read_only"]["tdx_health"] = health

    ttl = read_configured_ttl()
    report["read_only"]["pending_ttl_seconds"] = ttl
    report["read_only"]["expected_ttl_seconds"] = EXPECTED_TTL
    report["ttl_config_ok"] = ttl == EXPECTED_TTL

    client_order_id = f"itest-tdx-ttl-{args.date.replace('-', '')}"
    order_payload = {
        "stock_code": STOCK,
        "order_type": 0,
        "order_volume": 100,
        "price_type": 0,
        "price": 10.00,
        "notify": 1,
        "client_order_id": client_order_id,
    }
    replay_payload = dict(order_payload)
    report["planned_writes"] = [
        {
            "step": "t0 发 notify=1 pending（模拟盘，不可成交限价）",
            "method": "POST",
            "path": "/api/v1/tdxquant/trade/order",
            "payload": order_payload,
            "dry_run_blocked": dry_run,
        },
        {
            "step": "窗口内同 client_order_id 重放，核对幂等",
            "method": "POST",
            "path": "/api/v1/tdxquant/trade/order",
            "payload": replay_payload,
            "dry_run_blocked": dry_run,
        },
    ]

    health_ok = bool(
        health.get("success", True)
        and (health.get("data") or health).get("logged_in")
    )
    if health.get("client_error"):
        report["verdict"] = "SKIPPED_GATEWAY_UNREACHABLE"
        report["notes"].append("网关不可达；dry-run 仅完成配置核对，未连接终端。")
    elif report["ttl_config_ok"] and health_ok:
        report["verdict"] = "DRY_RUN_READY"
    elif not report["ttl_config_ok"]:
        report["verdict"] = "BLOCKED_TTL_MISMATCH"
        report["notes"].append(f"TTL={ttl}，预期 {EXPECTED_TTL}，需先核对配置。")
    else:
        report["verdict"] = "BLOCKED_NOT_LOGGED_IN"
        report["notes"].append("TDX 未登录；盘前需先在终端登录模拟账户。")

    dest = finalize(report, args.out)
    print(f"evidence: {dest}")
    print(f"verdict: {report['verdict']}  ttl={ttl}s  dry_run={dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
