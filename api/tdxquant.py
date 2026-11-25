"""
TdxQuant（通达信量化）API 路由。

- 数据：POST /rpc/execute（仅 tdxdata，严格参数校验）
- 能力：GET /rpc/whitelist、/rpc/methods、/rpc/capabilities（tdxtrade 不开放通用 RPC）
- 交易：/trade/order、/trade/cancel、/trade/orders、/trade/asset、/trade/positions
- 交易不走通用反射 RPC，撤单由服务层做状态对账。
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps import get_api_key
from core.executor import API_MIN_TIMEOUT, normalize_timeout, run_module_call
from core.capabilities import build_capability_snapshot, evaluate_rpc
from core.rpc import InvalidRpcArguments, validate_kwargs
from core.tdx_trade import TdxNotLoggedInError, TdxTradeService
from models.common import RpcExecuteRequest
from providers.base import serialize_data
from providers.tdx_provider import (
    TdxConfigError,
    TdxError,
    TdxUnavailableError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tdxquant", tags=["TdxQuant"])

_tdx_provider_instance = None
_tdx_trade_service = None


def get_tdx_provider():
    global _tdx_provider_instance
    if _tdx_provider_instance is None:
        from config import config
        from providers.tdx_provider import TdxProvider

        _tdx_provider_instance = TdxProvider(config)
        _tdx_provider_instance.initialize()
    return _tdx_provider_instance


def set_tdx_provider(provider):
    global _tdx_provider_instance, _tdx_trade_service
    _tdx_provider_instance = provider
    _tdx_trade_service = None


def get_tdx_trade_service() -> TdxTradeService:
    global _tdx_trade_service
    if _tdx_trade_service is None:
        from config import config

        _tdx_trade_service = TdxTradeService(
            get_tdx_provider(), config,
            state_path=getattr(config.TDX, "idempotency_db", None),
        )
    return _tdx_trade_service


def _tdx_capability_probe(provider):
    try:
        ref = provider.get_module_reference("tdxdata")
    except Exception:
        ref = None
    if ref is None:
        return None
    return lambda function: callable(getattr(ref, function, None))


def _tdx_capability_snapshot(provider=None) -> Dict[str, Any]:
    provider = provider or get_tdx_provider()
    refs: Dict[str, Any] = {}
    try:
        refs["tdxdata"] = provider.get_module_reference("tdxdata")
    except Exception:
        refs["tdxdata"] = None
    return build_capability_snapshot(
        "tdxquant",
        module_refs=refs,
        runtime_available=provider.is_available,
    )


class TdxOrderRequest(BaseModel):
    stock_code: str = Field(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    order_type: int = Field(0, ge=0, le=1, description="0 买入 / 1 卖出")
    order_volume: int = Field(..., gt=0)
    price_type: int = Field(0, ge=0, le=3, description="0 限价 / 1 市价 / 2 涨停 / 3 跌停")
    price: float = Field(0.0, ge=0)
    notify: int = Field(0, ge=0, le=1, description="1 表示需要客户端手动确认")
    client_order_id: Optional[str] = Field(
        None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.:-]+$",
        description="调用方幂等键；同一 key 在 10 分钟内只提交一次",
    )


class TdxCancelRequest(BaseModel):
    stock_code: str = Field(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    order_id: str = Field(..., min_length=1)


def _error(message: str, code: str, status: int = 200) -> Dict[str, Any]:
    return {"success": False, "error": message, "error_code": code}


def _tdx_sdk_error(result: Any) -> Optional[str]:
    """识别 tqcenter 以普通 dict 返回的 SDK 错误。

    TDX 部分数据函数不抛异常，而是在返回值里放 ``{"error": -5, "msg": ...}``；
    如果原样包成 ``success=true``，调用方会把错误当成空数据。这里统一识别并
    交给路由转成 ``success=false``。
    """
    if not isinstance(result, dict):
        return None
    error = result.get("error")
    if error in (None, 0, "0", "", False):
        return None
    message = (
        result.get("msg")
        or result.get("Msg")
        or result.get("message")
        or result.get("Message")
        or ""
    )
    return f"TDX SDK 错误 {error}: {message}".rstrip()


@router.get("/health")
async def tdx_health(api_key: str = Depends(get_api_key)):
    provider = get_tdx_provider()
    data = provider.health()

    if not provider.is_available:
        data.update({"logged_in": False, "reason": "tqcenter 不可用"})
        return data

    try:
        probe = await run_module_call(
            "tdxquant",
            provider.probe_account,
            (),
            {},
            timeout=5,
            lane="data",
        )
        data.update(probe)
    except TimeoutError:
        data.update({"logged_in": None, "reason": "账户探测超时"})
    except TdxError as exc:
        data.update({"logged_in": False, "reason": str(exc)})

    # 探测过程可能触发 tq.initialize，回填最新状态
    data["available"] = provider.is_available
    data["initialized"] = provider.is_initialized
    data["status"] = "healthy" if data.get("logged_in") else "degraded"
    return data


@router.post("/rpc/execute")
async def execute_tdx_rpc(
    request: RpcExecuteRequest,
    api_key: str = Depends(get_api_key),
):
    start_time = datetime.now()

    if request.module != "tdxdata":
        status, reason = evaluate_rpc(
            "tdxquant", request.module, request.function
        )
        if request.module == "tdxtrade":
            error_code = "USE_TRADE_ENDPOINT"
        else:
            error_code = (
                "NOT_WHITELISTED" if status == "not_declared" else "NOT_SUPPORTED"
            )
        return {
            "success": False,
            "error": reason or "交易接口请使用 /api/v1/tdxquant/trade/*",
            "error_code": error_code,
            "support_status": status,
            "module": request.module,
            "function": request.function,
        }

    provider = get_tdx_provider()
    if not provider.is_available:
        return {
            "success": False,
            "error": "tdxquant 不可用：请确认终端已启动、tqcenter 路径与配置正确",
            "error_code": "TDX_UNAVAILABLE",
            "module": request.module,
            "function": request.function,
        }

    status, reason = evaluate_rpc(
        "tdxquant",
        request.module,
        request.function,
        probe=_tdx_capability_probe(provider),
    )
    if status != "supported":
        return {
            "success": False,
            "error": reason or f"函数 {request.module}.{request.function} 不支持",
            "error_code": (
                "NOT_WHITELISTED" if status == "not_declared" else "NOT_SUPPORTED"
            ),
            "support_status": status,
            "module": request.module,
            "function": request.function,
        }

    try:
        module_ref = provider.get_module_reference(request.module)
        func = getattr(module_ref, request.function, None)
        if func is None or not callable(func):
            return {
                "success": False,
                "error": f"函数 {request.module}.{request.function} 在当前运行时未提供",
                "error_code": "NOT_SUPPORTED",
                "support_status": "runtime_missing",
                "module": request.module,
                "function": request.function,
            }

        kwargs = dict(request.kwargs)
        validate_kwargs(func, kwargs, request.args)
        timeout = normalize_timeout(request.timeout or 30, minimum=API_MIN_TIMEOUT)
        args = tuple(request.args)

        def _invoke():
            # tq.initialize 是阻塞调用，必须留在 tdxquant 串行执行器里
            provider.ensure_initialized()
            return func(*args, **kwargs)

        result = await run_module_call(
            "tdxquant", _invoke, (), {}, timeout=timeout
        )
        elapsed = (datetime.now() - start_time).total_seconds()
        sdk_error = _tdx_sdk_error(result)
        if sdk_error:
            return {
                "success": False,
                "error": sdk_error,
                "error_code": "TDX_ERROR",
                "module": request.module,
                "function": request.function,
                "elapsed": elapsed,
            }
        return {
            "success": True,
            "data": serialize_data(result),
            "module": request.module,
            "function": request.function,
            "elapsed": elapsed,
        }
    except InvalidRpcArguments as exc:
        return {
            "success": False,
            "error": str(exc),
            "error_code": exc.error_code,
            "unknown_params": exc.unknown,
            "missing_params": exc.missing,
        }
    except TimeoutError as exc:
        return {
            "success": False,
            "error": f"执行超时: {exc}",
            "error_code": "TIMEOUT",
        }
    except TdxUnavailableError as exc:
        return {"success": False, "error": str(exc), "error_code": "TDX_UNAVAILABLE"}
    except TdxError as exc:
        return {"success": False, "error": str(exc), "error_code": "TDX_ERROR"}


@router.get("/rpc/whitelist")
async def tdx_whitelist(api_key: str = Depends(get_api_key)):
    """
    获取 TDX 通用 RPC 已支持函数清单。

    ``tdxtrade`` 不开放通用 RPC，因此这里只返回 ``tdxdata``；交易能力见
    /rpc/capabilities 的 typed_trade 区。
    """
    return _tdx_capability_snapshot()["rpc"]["supported"]


@router.get("/rpc/capabilities")
async def tdx_capabilities(api_key: str = Depends(get_api_key)):
    """
    获取 TDX 完整能力矩阵（supported / unsupported / typed_trade）。
    """
    return _tdx_capability_snapshot()


@router.get("/rpc/methods")
async def tdx_methods(api_key: str = Depends(get_api_key)):
    """
    列出所有可通过通用 RPC 调用的 TDX 方法。

    只包含 ``tdxdata`` 的 supported 函数；``tdxtrade`` 不会出现在这里。
    """
    supported = _tdx_capability_snapshot()["rpc"]["supported"]
    methods = [
        {"module": module, "function": function}
        for module, functions in supported.items()
        for function in functions
    ]
    return {"total": len(methods), "methods": methods}


@router.post("/trade/order")
async def place_order(
    request: TdxOrderRequest,
    api_key: str = Depends(get_api_key),
):
    if request.price_type == 0 and request.price <= 0:
        return _error("限价单 price 必须大于 0", "INVALID_ARGUMENT")

    service = get_tdx_trade_service()
    try:
        result = await service.place_order(
            stock_code=request.stock_code,
            order_type=request.order_type,
            order_volume=request.order_volume,
            price_type=request.price_type,
            price=request.price,
            notify=request.notify,
            client_order_id=request.client_order_id,
        )
        return {"success": result.get("success", False), "data": result}
    except TdxConfigError as exc:
        return _error(str(exc), "TDX_CONFIG")
    except TdxUnavailableError as exc:
        return _error(str(exc), "TDX_UNAVAILABLE")
    except TdxNotLoggedInError as exc:
        return _error(str(exc), "TDX_NOT_LOGGED_IN")
    except TimeoutError as exc:
        return _error(f"下单超时: {exc}", "TIMEOUT")
    except TdxError as exc:
        return _error(str(exc), "TDX_ERROR")


@router.post("/trade/cancel")
async def cancel_order(
    request: TdxCancelRequest,
    api_key: str = Depends(get_api_key),
):
    service = get_tdx_trade_service()
    try:
        result = await service.cancel_order(
            stock_code=request.stock_code,
            order_id=request.order_id,
        )
        return {"success": result.get("success", False), "data": result}
    except TdxConfigError as exc:
        return _error(str(exc), "TDX_CONFIG")
    except TdxUnavailableError as exc:
        return _error(str(exc), "TDX_UNAVAILABLE")
    except TdxNotLoggedInError as exc:
        return _error(str(exc), "TDX_NOT_LOGGED_IN")
    except TimeoutError as exc:
        return _error(f"撤单对账超时: {exc}", "TIMEOUT")
    except TdxError as exc:
        return _error(str(exc), "TDX_ERROR")


@router.get("/trade/orders")
async def query_orders(api_key: str = Depends(get_api_key)):
    service = get_tdx_trade_service()
    try:
        return {"success": True, "data": await service.query_orders()}
    except TdxNotLoggedInError as exc:
        return _error(str(exc), "TDX_NOT_LOGGED_IN")
    except TdxError as exc:
        return _error(str(exc), "TDX_ERROR")


@router.get("/trade/asset")
async def query_asset(api_key: str = Depends(get_api_key)):
    service = get_tdx_trade_service()
    try:
        return {"success": True, "data": await service.query_asset()}
    except TdxNotLoggedInError as exc:
        return _error(str(exc), "TDX_NOT_LOGGED_IN")
    except TdxError as exc:
        return _error(str(exc), "TDX_ERROR")


@router.get("/trade/positions")
async def query_positions(api_key: str = Depends(get_api_key)):
    service = get_tdx_trade_service()
    try:
        return {"success": True, "data": await service.query_positions()}
    except TdxNotLoggedInError as exc:
        return _error(str(exc), "TDX_NOT_LOGGED_IN")
    except TdxError as exc:
        return _error(str(exc), "TDX_ERROR")
