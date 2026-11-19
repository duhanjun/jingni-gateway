# -*- coding: utf-8 -*-
"""
gmtrade 外部交易 sidecar。

运行在 Python 3.10（gmtrade 3.0.6 只提供 cp36-cp310 wheel）。
网关通过 JSON Lines 与它通信，stdin 一行一个请求，stdout 一行一个响应。
"""

import json
import os
import sys

# gmtrade 的日志可能写到 stdout；把 import 阶段的 stdout 重定向到 stderr，避免污染协议
_REAL_STDOUT = sys.stdout
sys.stdout = sys.stderr

from gmtrade.api import (  # noqa: E402
    OrderSide_Buy,
    OrderSide_Sell,
    OrderType_Limit,
    OrderType_Market,
    PositionEffect_Close,
    PositionEffect_CloseToday,
    PositionEffect_CloseYesterday,
    PositionEffect_Open,
    account,
    get_cash,
    get_orders,
    get_positions,
    login,
    order_cancel,
    order_volume,
    set_endpoint,
    set_token,
)

sys.stdout = _REAL_STDOUT


def _jsonable(value):
    """把 protobuf 对象递归转换为可 JSON 序列化的结构。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if hasattr(value, "SerializeToString"):
        try:
            from google.protobuf.json_format import MessageToDict

            return MessageToDict(value, preserving_proto_field_name=True)
        except Exception:
            return str(value)
    if hasattr(value, "__dict__"):
        return {
            str(k): _jsonable(v)
            for k, v in vars(value).items()
            if not str(k).startswith("_")
        }
    return str(value)


def _response(req_id, ok, data=None, error=None):
    payload = {"id": req_id, "ok": bool(ok)}
    if ok:
        payload["data"] = _jsonable(data)
    else:
        payload["error"] = str(error)
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def _build_order(params):
    # 网关 GMTradeService 传入的是 gmtrade 常量：1=买、2=卖；1=限价、2=市价。
    # 同时兼容 API 的 0=买、1=卖 / 0=限价、1=市价。
    side_raw = int(params.get("side", 0))
    side = OrderSide_Buy if side_raw in (0, 1) else OrderSide_Sell
    order_type_raw = int(params.get("order_type", 0))
    order_type = OrderType_Limit if order_type_raw in (0, 1) else OrderType_Market
    position_effect = int(params.get("position_effect", 1))
    effect_map = {
        1: PositionEffect_Open,
        2: PositionEffect_Close,
        3: PositionEffect_CloseToday,
    }
    return {
        "symbol": params["symbol"],
        "volume": int(params["volume"]),
        "side": side,
        "order_type": order_type,
        "position_effect": effect_map.get(position_effect, PositionEffect_Open),
        "price": float(params.get("price", 0.0)),
        # sidecar 只登录一个账户；不把 UUID 再传给 gmtrade，避免账户解析差异。
        "account": None,
    }


def main():
    token = os.getenv("JINGNI_GM_TOKEN", "")
    account_id = os.getenv("JINGNI_GM_ACCOUNT_ID", "")
    endpoint = os.getenv("JINGNI_GMTRADE_ENDPOINT", "api.myquant.cn:9000")

    if not token or not account_id:
        _response(None, False, error="JINGNI_GM_TOKEN / JINGNI_GM_ACCOUNT_ID 未配置")
        return 1

    try:
        set_token(token)
        set_endpoint(endpoint)
        acct = account(account_id=account_id)
        login(acct)
    except Exception as exc:
        _response(None, False, error=f"gmtrade login 失败: {exc}")
        return 1

    _response(None, True, {"ready": True, "account_len": len(account_id), "endpoint": endpoint})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req_id = None
        try:
            req = json.loads(line)
            req_id = req.get("id")
            action = req.get("action")
            params = req.get("params") or {}

            if action == "ping":
                _response(req_id, True, {"ready": True})
            elif action == "cash":
                _response(req_id, True, get_cash())
            elif action == "positions":
                _response(req_id, True, get_positions())
            elif action == "orders":
                _response(req_id, True, get_orders())
            elif action == "place":
                _response(req_id, True, order_volume(**_build_order(params)))
            elif action == "cancel":
                wait_orders = params.get("wait_cancel_orders", params)
                if isinstance(wait_orders, dict):
                    wait_orders = [wait_orders]
                result = order_cancel(wait_orders)
                # gmtrade 撤单成功时返回 None；网关需要非 None 才能判定成功。
                _response(req_id, True, result if result is not None else {"cancelled": True})
            elif action == "shutdown":
                _response(req_id, True, {"stopped": True})
                return 0
            else:
                _response(req_id, False, error=f"未知 action: {action}")
        except Exception as exc:
            _response(req_id, False, error=f"{type(exc).__name__}: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
