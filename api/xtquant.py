"""
XtQuant (迅投QMT) API 路由模块。

本模块提供 XtQuant 量化平台的 RESTful API 接口。

路由前缀：
    /api/v1/xtquant

端点说明：
    GET  /health: 健康检查
    POST /rpc/execute: 执行 RPC 调用
    GET  /rpc/whitelist: 获取函数白名单
    GET  /rpc/methods: 获取可用方法列表
    POST /symbol/convert: 股票代码格式转换
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

from models.common import RpcExecuteRequest, SymbolConvertRequest
from providers.base import serialize_data
from api.deps import get_api_key
from core.executor import run_module_call
from core.rpc import InvalidRpcArguments, validate_kwargs
from core.xt_trade import XtConfigError, XtTradeError, XtTradeService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/xtquant", tags=["XtQuant"])

_xtquant_provider_instance = None
_xt_trade_service = None


def get_xtquant_provider():
    """
    获取 XtQuant 提供者实例。
    
    使用单例模式，确保全局只有一个提供者实例。
    
    返回：
        XtQuantProvider 实例
    """
    global _xtquant_provider_instance
    if _xtquant_provider_instance is None:
        from providers.xtquant_provider import XtQuantProvider
        from config import config
        _xtquant_provider_instance = XtQuantProvider(config)
        _xtquant_provider_instance.initialize()
    return _xtquant_provider_instance


def set_xtquant_provider(provider):
    """
    设置 XtQuant 提供者实例。
    
    参数：
        provider: XtQuantProvider 实例
    """
    global _xtquant_provider_instance, _xt_trade_service
    _xtquant_provider_instance = provider
    _xt_trade_service = None


def get_xt_trade_service() -> XtTradeService:
    global _xt_trade_service
    if _xt_trade_service is None:
        from config import config
        _xt_trade_service = XtTradeService(get_xtquant_provider(), config)
    return _xt_trade_service


class XtOrderRequest(BaseModel):
    stock_code: str = Field(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    order_type: int = Field(0, ge=0, le=1, description="0 买入 / 1 卖出")
    order_volume: int = Field(..., gt=0)
    price_type: int = Field(0, ge=0, le=1, description="0 限价 / 1 最新价")
    price: float = Field(0.0, ge=0)
    client_order_id: Optional[str] = Field(
        None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )


class XtCancelRequest(BaseModel):
    order_id: int = Field(..., gt=0)


def _trade_error(message: str, code: str) -> Dict[str, Any]:
    return {"success": False, "error": message, "error_code": code}


class XtQuantRpcExecuteRequest(BaseModel):
    """
    XtQuant RPC 执行请求模型。
    
    属性：
        module: 模块名称 (xtdata, xttrader)
        function: 函数名称
        kwargs: 函数参数字典
    """
    module: str
    function: str
    kwargs: Dict[str, Any] = {}


async def _execute_xtquant_rpc_call(
    module: str,
    function: str,
    kwargs: dict,
    timeout: int = 30
) -> dict:
    """
    执行 XtQuant RPC 调用。
    
    参数：
        module: 模块名称
        function: 函数名称
        kwargs: 函数参数
        timeout: 超时时间（秒）
    
    返回：
        包含执行结果的字典
    """
    start_time = datetime.now()

    provider = get_xtquant_provider()

    if not provider.is_available:
        return {
            "success": False,
            "error": "XtQuant 服务不可用",
            "module": module,
            "function": function
        }

    if not provider.is_function_whitelisted(module, function):
        return {
            "success": False,
            "error": f"函数 {module}.{function} 不在白名单中",
            "module": module,
            "function": function
        }

    if module == "xttrader":
        from core.rpc import execute_xttrader_method
        result = await run_module_call(
            "xttrader",
            execute_xttrader_method,
            (function, [], kwargs),
            timeout=timeout,
            lane="trade",
        )
        elapsed = (datetime.now() - start_time).total_seconds()
        result["module"] = module
        result["function"] = function
        result["elapsed"] = elapsed
        if result.get("success"):
            logger.info(f"XtQuant RPC 成功: {module}.{function}, 耗时: {elapsed:.2f}s")
        return result

    mod_ref = provider.get_module_reference(module)
    if mod_ref is None:
        return {
            "success": False,
            "error": f"不支持的模块: {module}。支持的模块: xtdata, xttrader",
            "module": module,
            "function": function
        }

    func = getattr(mod_ref, function, None)
    if func is None:
        return {
            "success": False,
            "error": f"函数 {module}.{function} 未找到",
            "module": module,
            "function": function
        }

    try:
        validate_kwargs(func, kwargs)
        result = await run_module_call(module, func, (), kwargs, timeout=timeout)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"XtQuant RPC 成功: {module}.{function}, 耗时: {elapsed:.2f}s")

        return {
            "success": True,
            "data": serialize_data(result),
            "module": module,
            "function": function,
            "elapsed": elapsed
        }

    except InvalidRpcArguments as e:
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.warning(f"XtQuant RPC 参数非法: {module}.{function}, {e}")
        return {
            "success": False,
            "error": str(e),
            "error_code": e.error_code,
            "unknown_params": e.unknown,
            "missing_params": e.missing,
            "module": module,
            "function": function,
            "elapsed": elapsed
        }
    except TimeoutError:
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.error(f"XtQuant RPC 超时: {module}.{function}")
        return {
            "success": False,
            "error": f"执行超时 ({timeout}s)",
            "module": module,
            "function": function,
            "elapsed": elapsed
        }
    except Exception as e:
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.error(f"XtQuant RPC 失败: {module}.{function}, 错误: {e}")
        return {
            "success": False,
            "error": str(e),
            "module": module,
            "function": function,
            "elapsed": elapsed
        }


@router.get("/health")
async def xtquant_health(api_key: str = Depends(get_api_key)):
    """
    检查 XtQuant 服务状态。
    
    返回：
        服务可用性状态和版本信息
    """
    provider = get_xtquant_provider()

    return {
        "status": "healthy" if provider.is_available else "degraded",
        "available": provider.is_available,
        "xtdata_available": provider.is_xtdata_available,
        "xttrader_available": provider.is_xttrader_available,
        "account_configured": bool(getattr(provider._config, "ACCOUNT_ID", "")),
        "version": provider.get_version()
    }


@router.post("/rpc/execute")
async def execute_xtquant_rpc(
    request: XtQuantRpcExecuteRequest,
    api_key: str = Depends(get_api_key),
    timeout: int = 30
):
    """
    执行 XtQuant RPC 调用。
    
    参数：
        request: RPC 执行请求
        timeout: 超时时间（秒）
    
    返回：
        执行结果
    """
    result = await _execute_xtquant_rpc_call(
        module=request.module,
        function=request.function,
        kwargs=request.kwargs,
        timeout=timeout
    )
    return result


@router.get("/rpc/whitelist")
async def get_xtquant_whitelist(api_key: str = Depends(get_api_key)):
    """
    获取 XtQuant RPC 函数白名单。
    
    返回：
        函数白名单字典
    """
    provider = get_xtquant_provider()
    return provider.get_rpc_whitelist()


@router.get("/rpc/methods")
async def list_xtquant_methods(api_key: str = Depends(get_api_key)):
    """
    列出所有可用的 XtQuant 方法。
    
    返回：
        可用方法列表
    """
    provider = get_xtquant_provider()
    whitelist = provider.get_rpc_whitelist()

    methods = []
    for module, functions in whitelist.items():
        for func in functions:
            methods.append({
                "module": module,
                "function": func
            })

    return {
        "total": len(methods),
        "methods": methods
    }


@router.post("/symbol/convert")
async def convert_symbols(
    request: SymbolConvertRequest,
    api_key: str = Depends(get_api_key)
):
    """
    转换股票代码格式。
    
    参数：
        request: 股票代码转换请求
    
    返回：
        转换结果
    """
    from providers.base import SymbolConverter

    converted = SymbolConverter.convert_symbols(request.symbols, request.to_format)

    return {
        "success": True,
        "original": request.symbols,
        "converted": converted,
        "format": request.to_format
    }


@router.post("/trade/order")
async def xt_place_order(
    request: XtOrderRequest,
    api_key: str = Depends(get_api_key),
):
    if request.price_type == 0 and request.price <= 0:
        return _trade_error("限价单 price 必须大于 0", "INVALID_ARGUMENT")

    service = get_xt_trade_service()
    try:
        result = await service.place_order(
            stock_code=request.stock_code,
            order_type=request.order_type,
            order_volume=request.order_volume,
            price_type=request.price_type,
            price=request.price,
            client_order_id=request.client_order_id,
        )
        return {"success": result.get("success", False), "data": result}
    except XtConfigError as exc:
        return _trade_error(str(exc), "QMT_CONFIG")
    except TimeoutError as exc:
        return _trade_error(f"下单超时: {exc}", "TIMEOUT")
    except XtTradeError as exc:
        return _trade_error(str(exc), "QMT_TRADE")


@router.post("/trade/cancel")
async def xt_cancel_order(
    request: XtCancelRequest,
    api_key: str = Depends(get_api_key),
):
    service = get_xt_trade_service()
    try:
        result = await service.cancel_order(request.order_id)
        return {"success": result.get("success", False), "data": result}
    except XtConfigError as exc:
        return _trade_error(str(exc), "QMT_CONFIG")
    except TimeoutError as exc:
        return _trade_error(f"撤单超时: {exc}", "TIMEOUT")
    except XtTradeError as exc:
        return _trade_error(str(exc), "QMT_TRADE")


@router.get("/trade/orders")
async def xt_query_orders(api_key: str = Depends(get_api_key)):
    service = get_xt_trade_service()
    try:
        return {"success": True, "data": await service.query_orders()}
    except XtTradeError as exc:
        return _trade_error(str(exc), "QMT_TRADE")


@router.get("/trade/asset")
async def xt_query_asset(api_key: str = Depends(get_api_key)):
    service = get_xt_trade_service()
    try:
        return {"success": True, "data": await service.query_asset()}
    except XtTradeError as exc:
        return _trade_error(str(exc), "QMT_TRADE")


@router.get("/trade/positions")
async def xt_query_positions(api_key: str = Depends(get_api_key)):
    service = get_xt_trade_service()
    try:
        return {"success": True, "data": await service.query_positions()}
    except XtTradeError as exc:
        return _trade_error(str(exc), "QMT_TRADE")
