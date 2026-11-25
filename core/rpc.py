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
import zlib
from datetime import datetime
from typing import Any, Dict, List, Optional

from providers.base import serialize_data
from .capabilities import evaluate_rpc, evaluate_ws_module
from .executor import normalize_timeout, run_module_call
from .sdk_compat import is_compat_function, wrap_trader

logger = logging.getLogger(__name__)

_PROVIDER_FOR_MODULE = {
    "xtdata": "xtquant",
    "xttrader": "xtquant",
    "gmdata": "gm",
    "gmtrade": "gm",
    "tdxdata": "tdxquant",
    "tdxtrade": "tdxquant",
}


class InvalidRpcArguments(ValueError):
    """RPC 参数校验失败。"""

    error_code = "INVALID_ARGUMENT"

    def __init__(self, message: str, unknown: Optional[List[str]] = None,
                 missing: Optional[List[str]] = None):
        super().__init__(message)
        self.unknown = unknown or []
        self.missing = missing or []


def validate_kwargs(
    func: Any, kwargs: Dict[str, Any], args: Optional[List[Any]] = None
) -> None:
    """
    按函数签名校验参数。

    与旧实现不同：未知参数不再被静默丢弃，而是直接报错，
    避免调用方以为参数生效、实际却用了默认值。位置参数会先与签名绑定，
    再判断是否缺少必填参数，因此 ``args`` 与 ``kwargs`` 可以混用。

    参数：
        func: 可调用对象
        kwargs: 待校验的关键字参数
        args: 待绑定的位置参数

    异常：
        InvalidRpcArguments: 存在未知参数、参数无法绑定或缺少必填参数
    """
    kwargs = kwargs or {}
    args = tuple(args or [])

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

    try:
        bound = signature.bind_partial(*args, **kwargs)
    except TypeError as exc:
        message = str(exc)
        missing = []
        if "missing a required argument" in message:
            missing = [message.rsplit(":", 1)[-1].strip()]
        raise InvalidRpcArguments(
            f"参数绑定失败: {message}", missing=missing
        ) from exc

    missing = [
        name for name, p in params.items()
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                      inspect.Parameter.KEYWORD_ONLY)
        and p.default is inspect.Parameter.empty
        and name not in bound.arguments
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
_xttrader_state = {
    "started": False,
    "connected": False,
    "connect_code": None,
}


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
        from core.sdk_compat import wrap_xtdata

        try:
            from config import config as _config
            compat_enabled = bool(getattr(_config, "XT_SDK_COMPAT", True))
        except ImportError:
            compat_enabled = True
        _xtdata_module = wrap_xtdata(xtdata, enabled=compat_enabled)
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


def _xttrader_probe(function: str):
    """探测 xttrader 方法是否存在；实例未创建时回退到 XtQuantTrader 类。"""
    if function in ("create_trader", "start", "connect"):
        return True
    # 兼容层提供的函数由代理对象在实例创建后暴露
    if is_compat_function("xttrader", function) and _compat_enabled():
        return True
    instance = get_xttrader_instance()
    target = instance
    if target is None:
        try:
            from xtquant.xttrader import XtQuantTrader
            target = XtQuantTrader
        except Exception:
            return None
    return callable(getattr(target, function, None))


def resolve_session_id(account: str) -> int:
    """为交易实例生成独立的 session_id。

    QMT 的 ``session_id`` 只要求是整数，历史上直接用 ``int(account)`` 会让
    非纯数字资金账户无法创建实例。这里改为：

    1. 显式配置 ``QMT_SESSION_ID`` 优先；
    2. 否则按账户做 crc32，得到稳定的 31 位正整数——
       同一账户重启复用同一会话，避免在终端留下幽灵会话。
    """
    try:
        from config import config
        configured = getattr(config, "QMT_SESSION_ID", None)
    except ImportError:  # pragma: no cover - 配置模块始终存在
        configured = None

    if configured not in (None, ""):
        try:
            session_id = int(configured)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"QMT_SESSION_ID 必须是整数: {configured!r}") from exc
        if session_id <= 0:
            raise ValueError("QMT_SESSION_ID 必须大于 0")
        return session_id

    account_key = str(account or "").strip()
    if not account_key:
        raise ValueError("账户 ID 不能为空，无法生成 session_id")
    session_id = zlib.crc32(account_key.encode("utf-8")) & 0x7FFFFFFF
    return session_id or 1


def create_xttrader_instance(
    account: str, mini_qmt_path: str = None, account_type: str = "STOCK"
) -> dict:
    """
    创建 XtQuantTrader 实例。

    参数：
        account: 账户 ID（用于生成 session_id，不再直接 int 转换）
        mini_qmt_path: MiniQMT 路径（可选，默认从配置读取）
        account_type: 账户类型，仅用于记录；实例创建后再由 StockAccount 指定

    返回：
        dict: 包含 success 和 data/error 的结果
    """
    global _xttrader_instance, _xttrader_account, _xttrader_callback

    normalized_type = str(account_type or "STOCK").strip().upper()
    if normalized_type != "STOCK":
        return {
            "success": False,
            "error": "仅支持普通股票账户（STOCK），信用/期权/期货账户不开放",
        }

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
        callback_cls = getattr(_xttrader_module, "XtQuantTraderCallback", None)
        if callback_cls is None:
            from xtquant.xttrader import XtQuantTraderCallback as callback_cls

        session_id = resolve_session_id(account)
        _xttrader_callback = callback_cls()
        raw_instance = _xttrader_module.XtQuantTrader(mini_qmt_path, session_id)
        _xttrader_instance = wrap_trader(raw_instance, enabled=_compat_enabled())
        _xttrader_instance.register_callback(_xttrader_callback)

        _xttrader_account = account
        _reset_xttrader_state()
        logger.info(
            f"XtQuantTrader 实例创建成功，账户: {account}, session_id: {session_id}"
        )
        return {
            "success": True,
            "data": f"交易实例创建成功，账户: {account}",
            "session_id": session_id,
        }

    except Exception as e:
        logger.error(f"创建 XtQuantTrader 实例失败: {e}")
        return {"success": False, "error": str(e)}


def _compat_enabled() -> bool:
    try:
        from config import config
        return bool(getattr(config, "XT_SDK_COMPAT", True))
    except ImportError:  # pragma: no cover
        return True


def _reset_xttrader_state() -> None:
    _xttrader_state.update({
        "started": False,
        "connected": False,
        "connect_code": None,
    })


def _trader_lifecycle(function: str) -> dict:
    """执行 start / connect，并返回真实结果而不是无条件成功。"""
    if _xttrader_instance is None:
        return {"success": False, "error": "XtQuantTrader 实例未创建，请先调用 create_trader"}

    if function == "start":
        if _xttrader_state["started"]:
            return {"success": True, "data": None, "already_started": True}
        method = getattr(_xttrader_instance, "start", None)
        if not callable(method):
            return {"success": False, "error": "XtQuantTrader.start 不可用"}
        try:
            return_code = method()
        except Exception as exc:
            logger.error("XtQuantTrader.start 失败: %s", exc)
            return {"success": False, "error": f"start 失败: {exc}"}
        _xttrader_state["started"] = True
        logger.info("XtQuantTrader.start 执行完成")
        return {"success": True, "data": return_code, "already_started": False}

    if _xttrader_state["connected"]:
        return {
            "success": True,
            "data": _xttrader_state["connect_code"],
            "already_connected": True,
        }

    method = getattr(_xttrader_instance, "connect", None)
    if not callable(method):
        return {"success": False, "error": "XtQuantTrader.connect 不可用"}
    try:
        return_code = method()
    except Exception as exc:
        logger.error("XtQuantTrader.connect 失败: %s", exc)
        return {"success": False, "error": f"connect 失败: {exc}"}

    ok = return_code == 0 or return_code is True
    _xttrader_state["connected"] = ok
    _xttrader_state["connect_code"] = return_code
    if not ok:
        logger.warning("XtQuantTrader.connect 返回非 0: %r", return_code)
        return {
            "success": False,
            "data": return_code,
            "error": f"连接交易服务器失败，返回码: {return_code}",
        }

    logger.info("XtQuantTrader.connect 成功")
    return {"success": True, "data": return_code, "already_connected": False}


def get_xttrader_state() -> dict:
    """返回交易实例的启动/连接状态快照。"""
    return dict(_xttrader_state)


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
        account = kwargs.get("account") if kwargs else None
        if account is None and args:
            account = args[0]
        mini_qmt_path = kwargs.get("mini_qmt_path")
        if mini_qmt_path is None and len(args) > 1:
            mini_qmt_path = args[1]
        account_type = kwargs.get("account_type", "STOCK")
        return create_xttrader_instance(account, mini_qmt_path, account_type)

    if _xttrader_instance is None:
        return {"success": False, "error": "XtQuantTrader 实例未创建，请先调用 create_trader"}

    if function in ("start", "connect"):
        return _trader_lifecycle(function)

    method = getattr(_xttrader_instance, function, None)
    if method is None:
        return {"success": False, "error": f"方法 {function} 在 XtQuantTrader 实例上未找到"}

    if not callable(method):
        return {"success": False, "error": f"{function} 不是可调用方法"}

    try:
        call_args = list(args)
        if "account" in kwargs:
            from xtquant.xttype import StockAccount
            account_str = kwargs.pop("account")
            account_type = kwargs.pop("account_type", "STOCK")
            kwargs["account"] = StockAccount(str(account_str), account_type)
        elif call_args and isinstance(call_args[0], str):
            # 位置参数里的账户字符串也要转成 StockAccount，
            # 否则 query_stock_asset("xxx") 会把字符串直接传给 SDK。
            try:
                first_param = next(iter(inspect.signature(method).parameters.values()))
            except (TypeError, ValueError, StopIteration):
                first_param = None
            if first_param is not None and first_param.name == "account":
                from xtquant.xttype import StockAccount
                call_args[0] = StockAccount(
                    call_args[0], kwargs.pop("account_type", "STOCK")
                )

        result = method(*call_args, **kwargs)
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
        timeout = normalize_timeout(timeout)

        provider_name = _PROVIDER_FOR_MODULE.get(module)

        # 通道边界：WebSocket RPC 只开放 xtdata/xttrader/gmdata/gmtrade；
        # TDX 只能走 HTTP。
        if provider_name:
            ws_status, ws_reason = evaluate_ws_module(provider_name, module)
            if ws_status != "supported":
                return {
                    "success": False,
                    "error": ws_reason or f"{module} 不开放 WebSocket RPC",
                    "error_code": "USE_HTTP_ENDPOINT",
                    "support_status": ws_status,
                    "module": module,
                    "function": function,
                }

        mod_ref = get_module_reference(module)

        if provider is not None and hasattr(provider, 'get_module_reference'):
            provider_ref = provider.get_module_reference(module)
            if provider_ref is not None:
                mod_ref = provider_ref

        probe = None
        if module == "xttrader":
            probe = _xttrader_probe
        elif mod_ref is not None:
            probe = lambda fn: callable(getattr(mod_ref, fn, None))

        if provider_name:
            status, reason = evaluate_rpc(provider_name, module, function, probe=probe)
            if status != "supported":
                return {
                    "success": False,
                    "error": reason or f"函数 {module}.{function} 不支持",
                    "error_code": (
                        "NOT_WHITELISTED"
                        if status == "not_declared" else "NOT_SUPPORTED"
                    ),
                    "support_status": status,
                    "module": module,
                    "function": function
                }

        if mod_ref is None:
            return {
                "success": False,
                "error": f"模块 {module} 未接入当前 RPC 通道",
                "error_code": "NOT_SUPPORTED",
                "support_status": "runtime_missing",
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

        logger.info(f"RPC 调用: {module}.{function}")
        logger.debug(f"  args={args}, kwargs={kwargs}")

        if module == "xtdata":
            adapted_kwargs = adapt_xtdata_params(function, kwargs)
            if adapted_kwargs != kwargs:
                logger.debug(f"  适配后的参数: {adapted_kwargs}")
                kwargs = adapted_kwargs

        validate_kwargs(func, kwargs, args)
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
