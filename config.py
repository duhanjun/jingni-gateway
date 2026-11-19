#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JingNiGateway 配置文件
======================

本文件包含 JingNiGateway 服务的所有配置项。

配置分类:
- 基础服务配置: API 端口、日志级别等
- xtquant 配置: MiniQMT 路径、账户信息等
- gm (掘金量化) 配置: Token、策略 ID 等

使用方法:
    from config import config
    
    # 访问配置项
    api_key = config.API_KEY
    gm_token = config.GM.token

环境变量支持:
    部分配置项支持通过环境变量覆盖，优先级: 环境变量 > 配置文件
"""

from datetime import datetime
from typing import Optional
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class GMConfig:
    """
    掘金量化 (gm) 配置类
    
    用于配置 GM 量化平台的连接参数和运行模式。
    
    Attributes:
        enabled: 是否启用 GM 模块
        token: 掘金量化 API Token
        strategy_id: 策略 ID
        account_id: 资金账户 ID
    
    Example:
        >>> gm_config = GMConfig(
        ...     enabled=True,
        ...     token="your-token",
        ...     strategy_id="your-strategy-id",
        ... )
    """
    
    def __init__(
        self,
        enabled: Optional[bool] = None,
        token: Optional[str] = None,
        strategy_id: Optional[str] = None,
        account_id: Optional[str] = None,
        gmtrade_python: Optional[str] = None,
        gmtrade_endpoint: Optional[str] = None,
    ):
        """
        初始化 GM 配置。所有凭据默认从环境变量读取，不再硬编码。

        Args:
            enabled: 是否启用 GM 模块；未显式传入时，有 token 才默认启用
            token:   从掘金量化客户端[系统设置]-[密钥管理(Token)]获取API Token
            strategy_id: 策略 ID，用于标识策略
            account_id: GM 资金账户 ID
        """
        self.token: str = token if token is not None else os.getenv("JINGNI_GM_TOKEN", "")
        self.strategy_id: str = (
            strategy_id if strategy_id is not None
            else os.getenv("JINGNI_GM_STRATEGY_ID", "")
        )
        self.account_id: str = (
            account_id if account_id is not None
            else os.getenv("JINGNI_GM_ACCOUNT_ID", "")
        )
        default_gmtrade_python = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), ".venv310", "Scripts", "python.exe"
        )
        self.gmtrade_python: str = (
            gmtrade_python if gmtrade_python is not None
            else (os.getenv("JINGNI_GMTRADE_PYTHON", "") or default_gmtrade_python)
        )
        self.gmtrade_endpoint: str = (
            gmtrade_endpoint if gmtrade_endpoint is not None
            else (os.getenv("JINGNI_GMTRADE_ENDPOINT", "") or "api.myquant.cn:9000")
        )

        env_enabled = os.getenv("JINGNI_GM_ENABLED")
        if enabled is not None:
            self.enabled = enabled
        elif env_enabled is None:
            self.enabled = bool(self.token)
        else:
            self.enabled = env_enabled.strip().lower() in ("1", "true", "yes", "on")


class TDXConfig:
    """
    TdxQuant（通达信量化）配置。

    tqcenter 直连依赖本机已启动并登录的通达信金融终端；
    account 为空时数据接口仍可用，但交易接口会拒绝调用。
    """

    def __init__(
        self,
        enabled: Optional[bool] = None,
        install_path: Optional[str] = None,
        account: Optional[str] = None,
        account_type: Optional[str] = None,
        timeout: Optional[int] = None,
        cancel_reconcile_timeout: Optional[int] = None,
        poll_interval: Optional[float] = None,
        idempotency_db: Optional[str] = None,
    ):
        self.install_path = install_path or os.getenv(
            "JINGNI_TDX_HOME", r"C:\new_tdx_mock"
        )

        env_enabled = os.getenv("JINGNI_TDX_ENABLED")
        if enabled is not None:
            self.enabled = enabled
        elif env_enabled is None:
            # 默认自动探测：安装目录存在即启用
            self.enabled = os.path.isdir(self.install_path)
        else:
            self.enabled = env_enabled.strip().lower() in ("1", "true", "yes", "on")

        self.account = (
            account if account is not None
            else os.getenv("JINGNI_TDX_ACCOUNT", "")
        )
        self.account_type = account_type or os.getenv("JINGNI_TDX_ACCOUNT_TYPE", "stock")
        self.timeout = int(timeout if timeout is not None else os.getenv("JINGNI_TDX_TIMEOUT", "30"))
        self.cancel_reconcile_timeout = int(
            cancel_reconcile_timeout if cancel_reconcile_timeout is not None
            else os.getenv("JINGNI_TDX_CANCEL_RECONCILE_TIMEOUT", "30")
        )
        self.poll_interval = float(
            poll_interval if poll_interval is not None
            else os.getenv("JINGNI_TDX_POLL_INTERVAL", "1.0")
        )
        default_idem_db = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data", "tdx_idempotency.sqlite3"
        )
        self.idempotency_db = (
            idempotency_db if idempotency_db is not None
            else os.getenv("JINGNI_TDX_IDEMPOTENCY_DB", default_idem_db)
        )


class Config:
    """
    JingNiGateway 主配置类
    
    包含服务运行所需的所有配置项。
    
    配置项说明:
        MINI_QMT_PATH: MiniQMT 客户端软件路径，xtquant 模块需要
        ACCOUNT_ID: MiniQMT 资金账户 ID
        API_KEY: API 认证密钥，客户端请求时需要携带
        API_HOST: 服务监听地址
        API_PORT: 服务监听端口
        LOG_LEVEL: 日志级别 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
        LOG_FILE: 日志文件路径
        CONNECT_TIMEOUT: xtquant 连接超时时间(秒)
        GM: 掘金量化配置对象
    
    Example:
        >>> from config import config
        >>> print(f"服务将运行在 {config.API_HOST}:{config.API_PORT}")
        >>> print(f"GM 模块启用状态: {config.GM.enabled}")
    """
    
    # ============================================
    # xtquant (迅投 QMT) 配置
    # ============================================
    
    # MiniQMT 客户端软件路径
    # 注意: 需要指向 userdata_mini 目录，xtquant 模块依赖此路径
    # Windows 示例: r"D:\gjzq\qmt\userdata_mini"
    MINI_QMT_PATH: str = r"D:\gjzq\qmt\userdata_mini"
    
    # MiniQMT 客户端资金账户
    # 必须通过 JINGNI_QMT_ACCOUNT 环境变量提供，禁止硬编码
    ACCOUNT_ID: str = ""

    # ============================================
    # API 服务配置
    # ============================================
    
    # API 认证密钥
    # 必须通过 JINGNI_API_KEY 环境变量提供；为空时服务拒绝所有受保护请求
    # 客户端请求时需在 Header 中携带: X-API-Key: your-api-key
    # 或在 URL 参数中携带: ?api_key=your-api-key
    API_KEY: str = ""
    
    # 服务监听地址
    # "0.0.0.0" 表示监听所有网络接口，允许外部访问
    # "127.0.0.1" 表示仅监听本地，只允许本机访问
    API_HOST: str = "127.0.0.1"
    
    # 服务监听端口
    # 默认 8000，如果被占用可修改为其他端口如 8080, 9000 等
    API_PORT: int = 8000
    
    # ============================================
    # 日志配置
    # ============================================
    
    # 日志级别
    # DEBUG: 最详细，包含所有调试信息
    # INFO: 一般信息，推荐日常使用
    # WARNING: 仅警告和错误
    # ERROR: 仅错误
    # CRITICAL: 仅严重错误
    LOG_LEVEL: str = "INFO"
    
    # 日志文件路径
    # 如果为相对路径，则相对于项目根目录
    # 设置为 None 或空字符串则不写入文件，仅输出到控制台
    LOG_FILE: str = "xtquant_proxy.log"
    
    # ============================================
    # xtquant 连接配置
    # ============================================
    
    # xtquant 连接超时时间（秒）
    # 连接 QMT 客户端时的最大等待时间
    CONNECT_TIMEOUT: int = 30
    
    # ============================================
    # gm (掘金量化) 配置
    # ============================================
    
    # GM 配置对象
    # 详细配置见 GMConfig 类；token/strategy/account 全部从环境变量读取
    GM: GMConfig = GMConfig()

    # ============================================
    # tdxquant (通达信量化) 配置
    # ============================================

    TDX: TDXConfig = TDXConfig()
    
    # ============================================
    # 高级配置 (一般不需要修改)
    # ============================================
    
    # WebSocket 心跳间隔（秒）
    # 用于检测客户端连接状态
    WS_HEARTBEAT_INTERVAL: int = 30
    
    # RPC 调用默认超时时间（秒）
    # 单个 RPC 调用的最大执行时间
    RPC_DEFAULT_TIMEOUT: int = 30
    
    # 最大并发连接数
    # WebSocket 最大客户端连接数
    MAX_CONNECTIONS: int = 100


# 全局配置实例
# 在项目中通过以下方式导入使用:
#   from config import config
#   print(config.API_KEY)
config = Config()


# 环境变量覆盖支持
# 允许通过环境变量覆盖部分配置，优先级: 环境变量 > 配置文件
def _load_env_config():
    """从环境变量加载配置覆盖"""
    if os.getenv("JINGNI_API_KEY"):
        config.API_KEY = os.getenv("JINGNI_API_KEY")

    if os.getenv("JINGNI_API_HOST"):
        config.API_HOST = os.getenv("JINGNI_API_HOST")

    if os.getenv("JINGNI_API_PORT"):
        config.API_PORT = int(os.getenv("JINGNI_API_PORT"))

    if os.getenv("JINGNI_LOG_LEVEL"):
        config.LOG_LEVEL = os.getenv("JINGNI_LOG_LEVEL")

    if os.getenv("JINGNI_QMT_PATH"):
        config.MINI_QMT_PATH = os.getenv("JINGNI_QMT_PATH")

    if os.getenv("JINGNI_QMT_ACCOUNT"):
        config.ACCOUNT_ID = os.getenv("JINGNI_QMT_ACCOUNT")

    if os.getenv("JINGNI_GM_TOKEN"):
        config.GM.token = os.getenv("JINGNI_GM_TOKEN")

    if os.getenv("JINGNI_GM_STRATEGY_ID"):
        config.GM.strategy_id = os.getenv("JINGNI_GM_STRATEGY_ID")

    if os.getenv("JINGNI_GM_ACCOUNT_ID"):
        config.GM.account_id = os.getenv("JINGNI_GM_ACCOUNT_ID")

    if os.getenv("JINGNI_GM_ENABLED"):
        config.GM.enabled = os.getenv("JINGNI_GM_ENABLED").strip().lower() in (
            "1", "true", "yes", "on"
        )


# 加载环境变量配置
_load_env_config()
