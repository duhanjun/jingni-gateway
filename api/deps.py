"""
API 认证依赖模块。

本模块提供 API Key 认证功能，支持通过 HTTP Header 和 Query 参数两种方式传递 API Key。

类说明：
    api_key_header: HTTP Header 方式的 API Key 提取器
    api_key_query: Query 参数方式的 API Key 提取器

函数说明：
    get_api_key: 获取并验证 API Key
    get_api_key_dependency: 获取 FastAPI 依赖项
"""

import hmac

from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader, APIKeyQuery

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
api_key_query = APIKeyQuery(name="api_key", auto_error=False)


async def get_api_key(
    header_key: str = Depends(api_key_header),
    query_key: str = Depends(api_key_query)
) -> str:
    """
    获取并验证 API Key。
    
    从 HTTP Header 或 Query 参数中获取 API Key 并验证其有效性。
    
    参数：
        header_key: HTTP Header 中的 API Key
        query_key: Query 参数中的 API Key
    
    返回：
        验证通过的 API Key
    
    异常：
        HTTPException: API Key 无效时抛出 401 错误
    """
    from config import config

    if not config.API_KEY:
        raise HTTPException(
            status_code=503,
            detail="服务未配置 API Key，请设置 JINGNI_API_KEY 环境变量后重启",
        )

    api_key = header_key or query_key
    if not api_key or not hmac.compare_digest(api_key, config.API_KEY):
        raise HTTPException(status_code=401, detail="无效的 API Key")
    return api_key


def get_api_key_dependency():
    """
    获取 API Key 验证的 FastAPI 依赖项。
    
    返回：
        FastAPI Depends 对象
    """
    return Depends(get_api_key)
