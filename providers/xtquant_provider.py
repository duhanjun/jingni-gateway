"""
XtQuant (迅投QMT) 数据源提供者模块。

本模块实现了 XtQuant (迅投QMT) 平台的数据源提供者。

类说明：
    XtQuantProvider: XtQuant 数据源提供者实现类
"""

from .base import BaseProvider, serialize_data, SymbolConverter
from typing import Dict, Any, List
import logging

from core.sdk_compat import wrap_xtdata
from core.whitelist import RPC_WHITELIST

logger = logging.getLogger(__name__)


class XtQuantProvider(BaseProvider):
    """
    XtQuant (迅投QMT) 数据源提供者实现类。
    
    本类封装了 XtQuant 量化平台的 API，提供统一的数据访问接口。
    
    属性：
        name: 提供者名称 ("xtquant")
        is_available: XtQuant 模块是否可用
        is_xtdata_available: xtdata 模块是否可用
        is_xttrader_available: xttrader 模块是否可用
    """

    def __init__(self, config):
        """
        初始化 XtQuant 提供者。
        
        参数：
            config: 配置对象
        """
        self._config = config
        self._xtdata = None
        self._xttrader = None
        self._xtdata_available = False
        self._xttrader_available = False
        self._trader_instance = None
        self._rpc_whitelist = {
            "xtdata": RPC_WHITELIST.get("xtdata", []),
            "xttrader": RPC_WHITELIST.get("xttrader", [])
        }

    @property
    def name(self) -> str:
        """获取提供者名称。"""
        return "xtquant"

    @property
    def is_available(self) -> bool:
        """检查 XtQuant 模块是否可用。"""
        return self._xtdata_available or self._xttrader_available

    @property
    def is_xtdata_available(self) -> bool:
        """检查 xtdata 模块是否可用。"""
        return self._xtdata_available

    @property
    def is_xttrader_available(self) -> bool:
        """检查 xttrader 模块是否可用。"""
        return self._xttrader_available

    def initialize(self) -> bool:
        """
        初始化 XtQuant 模块。
        
        尝试加载 xtdata 和 xttrader 模块。
        
        返回：
            初始化成功返回 True，否则返回 False
        """
        try:
            from xtquant import xtdata
            compat_enabled = bool(getattr(self._config, "XT_SDK_COMPAT", True))
            self._xtdata = wrap_xtdata(xtdata, enabled=compat_enabled)
            self._xtdata_available = True
            logger.info("xtquant.xtdata 模块加载成功")
        except ImportError as e:
            logger.warning(f"xtquant.xtdata 模块导入失败: {e}")
            self._xtdata_available = False

        try:
            from xtquant import xttrader
            from xtquant.xttrader import XtQuantTraderCallback
            from xtquant.xttype import StockAccount
            from xtquant import xtconstant
            self._xttrader = xttrader
            self._xttrader_available = True
            logger.info("xtquant.xttrader 模块加载成功")
        except ImportError as e:
            logger.warning(f"xtquant.xttrader 模块导入失败: {e}")
            self._xttrader_available = False

        return self._xtdata_available or self._xttrader_available

    def cleanup(self):
        """清理资源。"""
        if self._trader_instance:
            try:
                self._trader_instance.stop()
            except Exception as e:
                logger.error(f"停止 xttrader 失败: {e}")
            self._trader_instance = None

    def get_rpc_whitelist(self) -> Dict[str, List[str]]:
        """获取 RPC 函数白名单。"""
        return self._rpc_whitelist

    def get_module_reference(self, module_name: str):
        """
        根据名称获取模块引用。
        
        参数：
            module_name: 模块名称 (xtdata, xttrader)
        
        返回：
            模块引用，如果不可用则返回 None
        """
        if not self.is_available:
            return None

        if module_name == "xtdata":
            return self._xtdata
        elif module_name == "xttrader":
            return self._xttrader
        else:
            return None

    def is_function_whitelisted(self, module: str, function: str) -> bool:
        """
        检查函数是否在白名单中。
        
        参数：
            module: 模块名称
            function: 函数名称
        
        返回：
            在白名单中返回 True，否则返回 False
        """
        if module not in self._rpc_whitelist:
            return False
        return function in self._rpc_whitelist[module]

    def get_version(self) -> str:
        """
        获取 XtQuant 版本信息。
        
        返回：
            版本信息字符串
        """
        versions = []
        if self._xtdata_available and self._xtdata:
            versions.append("xtdata: 可用")
        if self._xttrader_available and self._xttrader:
            versions.append("xttrader: 可用")
        return ", ".join(versions) if versions else "不可用"

    def create_trader(self, account: str, account_type: str = "STOCK"):
        """
        创建交易实例。

        统一委托给 ``core.rpc.create_xttrader_instance``，避免在 provider 内
        保留第二套构造逻辑（历史实现用三参 XtQuantTrader，且 session_id 取
        ``int(account)``，非纯数字账户会直接失败）。

        参数：
            account: 账户 ID
            account_type: 账户类型，默认为 "STOCK"

        返回：
            包含创建结果的字典
        """
        from core.rpc import create_xttrader_instance

        return create_xttrader_instance(account, account_type=account_type)

    @staticmethod
    def convert_symbol_to_xtquant(symbol: str) -> str:
        """
        将股票代码转换为 xtquant 格式。
        
        参数：
            symbol: 原始股票代码
        
        返回：
            xtquant 格式的股票代码
        """
        return SymbolConverter.gm_to_xtquant(symbol)

    @staticmethod
    def convert_symbol_from_xtquant(symbol: str) -> str:
        """
        将 xtquant 格式的股票代码转换为其他格式。
        
        参数：
            symbol: xtquant 格式的股票代码
        
        返回：
            转换后的股票代码
        """
        return SymbolConverter.xtquant_to_gm(symbol)

    @staticmethod
    def convert_symbols(symbols: List[str], to_format: str) -> List[str]:
        """
        批量转换股票代码格式。
        
        参数：
            symbols: 股票代码列表
            to_format: 目标格式
        
        返回：
            转换后的股票代码列表
        """
        return SymbolConverter.convert_symbols(symbols, to_format)
