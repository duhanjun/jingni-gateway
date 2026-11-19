"""
RPC 执行模块。

本模块为 JingNiGateway 服务提供核心的 RPC（远程过程调用）执行功能。
主要功能包括：
- 模块初始化和引用管理
- 函数白名单验证
- 不同数据源的参数适配
- 支持超时的异步 RPC 执行

支持的模块：
- xtdata: XtQuant 数据模块
- xttrader: XtQuant 交易模块
- gmdata: GM (掘金量化) 数据模块
- gmtrade: GM (掘金量化) 交易模块
"""

import asyncio
import inspect
import logging
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

from providers.base import serialize_data
from .executor import run_module_call

logger = logging.getLogger(__name__)


class InvalidRpcArguments(ValueError):
    """RPC 参数校验失败。"""

    error_code = "INVALID_ARGUMENT"

    def __init__(self, message: str, unknown: Optional[List[str]] = None,
                 missing: Optional[List[str]] = None):
        super().__init__(message)
        self.unknown = unknown or []
        self.missing = missing or []


def validate_kwargs(func: Any, kwargs: Dict[str, Any]) -> None:
    """
    按函数签名校验关键字参数。

    与旧实现不同：未知参数不再被静默丢弃，而是直接报错，
    避免调用方以为参数生效、实际却用了默认值。

    参数：
        func: 可调用对象
        kwargs: 待校验的关键字参数

    异常：
        InvalidRpcArguments: 存在未知参数或缺少必填参数
    """
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        # C 扩展/内建函数可能没有签名，交给底层自行报错
        return

    params = signature.parameters
    accepts_var_kw = any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
    )
    allowed = {
        name for name, p in params.items()
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                      inspect.Parameter.KEYWORD_ONLY)
    }

    unknown = sorted(set(kwargs) - allowed)
    if unknown and not accepts_var_kw:
        raise InvalidRpcArguments(
            f"未知参数: {', '.join(unknown)}；允许的参数: {', '.join(sorted(allowed)) or '无'}",
            unknown=unknown,
        )

    missing = [
        name for name, p in params.items()
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                      inspect.Parameter.KEYWORD_ONLY)
        and p.default is inspect.Parameter.empty
        and name not in kwargs
    ]
    if missing:
        raise InvalidRpcArguments(
            f"缺少必填参数: {', '.join(missing)}",
            missing=missing,
        )

_xtdata_module = None
_xttrader_module = None
_gm_api_module = None
_xttrader_instance = None
_xttrader_account = None
_xttrader_callback = None


def initialize_modules():
    """
    初始化所有数据源的模块引用。

    本函数尝试导入并缓存所有支持的量化库模块引用。
    如果某个模块不可用，会记录警告日志但继续执行。

    注意：
        应在应用程序启动时调用此函数。
    """
    global _xtdata_module, _xttrader_module, _gm_api_module

    try:
        from xtquant import xtdata
        _xtdata_module = xtdata
        logger.info("xtdata 模块初始化成功")
    except ImportError:
        logger.warning("xtdata 模块不可用")

    try:
        from xtquant import xttrader
        _xttrader_module = xttrader
        logger.info("xttrader 模块初始化成功")
    except ImportError:
        logger.warning("xttrader 模块不可用")

    try:
        import gm.api as gm_api
        _gm_api_module = gm_api
        logger.info("gm.api 模块初始化成功")
    except ImportError:
        logger.warning("gm.api 模块不可用")


def get_module_reference(module_name: str):
    """
    根据名称获取模块引用。

    参数：
        module_name: 模块名称 (xtdata, xttrader, gmdata, gmtrade)

    返回：
        模块引用，如果不可用则返回 None

    示例：
        >>> mod = get_module_reference("xtdata")
        >>> mod.get_market_data(...)
    """
    if module_name == "xtdata":
        return _xtdata_module
    elif module_name == "xttrader":
        return _xttrader_module
    elif module_name in ("gmdata", "gmtrade"):
        return _gm_api_module
    else:
        return None


def get_xttrader_instance():
    """
    获取 XtQuantTrader 实例。

    返回：
        XtQuantTrader 实例，如果未创建则返回 None
    """
    return _xttrader_instance


def create_xttrader_instance(account: str, mini_qmt_path: str = None) -> dict:
    """
    创建 XtQuantTrader 实例。

    参数：
        account: 账户 ID（作为 session_id）
        mini_qmt_path: MiniQMT 路径（可选，默认从配置读取）

    返回：
        dict: 包含 success 和 data/error 的结果
    """
    global _xttrader_instance, _xttrader_account, _xttrader_callback

    if _xttrader_module is None:
        return {"success": False, "error": "xttrader 模块未初始化"}

    if _xttrader_instance is not None:
        logger.info(f"XtQuantTrader 实例已存在，账户: {_xttrader_account}")
        return {"success": True, "data": f"交易实例已存在，账户: {_xttrader_account}"}

    if not mini_qmt_path:
        try:
            from config import config
            mini_qmt_path = getattr(config, 'MINI_QMT_PATH', None)
        except ImportError:
            pass

    if not mini_qmt_path:
        return {"success": False, "error": "mini_qmt_path 参数是必需的，且未在配置中找到"}

    try:
        from xtquant.xttrader import XtQuantTraderCallback

        _xttrader_callback = XtQuantTraderCallback()
        _xttrader_instance = _xttrader_module.XtQuantTrader(
            mini_qmt_path, int(account)
        )
        _xttrader_instance.register_callback(_xttrader_callback)

        _xttrader_account = account
        logger.info(f"XtQuantTrader 实例创建成功，账户: {account}")
        return {"success": True, "data": f"交易实例创建成功，账户: {account}"}

    except Exception as e:
        logger.error(f"创建 XtQuantTrader 实例失败: {e}")
        return {"success": False, "error": str(e)}


def execute_xttrader_method(function: str, args: List[Any], kwargs: Dict[str, Any]) -> dict:
    """
    在 XtQuantTrader 实例上执行方法。

    参数：
        function: 方法名称
        args: 位置参数
        kwargs: 关键字参数

    返回：
        dict: 包含 success 和 data/error 的结果
    """
    global _xttrader_instance

    if function == "create_trader":
        account = kwargs.get("account")
        mini_qmt_path = kwargs.get("mini_qmt_path")
        return create_xttrader_instance(account, mini_qmt_path)

    if _xttrader_instance is None:
        return {"success": False, "error": "XtQuantTrader 实例未创建，请先调用 create_trader"}

    if function in ("start", "connect"):
        return {"success": True, "data": f"{function} 已在初始化时执行"}

    method = getattr(_xttrader_instance, function, None)
    if method is None:
        return {"success": False, "error": f"方法 {function} 在 XtQuantTrader 实例上未找到"}

    if not callable(method):
        return {"success": False, "error": f"{function} 不是可调用方法"}

    try:
        if "account" in kwargs:
            from xtquant.xttype import StockAccount
            account_str = kwargs.pop("account")
            account_type = kwargs.pop("account_type", "STOCK")
            kwargs["account"] = StockAccount(str(account_str), account_type)

        result = method(*args, **kwargs)
        return {"success": True, "data": serialize_data(result)}
    except Exception as e:
        logger.error(f"执行 xttrader.{function} 失败: {e}")
        return {"success": False, "error": str(e)}


def is_function_whitelisted(module: str, function: str) -> bool:
    """
    检查函数是否在白名单中。

    参数：
        module: 模块名称
        function: 函数名称

    返回：
        如果在白名单中返回 True，否则返回 False
    """
    from .whitelist import is_function_whitelisted as check_whitelist
    return check_whitelist(module, function)


def adapt_xtdata_params(function: str, kwargs: dict) -> dict:
    """
    适配 xtdata 接口参数。

    部分 xtdata 函数有特定的参数要求。
    本函数将输入参数适配为期望的格式。

    参数：
        function: 函数名称
        kwargs: 输入的关键字参数

    返回：
        适配后的关键字参数

    注意：
        当前处理以下函数的参数适配：
        - get_financial_data
        - download_financial_data
    """
    if function == "get_financial_data":
        adapted = {}
        if "stock_list" in kwargs:
            adapted["stock_list"] = kwargs["stock_list"]
        if "table_list" in kwargs:
            adapted["table_list"] = kwargs["table_list"]
        elif "indicators" in kwargs:
            adapted["table_list"] = kwargs["indicators"]
        if "start_time" in kwargs:
            adapted["start_time"] = kwargs["start_time"]
        if "end_time" in kwargs:
            adapted["end_time"] = kwargs["end_time"]
        if "report_type" in kwargs:
            adapted["report_type"] = kwargs["report_type"]
        return adapted

    elif function == "download_financial_data":
        adapted = {}
        if "stock_list" in kwargs:
            adapted["stock_list"] = kwargs["stock_list"]
        if "table_list" in kwargs:
            adapted["table_list"] = kwargs["table_list"]
        elif "indicators" in kwargs:
            adapted["table_list"] = kwargs["indicators"]
        if "start_time" in kwargs:
            adapted["start_time"] = kwargs["start_time"]
        if "end_time" in kwargs:
            adapted["end_time"] = kwargs["end_time"]
        if "incrementally" in kwargs:
            adapted["incrementally"] = kwargs["incrementally"]
        return adapted

    return kwargs


async def execute_rpc_call(
    module: str,
    function: str,
    args: List[Any],
    kwargs: Dict[str, Any],
    timeout: int = 30,
    provider: Any = None
) -> dict:
    """
    执行 RPC 调用。

    这是执行远程过程调用的主入口。
    它会验证函数是否在白名单中，必要时适配参数，
    并在线程池中执行调用。

    参数：
        module: 模块名称 (xtdata, xttrader, gmdata, gmtrade)
        function: 要调用的函数名称
        args: 函数的位置参数
        kwargs: 函数的关键字参数
        timeout: 执行超时时间（秒），默认 30 秒
        provider: 可选的数据源实例，用于获取模块引用

    返回：
        dict: 结果字典，包含以下键：
            - success: bool - 调用是否成功
            - data: Any - 序列化后的结果数据（成功时）
            - error: str - 错误信息（失败时）
            - module: str - 模块名称
            - function: str - 函数名称
            - execution_time_ms: float - 执行时间（毫秒）

    示例：
        >>> result = await execute_rpc_call(
        ...     "xtdata",
        ...     "get_market_data",
        ...     [],
        ...     {"stock_list": ["000001.SZ"], "period": "1d"}
        ... )
        >>> if result["success"]:
        ...     print(result["data"])
    """
    start_time = datetime.now()

    try:
        mod_ref = get_module_reference(module)

        if provider is not None and hasattr(provider, 'get_module_reference'):
            provider_ref = provider.get_module_reference(module)
            if provider_ref is not None:
                mod_ref = provider_ref

        if mod_ref is None:
            return {
                "success": False,
                "error": f"不支持的模块: {module}",
                "module": module,
                "function": function
            }

        if not is_function_whitelisted(module, function):
            return {
                "success": False,
                "error": f"函数 {module}.{function} 不在白名单中",
                "module": module,
                "function": function
            }

        if module == "xttrader":
            result = await run_module_call(
                "xttrader",
                execute_xttrader_method,
                (function, args, kwargs),
                timeout=timeout,
                lane="trade",
            )
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            result["module"] = module
            result["function"] = function
            result["execution_time_ms"] = execution_time
            return result

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

        logger.info(f"RPC 调用: {module}.{function}")
        logger.debug(f"  args={args}, kwargs={kwargs}")

        if module == "xtdata":
            adapted_kwargs = adapt_xtdata_params(function, kwargs)
            if adapted_kwargs != kwargs:
                logger.debug(f"  适配后的参数: {adapted_kwargs}")
                kwargs = adapted_kwargs

        validate_kwargs(func, kwargs)
        result = await run_module_call(
            module, func, args, kwargs, timeout=timeout,
            lane="trade" if module == "gmtrade" else "data",
        )

        serialized_result = serialize_data(result)

        execution_time = (datetime.now() - start_time).total_seconds() * 1000

        logger.info(f"RPC 调用成功: {module}.{function}, 耗时: {execution_time:.2f}ms")

        return {
            "success": True,
            "data": serialized_result,
            "module": module,
            "function": function,
            "execution_time_ms": execution_time
        }

    except InvalidRpcArguments as e:
        logger.warning(f"RPC 参数校验失败: {module}.{function}: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_code": e.error_code,
            "unknown_params": e.unknown,
            "missing_params": e.missing,
            "module": module,
            "function": function,
            "execution_time_ms": (datetime.now() - start_time).total_seconds() * 1000
        }
    except TimeoutError as e:
        logger.error(f"RPC 调用超时: {module}.{function}")
        return {
            "success": False,
            "error": str(e),
            "module": module,
            "function": function,
            "execution_time_ms": (datetime.now() - start_time).total_seconds() * 1000
        }
    except Exception as e:
        logger.error(f"RPC 调用失败: {module}.{function}")
        logger.error(f"错误: {str(e)}")
        logger.error(f"堆栈跟踪: {traceback.format_exc()}")

        return {
            "success": False,
            "error": str(e),
            "error_traceback": traceback.format_exc(),
            "module": module,
            "function": function,
            "execution_time_ms": (datetime.now() - start_time).total_seconds() * 1000
        }
