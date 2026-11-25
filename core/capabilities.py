# -*- coding: utf-8 -*-
"""能力矩阵：把“已支持 / 明确不支持 / 运行时缺失”固化为代码。

设计原则：
1. ``RPC_WHITELIST`` 仍是声明的安全边界，不直接对外当作“已支持”清单；
2. 本模块在其上做三层收敛：
   - 模块是否开放通用 RPC（``tdxtrade`` 只允许走类型化交易）；
   - provider 是否只支持子集（GM ``gmtrade`` 只有三个查询 action）；
   - 运行时模块是否真的提供该函数；
3. ``/rpc/whitelist``、``/rpc/methods`` 只暴露 ``supported``；
4. ``/rpc/execute`` 对明确不支持的函数返回 ``NOT_SUPPORTED``，不再等到
   ``getattr`` 失败后返回 ``NOT_FOUND``。
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.sdk_compat import (
    UPGRADE_HINT,
    describe_missing_sdk,
    is_compat_function,
    missing_entry,
)
from core.whitelist import BLOCKED_RPC_FUNCTIONS, RPC_WHITELIST

SUPPORTED = "supported"
UNSUPPORTED = "unsupported"
RUNTIME_MISSING = "runtime_missing"
NOT_DECLARED = "not_declared"
UNKNOWN_MODULE = "unknown_module"

PROVIDER_MODULES: Dict[str, Tuple[str, ...]] = {
    "xtquant": ("xtdata", "xttrader"),
    "gm": ("gmdata", "gmtrade"),
    "tdxquant": ("tdxdata", "tdxtrade"),
}

# 只有这些模块开放通用 RPC；tdxtrade 只能走 /trade/*。
RPC_EXPOSED_MODULES: Dict[str, Tuple[str, ...]] = {
    "xtquant": ("xtdata", "xttrader"),
    "gm": ("gmdata", "gmtrade"),
    "tdxquant": ("tdxdata",),
}

# WebSocket RPC 只开放这些模块；TDX 没有 WebSocket RPC，只能走 HTTP。
WS_EXPOSED_MODULES: Dict[str, Tuple[str, ...]] = {
    "xtquant": ("xtdata", "xttrader"),
    "gm": ("gmdata", "gmtrade"),
    "tdxquant": (),
}

# provider 级别的支持子集。GM 交易侧车目前只有 get_cash/get_position/get_orders
# 三个查询 action；其余信用、期权、基金、IPO、债券、算法单等均未实现。
SUPPORTED_RPC_OVERRIDES: Dict[Tuple[str, str], frozenset] = {
    ("gm", "gmtrade"): frozenset({"get_cash", "get_position", "get_orders"}),
}

OVERRIDE_REASONS: Dict[Tuple[str, str], str] = {
    ("gm", "gmtrade"): (
        "GM 交易面只支持 get_cash/get_position/get_orders 三个查询；"
        "下单/撤单走 /trade/*；信用、期权、基金、IPO、债券、算法单等未实现"
    ),
}

# 交易写操作：不在通用 RPC 中开放，必须走类型化端点。
TYPED_ONLY_FUNCTIONS: Dict[Tuple[str, str], frozenset] = {
    ("xtquant", "xttrader"): frozenset({"order_stock", "cancel_order_stock"}),
    ("gm", "gmtrade"): frozenset({
        "order_volume", "order_value", "order_percent",
        "order_target_volume", "order_target_value", "order_target_percent",
        "order_batch", "order_cancel", "order_cancel_all", "order_close_all",
    }),
    ("tdxquant", "tdxtrade"): frozenset({"order_stock", "cancel_order_stock"}),
}

TYPED_ONLY_REASONS: Dict[Tuple[str, str], str] = {
    ("xtquant", "xttrader"): (
        "下单/撤单只允许走 /api/v1/xtquant/trade/order|cancel"
    ),
    ("gm", "gmtrade"): (
        "GM 只提供 order_volume/order_cancel 类型化端点；"
        "其他 order_* 未实现，且不允许走通用 RPC"
    ),
    ("tdxquant", "tdxtrade"): (
        "TDX 交易不开放通用 RPC；查询和下单/撤单都走 /api/v1/tdxquant/trade/*"
    ),
}

# 明确不支持、且不在白名单里的函数。它们不会出现在 /rpc/methods，
# 但会出现在 /rpc/capabilities 的 unsupported 区，调用时返回 NOT_SUPPORTED。
KNOWN_UNSUPPORTED: Dict[Tuple[str, str], Dict[str, str]] = {
    ("xtquant", "xttrader"): {
        "register_callback": "回调对象无法通过 JSON 传输；由网关内部注册",
        "export_data": "高危：可向服务器任意路径写文件，已从 RPC 面移除",
        "smt_negotiate_order_async": "SMT 协议交易未实现",
    },
    ("tdxquant", "tdxdata"): {
        "get_version": "tqcenter 当前版本不提供 get_version",
        "subscribe_quote": "TDX 实时行情推送未接入",
        "subscribe_hq": "TDX 实时行情推送未接入",
        "unsubscribe_hq": "TDX 实时行情推送未接入",
        "get_subscribe_hq_stock_list": "TDX 实时行情推送未接入",
        "get_financial_data_by_date": "TDX 扩展数据函数未开放",
        "get_gpjy_value": "TDX 扩展数据函数未开放",
        "get_gpjy_value_by_date": "TDX 扩展数据函数未开放",
        "get_bkjy_value": "TDX 扩展数据函数未开放",
        "get_bkjy_value_by_date": "TDX 扩展数据函数未开放",
        "get_scjy_value": "TDX 扩展数据函数未开放",
        "get_scjy_value_by_date": "TDX 扩展数据函数未开放",
        "get_gb_info": "TDX 扩展数据函数未开放",
        "get_gb_info_by_date": "TDX 扩展数据函数未开放",
        "get_ipo_info": "TDX 扩展数据函数未开放",
        "get_zdt_data": "TDX 扩展数据函数未开放",
        "get_relation": "TDX 扩展数据函数未开放",
    },
    ("tdxquant", "tdxtrade"): {
        "query_history_trade": "tqcenter 当前版本未提供该函数",
    },
}

TYPED_TRADE: Dict[str, Dict[str, Any]] = {
    "xtquant": {
        "operations": [
            "order_stock", "cancel_order_stock",
            "query_stock_asset", "query_stock_orders", "query_stock_positions",
        ],
        "endpoints": [
            "/api/v1/xtquant/trade/order",
            "/api/v1/xtquant/trade/cancel",
            "/api/v1/xtquant/trade/orders",
            "/api/v1/xtquant/trade/asset",
            "/api/v1/xtquant/trade/positions",
        ],
        "note": "普通股票账户；order_type 0 买/1 卖；price_type 0 限价/1 最新价",
        "account_scope": "single_account",
        "multi_account": False,
        "idempotency": "process_memory",
    },
    "gm": {
        "operations": [
            "order_volume", "order_cancel",
            "get_cash", "get_position", "get_orders",
        ],
        "endpoints": [
            "/api/v1/gm/trade/order",
            "/api/v1/gm/trade/cancel",
            "/api/v1/gm/trade/orders",
            "/api/v1/gm/trade/asset",
            "/api/v1/gm/trade/positions",
        ],
        "note": "普通股票账户；按量下单；side 0 买/1 卖；order_type 0 限价/1 市价",
        "account_scope": "single_account",
        "multi_account": False,
        "idempotency": "process_memory",
    },
    "tdxquant": {
        "operations": [
            "order_stock", "cancel_order_stock",
            "query_stock_asset", "query_stock_orders", "query_stock_positions",
        ],
        "endpoints": [
            "/api/v1/tdxquant/trade/order",
            "/api/v1/tdxquant/trade/cancel",
            "/api/v1/tdxquant/trade/orders",
            "/api/v1/tdxquant/trade/asset",
            "/api/v1/tdxquant/trade/positions",
        ],
        "note": "普通股票账户；price_type 0 限价/1 市价/2 涨停/3 跌停",
        "account_scope": "single_account",
        "multi_account": False,
        "idempotency": "process_memory+sqlite",
    },
}


@dataclass(frozen=True)
class Capability:
    """单个函数的支持状态。"""

    function: str
    status: str
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "function": self.function,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass
class ModuleCapability:
    """单个模块的收敛结果。"""

    module: str
    exposed: bool
    supported: List[str]
    unsupported: List[Capability]


def evaluate_rpc(
    provider: str,
    module: str,
    function: str,
    probe: Optional[Callable[[str], Optional[bool]]] = None,
) -> Tuple[str, Optional[str]]:
    """判断一个函数能否通过通用 RPC 调用。

    ``probe`` 返回 True/False 表示运行时是否存在；返回 None 表示当前无法验证
    （例如 SDK 未安装、交易实例未创建），此时保留“声明支持”但不标记缺失。
    """

    if module not in RPC_WHITELIST:
        return UNKNOWN_MODULE, f"未知模块: {module}"

    if module not in RPC_EXPOSED_MODULES.get(provider, ()):
        return UNSUPPORTED, TYPED_ONLY_REASONS.get(
            (provider, module),
            "该模块不开放通用 RPC，请使用类型化交易端点",
        )

    if function in TYPED_ONLY_FUNCTIONS.get((provider, module), frozenset()):
        return UNSUPPORTED, TYPED_ONLY_REASONS.get(
            (provider, module), "交易写操作只允许走类型化端点"
        )

    known_reason = KNOWN_UNSUPPORTED.get((provider, module), {}).get(function)
    if known_reason:
        return UNSUPPORTED, known_reason

    if (module, function) in BLOCKED_RPC_FUNCTIONS:
        return UNSUPPORTED, "写操作只允许走类型化交易端点"

    if function not in RPC_WHITELIST[module]:
        return NOT_DECLARED, f"函数 {module}.{function} 不在支持清单中"

    # 能力边界优先于 SDK 可用性：信用、银证转账、SMT 等即使 SDK 恢复
    # 同名 API，也不得自动暴露为通用 RPC。
    entry = missing_entry(module, function)
    if entry is not None and entry.policy_blocked:
        return UNSUPPORTED, f"{entry.reason}；即使 SDK 恢复也不会开放"

    override = SUPPORTED_RPC_OVERRIDES.get((provider, module))
    if override is not None and function not in override:
        return UNSUPPORTED, OVERRIDE_REASONS.get(
            (provider, module), "该 provider 未实现此函数"
        )

    if probe is not None:
        exists = probe(function)
        if exists is False:
            entry = missing_entry(module, function)
            if entry is not None:
                if not entry.derivable:
                    return RUNTIME_MISSING, f"{entry.reason}；{UPGRADE_HINT}"
                return RUNTIME_MISSING, (
                    f"兼容实现依赖的 {entry.derivation} 不可用；{UPGRADE_HINT}"
                )
            return RUNTIME_MISSING, f"当前运行时模块未提供 {module}.{function}"

    return SUPPORTED, None


def resolve_module(
    provider: str,
    module: str,
    probe: Optional[Callable[[str], Optional[bool]]] = None,
) -> ModuleCapability:
    """把一个模块的白名单收敛为 supported / unsupported 两部分。"""

    declared = list(RPC_WHITELIST.get(module, []))
    exposed = module in RPC_EXPOSED_MODULES.get(provider, ())
    supported: List[str] = []
    unsupported: List[Capability] = []
    seen = set()

    for function in declared:
        status, reason = evaluate_rpc(provider, module, function, probe)
        if status == SUPPORTED:
            supported.append(function)
        else:
            unsupported.append(Capability(function, status, reason))
        seen.add(function)

    # 类型化交易写操作即使不在白名单，也要在矩阵中明确列出“不支持 RPC”。
    for function in sorted(TYPED_ONLY_FUNCTIONS.get((provider, module), frozenset())):
        if function in seen:
            continue
        unsupported.append(Capability(
            function,
            UNSUPPORTED,
            TYPED_ONLY_REASONS.get(
                (provider, module), "交易写操作只允许走类型化端点"
            ),
        ))
        seen.add(function)

    # 已知不支持、且不在白名单的函数。
    for function, reason in sorted(KNOWN_UNSUPPORTED.get((provider, module), {}).items()):
        if function in seen:
            continue
        unsupported.append(Capability(function, UNSUPPORTED, reason))
        seen.add(function)

    return ModuleCapability(
        module=module,
        exposed=exposed,
        supported=supported,
        unsupported=unsupported,
    )


def evaluate_ws_module(provider: str, module: str) -> Tuple[str, Optional[str]]:
    """判断模块是否允许通过 WebSocket RPC 调用。

    通道边界：TDX 没有 WebSocket RPC，只能走 HTTP。
    """
    if module not in RPC_WHITELIST:
        return UNKNOWN_MODULE, f"未知模块: {module}"

    if module not in WS_EXPOSED_MODULES.get(provider, ()):
        if provider == "tdxquant":
            return UNSUPPORTED, (
                "TDX 没有 WebSocket RPC，请使用 HTTP "
                "/api/v1/tdxquant/rpc/execute"
            )
        return UNSUPPORTED, "该模块不开放 WebSocket RPC"

    return SUPPORTED, None


def _compat_active(module: str, function: str, module_ref: Any) -> bool:
    """判断兼容实现是否真的在生效。

    代理对象暴露 ``has_real`` 时，可以区分“SDK 已恢复同名 API”和
    “仍由网关兜底”；SDK 升级后真实实现优先，兼容标记应自动消失。
    """
    if not is_compat_function(module, function):
        return False
    if module_ref is not None and hasattr(module_ref, "has_real"):
        return not module_ref.has_real(function)
    return True


def build_capability_snapshot(
    provider: str,
    module_refs: Optional[Dict[str, Any]] = None,
    probes: Optional[Dict[str, Callable[[str], Optional[bool]]]] = None,
    runtime_available: bool = True,
) -> Dict[str, Any]:
    """构建 /rpc/capabilities 的返回体。

    ``module_refs`` 用于运行时探测模块函数是否存在；没有引用时按声明清单返回。
    ``probes`` 用于无法直接 getattr 的模块（如 xttrader 实例方法）。
    """

    module_refs = module_refs or {}
    probes = probes or {}
    supported_map: Dict[str, List[str]] = {}
    unsupported_map: Dict[str, List[Dict[str, Any]]] = {}
    compat_map: Dict[str, List[str]] = {}
    count_map: Dict[str, Dict[str, int]] = {}
    verified = False

    for module in PROVIDER_MODULES.get(provider, ()):
        probe = probes.get(module)
        module_ref = module_refs.get(module)

        if probe is None and module_ref is not None:
            verified = True

            def module_probe(function: str, ref=module_ref) -> bool:
                return callable(getattr(ref, function, None))

            probe = module_probe

        result = resolve_module(provider, module, probe)
        if result.exposed:
            supported_map[module] = result.supported
            # 只有拿到运行时探测结果时才敢标记 compat；没有探测时
            # 白名单里的函数一律按“声明”处理，不能宣称兼容层已生效。
            compat_names = [
                function for function in result.supported
                if probe is not None and _compat_active(module, function, module_ref)
            ]
            if compat_names:
                compat_map[module] = compat_names
        unsupported_map[module] = [item.to_dict() for item in result.unsupported]
        count_map[module] = {
            "declared": len(RPC_WHITELIST.get(module, [])),
            "supported": len(result.supported),
            "unsupported": len(result.unsupported),
            "runtime_missing": sum(
                1 for item in result.unsupported if item.status == RUNTIME_MISSING
            ),
            "compat": len(compat_map.get(module, [])),
        }

    return {
        "provider": provider,
        "runtime": {
            "available": bool(runtime_available),
            "verified": verified,
        },
        "modules": list(RPC_EXPOSED_MODULES.get(provider, ())),
        "ws_modules": list(WS_EXPOSED_MODULES.get(provider, ())),
        "rpc": {
            "supported": supported_map,
            "unsupported": unsupported_map,
            "compat": compat_map,
            "counts": count_map,
        },
        "missing_sdk": describe_missing_sdk() if provider == "xtquant" else {},
        "ws": {
            "rpc_modules": list(WS_EXPOSED_MODULES.get(provider, ())),
            "market_data_push": False,
            "trade_event_push": False,
        },
        "typed_trade": TYPED_TRADE.get(provider, {}),
        "policy": (
            "只有 rpc.supported 中的函数可以通过 /rpc/execute 调用；"
            "unsupported 返回 NOT_SUPPORTED；未声明的函数返回 NOT_WHITELISTED；"
            "rpc.compat 中的函数由网关兼容层提供，SDK 恢复同名 API 后自动切换为真实实现。"
        ),
    }
