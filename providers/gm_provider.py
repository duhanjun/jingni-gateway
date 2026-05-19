"""
GM (掘金量化) 数据源提供者模块。

本模块实现了 GM (掘金量化) 平台的数据源提供者。

类说明：
    GMProvider: GM 数据源提供者实现类
"""

from .base import BaseProvider, serialize_data, SymbolConverter
from typing import Dict, Any, List
import logging

from core.whitelist import RPC_WHITELIST

logger = logging.getLogger(__name__)


class GMProvider(BaseProvider):
    """
    GM (掘金量化) 数据源提供者实现类。
    
    本类封装了 GM 量化平台的 API，提供统一的数据访问接口。
    
    属性：
        name: 提供者名称 ("gm")
        is_available: GM 模块是否可用
    """

    def __init__(self, config):
        """
        初始化 GM 提供者。
        
        参数：
            config: 配置对象
        """
        self._config = config
        self._api = None
        self._available = False
        self._token_set = False
        self._rpc_whitelist = {
            "gmdata": RPC_WHITELIST.get("gmdata", []),
            "gmtrade": RPC_WHITELIST.get("gmtrade", [])
        }

    @property
    def name(self) -> str:
        """获取提供者名称。"""
        return "gm"

    @property
    def is_available(self) -> bool:
        """检查 GM 模块是否可用。"""
        return self._available

    def initialize(self) -> bool:
        """
        初始化 GM 模块。
        
        尝试加载 GM API 并设置 Token。
        
        返回：
            初始化成功返回 True，否则返回 False
        """
        try:
            import gm.api as api
            self._api = api
            self._available = True
            logger.info("gm.api 模块加载成功")

            if hasattr(self._config, 'GM'):
                if self._config.GM.token:
                    self._api.set_token(self._config.GM.token)
                    self._token_set = True
                    logger.info("GM Token 已设置")
                else:
                    logger.warning("GM Token 未配置，部分功能可能不可用")

                if self._config.GM.account_id:
                    self._api.set_account_id(self._config.GM.account_id)
                    logger.info(f"GM 账户 ID 已设置: {self._config.GM.account_id}")

                mode = getattr(self._config.GM, 'mode', None)
                if mode:
                    logger.info(f"GM 运行模式: {mode}")
            else:
                logger.warning("GM 配置未找到，部分功能可能不可用")

            return True

        except ImportError as e:
            logger.warning(f"GM 模块导入失败: {e}")
            self._available = False
            return False

    def cleanup(self):
        """清理资源。"""
        pass

    def get_rpc_whitelist(self) -> Dict[str, List[str]]:
        """获取 RPC 函数白名单。"""
        return self._rpc_whitelist

    def get_module_reference(self, module_name: str):
        """
        根据名称获取模块引用。
        
        参数：
            module_name: 模块名称 (gmdata, gmtrade)
        
        返回：
            模块引用，如果不可用则返回 None
        """
        if not self._available:
            return None

        if module_name in ("gmdata", "gmtrade"):
            return self._api
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
        获取 GM 版本信息。
        
        返回：
            GM 版本字符串
        """
        if self._available and self._api:
            return self._api.get_version()
        return "未知"

    @staticmethod
    def convert_symbol_to_gm(symbol: str) -> str:
        """
        将股票代码转换为 GM 格式。
        
        参数：
            symbol: 原始股票代码
        
        返回：
            GM 格式的股票代码
        """
        return SymbolConverter.xtquant_to_gm(symbol)

    @staticmethod
    def convert_symbol_to_xtquant(symbol: str) -> str:
        """
        将股票代码转换为 xtquant 格式。
        
        参数：
            symbol: GM 格式的股票代码
        
        返回：
            xtquant 格式的股票代码
        """
        return SymbolConverter.gm_to_xtquant(symbol)

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
