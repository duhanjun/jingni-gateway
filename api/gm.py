"""
GM (掘金量化) API 路由模块。

本模块提供 GM 量化平台的 RESTful API 接口。

路由前缀：
    /api/v1/gm

端点说明：
    GET  /: 服务根端点
    GET  /status: 获取服务状态
    GET  /health: 健康检查
    GET  /rpc/methods: 获取可用方法列表
    GET  /rpc/whitelist: 获取函数白名单
    POST /rpc/execute: 执行 RPC 调用
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
import inspect
import concurrent.futures

from models.common import RpcExecuteRequest, SymbolConvertRequest
from providers.base import serialize_data
from api.deps import get_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/gm", tags=["GM"])

_gm_provider_instance = None


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
    global _gm_provider_instance
    _gm_provider_instance = provider


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
        "version": "1.0.0",
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
    return {
        "status": "healthy",
        "gm_available": provider.is_available
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

        whitelist = provider.get_rpc_whitelist()
        modules_to_check = [module] if module else list(whitelist.keys())
        all_methods = []

        for mod_name in modules_to_check:
            if mod_name not in whitelist:
                continue

            mod_ref = provider.get_module_reference(mod_name)
            if mod_ref is None:
                continue

            for func_name in whitelist[mod_name]:
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
    获取 GM RPC 函数白名单。
    
    返回：
        函数白名单字典
    """
    provider = get_gm_provider()
    return {
        "success": True,
        "provider": "gm",
        "whitelist": provider.get_rpc_whitelist(),
        "message": "只有白名单中的函数可以通过 RPC 调用"
    }


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

    from config import config

    if module == "gmtrade":
        if function == "run":
            kwargs.setdefault("strategy_id", config.GM.strategy_id)

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
        if mod_ref is None:
            return {
                "success": False,
                "error": f"不支持的模块: {module}。支持的模块: gmdata, gmtrade",
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

        func = getattr(mod_ref, function, None)
        if func is None:
            return {
                "success": False,
                "error": f"函数 {module}.{function} 未找到",
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

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            try:
                result = future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                raise TimeoutError(f"函数执行超时 ({timeout}s)")

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
            "module": module,
            "function": function,
            "execution_time_ms": (datetime.now() - start_time).total_seconds() * 1000
        }
    except Exception as e:
        logger.error(f"GM RPC 失败: {module}.{function}, 错误: {e}")
        return {
            "success": False,
            "error": str(e),
            "module": module,
            "function": function,
            "execution_time_ms": (datetime.now() - start_time).total_seconds() * 1000
        }
