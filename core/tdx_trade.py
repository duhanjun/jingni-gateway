"""
TdxQuant 交易服务。

职责：
- 下单：Value 三态转成 canonical order_state；
- 撤单：不信任 cancel_order_stock 的返回值，按委托状态 + 资金变化对账；
- 查询：委托、资产、持仓；
- 所有 TQ 调用都走 module="tdxquant" 的串行执行器；
- 幂等：进程内缓存 + 可选 SQLite 落盘，重启后按 client_order_id 重放。
"""

import asyncio
import json
import logging
import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.executor import run_module_call
from providers.tdx_provider import TdxError, TdxProvider

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("tdx.audit")

ORDER_TYPE_MAP = {0: "buy", 1: "sell"}
PRICE_TYPE_MAP = {0: "limit", 1: "market", 2: "limit_up", 3: "limit_down"}
ORDER_STATE_MAP = {0: "failed", 1: "pending_confirm", 2: "accepted"}
STATUS_TEXT = {
    0: "invalid",
    1: "open",
    2: "partially_filled",
    3: "filled",
    4: "partially_cancelled",
    5: "cancelled",
}
TERMINAL_CANCEL_STATUS = {0, 4, 5}


class TdxNotLoggedInError(TdxError):
    """TQ 账户未登录或资产返回为空。"""


class TdxTradeService:
    """tqcenter 交易服务。"""

    def __init__(self, provider: TdxProvider, config=None, state_path: Optional[str] = None):
        self._provider = provider
        self._config = config or getattr(provider, "_config", None)
        tdx = getattr(self._config, "TDX", None)
        self._timeout = tdx.timeout if tdx else 30
        self._cancel_timeout = tdx.cancel_reconcile_timeout if tdx else 30
        self._poll_interval = tdx.poll_interval if tdx else 1.0

        # 进程内下单幂等缓存：key = client_order_id，TTL 10 分钟，最多 1000 条。
        # accepted 与 pending_confirm 都缓存；可选 SQLite 落盘用于跨重启重放。
        self._order_cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._order_cache_lock = threading.Lock()
        self._order_cache_ttl = 600.0
        self._order_cache_max = 1000
        self._state_path = str(state_path) if state_path else None
        self._state_lock = threading.Lock()
        if self._state_path:
            self._init_state_store()

    # ------------------------------------------------------------------
    # 下单
    # ------------------------------------------------------------------
    def _place_sync(
        self,
        stock_code: str,
        order_type: int,
        order_volume: int,
        price_type: int,
        price: float,
        notify: int,
    ) -> Dict[str, Any]:
        tq = self._provider.ensure_initialized()
        handle = self._provider.account_handle()
        raw = tq.order_stock(
            account_id=handle,
            stock_code=stock_code,
            order_type=order_type,
            order_volume=order_volume,
            price_type=price_type,
            price=price,
            notify=notify,
        )
        raw_dict = raw if isinstance(raw, dict) else {"Value": raw}
        value = int(raw_dict.get("Value", 0))
        wtbh = raw_dict.get("Wtbh")
        return {
            "order_id": str(wtbh) if wtbh else None,
            "stock_code": stock_code,
            "side": ORDER_TYPE_MAP.get(order_type, str(order_type)),
            "volume": int(order_volume),
            "price": float(price),
            "price_type": PRICE_TYPE_MAP.get(price_type, str(price_type)),
            "state": ORDER_STATE_MAP.get(value, "unknown"),
            "success": value in (1, 2),
            "raw_value": value,
            "message": raw_dict.get("Msg"),
            "raw": raw_dict,
        }

    async def place_order(
        self,
        stock_code: str,
        order_type: int,
        order_volume: int,
        price_type: int,
        price: float,
        notify: int = 0,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if client_order_id:
            cached = self._get_cached_order(client_order_id)
            if cached is not None:
                replay = dict(cached)
                replay["idempotent_replay"] = True
                audit_logger.info(
                    "place_order replay client_order_id=%s order_id=%s",
                    client_order_id, replay.get("order_id"),
                )
                return replay

        result = await run_module_call(
            "tdxquant",
            self._place_sync,
            (stock_code, order_type, order_volume, price_type, price, notify),
            {},
            timeout=self._timeout,
            lane="trade",
        )
        result["idempotent_replay"] = False

        # pending_confirm 没有 order_id，但同样必须幂等，避免重复发送客户端确认信号
        if client_order_id and result.get("state") in ("accepted", "pending_confirm"):
            self._cache_order(client_order_id, result)

        audit_logger.info(
            "place_order stock=%s side=%s volume=%s price=%s state=%s order_id=%s raw=%s",
            stock_code, result.get("side"), order_volume, price,
            result.get("state"), result.get("order_id"), result.get("raw_value"),
        )
        return result

    def _get_cached_order(self, client_order_id: str) -> Optional[Dict[str, Any]]:
        with self._order_cache_lock:
            entry = self._order_cache.get(client_order_id)
            if entry is not None:
                if time.monotonic() - entry["ts"] > self._order_cache_ttl:
                    self._order_cache.pop(client_order_id, None)
                else:
                    self._order_cache.move_to_end(client_order_id)
                    return entry["result"]

        persisted = self._get_persisted_order(client_order_id)
        if persisted is None:
            return None
        with self._order_cache_lock:
            self._order_cache[client_order_id] = {
                "ts": time.monotonic(),
                "result": dict(persisted),
            }
            self._order_cache.move_to_end(client_order_id)
        return persisted

    def _cache_order(self, client_order_id: str, result: Dict[str, Any]) -> None:
        self._save_persisted_order(client_order_id, result)
        with self._order_cache_lock:
            self._order_cache[client_order_id] = {
                "ts": time.monotonic(),
                "result": dict(result),
            }
            self._order_cache.move_to_end(client_order_id)
            while len(self._order_cache) > self._order_cache_max:
                self._order_cache.popitem(last=False)

    def _init_state_store(self) -> None:
        path = Path(self._state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._state_lock:
            conn = sqlite3.connect(str(path), timeout=2)
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS tdx_order_idempotency ("
                    "client_order_id TEXT PRIMARY KEY, "
                    "created_at REAL NOT NULL, "
                    "result_json TEXT NOT NULL)"
                )
                conn.commit()
            finally:
                conn.close()

    def _get_persisted_order(self, client_order_id: str) -> Optional[Dict[str, Any]]:
        if not self._state_path:
            return None
        with self._state_lock:
            conn = sqlite3.connect(self._state_path, timeout=2)
            try:
                row = conn.execute(
                    "SELECT created_at, result_json FROM tdx_order_idempotency "
                    "WHERE client_order_id = ?",
                    (client_order_id,),
                ).fetchone()
                if row is None:
                    return None
                if time.time() - float(row[0]) > self._order_cache_ttl:
                    conn.execute(
                        "DELETE FROM tdx_order_idempotency WHERE client_order_id = ?",
                        (client_order_id,),
                    )
                    conn.commit()
                    return None
                return json.loads(row[1])
            except (sqlite3.Error, ValueError, TypeError) as exc:
                logger.warning("tdx idempotency read failed: %s", exc)
                return None
            finally:
                conn.close()

    def _save_persisted_order(self, client_order_id: str, result: Dict[str, Any]) -> None:
        if not self._state_path:
            return
        payload = json.dumps(result, ensure_ascii=False, default=str)
        with self._state_lock:
            conn = sqlite3.connect(self._state_path, timeout=2)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO tdx_order_idempotency "
                    "(client_order_id, created_at, result_json) VALUES (?, ?, ?)",
                    (client_order_id, time.time(), payload),
                )
                conn.commit()
            except sqlite3.Error as exc:
                logger.warning("tdx idempotency write failed: %s", exc)
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # 撤单 + 对账
    # ------------------------------------------------------------------
    def _cancel_sync(self, stock_code: str, order_id: str) -> Dict[str, Any]:
        tq = self._provider.ensure_initialized()
        handle = self._provider.account_handle()
        raw = tq.cancel_order_stock(handle, stock_code, str(order_id))
        return raw if isinstance(raw, dict) else {"Value": raw}

    async def cancel_order(self, stock_code: str, order_id: str) -> Dict[str, Any]:
        """
        撤单并等待状态落地。

        cancel_order_stock 的返回值不可信：
        - Value=0 可能是“提交被拒”，也可能是“已提交但异步生效”；
        - 刚下单立刻撤时，终端常直接拒绝提交。
        因此以委托状态（0/4/5）为最终判据，并在仍为未成交时重试提交。
        """
        before = await self.query_asset()
        deadline = time.monotonic() + self._cancel_timeout
        last_order = None
        last_raw: Dict[str, Any] = {}
        polls = 0
        attempts = 0

        while attempts < 5 and time.monotonic() < deadline:
            attempts += 1
            last_raw = await run_module_call(
                "tdxquant",
                self._cancel_sync,
                (stock_code, str(order_id)),
                {},
                timeout=self._timeout,
                lane="trade",
            )
            raw_value = int(last_raw.get("Value", 0)) if isinstance(last_raw, dict) else 0

            # 每次提交后观察 3 个轮询周期
            for _ in range(3):
                polls += 1
                last_order = await self._find_order(order_id)
                if self._is_terminal(last_order):
                    return await self._cancel_result(
                        stock_code, order_id, before, last_raw, "confirmed",
                        last_order, polls, attempts,
                    )
                if time.monotonic() >= deadline:
                    break
                await asyncio.sleep(self._poll_interval)

            if raw_value != 0:
                # 提交已被受理，不再重复提交，继续轮询到截止
                while time.monotonic() < deadline:
                    polls += 1
                    last_order = await self._find_order(order_id)
                    if self._is_terminal(last_order):
                        return await self._cancel_result(
                            stock_code, order_id, before, last_raw, "confirmed",
                            last_order, polls, attempts,
                        )
                    await asyncio.sleep(self._poll_interval)
                break

        state = "pending" if last_order else "failed"
        return await self._cancel_result(
            stock_code, order_id, before, last_raw, state,
            last_order, polls, attempts,
        )

    async def _find_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        orders = await self.query_orders()
        return next(
            (o for o in orders if str(o.get("order_id")) == str(order_id)),
            None,
        )

    @staticmethod
    def _is_terminal(order: Optional[Dict[str, Any]]) -> bool:
        if not order:
            return False
        try:
            return int(order.get("status")) in TERMINAL_CANCEL_STATUS
        except (TypeError, ValueError):
            return False

    async def _cancel_result(
        self,
        stock_code: str,
        order_id: str,
        before: Dict[str, Any],
        raw: Dict[str, Any],
        state: str,
        order: Optional[Dict[str, Any]],
        polls: int,
        attempts: int,
    ) -> Dict[str, Any]:
        after = await self.query_asset()
        result = {
            "success": state == "confirmed",
            "cancel_state": state,
            "order_id": str(order_id),
            "stock_code": stock_code,
            "status": order.get("status") if order else None,
            "status_text": order.get("status_text") if order else None,
            "polls": polls,
            "attempts": attempts,
            "cash_before": before.get("cash"),
            "cash_after": after.get("cash"),
            "raw_value": int(raw.get("Value", 0)) if isinstance(raw, dict) else 0,
            "raw": raw,
        }
        audit_logger.info(
            "cancel_order stock=%s order_id=%s attempts=%s raw_value=%s state=%s status=%s polls=%s",
            stock_code, order_id, attempts, result["raw_value"], state, result["status"], polls,
        )
        return result

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def _query_orders_sync(self) -> List[Dict[str, Any]]:
        tq = self._provider.ensure_initialized()
        handle = self._provider.account_handle()
        return tq.query_stock_orders(handle)

    def _query_asset_sync(self) -> Dict[str, Any]:
        tq = self._provider.ensure_initialized()
        handle = self._provider.account_handle()
        return tq.query_stock_asset(handle)

    def _query_positions_sync(self) -> List[Dict[str, Any]]:
        tq = self._provider.ensure_initialized()
        handle = self._provider.account_handle()
        return tq.query_stock_positions(handle)

    async def query_orders(self) -> List[Dict[str, Any]]:
        rows = await run_module_call(
            "tdxquant", self._query_orders_sync, (), {}, timeout=self._timeout, lane="trade"
        )
        if isinstance(rows, dict):
            rows = rows.get("Value") or []
        if not isinstance(rows, list):
            return []
        return [self._normalize_order(row) for row in rows]

    async def query_asset(self) -> Dict[str, Any]:
        raw = await run_module_call(
            "tdxquant", self._query_asset_sync, (), {}, timeout=self._timeout, lane="trade"
        )
        if not isinstance(raw, dict) or (
            not raw.get("Value") and not raw.get("Cash")
        ):
            raise TdxNotLoggedInError("账户未登录或资产为空，请先在通达信客户端登录模拟/实盘账户")
        if raw.get("ErrorId", "0") != "0":
            return {"ErrorId": raw.get("ErrorId"), "raw": raw}
        try:
            cash = float(raw.get("Cash"))
        except (TypeError, ValueError):
            cash = None
        return {
            "cash": cash,
            "asset": raw.get("Asset"),
            "market_value": raw.get("MarketValue"),
            "raw": raw,
        }

    async def query_positions(self) -> List[Dict[str, Any]]:
        rows = await run_module_call(
            "tdxquant", self._query_positions_sync, (), {}, timeout=self._timeout, lane="trade"
        )
        if isinstance(rows, dict):
            rows = rows.get("Value") or []
        if not isinstance(rows, list):
            return []
        return [self._normalize_position(row) for row in rows]

    # ------------------------------------------------------------------
    # 规范化
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_order(row: Dict[str, Any]) -> Dict[str, Any]:
        try:
            status = int(row.get("Status"))
        except (TypeError, ValueError):
            status = None
        return {
            "order_id": str(row.get("Wtbh")),
            "stock_code": row.get("Code"),
            "time": row.get("Time"),
            "side": ORDER_TYPE_MAP.get(
                row.get("BSFlag"),
                "unknown" if row.get("BSFlag") == -1 else str(row.get("BSFlag")),
            ),
            "status": status,
            "status_text": STATUS_TEXT.get(status, "unknown") if status is not None else "unknown",
            "order_price": row.get("WtPrice"),
            "filled_price": row.get("CjPrice"),
            "filled_volume": row.get("CjVol"),
            "order_volume": row.get("WtVol"),
            "raw": row,
        }

    @staticmethod
    def _normalize_position(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "stock_code": row.get("Code"),
            "total_volume": row.get("TotalVol"),
            "available_volume": row.get("CanUseVol"),
            "cost": row.get("Cbj"),
            "raw": row,
        }
