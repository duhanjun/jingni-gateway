"""
API 路由模块。

本模块导出所有 API 路由和依赖项。

导出内容：
    gm_router: GM (掘金量化) API 路由
    xtquant_router: XtQuant (迅投QMT) API 路由
    get_api_key: API Key 验证函数
    get_api_key_dependency: FastAPI 依赖项
"""

from .gm import router as gm_router
from .xtquant import router as xtquant_router
from .deps import get_api_key, get_api_key_dependency

__all__ = ['gm_router', 'xtquant_router', 'get_api_key', 'get_api_key_dependency']
