# -*- coding: utf-8 -*-
"""Phase 3 / TDX-03：TDX 分钟数据确认（只读，仅模拟盘环境）。

背景（见 真实环境联调记录-GM-TDX-20261125.md 第 3.1 节）：
- 11-25 全天 1m/5m/15m/30m/1h 均 success=true、data={}；1d 正常更新；
- 标的参数名必须是 stock_list，用 stock_code 会返回 INVALID_ARGUMENT（入口层正确拒绝）。

本脚本只发只读 RPC get_market_data，不下单；逐周期判定 DATA / EMPTY / ERROR：
- DATA：success=true 且返回 bar 非空；
- EMPTY：success=true 但 data 为空，记为终端数据 / 权限限制，不误判网关缺陷；
- ERROR：success=false 或调用异常。
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

PERIODS = ["1m", "5m", "15m", "30m", "1h", "1d"]
STOCK = "600000.SH"


def classify(resp: dict) -> str:
    if resp.get("client_error"):
        return "UNREACHABLE"
    if resp.get("http_status") in (400, 401, 403, 500):
        return "ERROR"
    if not resp.get("success", True):
        return "ERROR"
    data = resp.get("data")
    if isinstance(data, dict):
        # 网关 RPC 返回两层信封：{"success": true, "data": {"data": <payload>}}
        # 旧逻辑只解了 Value，导致空 payload 被误判为 DATA。
        if "Value" in data:
            data = data.get("Value")
        elif "data" in data:
            data = data.get("data")
    empty = data in (None, {}, [], "")
    return "EMPTY" if empty else "DATA"


def main() -> int:
    args = base_parser("TDX 分钟数据确认").parse_args()
    dry_run = not args.confirm_sim
    report = new_report("04_tdx_minute_data", args.date, dry_run)
    report["criteria"] = [
        "1m/5m/15m/30m/1h：success=true 且对应周期 bar 非空，最新 bar 时间接近当前时间",
        "若分钟周期仍为空：记为终端数据 / 权限限制（EMPTY），不判网关缺陷",
        "1d 作为对照：应正常返回最新 Close/Volume",
        "参数名必须用 stock_list；stock_code 应被入口层拒绝 INVALID_ARGUMENT",
    ]

    client = GatewayClient(build_base(args.base), load_env().get("JINGNI_API_KEY", ""))
    report["read_only"]["health"] = client.request("GET", "/api/v1/tdxquant/health")

    periods: dict[str, dict] = {}
    for period in PERIODS:
        resp = client.rpc(
            "tdxquant",
            "tdxdata",
            "get_market_data",
            kwargs={
                "field_list": ["Open", "High", "Low", "Close", "Volume"],
                "stock_list": [STOCK],
                "period": period,
                "count": 10,
            },
            timeout=30,
        )
        periods[period] = {"verdict": classify(resp), "response": resp}
    report["read_only"]["market_data"] = periods

    invalid_param = client.rpc(
        "tdxquant",
        "tdxdata",
        "get_market_data",
        kwargs={"field_list": ["Close"], "stock_code": [STOCK], "period": "1m"},
        timeout=20,
    )
    report["read_only"]["invalid_param_rejected"] = invalid_param

    minute_verdicts = {p: periods[p]["verdict"] for p in PERIODS[:-1]}
    report["minute_verdicts"] = minute_verdicts
    report["daily_verdict"] = periods["1d"]["verdict"]

    if report["read_only"]["health"].get("client_error"):
        report["verdict"] = "SKIPPED_GATEWAY_UNREACHABLE"
        report["notes"].append("网关不可达；下一交易日盘中重跑本只读脚本。")
    elif all(v == "EMPTY" for v in minute_verdicts.values()):
        report["verdict"] = "CONFIRMED_EMPTY_MINUTES"
        report["notes"].append("分钟周期仍全部为空；维持终端数据 / 权限限制结论，1d 对照见 daily_verdict。")
    elif any(v == "DATA" for v in minute_verdicts.values()):
        report["verdict"] = "MINUTE_DATA_AVAILABLE"
        report["notes"].append("已有分钟周期返回 bar；需核对最新 bar 时间戳是否接近当前时间。")
    else:
        report["verdict"] = "REVIEW_ERRORS"
        report["notes"].append("存在 ERROR 响应，需结合 error_code 定位是入口校验还是终端异常。")

    dest = finalize(report, args.out)
    print(f"evidence: {dest}")
    print(f"verdict: {report['verdict']}  minutes={minute_verdicts}  1d={report['daily_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
