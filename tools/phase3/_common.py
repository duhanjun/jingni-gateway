# -*- coding: utf-8 -*-
"""Phase 3 开盘期验证脚本公共工具（仅模拟盘 / 只读优先）。

安全约束：
- 默认 dry-run：不发送任何下单 / 撤单写请求，只读取健康、资产、委托等只读端点，
  并把"拟发送"的请求体写入证据 JSON，供下一交易日人工复核后在模拟盘执行。
- 只有显式传入 ``--confirm-sim`` 才允许调用写端点；即便如此也只对接模拟账户，
  脚本不读取、不修改真实账户配置。
- 网关不可达时降级为 SKIPPED / DRY_RUN_READY，不把连接失败误判为代码失败。
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
ENV_PATH = ROOT / ".env"
DEFAULT_BASE = "http://127.0.0.1:8010"


def load_env() -> Dict[str, str]:
    """读取 .env 中的键值（不回显敏感值）。"""
    env: Dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def build_base(explicit: Optional[str]) -> str:
    if explicit:
        return explicit.rstrip("/")
    env = load_env()
    host = env.get("JINGNI_API_HOST", "127.0.0.1")
    port = env.get("JINGNI_API_PORT", "8010")
    return f"http://{host}:{port}"


def api_key() -> str:
    return load_env().get("JINGNI_API_KEY", "")


class GatewayClient:
    """极简 HTTP 客户端；所有异常收敛为带 client_error 的 dict。"""

    def __init__(self, base: str, key: str, timeout: float = 30.0):
        self.base = base.rstrip("/")
        self.key = key
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        body = (
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if payload is not None
            else None
        )
        headers = {"X-API-Key": self.key}
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            self.base + path, data=body, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return {"http_status": resp.status, "data": json.loads(raw)}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                return {"http_status": exc.code, **json.loads(raw)}
            except json.JSONDecodeError:
                return {"http_status": exc.code, "raw": raw}
        except Exception as exc:  # noqa: BLE001 - 连接失败也落证据
            return {
                "success": False,
                "client_error": True,
                "error": f"{type(exc).__name__}: {exc}",
            }

    def rpc(
        self,
        provider: str,
        module: str,
        function: str,
        kwargs: Optional[Dict[str, Any]] = None,
        args: Optional[list] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        return self.request(
            "POST",
            f"/api/v1/{provider}/rpc/execute",
            {
                "module": module,
                "function": function,
                "args": args or [],
                "kwargs": kwargs or {},
                "timeout": timeout,
            },
            timeout=timeout,
        )


def evidence_dir(trade_date: str) -> Path:
    folder = ROOT / "data" / "itest" / trade_date.replace("-", "")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def write_evidence(trade_date: str, name: str, payload: Dict[str, Any]) -> Path:
    dest = evidence_dir(trade_date) / name
    dest.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return dest


def base_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--base", help="网关地址，默认读 .env 或 127.0.0.1:8010")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                        help="交易日期 YYYY-MM-DD，默认今天")
    parser.add_argument(
        "--confirm-sim",
        action="store_true",
        help="允许调用模拟盘写端点；默认 dry-run，只发只读请求",
    )
    parser.add_argument(
        "--out", help="证据 JSON 输出路径（默认 data/itest/<date>/ 下）"
    )
    return parser


def new_report(item: str, trade_date: str, dry_run: bool) -> Dict[str, Any]:
    return {
        "item": item,
        "trade_date": trade_date,
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "dry-run" if dry_run else "sim-live",
        "account_scope": "simulated",
        "verdict": "DRY_RUN_READY",
        "criteria": [],
        "read_only": {},
        "planned_writes": [],
        "notes": [],
    }


def finalize(report: Dict[str, Any], out: Optional[str]) -> Path:
    if out:
        dest = Path(out)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return dest
    return write_evidence(report["trade_date"], f"phase3_{report['item']}.json", report)
