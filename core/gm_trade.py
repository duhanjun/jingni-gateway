"""
GM (掘金量化) 类型化交易服务。

只暴露 order_volume / order_cancel / 查询，不把下单能力留在通用反射 RPC。
"""

import asyncio
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from core.executor import run_module_call

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("gm.audit")

SIDE_BUY = 1
SIDE_SELL = 2
ORDER_TYPE_LIMIT = 1
ORDER_TYPE_MARKET = 2
POSITION_EFFECT_OPEN = 1
POSITION_EFFECT_CLOSE = 2


class GMTradeError(RuntimeError):
    """GM 交易错误基类。"""


class GMConfigError(GMTradeError):
    """GM 配置缺失。"""


class GMNotLoggedInError(GMTradeError):
    """GM 交易账户未登录或资金查询为空。"""


class GMTradeService:
    def __init__(self, api, config):
        self._api = api
        self._config = config
        self._account = getattr(getattr(config, "GM", None), "account_id", "") or ""
        self._timeout = getattr(config, "CONNECT_TIMEOUT", 30)

        self._order_cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._order_cache_lock = threading.Lock()
        self._order_cache_ttl = 600.0
        self._order_cache_max = 1000

    def _require_api(self):
        if self._api is None:
            raise GMConfigError("GM API 不可用，请确认 gm 模块已安装且 Token 已配置")
        gm_cfg = getattr(self._config, "GM", None)
        if not gm_cfg or not getattr(gm_cfg, "token", ""):
            raise GMConfigError("GM Token 未配置（JINGNI_GM_TOKEN），已拒绝调用交易接口")
        return self._api

    async def _call(self, function: str, kwargs: Dict[str, Any], timeout: Optional[float] = None) -> Any:
        api = self._require_api()
        func = getattr(api, function, None)
        if func is None or not callable(func):
            raise GMTradeError(f"GM API 不支持 {function}")
        try:
            return await run_module_call(
                "gmtrade",
                func,
                (),
                kwargs,
                timeout=timeout or self._timeout,
                lane="trade",
            )
        except (GMTradeError, TimeoutError):
            raise
        except Exception as exc:
            # gm.api 抛的是 GmError，不是 GMTradeError；统一转成网关可序列化的错误
            raise GMTradeError(f"GM {function} 调用失败: {exc}") from exc

    async def place_order(
        self,
        symbol: str,
        volume: int,
        side: int,
        order_type: int,
        price: float,
        position_effect: int = POSITION_EFFECT_OPEN,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if client_order_id:
            cached = self._get_cached(client_order_id)
            if cached is not None:
                replay = dict(cached)
                replay["idempotent_replay"] = True
                return replay

        kwargs = {
            "symbol": symbol,
            "volume": int(volume),
            "side": SIDE_BUY if side == 0 else SIDE_SELL,
            "order_type": ORDER_TYPE_LIMIT if order_type == 0 else ORDER_TYPE_MARKET,
            "price": float(price),
            "position_effect": int(position_effect),
        }
        if self._account:
            kwargs["account"] = self._account

        raw = await self._call("order_volume", kwargs)
        order = self._first_order(raw)
        order_id = None
        if isinstance(order, dict):
            order_id = order.get("order_id") or order.get("orderId")
        accepted = order_id is not None

        canonical = {
            "order_id": str(order_id) if order_id is not None else None,
            "symbol": symbol,
            "side": "buy" if side == 0 else "sell",
            "volume": int(volume),
            "price": float(price),
            "order_type": "limit" if order_type == 0 else "market",
            "position_effect": int(position_effect),
            "state": "accepted" if accepted else "failed",
            "success": accepted,
            "raw": raw,
            "idempotent_replay": False,
        }

        # GM 的 order_volume 返回“已报”后，柜台仍可能立即拒单（status=8）。
        # 做一次短延迟查询，避免 API 把已拒绝委托返回成 accepted。
        if accepted:
            snapshot = await self._initial_order_snapshot(str(order_id))
            if snapshot is not None:
                canonical["status"] = snapshot.get("status")
                if snapshot.get("status") == 8:
                    canonical["state"] = "rejected"
                    canonical["success"] = False
                    canonical["reject_reason"] = snapshot.get("ord_rej_reason_detail")

        if client_order_id and accepted:
            self._cache_order(client_order_id, canonical)

        audit_logger.info(
            "place_order symbol=%s side=%s volume=%s state=%s order_id=%s",
            symbol, canonical["side"], volume, canonical["state"], canonical["order_id"],
        )
        return canonical

    async def _initial_order_snapshot(self, order_id: str) -> Optional[Dict[str, Any]]:
        """短延迟查一次委托，识别柜台立即拒单；查询失败不影响已受理结果。"""
        try:
            await asyncio.sleep(0.15)
            orders = await self.query_orders()
        except Exception as exc:
            logger.warning("GM 下单后状态查询失败: %s", exc)
            return None
        for order in orders:
            if isinstance(order, dict) and str(order.get("order_id")) == str(order_id):
                return order
        return None

    async def cancel_order(self, order_id: str, cl_ord_id: Optional[str] = None) -> Dict[str, Any]:
        # gm.api / gmtrade.order_cancel 接收单个 dict 或 list[dict]，键是 cl_ord_id/account_id。
        # API 允许调用方传 order_id；gmtrade 需要 cl_ord_id，先按委托列表解析一次。
        target_cl_ord_id = cl_ord_id or str(order_id)
        if not cl_ord_id:
            try:
                for order in await self.query_orders():
                    if isinstance(order, dict) and str(order.get("order_id")) == str(order_id):
                        target_cl_ord_id = str(order.get("cl_ord_id") or order_id)
                        break
            except Exception as exc:
                logger.warning("解析 GM order_id -> cl_ord_id 失败，按原值撤单: %s", exc)
        kwargs = {"cl_ord_id": target_cl_ord_id}
        if self._account:
            kwargs["account_id"] = self._account
        raw = await self._call("order_cancel", kwargs)
        success = raw is not False and raw is not None
        audit_logger.info("cancel_order order_id=%s success=%s", order_id, success)
        return {
            "success": success,
            "cancel_state": "confirmed" if success else "failed",
            "order_id": str(order_id),
            "raw": raw,
        }

    async def query_orders(self) -> List[Dict[str, Any]]:
        # gm.api.get_orders() 不接受账号参数，返回当前终端关联账户的日内委托
        raw = await self._call("get_orders", {})
        return raw if isinstance(raw, list) else []

    async def query_asset(self) -> Dict[str, Any]:
        kwargs = {"account_id": self._account} if self._account else {}
        raw = await self._call("get_cash", kwargs)
        if not isinstance(raw, dict) or not raw:
            raise GMNotLoggedInError(
                "GM 交易账户未登录或资金为空，请在掘金终端确认交易账户已连接"
            )
        return raw

    async def query_positions(self) -> List[Dict[str, Any]]:
        kwargs = {"account_id": self._account} if self._account else {}
        raw = await self._call("get_position", kwargs)
        return raw if isinstance(raw, list) else []

    @staticmethod
    def _first_order(raw: Any) -> Optional[Dict[str, Any]]:
        if isinstance(raw, list) and raw:
            return raw[0] if isinstance(raw[0], dict) else None
        if isinstance(raw, dict):
            return raw
        return None

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
