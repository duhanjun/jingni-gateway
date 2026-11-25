"""
GM (掘金量化) API 路由模块。

本模块提供 GM 量化平台的 RESTful API 接口。

路由前缀：
    /api/v1/gm

端点说明：
    GET  /: 服务根端点
    GET  /status: 获取服务状态
    GET  /health: 健康检查
    GET  /rpc/methods: 获取已支持方法列表
    GET  /rpc/whitelist: 获取已支持函数清单
    GET  /rpc/capabilities: 获取完整能力矩阵
    POST /rpc/execute: 执行 supported 内 RPC 调用
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime
import inspect
import logging

import pandas as pd

from models.common import RpcExecuteRequest, SymbolConvertRequest
from providers.base import serialize_data
from api.deps import get_api_key
from core.executor import API_MIN_TIMEOUT, normalize_timeout, run_module_call
from core.capabilities import build_capability_snapshot, evaluate_rpc
from core.gm_trade import GMConfigError, GMNotLoggedInError, GMTradeError, GMTradeService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/gm", tags=["GM"])

_gm_provider_instance = None
_gm_trade_service = None


def get_gm_provider():
    """
    获取 GM 提供者实例。
    
    使用单例模式，确保全局只有一个提供者实例。
    
    返回：
        GMProvider 实例
    """
    global _gm_provider_instance
    if _gm_provider_instance is None:
        from providers.gm_provider import GMProvider
        from config import config
        _gm_provider_instance = GMProvider(config)
        _gm_provider_instance.initialize()
    return _gm_provider_instance


def set_gm_provider(provider):
    """
    设置 GM 提供者实例。
    
    参数：
        provider: GMProvider 实例
    """
    global _gm_provider_instance, _gm_trade_service
    _gm_provider_instance = provider
    _gm_trade_service = None


def get_gm_trade_service() -> GMTradeService:
    global _gm_trade_service
    if _gm_trade_service is None:
        from config import config
        provider = get_gm_provider()
        _gm_trade_service = GMTradeService(
            provider.get_module_reference("gmtrade"),
            config,
        )
    return _gm_trade_service


def _gm_capability_refs(provider) -> Dict[str, Any]:
    refs: Dict[str, Any] = {}
    for module in ("gmdata", "gmtrade"):
        try:
            refs[module] = provider.get_module_reference(module)
        except Exception:
            refs[module] = None
    return refs


def _gm_capability_snapshot(provider=None) -> Dict[str, Any]:
    provider = provider or get_gm_provider()
    return build_capability_snapshot(
        "gm",
        module_refs=_gm_capability_refs(provider),
        runtime_available=provider.is_available,
    )


class GMOrderRequest(BaseModel):
    symbol: str = Field(
        ...,
        pattern=r"^(SHSE|SZSE|BJSE)\.\d{6}$",
        description="掘金代码；支持上海 SHSE、深圳 SZSE、北交所 BJSE",
    )
    volume: int = Field(..., gt=0)
    side: int = Field(0, ge=0, le=1, description="0 买入 / 1 卖出")
    order_type: int = Field(0, ge=0, le=1, description="0 限价 / 1 市价")
    price: float = Field(0.0, ge=0)
    position_effect: int = Field(1, ge=1, le=3, description="1 开仓 / 2 平仓 / 3 平今")
    client_order_id: Optional[str] = Field(
        None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )


class GMCancelRequest(BaseModel):
    order_id: Optional[str] = Field(None, min_length=1, description="券商委托号或 cl_ord_id")
    cl_ord_id: Optional[str] = Field(None, min_length=1, description="客户端委托 ID；优先使用")


def _trade_error(message: str, code: str) -> Dict[str, Any]:
    return {"success": False, "error": message, "error_code": code}


@router.get("/")
async def gm_root():
    """
    GM 服务根端点。
    
    返回：
        服务基本信息
    """
    provider = get_gm_provider()
    return {
        "service": "gm-data-gateway",
        "version": "2.0.0",
        "status": "running",
        "available": provider.is_available,
        "token_set": provider._token_set if provider.is_available else False
    }


@router.get("/status")
async def get_gm_status():
    """
    获取 GM 服务状态。
    
    返回：
        服务状态信息
    """
    try:
        provider = get_gm_provider()
        return {
            "available": provider.is_available,
            "token_set": provider._token_set if provider.is_available else False,
            "version": provider.get_version() if provider.is_available else "未知"
        }
    except Exception as e:
        return {"available": False, "error": str(e)}


@router.get("/health")
async def health_check():
    """
    健康检查端点。
    
    返回：
        健康状态
    """
    provider = get_gm_provider()
    ready = provider.is_available and provider.token_configured
    return {
        "status": "healthy" if ready else "degraded",
        "gm_available": provider.is_available,
        "token_configured": provider.token_configured,
        "account_configured": provider.account_configured,
        "gmtrade_available": provider.gmtrade_available,
    }


@router.get("/rpc/methods")
async def get_rpc_methods(
    module: Optional[str] = None,
    api_key: str = Depends(get_api_key)
):
    """
    获取可用的 GM RPC 方法。
    
    参数：
        module: 可选的模块名称过滤
    
    返回：
        可用方法列表及其签名和文档
    """
    try:
        provider = get_gm_provider()

        if not provider.is_available:
            raise HTTPException(status_code=503, detail="GM 服务不可用")

        snapshot = _gm_capability_snapshot(provider)
        supported = snapshot["rpc"]["supported"]
        if module and module not in supported:
            raise HTTPException(
                status_code=404,
                detail=f"模块 {module} 不在 supported 清单；请查看 /api/v1/gm/rpc/capabilities",
            )
        modules_to_check = [module] if module else list(supported.keys())
        all_methods = []

        for mod_name in modules_to_check:
            if mod_name not in supported:
                continue

            mod_ref = provider.get_module_reference(mod_name)
            if mod_ref is None:
                continue

            for func_name in supported[mod_name]:
                try:
                    func = getattr(mod_ref, func_name, None)
                    if func is None or not callable(func):
                        continue

                    sig = inspect.signature(func)
                    parameters = []
                    for param_name, param in sig.parameters.items():
                        param_info = {
                            "name": param_name,
                            "default": str(param.default) if param.default != inspect.Parameter.empty else None,
                            "annotation": str(param.annotation) if param.annotation != inspect.Parameter.empty else None
                        }
                        parameters.append(param_info)

                    docstring = inspect.getdoc(func)
                    signature_str = f"{func_name}{str(sig)}"

                    all_methods.append({
                        "name": func_name,
                        "module": mod_name,
                        "signature": signature_str,
                        "docstring": docstring[:500] if docstring else None,
                        "parameters": parameters
                    })
                except Exception as e:
                    logger.warning(f"获取方法 {mod_name}.{func_name} 失败: {e}")
                    continue

        return {
            "success": True,
            "provider": "gm",
            "modules": modules_to_check,
            "methods": all_methods,
            "count": len(all_methods)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 GM RPC 方法失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rpc/whitelist")
async def get_rpc_whitelist(api_key: str = Depends(get_api_key)):
    """
    获取 GM RPC 已支持函数清单。

    只返回当前运行时真正可用的 supported 函数；明确不支持的函数请查看
    /rpc/capabilities。
    """
    provider = get_gm_provider()
    snapshot = _gm_capability_snapshot(provider)
    return {
        "success": True,
        "provider": "gm",
        "whitelist": snapshot["rpc"]["supported"],
        "message": "只有 supported 中的函数可以通过 RPC 调用；unsupported 见 /rpc/capabilities"
    }


@router.get("/rpc/capabilities")
async def get_gm_capabilities(api_key: str = Depends(get_api_key)):
    """
    获取 GM 完整能力矩阵（supported / unsupported / typed_trade）。
    """
    return _gm_capability_snapshot()


@router.post("/rpc/execute")
async def execute_rpc(
    request: RpcExecuteRequest,
    api_key: str = Depends(get_api_key)
):
    """
    执行 GM RPC 调用。
    
    参数：
        request: RPC 执行请求
    
    返回：
        执行结果
    """
    result = await _execute_gm_rpc_call(
        request.module,
        request.function,
        request.args,
        request.kwargs,
        request.timeout
    )
    return result


# GM 底层 protobuf/计算函数的入参形态与 JSON 不完全一致，在网关入口做最小归一化。
_GM_L2_FUNCTIONS = {
    "get_history_bars_l2",
    "get_history_l2bars",
    "get_history_l2orders",
    "get_history_l2orders_queue",
    "get_history_l2ticks",
    "get_history_l2transactions",
    "get_history_ticks_l2",
    "get_history_transaction_l2",
}


def _normalize_gm_kwargs(module: str, function: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """把 HTTP JSON 入参归一化为 GM SDK 需要的类型。

    只处理有明确 SDK 约束的场景，不改变函数语义：
    - L2 历史函数要求 ``symbols`` 为逗号分隔字符串，JSON 调用方习惯传列表；
    - ``stk_get_symbol_sector`` 的 ``sector_type`` 在 protobuf 中是字符串；
    - ``option_calculate_hv`` 要求 ``price`` 为 pandas.Series，JSON 只能传数组；
    - 期权组合查询未显式传 ``account_id`` 时使用配置账户。
    """
    if module != "gmdata":
        return kwargs

    normalized = dict(kwargs)

    if function in _GM_L2_FUNCTIONS:
        symbols = normalized.get("symbols")
        if isinstance(symbols, list):
            normalized["symbols"] = ",".join(str(item) for item in symbols)

    if function == "stk_get_symbol_sector":
        sector_type = normalized.get("sector_type")
        if isinstance(sector_type, int):
            normalized["sector_type"] = str(sector_type)

    if function == "option_calculate_hv":
        price = normalized.get("price")
        if isinstance(price, list):
            normalized["price"] = pd.Series(price, dtype="float64")

    if function in {"option_get_comb_info", "option_get_comb_pos"}:
        if not normalized.get("account_id"):
            try:
                from config import config
                account_id = getattr(getattr(config, "GM", None), "account_id", "")
                if account_id:
                    normalized["account_id"] = account_id
            except Exception:  # pragma: no cover - 配置异常不阻断查询
                logger.warning("读取 GM 账户配置失败，期权组合查询不注入 account_id")

    return normalized


async def _execute_gm_rpc_call(
    module: str,
    function: str,
    args: list,
    kwargs: dict,
    timeout: int = 30
) -> dict:
    """
    执行 GM RPC 调用。
    
    参数：
        module: 模块名称
        function: 函数名称
        args: 位置参数
        kwargs: 关键字参数
        timeout: 超时时间（秒）
    
    返回：
        包含执行结果的字典
    """
    start_time = datetime.now()

    try:
        timeout = normalize_timeout(timeout, minimum=API_MIN_TIMEOUT)
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
            "error_code": "INVALID_ARGUMENT",
            "module": module,
            "function": function,
        }

    try:
        provider = get_gm_provider()

        if not provider.is_available:
            return {
                "success": False,
                "error": "GM 服务不可用",
                "module": module,
                "function": function
            }

        mod_ref = provider.get_module_reference(module)
        probe = None
        if mod_ref is not None:
            probe = lambda fn: callable(getattr(mod_ref, fn, None))

        status, reason = evaluate_rpc("gm", module, function, probe=probe)
        if status != "supported":
            return {
                "success": False,
                "error": reason or f"函数 {module}.{function} 不支持",
                "error_code": (
                    "NOT_WHITELISTED" if status == "not_declared" else "NOT_SUPPORTED"
                ),
                "support_status": status,
                "module": module,
                "function": function
            }

        if mod_ref is None:
            return {
                "success": False,
                "error": f"模块 {module} 当前不可用",
                "error_code": "NOT_SUPPORTED",
                "support_status": "runtime_missing",
                "module": module,
                "function": function
            }

        func = getattr(mod_ref, function, None)
        if func is None:
            return {
                "success": False,
                "error": f"函数 {module}.{function} 在当前运行时未提供",
                "error_code": "NOT_SUPPORTED",
                "support_status": "runtime_missing",
                "module": module,
                "function": function
            }

        if not callable(func):
            return {
                "success": False,
                "error": f"{module}.{function} 不可调用",
                "module": module,
                "function": function
            }

        logger.info(f"GM RPC 调用: {module}.{function}")
        logger.debug(f"  args={args}, kwargs={kwargs}")

        normalized_kwargs = _normalize_gm_kwargs(module, function, kwargs)
        logger.debug(f"  normalized_kwargs={normalized_kwargs}")

        result = await run_module_call(
            module, func, args, normalized_kwargs, timeout=timeout,
            lane="trade" if module == "gmtrade" else "data",
        )

        serialized_result = serialize_data(result)

        execution_time = (datetime.now() - start_time).total_seconds() * 1000

        logger.info(f"GM RPC 成功: {module}.{function}, 耗时: {execution_time:.2f}ms")

        return {
            "success": True,
            "provider": "gm",
            "data": serialized_result,
            "module": module,
            "function": function,
            "execution_time_ms": execution_time
        }

    except TimeoutError as e:
        logger.error(f"GM RPC 超时: {module}.{function}")
        return {
            "success": False,
            "error": str(e),
            "error_code": "TIMEOUT",
            "module": module,
            "function": function,
            "execution_time_ms": (datetime.now() - start_time).total_seconds() * 1000
        }
    except Exception as e:
        logger.error(f"GM RPC 失败: {module}.{function}, 错误: {e}")
        return {
            "success": False,
            "error": f"{type(e).__name__}: {e}",
            "error_code": "GM_SDK_ERROR",
            "exception_type": type(e).__name__,
            "module": module,
            "function": function,
            "execution_time_ms": (datetime.now() - start_time).total_seconds() * 1000
        }


@router.post("/trade/order")
async def gm_place_order(
    request: GMOrderRequest,
    api_key: str = Depends(get_api_key),
):
    if request.order_type == 0 and request.price <= 0:
        return _trade_error("限价单 price 必须大于 0", "INVALID_ARGUMENT")

    service = get_gm_trade_service()
    try:
        result = await service.place_order(
            symbol=request.symbol,
            volume=request.volume,
            side=request.side,
            order_type=request.order_type,
            price=request.price,
            position_effect=request.position_effect,
            client_order_id=request.client_order_id,
        )
        return {"success": result.get("success", False), "data": result}
    except GMConfigError as exc:
        return _trade_error(str(exc), "GM_CONFIG")
    except TimeoutError as exc:
        return _trade_error(f"下单超时: {exc}", "TIMEOUT")
    except GMTradeError as exc:
        return _trade_error(str(exc), "GM_TRADE")


@router.post("/trade/cancel")
async def gm_cancel_order(
    request: GMCancelRequest,
    api_key: str = Depends(get_api_key),
):
    if not request.cl_ord_id and not request.order_id:
        return _trade_error("撤单需要 order_id 或 cl_ord_id", "INVALID_ARGUMENT")
    service = get_gm_trade_service()
    try:
        result = await service.cancel_order(
            request.order_id or request.cl_ord_id,
            cl_ord_id=request.cl_ord_id,
        )
        return {"success": result.get("success", False), "data": result}
    except GMConfigError as exc:
        return _trade_error(str(exc), "GM_CONFIG")
    except TimeoutError as exc:
        return _trade_error(f"撤单超时: {exc}", "TIMEOUT")
    except GMTradeError as exc:
        return _trade_error(str(exc), "GM_TRADE")


@router.get("/trade/orders")
async def gm_query_orders(api_key: str = Depends(get_api_key)):
    service = get_gm_trade_service()
    try:
        return {"success": True, "data": await service.query_orders()}
    except GMTradeError as exc:
        return _trade_error(str(exc), "GM_TRADE")


@router.get("/trade/asset")
async def gm_query_asset(api_key: str = Depends(get_api_key)):
    service = get_gm_trade_service()
    try:
        return {"success": True, "data": await service.query_asset()}
    except GMNotLoggedInError as exc:
        return _trade_error(str(exc), "GM_NOT_LOGGED_IN")
    except GMTradeError as exc:
        return _trade_error(str(exc), "GM_TRADE")


@router.get("/trade/positions")
async def gm_query_positions(api_key: str = Depends(get_api_key)):
    service = get_gm_trade_service()
    try:
        return {"success": True, "data": await service.query_positions()}
    except GMTradeError as exc:
        return _trade_error(str(exc), "GM_TRADE")
