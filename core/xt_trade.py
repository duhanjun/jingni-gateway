"""
XtQuant（迅投 QMT）类型化交易服务。

- 所有调用走 xttrader 的 trade lane；
- 下单/撤单不再通过通用反射 RPC；
- 进程内 client_order_id 幂等缓存，重启丢失。
"""

import asyncio
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from core.executor import run_module_call
from core.rpc import execute_xttrader_method

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("xtquant.audit")

# xtconstant 常用值（避免在无 xtquant 环境 import 失败）
STOCK_BUY = 23
STOCK_SELL = 24
FIX_PRICE = 11
LATEST_PRICE = 5

# 委托状态（xtconstant.ORDER_STATUS_*）
ORDER_STATUS_UNREPORTED = 48
ORDER_STATUS_WAIT_REPORTING = 49
ORDER_STATUS_REPORTED = 50
ORDER_STATUS_REPORTED_CANCEL = 51
ORDER_STATUS_PARTSUCC_CANCEL = 52
ORDER_STATUS_PART_CANCEL = 53
ORDER_STATUS_CANCELED = 54
ORDER_STATUS_PART_SUCC = 55
ORDER_STATUS_SUCCEEDED = 56
ORDER_STATUS_JUNK = 57
ORDER_STATUS_UNKNOWN = 255

# 撤单成功的终态：部撤 / 全撤 / 废单
TERMINAL_CANCEL_STATUS = {
    ORDER_STATUS_PART_CANCEL,
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_JUNK,
}
# 仍在场内、撤单尚未落地的状态
ACTIVE_ORDER_STATUS = {
    ORDER_STATUS_UNREPORTED,
    ORDER_STATUS_WAIT_REPORTING,
    ORDER_STATUS_REPORTED,
    ORDER_STATUS_REPORTED_CANCEL,
    ORDER_STATUS_PARTSUCC_CANCEL,
}
FILLED_STATUS = {ORDER_STATUS_PART_SUCC, ORDER_STATUS_SUCCEEDED}

ORDER_STATUS_TEXT = {
    ORDER_STATUS_UNREPORTED: "unreported",
    ORDER_STATUS_WAIT_REPORTING: "wait_reporting",
    ORDER_STATUS_REPORTED: "reported",
    ORDER_STATUS_REPORTED_CANCEL: "reported_cancel",
    ORDER_STATUS_PARTSUCC_CANCEL: "part_succ_cancel",
    ORDER_STATUS_PART_CANCEL: "part_cancel",
    ORDER_STATUS_CANCELED: "canceled",
    ORDER_STATUS_PART_SUCC: "part_succeeded",
    ORDER_STATUS_SUCCEEDED: "succeeded",
    ORDER_STATUS_JUNK: "junk",
    ORDER_STATUS_UNKNOWN: "unknown",
}


class XtTradeError(RuntimeError):
    """XtQuant 交易错误基类。"""


class XtConfigError(XtTradeError):
    """配置缺失（未配置 QMT 资金账户）。"""


class XtTradeService:
    def __init__(self, provider, config=None):
        self._provider = provider
        self._config = config or getattr(provider, "_config", None)
        self._account = getattr(self._config, "ACCOUNT_ID", "") if self._config else ""
        self._timeout = getattr(self._config, "CONNECT_TIMEOUT", 30) if self._config else 30
        # 撤单终态对账：cancel_order_stock 返回 0 只代表提交成功，必须等委托状态落地
        self._cancel_timeout = float(
            getattr(self._config, "XT_CANCEL_RECONCILE_TIMEOUT", 5) if self._config else 5
        )
        self._cancel_poll_interval = float(
            getattr(self._config, "XT_CANCEL_POLL_INTERVAL", 0.2) if self._config else 0.2
        )

        self._order_cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._order_cache_lock = threading.Lock()
        self._order_cache_ttl = 600.0
        self._order_cache_max = 1000

    def _require_account(self) -> str:
        if not self._account:
            raise XtConfigError("未配置 QMT 资金账户（JINGNI_QMT_ACCOUNT）")
        return str(self._account)

    async def _call(self, function: str, kwargs: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        return await run_module_call(
            "xttrader",
            execute_xttrader_method,
            (function, [], kwargs),
            {},
            timeout=timeout or self._timeout,
            lane="trade",
        )

    async def place_order(
        self,
        stock_code: str,
        order_type: int,
        order_volume: int,
        price_type: int,
        price: float,
        client_order_id: Optional[str] = None,
        strategy_name: str = "jingni-gateway",
    ) -> Dict[str, Any]:
        account = self._require_account()

        if client_order_id:
            cached = self._get_cached(client_order_id)
            if cached is not None:
                replay = dict(cached)
                replay["idempotent_replay"] = True
                return replay

        xt_order_type = STOCK_BUY if order_type == 0 else STOCK_SELL
        xt_price_type = FIX_PRICE if price_type == 0 else LATEST_PRICE

        result = await self._call(
            "order_stock",
            {
                "account": account,
                "stock_code": stock_code,
                "order_type": xt_order_type,
                "order_volume": int(order_volume),
                "price_type": xt_price_type,
                "price": float(price),
                "strategy_name": strategy_name,
                "order_remark": client_order_id or "",
            },
        )

        raw = result.get("data") if isinstance(result, dict) else None
        order_id = raw if isinstance(raw, int) else None
        accepted = bool(result.get("success")) and order_id is not None and order_id > 0

        canonical = {
            "order_id": str(order_id) if accepted else None,
            "stock_code": stock_code,
            "side": "buy" if order_type == 0 else "sell",
            "volume": int(order_volume),
            "price": float(price),
            "price_type": "limit" if price_type == 0 else "market",
            "state": "accepted" if accepted else "failed",
            "success": accepted,
            "message": result.get("error") if isinstance(result, dict) else None,
            "raw": result,
            "idempotent_replay": False,
        }

        if client_order_id and canonical["success"]:
            self._cache_order(client_order_id, canonical)

        audit_logger.info(
            "place_order stock=%s side=%s volume=%s price=%s state=%s order_id=%s",
            stock_code, canonical["side"], order_volume, price,
            canonical["state"], canonical["order_id"],
        )
        return canonical

    async def cancel_order(self, order_id: int) -> Dict[str, Any]:
        """撤单并对账终态。

        ``cancel_order_stock`` 返回 0 仅表示撤单请求被受理，不代表委托已撤。
        这里按“提交 → 轮询委托状态 → 终态判定”处理：

        - 53/54/57（部撤/全撤/废单）→ ``confirmed``；
        - 55/56（部成/已成）→ ``failed``，原因 ``ORDER_ALREADY_FILLED``；
        - 其余活动状态或超时 → ``pending``；
        - 查不到委托 → ``unknown``。
        """
        account = self._require_account()
        result = await self._call(
            "cancel_order_stock",
            {"account": account, "order_id": int(order_id)},
        )
        data = result.get("data") if isinstance(result, dict) else None
        request_accepted = bool(result.get("success")) and data == 0

        deadline = time.monotonic() + self._cancel_timeout
        polls = 0
        last_order: Optional[Dict[str, Any]] = None
        status: Optional[int] = None

        while True:
            polls += 1
            try:
                orders = await self.query_orders()
            except XtTradeError as exc:
                logger.warning("撤单对账查询失败: %s", exc)
                orders = []
            last_order = next(
                (o for o in orders if str(o.get("order_id")) == str(order_id)),
                None,
            )
            status = self._extract_status(last_order)

            if status in TERMINAL_CANCEL_STATUS:
                break
            if status in FILLED_STATUS:
                break
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(self._cancel_poll_interval)

        if status in TERMINAL_CANCEL_STATUS:
            state = "confirmed"
            success = True
            error = None
        elif status in FILLED_STATUS:
            state = "failed"
            success = False
            error = "ORDER_ALREADY_FILLED"
        elif status is None:
            state = "unknown"
            success = False
            error = "ORDER_NOT_FOUND"
        else:
            state = "pending"
            success = False
            error = "CANCEL_NOT_CONFIRMED"

        payload = {
            "success": success,
            "cancel_state": state,
            "order_id": str(order_id),
            "status": status,
            "status_text": ORDER_STATUS_TEXT.get(status, "unknown"),
            "request_accepted": request_accepted,
            "polls": polls,
            "error": error,
            "raw": result,
            "order": last_order,
        }
        audit_logger.info(
            "cancel_order order_id=%s request_accepted=%s state=%s status=%s polls=%s",
            order_id, request_accepted, state, status, polls,
        )
        return payload

    @staticmethod
    def _extract_status(order: Optional[Dict[str, Any]]) -> Optional[int]:
        """从原始委托字典/对象中读取 order_status。"""
        if not order:
            return None
        value = None
        if isinstance(order, dict):
            value = order.get("order_status")
            if value is None:
                value = order.get("status")
        else:
            value = getattr(order, "order_status", None)
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    async def query_orders(self) -> List[Dict[str, Any]]:
        account = self._require_account()
        result = await self._call(
            "query_stock_orders",
            {"account": account, "cancelable_only": False},
        )
        if not result.get("success"):
            raise XtTradeError(result.get("error") or "查询委托失败")
        data = result.get("data")
        return data if isinstance(data, list) else []

    async def query_asset(self) -> Dict[str, Any]:
        account = self._require_account()
        result = await self._call("query_stock_asset", {"account": account})
        if not result.get("success"):
            raise XtTradeError(result.get("error") or "查询资产失败")
        return result.get("data") if isinstance(result.get("data"), dict) else {"raw": result.get("data")}

    async def query_positions(self) -> List[Dict[str, Any]]:
        account = self._require_account()
        result = await self._call("query_stock_positions", {"account": account})
        if not result.get("success"):
            raise XtTradeError(result.get("error") or "查询持仓失败")
        data = result.get("data")
        return data if isinstance(data, list) else []

    def _get_cached(self, client_order_id: str) -> Optional[Dict[str, Any]]:
        with self._order_cache_lock:
            entry = self._order_cache.get(client_order_id)
            if entry is None:
                return None
            if time.monotonic() - entry["ts"] > self._order_cache_ttl:
                self._order_cache.pop(client_order_id, None)
                return None
            self._order_cache.move_to_end(client_order_id)
            return entry["result"]

    def _cache_order(self, client_order_id: str, result: Dict[str, Any]) -> None:
        with self._order_cache_lock:
            self._order_cache[client_order_id] = {
                "ts": time.monotonic(),
                "result": dict(result),
            }
            self._order_cache.move_to_end(client_order_id)
            while len(self._order_cache) > self._order_cache_max:
                self._order_cache.popitem(last=False)
