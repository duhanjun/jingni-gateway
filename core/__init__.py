"""
核心模块初始化。

本模块导出应用程序中使用的核心组件：
- ConnectionManager: WebSocket 连接管理器
- WebSocketCallbackHandler: WebSocket 回调处理器
- execute_rpc_call: RPC 执行函数
- get_module_reference: 模块引用获取器
- is_function_whitelisted: 白名单检查器
- RPC_WHITELIST: RPC 函数白名单
"""

from .websocket import ConnectionManager, WebSocketCallbackHandler
from .rpc import execute_rpc_call, get_module_reference, is_function_whitelisted
from .whitelist import RPC_WHITELIST

__all__ = [
    'ConnectionManager',
    'WebSocketCallbackHandler',
    'execute_rpc_call',
    'get_module_reference',
    'is_function_whitelisted',
    'RPC_WHITELIST',
]
