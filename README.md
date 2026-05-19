<<<<<<< HEAD
# JingNiGateway

<p align="center">
  <b>基于 FastAPI 和 WebSocket 的多源量化数据网关服务</b>
</p>

<p align="center">
  <a href="#特性">特性</a> •
  <a href="#项目结构">项目结构</a> •
  <a href="#快速开始">快速开始</a> •
  <a href="#api文档">API文档</a> •
  <a href="#测试">测试</a>
</p>

---

## ✨ 特性

- 🚀 **双源数据支持**：同时支持 **xtquant (迅投QMT)** 和 **gm (掘金量化)** 两大主流量化平台
- 📡 **WebSocket 实时推送**：订阅式行情推送和交易事件回调
- 🔒 **安全认证**：API Key 验证机制，支持 Header 和 Query 参数
- 🔄 **数据序列化**：自动处理 DataFrame、NaN、Inf 等复杂数据类型
- 🔌 **连接管理**：支持自动重连、心跳检测、连接状态追踪
- 📚 **完整文档**：自动生成 API 文档，支持方法列表查询
- 🎯 **零配置**：开箱即用，默认配置满足开发需求
- 🛡️ **函数白名单**：仅允许调用白名单内的函数，保障安全
- 🧪 **全面测试**：覆盖所有核心功能的测试用例

---

## 📁 项目结构

```
jingni_gateway/
├── main.py                 # 应用入口
├── config.py               # 配置管理
├── core/                   # 核心模块
│   ├── __init__.py
│   ├── whitelist.py        # RPC 函数白名单
│   ├── rpc.py              # RPC 执行引擎
│   └── websocket.py        # WebSocket 连接管理
├── api/                    # API 路由
│   ├── __init__.py
│   ├── deps.py             # 公共依赖
│   ├── gm.py               # GM 接口路由
│   └── xtquant.py          # XtQuant 接口路由
├── providers/              # 数据源提供者
│   ├── __init__.py
│   ├── base.py             # 基类和工具函数
│   ├── gm_provider.py      # GM 提供者
│   └── xtquant_provider.py # XtQuant 提供者
├── models/                 # 数据模型
│   ├── __init__.py
│   └── common.py           # 公共模型
├── tests/                  # 测试文件
│   ├── __init__.py
│   ├── test_config.py      # 测试配置
│   ├── test_api_health.py  # API 健康检查测试
│   ├── test_api_websocket.py # WebSocket 测试
│   ├── test_xtquant_data.py # XtQuant 数据接口测试
│   ├── test_xtquant_trader.py # XtQuant 交易接口测试
│   ├── test_gm_data.py     # GM 数据接口测试
│   └── test_gm_trader.py   # GM 交易接口测试
└── README.md               # 项目文档
```

---

## 🏗️ 架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        JingNiGateway v2.0                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────┐          ┌─────────────────────────────────────┐   │
│  │   HTTP API      │          │           WebSocket                 │   │
│  │                 │          │                                     │   │
│  │  /api/v1/rpc/*  │          │  /ws?client_id=xxx&api_key=xxx      │   │
│  │  /api/v1/gm/*   │          │                                     │   │
│  │  /api/v1/stats  │          │  - 行情订阅                          │   │
│  │                 │          │  - 交易回调                          │   │
│  └────────┬────────┘          └──────────────────┬──────────────────┘    │
│           │                                      │                       │
│           └──────────────────┬───────────────────┘                       │
│                              │                                          │
│  ┌───────────────────────────▼──────────────────────────────────────┐   │
│  │                    ConnectionManager                              │   │
│  │     连接管理    •    订阅管理    •    消息队列    •    心跳检测      │   │
│  └───────────────────────────┬──────────────────────────────────────┘   │
│                              │                                          │
│  ┌───────────────────────────▼──────────────────────────────────────┐   │
│  │                  RPC Executor (ThreadPool)                        │   │
│  │   函数白名单检查  •  参数序列化  •  超时控制  •  错误处理            │   │
│  └───────────────────────────┬──────────────────────────────────────┘   │
│                              │                                          │
│         ┌────────────────────┴────────────────────┐                     │
│         │                                         │                     │
│  ┌──────▼──────┐                         ┌───────▼───────┐              │
│  │  xtquant    │                         │      gm       │              │
│  │  Provider   │                         │   Provider    │              │
│  ├─────────────┤                         ├───────────────┤              │
│  │ • xtdata    │                         │ • gmdata      │              │
│  │ • xttrader  │                         │ • gmtrade     │              │
│  └─────────────┘                         └───────────────┘              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 📦 安装

### 1. 前置要求

| 组件 | 版本要求 | 说明 |
|------|---------|------|
| Python | 3.8 - 3.12 | 推荐使用 Python 3.10+ |
| 迅投 QMT | 最新版 | 如需使用 xtquant 接口 |
| 掘金量化 | 最新版 | 如需使用 gm 接口 |

### 2. 安装依赖

```bash
# 克隆项目
git clone <repository-url>
cd JingNiGateway

# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置量化模块

#### xtquant (迅投QMT)

从 QMT 安装目录复制 `xtquant` 文件夹到虚拟环境：

```bash
# Windows 示例
copy "D:\gjzq\qmt\bin.x64\Lib\site-packages\xtquant" ".venv\Lib\site-packages\"
```

#### gm (掘金量化)

```bash
pip install gm
```

---

## 🚀 快速开始

### 1. 配置服务

编辑 `config.py`：

```python
class Config:
    # MiniQMT 客户端路径（xtquant 需要）
    MINI_QMT_PATH = r"D:\qmt\userdata_mini"
    
    # 资金账户
    ACCOUNT_ID = "your-account-id"
    
    # API 密钥
    API_KEY = "your-api-key"
    
    # 服务配置
    API_HOST = "0.0.0.0"
    API_PORT = 8000
    
    # gm (掘金量化) 配置
    GM = GMConfig(
        enabled=True,
        token="your-gm-token",
        strategy_id="your-strategy-id"
    )
```

### 2. 启动服务

```bash
python main.py
```

或使用 uvicorn：

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 3. 访问服务

| 端点 | 地址 | 说明 |
|------|------|------|
| 服务地址 | http://localhost:8000 | 根路径 |
| API 文档 | http://localhost:8000/docs | Swagger UI |
| 备用文档 | http://localhost:8000/redoc | ReDoc |
| WebSocket | ws://localhost:8000/ws | WebSocket 连接 |

---

## 📖 API文档

### HTTP API

#### xtquant RPC 执行

```bash
POST /api/v1/rpc/execute
```

**请求示例**：

```bash
curl -X POST "http://localhost:8000/api/v1/rpc/execute" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "module": "xtdata",
    "function": "get_market_data",
    "kwargs": {
      "field_list": ["close"],
      "stock_list": ["000001.SZ"],
      "period": "1d",
      "start_time": "20240101",
      "end_time": "20241231"
    },
    "timeout": 30
  }'
```

**响应示例**：

```json
{
  "success": true,
  "data": {
    "000001.SZ": {
      "close": [10.5, 10.6, 10.7]
    }
  },
  "execution_time_ms": 125.5
}
```

#### gm (掘金量化) RPC 执行

```bash
POST /api/v1/gm/rpc/execute
```

**请求示例**：

```bash
curl -X POST "http://localhost:8000/api/v1/gm/rpc/execute" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "module": "gmdata",
    "function": "history_n",
    "kwargs": {
      "symbol": "SZSE.002594",
      "frequency": "1d",
      "count": 10
    }
  }'
```

#### 获取可用方法列表

```bash
# xtquant 方法
GET /api/v1/rpc/methods?module=xtdata

# gm 方法
GET /api/v1/gm/rpc/methods?module=gmdata
```

#### 获取函数白名单

```bash
GET /api/v1/rpc/whitelist
```

#### 获取服务统计

```bash
GET /api/v1/stats
```

### WebSocket API

#### Python 示例

```python
import asyncio
import websockets
import json

async def test_ws():
    uri = "ws://localhost:8000/ws?client_id=test_client&api_key=your-api-key"
    async with websockets.connect(uri) as ws:
        # 接收连接成功消息
        welcome = await ws.recv()
        print(f"欢迎消息: {welcome}")

        # 订阅行情
        await ws.send(json.dumps({
            "type": "subscribe_quote",
            "stock_code": "000001.SZ",
            "period": "tick"
        }))

        # 接收实时行情
        while True:
            data = await ws.recv()
            print(data)

asyncio.run(test_ws())
```

#### WebSocket 消息类型

| 类型 | 方向 | 说明 |
|------|------|------|
| `connected` | 服务端 → 客户端 | 连接成功 |
| `subscribe_quote` | 客户端 → 服务端 | 订阅行情 |
| `unsubscribe_quote` | 客户端 → 服务端 | 取消订阅 |
| `quote_data` | 服务端 → 客户端 | 行情数据推送 |
| `rpc_call` | 客户端 → 服务端 | RPC 调用 |
| `rpc_response` | 服务端 → 客户端 | RPC 响应 |
| `heartbeat` | 服务端 → 客户端 | 心跳检测 |
| `pong` | 服务端 → 客户端 | 心跳响应 |

---

## 🧪 测试

### 运行所有测试

```bash
pytest tests/ -v
```

### 运行特定测试

```bash
# API 健康检查
pytest tests/test_api_health.py -v

# XtQuant 数据接口
pytest tests/test_xtquant_data.py -v

# GM 数据接口
pytest tests/test_gm_data.py -v
```

### 测试覆盖率

```bash
pytest tests/ --cov=. --cov-report=html
```

---

## 📋 支持的接口

### xtquant (迅投QMT)

#### xtdata 行情接口

| 函数 | 说明 |
|------|------|
| `get_market_data` | 获取历史行情 |
| `get_full_tick` | 获取 Tick 数据 |
| `get_instrument_detail` | 获取合约详情 |
| `get_trading_dates` | 获取交易日历 |
| `get_financial_data` | 获取财务数据 |
| `subscribe_quote` | 订阅行情 |
| `download_history_data` | 下载历史数据 |

#### xttrader 交易接口

| 函数 | 说明 |
|------|------|
| `create_trader` | 创建交易实例 |
| `order_stock` | 股票下单 |
| `cancel_order_stock` | 撤单 |
| `query_stock_asset` | 查询资金 |
| `query_stock_positions` | 查询持仓 |
| `query_stock_orders` | 查询订单 |

### gm (掘金量化)

#### gmdata 数据接口

| 函数 | 说明 |
|------|------|
| `history_n` | 获取历史行情 |
| `history` | 获取历史行情 |
| `get_instruments` | 获取标的信息 |
| `get_trading_dates` | 获取交易日历 |
| `stk_get_fundamentals_*` | 获取财务数据 |
| `stk_get_daily_*` | 获取每日数据 |

#### gmtrade 交易接口

| 函数 | 说明 |
|------|------|
| `order_volume` | 按量下单 |
| `order_value` | 按价值下单 |
| `order_cancel` | 撤单 |
| `get_cash` | 获取资金 |
| `get_position` | 获取持仓 |
| `get_orders` | 获取订单 |

---

## 🔧 开发指南

### 代码规范

- 使用 Python 3.8+ 特性
- 遵循 PEP 8 编码规范
- 类名使用 PascalCase
- 函数和变量使用 snake_case
- 常量使用 UPPER_SNAKE_CASE

### 添加新的 RPC 函数

1. 在 `core/whitelist.py` 中添加函数到白名单
2. 在相应的 provider 中实现功能
3. 添加测试用例

### 添加新的 Provider

1. 继承 `providers/base.py` 中的 `BaseProvider`
2. 实现所有抽象方法
3. 在 `main.py` 中注册 provider

---

## 📄 许可证

MIT License

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！
=======
# jingni-gateway
>>>>>>> ade59ef18e65f9c8b222be5d8dc9a8a10041b5b6
