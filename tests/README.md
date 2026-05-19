# JingNiGateway 测试文档

## 📋 测试概述

本测试套件为 JingNiGateway 量化数据网关服务提供全面的功能验证，覆盖 HTTP API、WebSocket 连接、数据接口和交易接口等核心功能。

## 📁 测试文件结构

```
tests/
├── __init__.py              # 测试包初始化
├── test_config.py           # 测试配置和工具函数
├── test_api_health.py       # API 健康检查测试
├── test_api_websocket.py    # WebSocket 连接测试
├── test_xtquant_data.py     # XtQuant 数据接口测试
├── test_xtquant_trader.py   # XtQuant 交易接口测试
├── test_gm_data.py          # GM 数据接口测试
└── test_gm_trader.py        # GM 交易接口测试
```

## 🚀 快速开始

### 环境要求

- Python 3.8+
- pytest >= 7.0
- requests >= 2.28
- websockets >= 10.0

### 安装测试依赖

```bash
pip install pytest requests websockets
```

### 运行所有测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行并显示详细输出
pytest tests/ -v -s

# 生成覆盖率报告
pytest tests/ --cov=. --cov-report=html
```

### 运行特定测试文件

```bash
# API 健康检查
pytest tests/test_api_health.py -v

# WebSocket 测试
pytest tests/test_api_websocket.py -v

# XtQuant 数据接口
pytest tests/test_xtquant_data.py -v

# XtQuant 交易接口
pytest tests/test_xtquant_trader.py -v

# GM 数据接口
pytest tests/test_gm_data.py -v

# GM 交易接口
pytest tests/test_gm_trader.py -v
```

### 运行特定测试用例

```bash
# 运行特定测试类
pytest tests/test_xtquant_data.py::TestXtQuantMarketData -v

# 运行特定测试方法
pytest tests/test_xtquant_data.py::TestXtQuantMarketData::test_get_market_data -v
```

## ⚙️ 测试配置

### 配置文件

测试配置位于 `test_config.py`，包含以下关键配置：

```python
# 服务地址
BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000/ws"

# API 密钥
API_KEY = "your-api-key"

# 测试标的
TEST_STOCK = "000001.SZ"  # 平安银行
BYD_SYMBOL = "SZSE.002594"  # 比亚迪

# 账户配置
ACCOUNT_ID = "your-account-id"
```

### 环境变量

可以通过环境变量覆盖默认配置：

```bash
export JINGNI_API_KEY="your-api-key"
export JINGNI_ACCOUNT_ID="your-account-id"
export JINGNI_BASE_URL="http://localhost:8000"
```

## 📊 测试分类

### 1. API 健康检查测试 (test_api_health.py)

| 测试项 | 说明 |
|--------|------|
| `test_root` | 根路径访问测试 |
| `test_health_check` | 健康检查端点测试 |
| `test_openapi_docs` | API 文档访问测试 |
| `test_stats_endpoint` | 统计端点测试 |

### 2. WebSocket 测试 (test_api_websocket.py)

| 测试项 | 说明 |
|--------|------|
| `test_websocket_connect` | WebSocket 连接测试 |
| `test_websocket_auth` | 认证测试 |
| `test_websocket_rpc_call` | RPC 调用测试 |
| `test_websocket_heartbeat` | 心跳测试 |

### 3. XtQuant 数据接口测试 (test_xtquant_data.py)

#### 行情数据测试 (TestXtQuantMarketData)

| 测试项 | 说明 |
|--------|------|
| `test_get_market_data` | 获取历史行情 |
| `test_get_full_tick` | 获取 Tick 数据 |
| `test_get_instrument_detail` | 获取合约详情 |
| `get_trading_dates` | 获取交易日历 |
| `test_get_financial_data` | 获取财务数据 |

#### 数据订阅测试 (TestXtQuantSubscription)

| 测试项 | 说明 |
|--------|------|
| `test_subscribe_quote` | 订阅行情 |
| `test_download_history_data` | 下载历史数据 |

### 4. XtQuant 交易接口测试 (test_xtquant_trader.py)

| 测试项 | 说明 |
|--------|------|
| `test_create_trader` | 创建交易实例 |
| `test_query_asset` | 查询资金 |
| `test_query_positions` | 查询持仓 |
| `test_query_orders` | 查询订单 |

### 5. GM 数据接口测试 (test_gm_data.py)

| 测试项 | 说明 |
|--------|------|
| `test_history_n` | 获取历史行情 (history_n) |
| `test_history` | 获取历史行情 (history) |
| `test_get_instruments` | 获取标的信息 |
| `test_get_trading_dates` | 获取交易日历 |
| `test_stk_get_fundamentals` | 获取财务数据 |

### 6. GM 交易接口测试 (test_gm_trader.py)

| 测试项 | 说明 |
|--------|------|
| `test_order_volume` | 按量下单 |
| `test_order_value` | 按价值下单 |
| `test_get_cash` | 获取资金 |
| `test_get_position` | 获取持仓 |

## 📝 测试输出格式

所有测试使用统一的输出格式：

```
================================================================================
[TEST] test_get_market_data - 测试获取历史行情
File: test_xtquant_data.py
================================================================================
[INFO] 调用函数: get_market_data
[INFO] 参数: {'stock_list': ['000001.SZ'], 'period': '1d'}
--------------------------------------------------------------------------------
[DATA] 历史行情 (最近10天) - 000001.SZ
  - 数据条数: 10
  - 字段: ['open', 'high', 'low', 'close', 'volume']
  - 最新收盘价: 10.50
--------------------------------------------------------------------------------
[RESULT] ✅ 获取历史行情 (get_market_data) - 成功
         标的: 000001.SZ, 周期: 1d
================================================================================
```

## 🔧 测试工具函数

### print_test_header

打印测试头部信息：

```python
print_test_header("test_name", "测试描述", "test_file.py")
```

### print_data_summary

打印数据摘要：

```python
print_data_summary("数据标题", data_object)
```

### print_result

打印测试结果：

```python
print_result("测试名称", success=True, detail="详细信息")
```

## 🛠️ 故障排除

### 常见问题

1. **连接失败**
   - 检查服务是否启动
   - 验证 BASE_URL 配置
   - 检查防火墙设置

2. **认证失败**
   - 验证 API_KEY 配置
   - 检查请求头格式

3. **数据接口失败**
   - 检查量化库是否正确安装
   - 验证账户配置
   - 检查网络连接

4. **交易接口失败**
   - 验证交易账户配置
   - 检查交易时间
   - 确认交易权限

### 调试模式

启用详细日志：

```bash
pytest tests/ -v -s --log-cli-level=DEBUG
```

## 📈 测试覆盖率

### 查看覆盖率报告

```bash
# 生成 HTML 报告
pytest tests/ --cov=. --cov-report=html

# 在浏览器中打开
open htmlcov/index.html
```

### 覆盖率目标

| 模块 | 目标覆盖率 |
|------|-----------|
| core/ | >= 90% |
| api/ | >= 85% |
| providers/ | >= 80% |
| models/ | >= 95% |

## 🔄 持续集成

### GitHub Actions 配置示例

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run tests
        run: pytest tests/ -v --cov=. --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

## 📚 最佳实践

1. **测试隔离**：每个测试用例应独立运行，不依赖其他测试
2. **清理资源**：测试完成后清理创建的资源
3. **异常处理**：正确处理预期异常
4. **超时设置**：为网络请求设置合理超时
5. **日志记录**：记录关键操作和错误信息

## 🤝 贡献测试

1. 为新功能添加对应测试
2. 保持测试风格一致
3. 更新测试文档
4. 确保所有测试通过
