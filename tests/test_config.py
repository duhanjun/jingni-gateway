#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JingNiGateway测试配置文件
统一从 config.py 导入测试所需的配置变量
提供测试输出格式化工具
"""

import sys
import os
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config

# ============================================================================
# 测试配置 - 全部从 config.py 导入
# ============================================================================

# API 认证配置
TEST_API_KEY = config.API_KEY
TEST_HEADERS = {"X-API-Key": TEST_API_KEY}

# 测试账户配置
TEST_ACCOUNT = config.ACCOUNT_ID if hasattr(config, 'ACCOUNT_ID') else "123456789"

# 测试股票配置
TEST_STOCK = "000001.SZ"  # 平安银行
TEST_STOCK_LIST = ["000001.SZ", "600000.SH"]  # 平安银行、浦发银行

# 测试交易配置
TEST_PRICE = 10.0
TEST_VOLUME = 100

# WebSocket 测试配置
TEST_CLIENT_ID = "test_client"

# 服务器配置
TEST_API_HOST = config.API_HOST
TEST_API_PORT = config.API_PORT
TEST_BASE_URL = f"http://{TEST_API_HOST}:{TEST_API_PORT}"

# 日志配置
TEST_LOG_LEVEL = config.LOG_LEVEL

# 连接超时配置
TEST_CONNECT_TIMEOUT = config.CONNECT_TIMEOUT

# ============================================================================
# GM (掘金量化) 配置 - 从 config.py 导入
# ============================================================================

# GM Token
TEST_GM_TOKEN = config.GM.token

# GM 策略 ID
TEST_GM_STRATEGY_ID = config.GM.strategy_id

# GM 账户 ID
TEST_GM_ACCOUNT = config.GM.account_id

# GM 运行模式
TEST_GM_MODE = getattr(config.GM, 'mode', None)

# GM 测试股票代码 (GM 格式)
TEST_GM_SYMBOL = "SZSE.002594"  # 比亚迪
TEST_GM_SYMBOL_LIST = ["SZSE.002594", "SHSE.600000"]

# ============================================================================
# 打印测试配置信息（调试用）
# ============================================================================

def print_test_config():
    """打印测试配置信息"""
    print("="*60)
    print("测试配置")
    print("="*60)
    print(f"API Key: {TEST_API_KEY}")
    print(f"测试账户：{TEST_ACCOUNT}")
    print(f"测试股票：{TEST_STOCK}")
    print(f"测试股票列表：{TEST_STOCK_LIST}")
    print(f"测试价格：{TEST_PRICE}")
    print(f"测试数量：{TEST_VOLUME}")
    print(f"API 主机：{TEST_API_HOST}")
    print(f"API 端口：{TEST_API_PORT}")
    print(f"基础 URL: {TEST_BASE_URL}")
    print("-"*60)
    print("GM 配置 (从 config.py 导入):")
    print(f"  GM Token: {TEST_GM_TOKEN[:10]}..." if TEST_GM_TOKEN else "  GM Token: 未配置")
    print(f"  GM 策略ID: {TEST_GM_STRATEGY_ID}")
    print(f"  GM 账户: {TEST_GM_ACCOUNT}")
    print(f"  GM 模式: {TEST_GM_MODE}")
    print(f"  GM 测试股票: {TEST_GM_SYMBOL}")
    print("="*60)


# ============================================================================
# 测试输出格式化工具（从 test_output.py 整合）
# ============================================================================

def print_separator(char: str = "=", length: int = 60):
    """打印分隔线"""
    print(char * length)


def print_test_header(test_name: str, description: str = "", test_file: str = ""):
    """打印测试标题"""
    print()
    print_separator()
    print(f"测试开始：{test_name} - {description}")
    if test_file:
        print(f"测试文件：{test_file}")
    print()


def print_test_result(test_num: int, test_name: str, passed: bool, message: str = ""):
    """
    打印测试结果
    
    Args:
        test_num: 测试序号
        test_name: 测试名称
        passed: 是否通过
        message: 附加消息
    """
    status = "✓ 通过" if passed else "✗ 失败"
    status_code = "通过" if passed else "失败"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    print()
    print(f"[{test_num:02d}] {status} - {test_name}")
    print(f"测试时间：{timestamp}")
    if message:
        print(f"测试结果：{message}")


def print_data_summary(title: str, data, max_length: int = 300):
    """
    打印数据概要信息
    
    Args:
        title: 标题
        data: 数据
        max_length: 字段值最大长度
    """
    print()
    print_separator()
    print(f"{title}")
    print_separator()
    
    if not data:
        print("数据为空")
        print_separator()
        return
    
    # 检查是否是字典（RPC 返回的数据）
    if isinstance(data, dict):
        print(f"数据类型：字典")
        for key, value in data.items():
            value_str = str(value)
            if len(value_str) > max_length:
                value_str = value_str[:max_length] + "..."
            print(f"  {key}: {value_str}")
    
    # 检查是否是列表
    elif isinstance(data, list):
        print(f"数据类型：列表")
        print(f"元素数量：{len(data)}")
        if len(data) > 0:
            print(f"\n前 5 个元素：")
            for i, item in enumerate(data[:5]):
                if isinstance(item, dict):
                    item_str = str(item)[:max_length]
                    if len(str(item)) > max_length:
                        item_str += "..."
                    print(f"  [{i}] dict: {item_str}")
                else:
                    item_str = str(item)
                    if len(item_str) > max_length:
                        item_str = item_str[:max_length] + "..."
                    print(f"  [{i}] {type(item).__name__}: {item_str}")
    
    else:
        print(f"数据类型：{type(data).__name__}")
        print(f"值：{str(data)[:max_length]}")
    
    print_separator()
    print()


def print_test_summary(total: int, passed: int, failed: int):
    """
    打印测试摘要
    
    Args:
        total: 总测试数
        passed: 通过数
        failed: 失败数
    """
    print()
    print_separator("=")
    print(f"测试摘要")
    print_separator("=")
    print(f"总测试数：{total}")
    print(f"✓ 通过：{passed}")
    print(f"✗ 失败：{failed}")
    success_rate = (passed / total * 100) if total > 0 else 0
    print(f"成功率：{success_rate:.1f}%")
    print_separator("=")


# 测试计数器（用于自动编号）
_test_counter = 0


def _print_result(test_name: str, passed: bool, message: str = "", test_file: str = ""):
    """打印测试结果（带自动编号）"""
    global _test_counter
    _test_counter += 1
    status = "[通过]" if passed else "[失败]"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    print()
    print("=" * 60)
    print(f"[{_test_counter:02d}] {status} - {test_name}")
    print(f"测试时间：{timestamp}")
    if message:
        print(f"测试结果：{message}")
    if test_file:
        print(f"测试文件：{test_file}") 
    print("=" * 60)


def reset_test_counter():
    """重置测试计数器"""
    global _test_counter
    _test_counter = 0


# 初始化 RPC 模块
try:
    from core.rpc import initialize_modules
    initialize_modules()
except Exception as e:
    print(f"[警告] 初始化 RPC 模块失败：{e}")


if __name__ == "__main__":
    print_test_config()
