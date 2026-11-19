"""
WebSocket 连接管理模块。

本模块为 JingNiGateway 服务提供 WebSocket 连接管理功能，
用于实时数据流传输。

类说明：
    ConnectionManager: 管理 WebSocket 客户端连接
    WebSocketCallbackHandler: 处理实时数据推送的回调

功能特性：
    - 客户端连接管理，支持 API Key 认证
    - 消息队列和消息分发
    - 行情和交易订阅管理
    - 自动心跳检测连接健康状态
    - 支持重连令牌机制
"""

import asyncio
import hmac
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    WebSocket 连接管理器，用于处理客户端连接。

    本类管理 WebSocket 连接、订阅和消息分发，
    用于实时数据流传输。

    属性：
        _active_connections: 活跃的 WebSocket 连接字典
        _message_queues: 每个客户端的消息队列字典
        _subscriptions: 每个客户端的订阅字典
        _last_heartbeat: 最后心跳时间字典
        _client_metadata: 客户端元数据字典
        _reconnect_tokens: 重连令牌字典

    示例：
        >>> manager = ConnectionManager()
        >>> connected = await manager.connect(websocket, "client1", "key", "expected_key")
        >>> await manager.send_to_client("client1", {"type": "data", "value": 123})
    """

    def __init__(self, max_connections: int = 100, heartbeat_interval: int = 30):
        """初始化连接管理器。"""
        self._active_connections: Dict[str, WebSocket] = {}
        self._message_queues: Dict[str, asyncio.Queue] = {}
        self._subscriptions: Dict[str, Dict[str, List[dict]]] = {}
        self._last_heartbeat: Dict[str, datetime] = {}
        self._client_metadata: Dict[str, dict] = {}
        self._reconnect_tokens: Dict[str, str] = {}
        self._max_connections = max(1, int(max_connections))
        self._heartbeat_interval = max(1.0, float(heartbeat_interval))

    async def connect(
        self,
        websocket: WebSocket,
        client_id: str,
        api_key: str,
        expected_api_key: str,
        auto_reconnect: bool = False
    ) -> bool:
        """
        接受 WebSocket 连接。

        参数：
            websocket: WebSocket 连接对象
            client_id: 客户端唯一标识符
            api_key: 客户端提供的 API Key
            expected_api_key: 期望的 API Key（用于验证）
            auto_reconnect: 是否启用自动重连支持

        返回：
            连接成功返回 True，否则返回 False
        """
        try:
            if not expected_api_key or not api_key or not hmac.compare_digest(
                api_key, expected_api_key
            ):
                await websocket.close(code=4001, reason="Invalid API Key")
                return False

            # 同一 client_id 重连时，先关闭旧连接，避免旧连接泄漏
            existing = self._active_connections.get(client_id)
            if existing is not None:
                try:
                    await existing.close(code=4002, reason="Replaced by new connection")
                except Exception:
                    pass
                self.disconnect(client_id)

            if len(self._active_connections) >= self._max_connections:
                await websocket.close(code=4003, reason="Max connections reached")
                logger.warning("拒绝 WebSocket 连接：已达上限 %s", self._max_connections)
                return False

            await websocket.accept()

            self._active_connections[client_id] = websocket
            self._message_queues[client_id] = asyncio.Queue()
            self._subscriptions[client_id] = {}
            self._last_heartbeat[client_id] = datetime.now()
            self._client_metadata[client_id] = {
                "connected_at": datetime.now(),
                "auto_reconnect": auto_reconnect,
                "message_count": 0
            }

            if auto_reconnect:
                self._reconnect_tokens[client_id] = (
                    f"token_{client_id}_{datetime.now().timestamp()}"
                )

            logger.info(f"客户端 {client_id} WebSocket 已连接")

            await self.send_to_client(client_id, {
                "type": "connected",
                "client_id": client_id,
                "timestamp": datetime.now().isoformat(),
                "message": "欢迎使用量化数据网关",
                "reconnect_token": self._reconnect_tokens.get(client_id)
            })

            return True
        except Exception as e:
            logger.error(f"接受 WebSocket 连接失败: {e}")
            return False

    def disconnect(self, client_id: str):
        """
        断开 WebSocket 客户端连接。

        参数：
            client_id: 要断开的客户端标识符
        """
        if client_id in self._active_connections:
            del self._active_connections[client_id]

        if client_id in self._message_queues:
            del self._message_queues[client_id]

        if client_id in self._subscriptions:
            self._cleanup_subscriptions(client_id)
            del self._subscriptions[client_id]

        if client_id in self._last_heartbeat:
            del self._last_heartbeat[client_id]

        if client_id in self._client_metadata:
            del self._client_metadata[client_id]

        self._reconnect_tokens.pop(client_id, None)

        logger.info(f"客户端 {client_id} 已断开连接")

    def touch(self, client_id: str) -> None:
        """记录客户端最近一次活动时间。"""
        if client_id in self._active_connections:
            self._last_heartbeat[client_id] = datetime.now()
            if client_id in self._client_metadata:
                self._client_metadata[client_id]["message_count"] += 1

    async def send_to_client(self, client_id: str, message: dict) -> bool:
        """
        向指定客户端发送消息。

        参数：
            client_id: 目标客户端标识符
            message: 要发送的消息字典

        返回：
            消息发送成功返回 True，否则返回 False
        """
        if client_id not in self._active_connections:
            logger.warning(f"客户端 {client_id} 不在线")
            return False

        try:
            websocket = self._active_connections[client_id]
            await websocket.send_json(message)

            if client_id in self._client_metadata:
                self._client_metadata[client_id]["message_count"] += 1

            return True
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            self.disconnect(client_id)
            return False

    async def broadcast(
        self,
        message: dict,
        target_clients: Optional[List[str]] = None
    ):
        """
        向多个客户端广播消息。

        参数：
            message: 要广播的消息字典
            target_clients: 目标客户端 ID 列表（None 表示所有客户端）
        """
        if target_clients is None:
            target_clients = list(self._active_connections.keys())

        for client_id in target_clients:
            await self.send_to_client(client_id, message)

    def add_subscription(self, client_id: str, sub_type: str, sub_info: dict):
        """
        为客户端添加订阅。

        参数：
            client_id: 客户端标识符
            sub_type: 订阅类型（如 'quote', 'trade'）
            sub_info: 订阅信息字典
        """
        if client_id not in self._subscriptions:
            self._subscriptions[client_id] = {}

        if sub_type not in self._subscriptions[client_id]:
            self._subscriptions[client_id][sub_type] = []

        self._subscriptions[client_id][sub_type].append(sub_info)
        logger.info(f"客户端 {client_id} 订阅了 {sub_type}: {sub_info}")

    def remove_subscription(self, client_id: str, sub_type: str, sub_id: Any):
        """
        移除客户端的订阅。

        参数：
            client_id: 客户端标识符
            sub_type: 订阅类型
            sub_id: 要移除的订阅 ID
        """
        if client_id in self._subscriptions:
            if sub_type in self._subscriptions[client_id]:
                self._subscriptions[client_id][sub_type] = [
                    sub for sub in self._subscriptions[client_id][sub_type]
                    if sub.get('id') != sub_id
                ]

    def _cleanup_subscriptions(self, client_id: str):
        """
        清理客户端的所有订阅。

        参数：
            client_id: 客户端标识符
        """
        if client_id in self._subscriptions:
            for sub_type, subs in self._subscriptions[client_id].items():
                for sub in subs:
                    if 'seq' in sub and sub_type == 'quote':
                        try:
                            from xtquant import xtdata
                            xtdata.unsubscribe_quote(sub['seq'])
                            logger.info(f"取消订阅: {sub['seq']}")
                        except Exception as e:
                            logger.error(f"取消订阅失败: {e}")

            self._subscriptions[client_id] = {}

    def get_subscribed_clients(
        self,
        sub_type: str,
        filter_key: str = None,
        filter_value: Any = None
    ) -> List[str]:
        """
        获取订阅了特定类型的客户端列表。

        参数：
            sub_type: 要筛选的订阅类型
            filter_key: 可选的筛选键
            filter_value: 可选的筛选值（用于匹配 filter_key）

        返回：
            符合订阅条件的客户端 ID 列表
        """
        clients = []
        for client_id, subs in self._subscriptions.items():
            if sub_type in subs:
                for sub in subs[sub_type]:
                    if filter_key is None:
                        clients.append(client_id)
                        break
                    elif sub.get(filter_key) == filter_value:
                        clients.append(client_id)
                        break
        return clients

    async def start_message_dispatcher(self, client_id: str):
        """
        启动客户端的消息分发器。

        本方法持续运行，从客户端的消息队列分发消息，
        并发送心跳检测。

        参数：
            client_id: 客户端标识符
        """
        try:
            while client_id in self._active_connections:
                try:
                    message = await asyncio.wait_for(
                        self._message_queues[client_id].get(),
                        timeout=self._heartbeat_interval
                    )
                    await self.send_to_client(client_id, message)
                except asyncio.TimeoutError:
                    last = self._last_heartbeat.get(client_id)
                    if last is not None:
                        stale = (datetime.now() - last).total_seconds()
                        if stale > self._heartbeat_interval * 2:
                            logger.warning(
                                "客户端 %s 心跳超时（%.1fs），关闭连接",
                                client_id, stale,
                            )
                            try:
                                await self._active_connections[client_id].close(
                                    code=4008, reason="Heartbeat timeout"
                                )
                            except Exception:
                                pass
                            self.disconnect(client_id)
                            break

                    await self.send_to_client(client_id, {
                        "type": "ping",
                        "timestamp": datetime.now().isoformat()
                    })
                except Exception as e:
                    logger.error(f"消息分发错误: {e}")
                    break
        except Exception as e:
            logger.error(f"消息分发器异常: {e}")
        finally:
            logger.info(f"客户端 {client_id} 消息分发器已停止")

    def get_stats(self) -> dict:
        """
        获取连接统计信息。

        返回：
            包含连接统计信息的字典
        """
        return {
            "total_connections": len(self._active_connections),
            "max_connections": self._max_connections,
            "heartbeat_interval": self._heartbeat_interval,
            "clients": {
                client_id: {
                    "connected_at": meta["connected_at"].isoformat(),
                    "auto_reconnect": meta["auto_reconnect"],
                    "message_count": meta["message_count"],
                    "subscriptions": len(self._subscriptions.get(client_id, {}))
                }
                for client_id, meta in self._client_metadata.items()
            }
        }

    @property
    def active_connections(self) -> Dict[str, WebSocket]:
        """获取所有活跃连接。"""
        return self._active_connections

    @property
    def message_queues(self) -> Dict[str, asyncio.Queue]:
        """获取所有消息队列。"""
        return self._message_queues


class WebSocketCallbackHandler:
    """
    WebSocket 回调处理器。

    本类为实时数据推送到 WebSocket 客户端创建回调函数。

    属性：
        _manager: ConnectionManager 实例

    示例：
        >>> handler = WebSocketCallbackHandler(manager)
        >>> callback = handler.create_quote_callback("client1", "000001.SZ", "tick")
    """

    def __init__(self, manager: ConnectionManager):
        """
        初始化回调处理器。

        参数：
            manager: ConnectionManager 实例
        """
        self._manager = manager

    def create_quote_callback(self, client_id: str, stock_code: str, period: str):
        """
        创建行情数据回调函数。

        参数：
            client_id: 接收数据的客户端标识符
            stock_code: 订阅的股票代码
            period: 数据周期（tick, 1m, 5m, 1d 等）

        返回：
            行情数据回调函数
        """
        def callback(datas):
            """行情数据回调。"""
            try:
                for code in datas:
                    data = datas[code]
                    message = {
                        "type": "quote_data",
                        "subscription_type": "quote",
                        "stock_code": code,
                        "period": period,
                        "data": self._serialize_data(data),
                        "timestamp": datetime.now().isoformat()
                    }

                    if client_id in self._manager.message_queues:
                        asyncio.create_task(
                            self._manager.message_queues[client_id].put(message)
                        )

                    logger.debug(f"行情推送: {code} -> 客户端 {client_id}")
            except Exception as e:
                logger.error(f"行情回调错误: {e}")

        return callback

    def create_trade_callback(self, client_id: str, callback_type: str):
        """
        创建交易回调函数。

        参数：
            client_id: 接收数据的客户端标识符
            callback_type: 交易回调类型（order, deal 等）

        返回：
            交易事件回调函数
        """
        def callback(data):
            """交易回调。"""
            try:
                message = {
                    "type": "trade_event",
                    "subscription_type": "trade",
                    "event_type": callback_type,
                    "data": self._serialize_data(data),
                    "timestamp": datetime.now().isoformat()
                }

                if client_id in self._manager.message_queues:
                    asyncio.create_task(
                        self._manager.message_queues[client_id].put(message)
                    )

                logger.debug(f"交易回调: {callback_type} -> 客户端 {client_id}")
            except Exception as e:
                logger.error(f"交易回调错误: {e}")

        return callback

    def _serialize_data(self, data: Any) -> Any:
        """
        序列化数据以便 JSON 传输。

        参数：
            data: 要序列化的数据

        返回：
            可 JSON 序列化的数据
        """
        from providers.base import serialize_data
        return serialize_data(data)
