"""
数据源提供者基类模块。

本模块定义了量化数据源提供者的基类和通用工具函数。

类说明：
    BaseProvider: 数据源提供者抽象基类

函数说明：
    serialize_data: 通用数据序列化函数

类说明：
    SymbolConverter: 股票代码格式转换器
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
import logging
import math

logger = logging.getLogger(__name__)


class BaseProvider(ABC):
    """
    量化数据源提供者基类。
    
    所有数据源提供者（如 XtQuant、GM）都应继承此类并实现所有抽象方法。
    
    属性：
        name: 提供者名称
        is_available: 是否可用
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """获取提供者名称。"""
        pass
    
    @property
    @abstractmethod
    def is_available(self) -> bool:
        """检查提供者是否可用。"""
        pass
    
    @abstractmethod
    def initialize(self) -> bool:
        """初始化提供者。"""
        pass
    
    @abstractmethod
    def cleanup(self):
        """清理提供者资源。"""
        pass
    
    @abstractmethod
    def get_rpc_whitelist(self) -> Dict[str, List[str]]:
        """获取 RPC 函数白名单。"""
        pass
    
    @abstractmethod
    def get_module_reference(self, module_name: str):
        """获取模块引用。"""
        pass


def serialize_data(data: Any) -> Any:
    """
    通用数据序列化函数。
    
    将各种数据类型转换为可 JSON 序列化的格式。
    支持 DataFrame、Series、ndarray、NaN、Inf 等特殊类型。
    
    参数：
        data: 要序列化的数据
    
    返回：
        可 JSON 序列化的数据
    """
    if data is None:
        return None
    
    if isinstance(data, (str, int, bool, type(None))):
        return data
    
    if isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return None
        return data
    
    if isinstance(data, dict):
        return {k: serialize_data(v) for k, v in data.items()}
    
    if isinstance(data, (list, tuple)):
        return [serialize_data(item) for item in data]
    
    if hasattr(data, 'strftime'):
        return data.strftime('%Y-%m-%d %H:%M:%S')
    
    try:
        import pandas as pd
        import numpy as np
        
        if isinstance(data, pd.DataFrame):
            records = data.to_dict('records')
            cleaned_records = []
            for record in records:
                cleaned_record = {}
                for k, v in record.items():
                    if isinstance(v, float):
                        if np.isnan(v) or np.isinf(v):
                            cleaned_record[k] = None
                        else:
                            cleaned_record[k] = v
                    elif isinstance(v, (pd.Timestamp, datetime)):
                        cleaned_record[k] = v.strftime('%Y-%m-%d %H:%M:%S') if hasattr(v, 'strftime') else str(v)
                    else:
                        cleaned_record[k] = serialize_data(v)
                cleaned_records.append(cleaned_record)
            
            return {
                '__type__': 'DataFrame',
                'columns': list(data.columns),
                'data': cleaned_records,
                'shape': list(data.shape)
            }
        
        if isinstance(data, pd.Series):
            return {
                '__type__': 'Series',
                'data': [serialize_data(v) for v in data.tolist()],
                'index': [str(i) for i in data.index.tolist()]
            }
        
        if isinstance(data, np.ndarray):
            return {
                '__type__': 'ndarray',
                'data': serialize_data(data.tolist()),
                'shape': list(data.shape),
                'dtype': str(data.dtype)
            }
        
        if isinstance(data, (np.integer,)):
            return int(data)
        
        if isinstance(data, (np.floating,)):
            if np.isnan(data) or np.isinf(data):
                return None
            return float(data)
            
    except ImportError:
        pass
    
    if hasattr(data, '__class__') and not isinstance(data, (dict, list, str, int, float, bool)):
        attrs = {}
        for attr in dir(data):
            if not attr.startswith('_') and not callable(getattr(data, attr, None)):
                try:
                    value = getattr(data, attr)
                    if not callable(value):
                        attrs[attr] = serialize_data(value)
                except Exception:
                    pass
        
        if attrs:
            return {
                '__type__': type(data).__name__,
                'attributes': attrs
            }
    
    if hasattr(data, '__dict__'):
        return {k: serialize_data(v) for k, v in data.__dict__.items()}
    
    try:
        return str(data)
    except Exception:
        return f"<不可序列化: {type(data).__name__}>"


class SymbolConverter:
    """
    股票代码格式转换器。
    
    用于在 xtquant 和 GM 两种格式之间转换股票代码。
    
    格式说明：
        xtquant 格式: 000001.SZ
        GM 格式: SZSE.000001
    """
    
    EXCHANGE_MAP_XTQUANT_TO_GM = {
        'SZ': 'SZSE',
        'SH': 'SHSE',
        'BJ': 'BJSE'
    }
    
    EXCHANGE_MAP_GM_TO_XTQUANT = {
        'SZSE': 'SZ',
        'SHSE': 'SH',
        'BJSE': 'BJ'
    }
    
    @classmethod
    def xtquant_to_gm(cls, symbol: str) -> str:
        """
        将 xtquant 格式的股票代码转换为 GM 格式。
        
        参数：
            symbol: xtquant 格式的股票代码（如 000001.SZ）
        
        返回：
            GM 格式的股票代码（如 SZSE.000001）
        
        示例：
            >>> SymbolConverter.xtquant_to_gm("000001.SZ")
            'SZSE.000001'
        """
        if '.' in symbol:
            parts = symbol.split('.')
            if len(parts) == 2:
                code, exchange = parts
                gm_exchange = cls.EXCHANGE_MAP_XTQUANT_TO_GM.get(exchange, exchange)
                return f"{gm_exchange}.{code}"
        return symbol
    
    @classmethod
    def gm_to_xtquant(cls, symbol: str) -> str:
        """
        将 GM 格式的股票代码转换为 xtquant 格式。
        
        参数：
            symbol: GM 格式的股票代码（如 SZSE.000001）
        
        返回：
            xtquant 格式的股票代码（如 000001.SZ）
        
        示例：
            >>> SymbolConverter.gm_to_xtquant("SZSE.000001")
            '000001.SZ'
        """
        if '.' in symbol:
            parts = symbol.split('.')
            if len(parts) == 2:
                exchange, code = parts
                xt_exchange = cls.EXCHANGE_MAP_GM_TO_XTQUANT.get(exchange, exchange)
                return f"{code}.{xt_exchange}"
        return symbol
    
    @classmethod
    def convert_symbols(cls, symbols: List[str], to_format: str) -> List[str]:
        """
        批量转换股票代码格式。
        
        参数：
            symbols: 股票代码列表
            to_format: 目标格式，"gm" 或 "xtquant"
        
        返回：
            转换后的股票代码列表
        """
        if to_format == "gm":
            return [cls.xtquant_to_gm(s) for s in symbols]
        elif to_format == "xtquant":
            return [cls.gm_to_xtquant(s) for s in symbols]
        return symbols
