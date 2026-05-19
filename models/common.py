"""
通用数据模型模块。

本模块定义了 API 请求和响应的 Pydantic 数据模型。

类说明：
    RpcExecuteRequest: RPC 执行请求模型
    SymbolConvertRequest: 股票代码转换请求模型
"""

from pydantic import BaseModel
from typing import List, Dict, Any, Optional


class RpcExecuteRequest(BaseModel):
    """
    RPC 执行请求模型。
    
    用于封装远程过程调用的请求参数。
    
    属性：
        module: 模块名称 (xtdata, xttrader, gmdata, gmtrade)
        function: 要调用的函数名称
        args: 位置参数列表
        kwargs: 关键字参数字典
        timeout: 执行超时时间（秒）
    
    示例：
        >>> request = RpcExecuteRequest(
        ...     module="xtdata",
        ...     function="get_market_data",
        ...     kwargs={"stock_list": ["000001.SZ"], "period": "1d"}
        ... )
    """
    module: str
    function: str
    args: List[Any] = []
    kwargs: Dict[str, Any] = {}
    timeout: Optional[int] = 30


class SymbolConvertRequest(BaseModel):
    """
    股票代码转换请求模型。
    
    用于在不同股票代码格式之间进行转换。
    
    属性：
        symbols: 要转换的股票代码列表
        to_format: 目标格式，"gm" 或 "xtquant"
    
    示例：
        >>> request = SymbolConvertRequest(
        ...     symbols=["000001.SZ", "600000.SH"],
        ...     to_format="gm"
        ... )
    """
    symbols: List[str]
    to_format: str = "gm"
