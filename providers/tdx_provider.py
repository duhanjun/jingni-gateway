"""
TdxQuant（通达信量化）数据源提供者。

只使用 tqcenter 直连，不包含 HTTP 17709 通道。
设计约束：
- import 与 initialize 分离：启动时只加载模块，首次调用时才 tq.initialize；
- 所有 TQ 调用应通过 core.executor 的串行执行器（module="tdxquant"）；
- 账户句柄缓存，句柄失效时显式重置。
"""

import logging
import os
import sys
import threading
from typing import Any, Dict, List, Optional

from .base import BaseProvider
from core.whitelist import RPC_WHITELIST

logger = logging.getLogger(__name__)


class TdxError(RuntimeError):
    """TdxQuant 调用错误基类。"""


class TdxUnavailableError(TdxError):
    """tqcenter 不可用（未启用、模块缺失、初始化失败）。"""


class TdxConfigError(TdxError):
    """配置缺失（如未配置资金账户）。"""


class TdxProvider(BaseProvider):
    """tqcenter 直连提供者。"""

    def __init__(self, config):
        self._config = config
        self._tdx_config = getattr(config, "TDX", None)
        self._tq = None
        self._available = False
        self._initialized = False
        self._account_handle: Optional[int] = None
        self._lock = threading.RLock()
        self._rpc_whitelist = {
            "tdxdata": RPC_WHITELIST.get("tdxdata", []),
            "tdxtrade": RPC_WHITELIST.get("tdxtrade", []),
        }

    @property
    def name(self) -> str:
        return "tdxquant"

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def is_enabled(self) -> bool:
        return bool(self._tdx_config and self._tdx_config.enabled)

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def account_configured(self) -> bool:
        return bool(self._tdx_config and self._tdx_config.account)

    def initialize(self) -> bool:
        """加载 tqcenter 模块；不建立连接，不调用 tq.initialize。"""
        if not self.is_enabled:
            logger.info("tdxquant 未启用（JINGNI_TDX_ENABLED=0）")
            return False

        if self._available:
            return True

        install_path = self._tdx_config.install_path
        plugin_path = os.path.join(install_path, "PYPlugins", "user")
        if not os.path.isdir(plugin_path):
            logger.warning("tqcenter 插件目录不存在: %s", plugin_path)
            return False

        if plugin_path not in sys.path:
            sys.path.append(plugin_path)

        try:
            from tqcenter import tq  # noqa: WPS433 - 运行时按安装目录加载
        except Exception as exc:
            logger.warning("tqcenter 加载失败: %s", exc)
            return False

        self._tq = tq
        self._available = True
        logger.info("tqcenter 模块加载成功: %s", plugin_path)
        return True

    def ensure_initialized(self):
        """确保 tq.initialize 已执行，返回 tq 模块。"""
        with self._lock:
            if not self._available and not self.initialize():
                raise TdxUnavailableError(
                    "tqcenter 不可用：请确认终端已启动、安装路径与 JINGNI_TDX_ENABLED 配置正确"
                )
            if not self._initialized:
                self._tq.initialize(__file__)
                self._initialized = True
                logger.info("tqcenter 初始化完成")
            return self._tq

    def account_handle(self) -> int:
        """获取并缓存资金账号句柄。"""
        cfg = self._tdx_config
        if not cfg or not cfg.account:
            raise TdxConfigError("未配置资金账户（JINGNI_TDX_ACCOUNT）")

        tq = self.ensure_initialized()
        with self._lock:
            if self._account_handle is None or self._account_handle < 0:
                handle = tq.stock_account(
                    account=cfg.account,
                    account_type=cfg.account_type,
                )
                if not isinstance(handle, int) or handle < 0:
                    raise TdxError(f"获取账户句柄失败: {handle!r}")
                self._account_handle = handle
                logger.info("账户句柄已缓存: %s", handle)
            return self._account_handle

    def reset_account_handle(self) -> None:
        with self._lock:
            self._account_handle = None

    def probe_account(self) -> Dict[str, Any]:
        """
        探测账户是否真正登录且有资产数据。

        未登录时 stock_account 仍可能返回句柄，query_stock_asset 返回
        {"ErrorId":"0","Value":[]}，因此必须检查 Cash 字段是否存在。
        """
        if not self.account_configured:
            return {"logged_in": False, "reason": "未配置 JINGNI_TDX_ACCOUNT"}

        try:
            tq = self.ensure_initialized()
            handle = self.account_handle()
            asset = tq.query_stock_asset(handle)
        except TdxConfigError as exc:
            return {"logged_in": False, "reason": str(exc)}
        except TdxUnavailableError as exc:
            return {"logged_in": False, "reason": str(exc)}
        except Exception as exc:  # pragma: no cover - 终端异常兜底
            return {"logged_in": False, "reason": f"账户探测失败: {exc}"}

        if not isinstance(asset, dict):
            return {"logged_in": False, "reason": "资产返回格式异常", "raw": asset}

        if asset.get("ErrorId", "0") != "0":
            return {
                "logged_in": False,
                "reason": f"资产查询失败: {asset.get('Msg') or asset.get('ErrorId')}",
                "raw": asset,
            }

        if "Cash" not in asset or asset.get("Cash") is None:
            return {
                "logged_in": False,
                "reason": "账户未登录或资产为空",
                "raw": asset,
            }

        return {
            "logged_in": True,
            "account_handle": handle,
            "cash": asset.get("Cash"),
        }

    def get_module_reference(self, module_name: str):
        if module_name in ("tdxdata", "tdxtrade"):
            if not self._available and not self.initialize():
                raise TdxUnavailableError("tqcenter 不可用")
            return self._tq
        return None

    def get_rpc_whitelist(self) -> Dict[str, List[str]]:
        return self._rpc_whitelist

    def is_function_whitelisted(self, module: str, function: str) -> bool:
        if module not in self._rpc_whitelist:
            return False
        return function in self._rpc_whitelist[module]

    def get_version(self) -> str:
        if not self._available:
            return "unavailable"
        version = getattr(self._tq, "__version__", None)
        return f"tqcenter {version}" if version else "tqcenter loaded"

    def health(self) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "enabled": self.is_enabled,
            "available": self.is_available,
            "initialized": self.is_initialized,
            "account_configured": self.account_configured,
            "version": self.get_version(),
        }

    def cleanup(self) -> None:
        with self._lock:
            if self._initialized and self._tq is not None:
                try:
                    self._tq.close()
                except Exception as exc:
                    logger.warning("tq.close() 失败: %s", exc)
            self._initialized = False
            self._account_handle = None
