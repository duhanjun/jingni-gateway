#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JingNiGateway - 量化数据网关服务

基于 FastAPI 构建的量化数据网关服务，支持 xtquant 和 GM (掘金量化) 两大平台。

功能特性：
- 双数据源支持（xtquant 和 GM）
- WebSocket 实时推送
- API Key 认证
- 自动数据序列化
"""

from contextlib import asynccontextmanager
from datetime import datetime
import asyncio
import json
import logging
import uvicorn

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends

from config import config
from api import gm_router, xtquant_router, tdx_router, get_api_key
from api.xtquant import get_xtquant_provider
from api.gm import get_gm_provider, set_gm_provider
from api.tdxquant import get_tdx_provider, set_tdx_provider
from core.websocket import ConnectionManager, WebSocketCallbackHandler
from core.rpc import (
    execute_rpc_call,
    initialize_modules,
    create_xttrader_instance,
    execute_xttrader_method,
    get_xttrader_instance,
    get_xttrader_state,
)
from core.executor import shutdown_executors

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

XTDATA_AVAILABLE = False
XTTRADER_AVAILABLE = False
GM_AVAILABLE = False

try:
    from xtquant import xtdata
    XTDATA_AVAILABLE = True
    logger.info("xtdata 模块可用")
except ImportError:
    logger.warning("xtdata 模块不可用")

try:
    from xtquant import xttrader
    XTTRADER_AVAILABLE = True
    logger.info("xttrader 模块可用")
except ImportError:
    logger.warning("xttrader 模块不可用")

ws_manager = ConnectionManager(
    max_connections=config.MAX_CONNECTIONS,
    heartbeat_interval=config.WS_HEARTBEAT_INTERVAL,
)
ws_callback_handler = WebSocketCallbackHandler(ws_manager)

gm_provider = None
tdx_provider = None


def _print_init_section(title: str):
    """打印初始化分节标题。"""
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"  {title}")
    logger.info("=" * 60)


def _print_init_status(provider: str, module: str, status: str, detail: str = ""):
    """打印初始化状态（带对齐格式）。"""
    status_icon = "✓" if status == "OK" else "✗"
    detail_str = f" ({detail})" if detail else ""
    logger.info(f"  [{status_icon}] {provider:12} | {module:20} | {status}{detail_str}")


def _init_xtquant():
    """初始化 XtQuant 模块。"""
    _print_init_section("XtQuant (迅投QMT) 初始化")

    _print_init_status("XtQuant", "xtdata", "OK" if XTDATA_AVAILABLE else "FAIL")
    _print_init_status("XtQuant", "xttrader", "OK" if XTTRADER_AVAILABLE else "FAIL")

    if XTTRADER_AVAILABLE:
        _init_xttrader()


def _init_gm():
    """初始化 GM 模块。"""
    global gm_provider

    _print_init_section("GM (掘金量化) 初始化")

    logger.info("正在初始化 GM 数据源...")
    gm_provider = get_gm_provider()
    set_gm_provider(gm_provider)

    if gm_provider:
        gm_status = "OK" if gm_provider.is_available else "FAIL"
        _print_init_status("GM", "gm.api", gm_status)

        if gm_provider.is_available:
            _print_init_status(
                "GM", "Token",
                "OK" if gm_provider.token_configured else "WARN",
                "已配置" if gm_provider.token_configured else "未配置 JINGNI_GM_TOKEN",
            )
            _print_init_status(
                "GM", "账户 ID",
                "OK" if gm_provider.account_configured else "WARN",
                "已配置" if gm_provider.account_configured else "未配置 JINGNI_GM_ACCOUNT_ID",
            )
            mode = config.GM.mode if hasattr(config, 'GM') and hasattr(config.GM, 'mode') else "N/A"
            _print_init_status("GM", "运行模式", "OK", mode)
    else:
        _print_init_status("GM", "gm.api", "FAIL")


def _init_tdx():
    """初始化 TdxQuant (通达信) 模块。"""
    global tdx_provider

    _print_init_section("TdxQuant (通达信) 初始化")

    tdx_provider = get_tdx_provider()
    set_tdx_provider(tdx_provider)

    if not tdx_provider.is_enabled:
        _print_init_status("TdxQuant", "tqcenter", "OFF", "未启用")
        return

    _print_init_status(
        "TdxQuant", "tqcenter",
        "OK" if tdx_provider.is_available else "FAIL",
        tdx_provider.get_version() if tdx_provider.is_available else "",
    )
    _print_init_status(
        "TdxQuant", "account",
        "OK" if tdx_provider.account_configured else "WARN",
        "已配置" if tdx_provider.account_configured else "未配置 JINGNI_TDX_ACCOUNT",
    )


def _print_startup_summary():
    """打印服务启动摘要。"""
    _print_init_section("服务启动完成")

    logger.info(f"  {'服务地址':12} | http://{config.API_HOST}:{config.API_PORT}")
    logger.info(f"  {'WebSocket':12} | ws://{config.API_HOST}:{config.API_PORT}/ws")
    logger.info("")

    logger.info("  数据源状态:")
    logger.info(f"    ├── xtquant:    xtdata={'ON' if XTDATA_AVAILABLE else 'OFF'}, xttrader={'ON' if XTTRADER_AVAILABLE else 'OFF'}")
    logger.info(f"    ├── gm:         {'ON' if gm_provider and gm_provider.is_available else 'OFF'}")
    logger.info(f"    └── tdxquant:   {'ON' if tdx_provider and tdx_provider.is_available else 'OFF'}")

    gm_mode = config.GM.mode if hasattr(config, 'GM') and hasattr(config.GM, 'mode') else "N/A"
    if gm_provider and gm_provider.is_available:
        logger.info(f"    运行模式: {gm_mode}")

    logger.info("")
    logger.info("  API 端点:")
    logger.info(f"    ├── GET  /                      - 服务信息")
    logger.info(f"    ├── GET  /health                - 健康检查")
    logger.info(f"    ├── GET  /api/v1/stats          - 服务统计")
    logger.info(f"    ├── WS   /ws                    - WebSocket")
    logger.info(f"    ├── GET  /api/v1/gm/            - GM API")
    logger.info(f"    ├── GET  /api/v1/xtquant/       - XtQuant API")
    logger.info(f"    └── GET  /api/v1/tdxquant/      - TdxQuant API (HTTP only)")
    logger.info("")
    logger.info("=" * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理器。"""
    global gm_provider

    logger.info("正在启动量化数据网关服务...")

    ws_callback_handler.set_loop(asyncio.get_running_loop())

    initialize_modules()

    _init_xtquant()

    _init_gm()

    _init_tdx()

    gm_provider = get_gm_provider()
    set_gm_provider(gm_provider)

    _print_startup_summary()

    yield

    logger.info("正在关闭服务...")
    _cleanup_xttrader()
    if tdx_provider:
        tdx_provider.cleanup()
    if gm_provider:
        gm_provider.cleanup()
    shutdown_executors(wait=False)


app = FastAPI(
    title="量化数据网关服务",
    version="2.0.0",
    description="量化数据网关服务 - 支持 xtquant 和 GM (掘金量化)",
    lifespan=lifespan
)

app.include_router(gm_router)
app.include_router(xtquant_router)
app.include_router(tdx_router)


def _init_xttrader():
    """初始化 XtTrader 实例。"""
    if not XTTRADER_AVAILABLE:
        logger.warning("XtTrader 模块不可用，跳过初始化")
        return False

    xttrader_instance = get_xttrader_instance()
    if xttrader_instance is not None:
        logger.info("XtTrader 已初始化")
        return True

    try:
        _print_init_section("XtTrader 交易模块初始化")

        mini_qmt_path = config.MINI_QMT_PATH
        account_id = config.ACCOUNT_ID

        logger.info(f"  MiniQMT 路径: {mini_qmt_path}")
        logger.info(f"  账户 ID: {account_id}")

        import os
        if not os.path.exists(mini_qmt_path):
            logger.error(f"MiniQMT 路径不存在: {mini_qmt_path}")
            return False

        logger.info("  正在创建交易实例...")
        result = create_xttrader_instance(account_id, mini_qmt_path)
        
        if result.get('success'):
            logger.info("  XtTrader 实例创建成功")
            
            xttrader_instance = get_xttrader_instance()
            if xttrader_instance:
                logger.info("  正在启动交易服务...")
                start_result = execute_xttrader_method("start", [], {})
                if not start_result.get("success"):
                    logger.warning(f"XtTrader start 失败: {start_result.get('error')}")
                    return False
                
                logger.info("  正在连接交易服务器...")
                connect_result = execute_xttrader_method("connect", [], {})
                state = get_xttrader_state()
                
                if connect_result.get("success"):
                    logger.info(
                        "  XtTrader 连接成功 (session_id=%s, state=%s)",
                        result.get("session_id"), state,
                    )
                    return True
                else:
                    logger.warning(
                        f"XtTrader 连接失败，返回码: {connect_result.get('data')}"
                    )
                    return False
        else:
            logger.error(f"XtTrader 实例创建失败: {result.get('error')}")
            return False

    except Exception as e:
        logger.error(f"XtTrader 初始化失败: {e}")
        return False


def _cleanup_xttrader():
    """清理 XtTrader 实例。"""
    xttrader_instance = get_xttrader_instance()
    if xttrader_instance:
        try:
            logger.info("正在停止 XtTrader 服务...")
            xttrader_instance.stop()
            logger.info("XtTrader 已清理")
        except Exception as e:
            logger.error(f"XtTrader 清理失败: {e}")


@app.get("/")
async def root():
    """根路径端点。"""
    return {
        "service": "quant-data-gateway",
        "version": "2.0.0",
        "status": "running",
        "providers": {
            "xtquant": {
                "xtdata_available": XTDATA_AVAILABLE,
                "xttrader_available": XTTRADER_AVAILABLE
            },
            "gm": {
                "available": gm_provider.is_available if gm_provider else False,
                "token_set": gm_provider._token_set if gm_provider and gm_provider.is_available else False
            },
            "tdxquant": {
                "enabled": tdx_provider.is_enabled if tdx_provider else False,
                "available": tdx_provider.is_available if tdx_provider else False,
                "initialized": tdx_provider.is_initialized if tdx_provider else False,
                "account_configured": tdx_provider.account_configured if tdx_provider else False
            }
        },
        "websocket_support": True,
        "websocket_rpc_modules": ["xtdata", "xttrader", "gmdata", "gmtrade"],
        "websocket_market_data": bool(
            getattr(config, "WS_MARKET_DATA_ENABLED", False)
        ),
        "websocket_trade_events": False,
        "architecture": "RPC + WebSocket",
        "boundaries": {
            "tdx_websocket_rpc": False,
            "tdx_transport": "http_only",
            "trade_event_push": False,
            "multi_account": False,
        },
    }


@app.get("/health")
async def health_check():
    """健康检查端点。"""
    gm_available = gm_provider.is_available if gm_provider else False
    tdx_available = tdx_provider.is_available if tdx_provider else False
    provider_flags = {
        "xtdata": XTDATA_AVAILABLE,
        "xttrader": XTTRADER_AVAILABLE,
        "gm": gm_available,
        "tdxquant": tdx_available,
    }
    available_count = sum(1 for value in provider_flags.values() if value)

    return {
        "status": "healthy" if available_count else "degraded",
        "providers": provider_flags,
        "available_providers": available_count,
        "xtdata_available": XTDATA_AVAILABLE,
        "xttrader_available": XTTRADER_AVAILABLE,
        "gm_available": gm_available,
        "tdx_available": tdx_available,
        "tdx_initialized": tdx_provider.is_initialized if tdx_provider else False,
        "xttrader_state": get_xttrader_state(),
        "ws_market_data": bool(getattr(config, "WS_MARKET_DATA_ENABLED", False)),
        "connections": ws_manager.get_stats()
    }


@app.get("/api/v1/stats")
async def get_stats(api_key: str = Depends(get_api_key)):
    """获取服务统计信息与各 Provider 的 supported RPC 清单。"""
    from api.gm import _gm_capability_snapshot
    from api.tdxquant import _tdx_capability_snapshot
    from api.xtquant import _xtquant_capability_snapshot

    snapshots = {
        "xtquant": _xtquant_capability_snapshot(),
        "gm": _gm_capability_snapshot(),
        "tdxquant": _tdx_capability_snapshot(),
    }

    return {
        "success": True,
        "connections": ws_manager.get_stats(),
        "capabilities": {
            name: snapshot["rpc"]["supported"]
            for name, snapshot in snapshots.items()
        },
        "compat": {
            name: snapshot["rpc"]["compat"]
            for name, snapshot in snapshots.items()
        },
        "counts": {
            name: snapshot["rpc"]["counts"]
            for name, snapshot in snapshots.items()
        },
        "policy": "只返回 supported；完整矩阵见各 Provider 的 /rpc/capabilities",
    }


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    client_id: str,
    api_key: str = "",
    auto_reconnect: bool = False
):
    """
    WebSocket 端点，用于实时数据流传输。
    
    参数：
        websocket: WebSocket 连接对象
        client_id: 客户端唯一标识符
        api_key: API 认证密钥
        auto_reconnect: 是否启用自动重连
    """
    connected = await ws_manager.connect(
        websocket, client_id, api_key, config.API_KEY, auto_reconnect
    )
    if not connected:
        return

    try:
        asyncio.create_task(ws_manager.start_message_dispatcher(client_id))

        while True:
            data = await websocket.receive_text()
            ws_manager.touch(client_id)
            message = json.loads(data)
            await _handle_ws_message(client_id, message)

    except WebSocketDisconnect:
        logger.info(f"客户端 {client_id} 已断开连接")
        ws_manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket 错误: {e}")
        ws_manager.disconnect(client_id)


async def _handle_ws_message(client_id: str, message: dict):
    """处理 WebSocket 消息。"""
    msg_type = message.get("type")

    if msg_type == "subscribe_quote":
        await _handle_subscribe_quote(client_id, message)
    elif msg_type == "subscribe_whole_quote":
        await _handle_subscribe_whole_quote(client_id, message)
    elif msg_type == "unsubscribe_quote":
        await _handle_unsubscribe_quote(client_id, message)
    elif msg_type in ("subscribe_trade_event", "subscribe_trade"):
        await _handle_subscribe_trade_event(client_id, message)
    elif msg_type == "rpc_call":
        await _handle_rpc_call(client_id, message)
    elif msg_type == "ping":
        ws_manager.touch(client_id)
        await ws_manager.send_to_client(client_id, {
            "type": "pong",
            "timestamp": datetime.now().isoformat()
        })
    elif msg_type == "pong":
        ws_manager.touch(client_id)
    elif msg_type == "reconnect":
        await _handle_reconnect(client_id, message)
    else:
        logger.warning(f"未知消息类型: {msg_type}")
        await ws_manager.send_to_client(client_id, {
            "type": "error",
            "message": f"未知消息类型: {msg_type}"
        })


async def _handle_subscribe_quote(client_id: str, message: dict):
    """处理行情订阅请求。

    边界：行情推送当前明确不支持（xtdata 全推需要回调 + 事件循环桥接，未做
    实盘验证），默认直接返回 ``NOT_SUPPORTED``，避免“订阅成功但永远没数据”。
    """
    stock_code = message.get("stock_code")

    if not getattr(config, "WS_MARKET_DATA_ENABLED", False):
        await ws_manager.send_to_client(client_id, {
            "type": "error",
            "error_code": "NOT_SUPPORTED",
            "feature": "market_data_push",
            "message": (
                "行情 WebSocket 推送未启用；请用 HTTP /rpc/execute 轮询 "
                "xtdata.get_full_tick / get_market_data"
            ),
        })
        return

    period = message.get("period", "tick")

    if not stock_code:
        await ws_manager.send_to_client(client_id, {
            "type": "error",
            "message": "缺少 stock_code 参数"
        })
        return

    if not XTDATA_AVAILABLE:
        await ws_manager.send_to_client(client_id, {
            "type": "error",
            "message": "xtdata 模块不可用"
        })
        return

    callback = ws_callback_handler.create_quote_callback(client_id, stock_code, period)

    try:
        from xtquant import xtdata
        seq = xtdata.subscribe_quote(
            stock_code=stock_code,
            period=period,
            callback=callback
        )

        if seq > 0:
            ws_manager.add_subscription(client_id, "quote", {
                "id": seq,
                "stock_code": stock_code,
                "period": period
            })

            await ws_manager.send_to_client(client_id, {
                "type": "subscribed",
                "subscription_type": "quote",
                "seq": seq,
                "stock_code": stock_code,
                "period": period
            })

            logger.info(f"客户端 {client_id} 订阅了 {stock_code} (seq={seq})")
        else:
            await ws_manager.send_to_client(client_id, {
                "type": "error",
                "message": f"订阅失败: {stock_code}"
            })
    except Exception as e:
        logger.error(f"订阅失败: {e}")
        await ws_manager.send_to_client(client_id, {
            "type": "error",
            "message": str(e)
        })


async def _handle_subscribe_whole_quote(client_id: str, message: dict):
    """处理全量行情订阅请求。

    边界：与单标的订阅相同，默认关闭；开启后仍需 SDK 提供带 callback 的
    ``subscribe_whole_quote``，否则数据不会到达客户端。
    """
    code_list = message.get("code_list")

    if not getattr(config, "WS_MARKET_DATA_ENABLED", False):
        await ws_manager.send_to_client(client_id, {
            "type": "error",
            "error_code": "NOT_SUPPORTED",
            "feature": "market_data_push",
            "message": (
                "全量行情 WebSocket 推送未启用；当前 xtdata 全推订阅缺少回调桥接，"
                "请改用 HTTP 轮询"
            ),
        })
        return

    if not code_list:
        await ws_manager.send_to_client(client_id, {
            "type": "error",
            "message": "缺少 code_list 参数"
        })
        return

    if not XTDATA_AVAILABLE:
        await ws_manager.send_to_client(client_id, {
            "type": "error",
            "message": "xtdata 模块不可用"
        })
        return

    try:
        import inspect
        from xtquant import xtdata

        params = inspect.signature(xtdata.subscribe_whole_quote).parameters
        if "callback" not in params:
            await ws_manager.send_to_client(client_id, {
                "type": "error",
                "error_code": "NOT_SUPPORTED",
                "feature": "market_data_push",
                "message": (
                    "当前 SDK 的 subscribe_whole_quote 不接受 callback，"
                    "全量行情无法推送；请改用 HTTP 轮询"
                ),
            })
            return

        callback = ws_callback_handler.create_quote_callback(
            client_id, "*", "tick"
        )
        seq = xtdata.subscribe_whole_quote(code_list=code_list, callback=callback)

        if seq > 0:
            ws_manager.add_subscription(client_id, "whole_quote", {
                "id": seq,
                "code_list": code_list
            })

            await ws_manager.send_to_client(client_id, {
                "type": "whole_quote",
                "seq": seq,
                "code_list": code_list
            })

            logger.info(f"客户端 {client_id} 订阅了全量行情 (seq={seq})")
        else:
            await ws_manager.send_to_client(client_id, {
                "type": "error",
                "message": "全量行情订阅失败"
            })
    except Exception as e:
        logger.error(f"全量行情订阅失败: {e}")
        await ws_manager.send_to_client(client_id, {
            "type": "error",
            "message": str(e)
        })


async def _handle_unsubscribe_quote(client_id: str, message: dict):
    """处理取消行情订阅请求。"""
    seq = message.get("seq")

    if seq is None:
        await ws_manager.send_to_client(client_id, {
            "type": "error",
            "message": "缺少 seq 参数"
        })
        return

    try:
        from xtquant import xtdata
        xtdata.unsubscribe_quote(seq)
        ws_manager.remove_subscription(client_id, "quote", seq)

        await ws_manager.send_to_client(client_id, {
            "type": "unsubscribed",
            "subscription_type": "quote",
            "seq": seq
        })

        logger.info(f"客户端 {client_id} 取消订阅 (seq={seq})")
    except Exception as e:
        logger.error(f"取消订阅失败: {e}")
        await ws_manager.send_to_client(client_id, {
            "type": "error",
            "message": str(e)
        })


async def _handle_subscribe_trade_event(client_id: str, message: dict):
    """处理交易事件订阅请求。

    边界：``trade_event`` 只是预留消息类型；xtquant 未实现交易回调，
    GM 未接 ``gmtrade.start()``，TDX 未接回调桥接，因此统一返回不支持，
    并明确指向轮询端点。
    """
    provider = message.get("provider", "xtquant")
    await ws_manager.send_to_client(client_id, {
        "type": "error",
        "error_code": "NOT_SUPPORTED",
        "feature": "trade_event_push",
        "message": (
            "交易事件推送未实现；请轮询 "
            f"/api/v1/{provider}/trade/orders 获取委托状态"
        ),
    })


async def _handle_rpc_call(client_id: str, message: dict):
    """处理 WebSocket RPC 调用请求。"""
    module = message.get("module")
    function = message.get("function")
    args = message.get("args", [])
    kwargs = message.get("kwargs", {})
    timeout = message.get("timeout", 30)
    request_id = message.get("request_id")

    try:
        result = await execute_rpc_call(module, function, args, kwargs, timeout)

        response = {
            "type": "rpc_response",
            "request_id": request_id,
            "success": result["success"],
            "data": result.get("data"),
            "error": result.get("error"),
            "error_code": result.get("error_code"),
            "support_status": result.get("support_status"),
            "execution_time_ms": result.get("execution_time_ms")
        }

        await ws_manager.send_to_client(client_id, response)

    except Exception as e:
        logger.error(f"RPC 调用失败: {e}")
        await ws_manager.send_to_client(client_id, {
            "type": "rpc_response",
            "request_id": request_id,
            "success": False,
            "error": str(e)
        })


async def _handle_reconnect(client_id: str, message: dict):
    """处理重连请求。"""
    token = message.get("token")
    reconnect_tokens = getattr(ws_manager, '_reconnect_tokens', {})

    if token and reconnect_tokens.get(client_id) == token:
        await ws_manager.send_to_client(client_id, {
            "type": "reconnect_ack",
            "message": "重连令牌有效",
            "timestamp": datetime.now().isoformat()
        })
    else:
        await ws_manager.send_to_client(client_id, {
            "type": "error",
            "message": "无效的重连令牌"
        })


if __name__ == "__main__":
    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT)
