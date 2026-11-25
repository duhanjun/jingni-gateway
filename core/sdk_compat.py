# -*- coding: utf-8 -*-
"""xtquant SDK 缺失函数兼容层。

背景：
    ``功能矩阵.md`` 记录当前 QMT SDK 缺失 26 个已在白名单声明的函数
    （xtdata 16 项 + xttrader 10 项）。这些函数不是“代码层不支持”，
    而是当前 SDK 版本没有对应 API。

本模块把 26 项缺口收敛成三种可测试的处置策略：

1. ``derived``：能用当前 SDK 已有 API 忠实推导的函数，由网关内置实现；
   一旦 SDK 恢复同名 API，代理层优先使用真实 API，兼容实现自动失效。
2. ``sdk_api_absent``：无法忠实推导（公式、ETF 下载、IPO 等），保持
   ``runtime_missing``，但给出明确原因和升级提示。
3. ``sdk_api_absent + policy_blocked``：当前 SDK 缺失，且即使恢复也不开放
   （信用、银证转账、SMT），避免 SDK 升级后越过能力边界。

对外接口：
- ``MISSING_SDK_FUNCTIONS``：26 项缺口登记表；
- ``wrap_xtdata``：给真实 xtdata 模块套兼容代理；
- ``wrap_trader``：给 XtQuantTrader 实例套兼容代理；
- ``is_compat_function``：判断某函数是否由兼容层提供；
- ``describe_missing_sdk``：输出缺口清单，供 ``/rpc/capabilities`` 使用。

安全约束：
- 兼容层只补齐白名单内的只读/能力型函数，不触碰交易写操作；
- 代理对象不修改真实 SDK 模块的属性，避免污染第三方库的全局状态。
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

STRATEGY_DERIVED = "derived"
STRATEGY_SDK_ABSENT = "sdk_api_absent"
UPGRADE_HINT = "升级 QMT xtquant SDK 后重启网关，运行时探测会自动恢复"

# QMT 支持的 K 线周期（与官方 get_period_list 输出一致）
QMT_PERIOD_LIST: Tuple[str, ...] = (
    "tick", "1m", "5m", "15m", "30m", "1h", "1d", "1w", "1M",
)


@dataclass(frozen=True)
class MissingSdkEntry:
    """单个 SDK 缺失函数的登记信息。"""

    module: str
    function: str
    strategy: str
    derivation: Optional[str]
    reason: str
    # True 表示即使 SDK 恢复同名 API，也因能力边界不对外开放
    policy_blocked: bool = False

    @property
    def derivable(self) -> bool:
        return self.strategy == STRATEGY_DERIVED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "function": self.function,
            "strategy": self.strategy,
            "derivation": self.derivation,
            "reason": self.reason,
            "policy_blocked": self.policy_blocked,
            "upgrade_hint": (
                UPGRADE_HINT
                if not self.derivable and not self.policy_blocked
                else None
            ),
        }


MISSING_SDK_FUNCTIONS: Tuple[MissingSdkEntry, ...] = (
    # ---------------- xtdata：16 项 ----------------
    MissingSdkEntry(
        "xtdata", "get_full_kline", STRATEGY_DERIVED, "get_market_data_ex(count=-1)",
        "用当前 SDK 的 get_market_data_ex 拉取全量历史 K 线",
    ),
    MissingSdkEntry(
        "xtdata", "download_etf_info", STRATEGY_SDK_ABSENT, None,
        "当前 SDK 未提供 ETF 信息下载接口；get_etf_info 只能按代码查询，无法替代全量下载",
    ),
    MissingSdkEntry(
        "xtdata", "download_holiday_data", STRATEGY_DERIVED, "get_holidays()",
        "以 get_holidays 触发并返回本地节假日表",
    ),
    MissingSdkEntry(
        "xtdata", "get_trading_time", STRATEGY_DERIVED, "get_trade_times(stock_code)",
        "当前 SDK 的交易时段接口名为 get_trade_times",
    ),
    MissingSdkEntry(
        "xtdata", "get_ipo_info", STRATEGY_SDK_ABSENT, None,
        "当前 SDK 没有新股信息数据源；交易侧 query_ipo_data 只覆盖已登录账户的申购额度",
    ),
    MissingSdkEntry(
        "xtdata", "get_period_list", STRATEGY_DERIVED, "静态周期表",
        "周期集合是 QMT 协议常量，不依赖运行时",
    ),
    MissingSdkEntry(
        "xtdata", "get_data_dir", STRATEGY_DERIVED, "init_data_dir()",
        "init_data_dir 返回当前数据目录，可忠实替代",
    ),
    MissingSdkEntry(
        "xtdata", "create_sector_folder", STRATEGY_DERIVED, "网关侧命名空间校验",
        "QMT 板块以“文件夹/板块名”命名，文件夹本身无需服务端对象",
    ),
    MissingSdkEntry(
        "xtdata", "create_sector", STRATEGY_DERIVED, "add_sector(sector_name, stock_list)",
        "当前 SDK 的板块创建函数名为 add_sector",
    ),
    MissingSdkEntry(
        "xtdata", "remove_stock_from_sector", STRATEGY_DERIVED,
        "get_stock_list_in_sector + remove_sector/add_sector",
        "先读板块成分，剔除目标标的后重建板块",
    ),
    MissingSdkEntry(
        "xtdata", "reset_sector", STRATEGY_DERIVED, "remove_sector + add_sector",
        "重置等价于删除后按给定成分重建",
    ),
    MissingSdkEntry(
        "xtdata", "subscribe_formula", STRATEGY_SDK_ABSENT, None,
        "公式订阅依赖 SDK 公式引擎，当前 SDK 未暴露该 API",
    ),
    MissingSdkEntry(
        "xtdata", "unsubscribe_formula", STRATEGY_SDK_ABSENT, None,
        "公式订阅依赖 SDK 公式引擎，当前 SDK 未暴露该 API",
    ),
    MissingSdkEntry(
        "xtdata", "call_formula", STRATEGY_SDK_ABSENT, None,
        "公式计算依赖 SDK 公式引擎，当前 SDK 未暴露该 API",
    ),
    MissingSdkEntry(
        "xtdata", "call_formula_batch", STRATEGY_SDK_ABSENT, None,
        "公式批量计算依赖 SDK 公式引擎，当前 SDK 未暴露该 API",
    ),
    MissingSdkEntry(
        "xtdata", "generate_index_data", STRATEGY_SDK_ABSENT, None,
        "自定义指数生成依赖 SDK 服务端能力，当前 SDK 未暴露该 API",
    ),
    # ---------------- xttrader：10 项 ----------------
    MissingSdkEntry(
        "xttrader", "query_position_statistics", STRATEGY_DERIVED,
        "query_stock_positions 聚合",
        "按持仓明细聚合数量、成本与市值",
    ),
    MissingSdkEntry(
        "xttrader", "query_com_fund", STRATEGY_SDK_ABSENT, None,
        "信用账户资金查询；网关只支持普通股票账户，当前 SDK 也未提供该 API",
        policy_blocked=True,
    ),
    MissingSdkEntry(
        "xttrader", "query_com_position", STRATEGY_SDK_ABSENT, None,
        "信用账户持仓查询；网关只支持普通股票账户，当前 SDK 也未提供该 API",
        policy_blocked=True,
    ),
    MissingSdkEntry(
        "xttrader", "query_data", STRATEGY_SDK_ABSENT, None,
        "通用数据查询的语义随券商版本变化，无法用现有查询安全替代",
    ),
    MissingSdkEntry(
        "xttrader", "query_bank_info", STRATEGY_SDK_ABSENT, None,
        "银证转账信息属于资金划转域，当前 SDK 未提供且不在网关开放范围",
        policy_blocked=True,
    ),
    MissingSdkEntry(
        "xttrader", "query_bank_amount", STRATEGY_SDK_ABSENT, None,
        "银证转账额度属于资金划转域，当前 SDK 未提供且不在网关开放范围",
        policy_blocked=True,
    ),
    MissingSdkEntry(
        "xttrader", "query_bank_transfer_stream", STRATEGY_SDK_ABSENT, None,
        "银证转账流水属于资金划转域，当前 SDK 未提供且不在网关开放范围",
        policy_blocked=True,
    ),
    MissingSdkEntry(
        "xttrader", "query_secu_account", STRATEGY_DERIVED, "query_account_infos()",
        "账户信息接口已存在，按账户号过滤即可",
    ),
    MissingSdkEntry(
        "xttrader", "smt_query_quoter", STRATEGY_SDK_ABSENT, None,
        "SMT 协议报价查询；SMT 交易链未实现，当前 SDK 未提供该 API",
        policy_blocked=True,
    ),
    MissingSdkEntry(
        "xttrader", "smt_query_compact", STRATEGY_SDK_ABSENT, None,
        "SMT 协议合约查询；SMT 交易链未实现，当前 SDK 未提供该 API",
        policy_blocked=True,
    ),
)

MISSING_SDK_INDEX: Dict[Tuple[str, str], MissingSdkEntry] = {
    (entry.module, entry.function): entry for entry in MISSING_SDK_FUNCTIONS
}


def describe_missing_sdk() -> Dict[str, List[Dict[str, Any]]]:
    """按模块输出 26 项缺口登记表。"""
    report: Dict[str, List[Dict[str, Any]]] = {}
    for entry in MISSING_SDK_FUNCTIONS:
        report.setdefault(entry.module, []).append(entry.to_dict())
    return report


def missing_entry(module: str, function: str) -> Optional[MissingSdkEntry]:
    return MISSING_SDK_INDEX.get((module, function))


def _require(current: Any, name: str) -> Any:
    func = getattr(current, name, None)
    if func is None or not callable(func):
        raise RuntimeError(f"兼容实现依赖的 SDK 函数 {name} 不可用")
    return func


def _field(row: Any, names: Sequence[str], default: Any = None) -> Any:
    """从 dict 或 SDK 对象上取第一个存在的字段。"""
    for name in names:
        if isinstance(row, dict):
            if name in row and row[name] is not None:
                return row[name]
        else:
            value = getattr(row, name, None)
            if value is not None:
                return value
    return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _rows(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        rows = value.get("Value")
        if isinstance(rows, list):
            return rows
    return []


# ---------------------------------------------------------------------------
# xtdata 兼容实现
# ---------------------------------------------------------------------------
def compat_get_full_kline(
    xtdata: Any,
    field_list: Optional[List[str]] = None,
    stock_list: Optional[List[str]] = None,
    period: str = "1d",
    start_time: str = "",
    end_time: str = "",
    count: int = -1,
    dividend_type: str = "none",
    fill_data: bool = True,
) -> Any:
    """全量 K 线：用 get_market_data_ex 拉取 count=-1 的历史数据。"""
    fetch = _require(xtdata, "get_market_data_ex")
    return fetch(
        field_list=field_list or [],
        stock_list=stock_list or [],
        period=period,
        start_time=start_time,
        end_time=end_time,
        count=-1,
        dividend_type=dividend_type,
        fill_data=fill_data,
    )


def compat_download_holiday_data(xtdata: Any) -> Any:
    """下载节假日数据：当前 SDK 以 get_holidays 提供，触发并返回本地表。"""
    return _require(xtdata, "get_holidays")()


def compat_get_trading_time(xtdata: Any, stock_code: str) -> Any:
    """交易时段：转发 get_trade_times。"""
    if not stock_code:
        raise ValueError("stock_code 不能为空")
    return _require(xtdata, "get_trade_times")(stock_code)


def compat_get_period_list(xtdata: Any = None) -> List[str]:
    """支持的周期列表（QMT 协议常量）。"""
    return list(QMT_PERIOD_LIST)


def compat_get_data_dir(xtdata: Any) -> Any:
    """数据目录：转发 init_data_dir。"""
    return _require(xtdata, "init_data_dir")()


def compat_create_sector_folder(xtdata: Any = None, folder_name: str = "") -> Dict[str, Any]:
    """创建板块文件夹（网关侧命名空间校验）。

    QMT 板块名本身是“文件夹/板块名”的扁平字符串，服务端没有独立文件夹对象，
    因此这里只校验命名并返回，后续 add_sector 用带前缀的名称即可。
    """
    name = (folder_name or "").strip()
    if not name:
        raise ValueError("folder_name 不能为空")
    if any(ch in name for ch in "/\\:*?\"<>|"):
        raise ValueError("folder_name 含非法字符")
    return {"folder": name, "created": True}


def compat_create_sector(
    xtdata: Any, sector_name: str, stock_list: Optional[List[str]] = None
) -> Any:
    """创建板块：转发 add_sector。"""
    if not sector_name:
        raise ValueError("sector_name 不能为空")
    return _require(xtdata, "add_sector")(sector_name, stock_list or [])


def compat_remove_stock_from_sector(
    xtdata: Any, sector_name: str, stock_list: Optional[List[str]] = None
) -> Dict[str, Any]:
    """从板块移除标的：读成分、剔除目标、重建板块。"""
    if not sector_name:
        raise ValueError("sector_name 不能为空")
    targets = {str(item) for item in (stock_list or [])}
    current = _require(xtdata, "get_stock_list_in_sector")(sector_name) or []
    remaining = [item for item in current if str(item) not in targets]
    _require(xtdata, "remove_sector")(sector_name)
    _require(xtdata, "add_sector")(sector_name, remaining)
    return {
        "sector_name": sector_name,
        "removed": len(current) - len(remaining),
        "remaining": len(remaining),
    }


def compat_reset_sector(
    xtdata: Any, sector_name: str, stock_list: Optional[List[str]] = None
) -> Dict[str, Any]:
    """重置板块：删除后按给定成分重建。"""
    if not sector_name:
        raise ValueError("sector_name 不能为空")
    _require(xtdata, "remove_sector")(sector_name)
    members = list(stock_list or [])
    if members:
        _require(xtdata, "add_sector")(sector_name, members)
    return {"sector_name": sector_name, "members": len(members)}


# ---------------------------------------------------------------------------
# xttrader 兼容实现
# ---------------------------------------------------------------------------
def compat_query_position_statistics(trader: Any, account: Any = None) -> Dict[str, Any]:
    """持仓统计：聚合 query_stock_positions。"""
    query = _require(trader, "query_stock_positions")
    positions = query(account) if account is not None else query()
    rows = _rows(positions)

    total_volume = 0
    total_cost = 0.0
    total_market_value = 0.0
    symbols: List[str] = []

    for row in rows:
        symbol = _field(row, ("stock_code", "symbol", "Code"))
        if symbol:
            symbols.append(str(symbol))

        volume = _to_float(_field(
            row, ("volume", "total_volume", "TotalVol", "m_nVolume"), 0
        ))
        total_volume += int(volume)

        cost = _to_float(_field(
            row, ("open_price", "cost", "avg_price", "Cbj", "m_dOpenPrice"), 0
        ))
        total_cost += cost * volume

        market_value = _field(
            row, ("market_value", "MarketValue", "m_dMarketValue")
        )
        if market_value is not None:
            total_market_value += _to_float(market_value, 0.0)

    return {
        "account": _account_id(account),
        "position_count": len(rows),
        "total_volume": total_volume,
        "total_cost": round(total_cost, 4),
        "total_market_value": round(total_market_value, 4),
        "symbols": symbols,
    }


def compat_query_secu_account(trader: Any, account: Any = None) -> List[Any]:
    """证券账户信息：转发 query_account_infos 并按账户过滤。"""
    infos = _rows(_require(trader, "query_account_infos")())
    target = _account_id(account)
    if not target:
        return infos
    return [
        row for row in infos
        if str(_field(row, ("account_id", "account", "AccountID"), "")) == target
    ]


def _account_id(account: Any) -> Optional[str]:
    if account is None:
        return None
    if isinstance(account, (str, int)):
        return str(account)
    return str(
        getattr(account, "account_id", None)
        or getattr(account, "account", None)
        or account
    )


_XT_DATA_HANDLERS: Dict[str, Callable[..., Any]] = {
    "get_full_kline": compat_get_full_kline,
    "download_holiday_data": compat_download_holiday_data,
    "get_trading_time": compat_get_trading_time,
    "get_period_list": compat_get_period_list,
    "get_data_dir": compat_get_data_dir,
    "create_sector_folder": compat_create_sector_folder,
    "create_sector": compat_create_sector,
    "remove_stock_from_sector": compat_remove_stock_from_sector,
    "reset_sector": compat_reset_sector,
}

_XT_TRADER_HANDLERS: Dict[str, Callable[..., Any]] = {
    "query_position_statistics": compat_query_position_statistics,
    "query_secu_account": compat_query_secu_account,
}


def compat_functions(module: str) -> List[str]:
    """返回某模块由兼容层提供的函数名。"""
    if module == "xtdata":
        return sorted(_XT_DATA_HANDLERS)
    if module == "xttrader":
        return sorted(_XT_TRADER_HANDLERS)
    return []


def is_compat_function(module: str, function: str) -> bool:
    if module == "xtdata":
        return function in _XT_DATA_HANDLERS
    if module == "xttrader":
        return function in _XT_TRADER_HANDLERS
    return False


class _CompatProxy:
    """只读代理：真实属性优先，缺失时使用兼容实现。"""

    _target: Any
    _handlers: Dict[str, Callable[..., Any]]

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        target = object.__getattribute__(self, "_target")
        try:
            return getattr(target, name)
        except AttributeError:
            handlers = object.__getattribute__(self, "_handlers")
            handler = handlers.get(name)
            if handler is None:
                raise AttributeError(
                    f"{type(target).__name__} 与兼容层均未提供 {name}"
                ) from None
            return functools.partial(handler, target)

    def __dir__(self) -> List[str]:
        target = object.__getattribute__(self, "_target")
        handlers = object.__getattribute__(self, "_handlers")
        return sorted(set(dir(target)) | set(handlers))

    @property
    def wrapped(self) -> Any:
        """返回被代理的真实对象。"""
        return object.__getattribute__(self, "_target")

    def has_real(self, name: str) -> bool:
        """真实对象是否已提供该属性（SDK 升级后用于区分真实实现）。"""
        target = object.__getattribute__(self, "_target")
        return callable(getattr(target, name, None))


class XtDataCompatModule(_CompatProxy):
    """xtdata 兼容代理。"""

    def __init__(self, module: Any):
        self._target = module
        self._handlers = _XT_DATA_HANDLERS

    def __repr__(self) -> str:
        return f"<XtDataCompatModule {self._target!r}>"


class XtTraderCompat(_CompatProxy):
    """XtQuantTrader 实例兼容代理。"""

    def __init__(self, trader: Any):
        self._target = trader
        self._handlers = _XT_TRADER_HANDLERS

    def __repr__(self) -> str:
        return f"<XtTraderCompat {self._target!r}>"


def wrap_xtdata(module: Any, enabled: bool = True) -> Any:
    """给 xtdata 模块套兼容代理；已代理或未启用时原样返回。"""
    if module is None or not enabled or isinstance(module, XtDataCompatModule):
        return module
    return XtDataCompatModule(module)


def wrap_trader(trader: Any, enabled: bool = True) -> Any:
    """给交易实例套兼容代理；已代理或未启用时原样返回。"""
    if trader is None or not enabled or isinstance(trader, XtTraderCompat):
        return trader
    return XtTraderCompat(trader)


def unwrap(obj: Any) -> Any:
    """解包兼容代理，返回真实对象。"""
    if isinstance(obj, _CompatProxy):
        return object.__getattribute__(obj, "_target")
    return obj
