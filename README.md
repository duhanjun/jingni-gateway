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

- 🚀 **三源支持**：同时支持 **xtquant (迅投QMT)**、**GM (掘金量化)** 和 **tdxquant (通达信量化)**
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
| Python | 3.10 - 3.12 | 推荐使用 Python 3.10+ |
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

安装到网关实际使用的项目虚拟环境（不要装到 uv 的 base Python）：

```powershell
cd D:\codebuddy\jingni-gateway
uv pip install --python .\.venv\Scripts\python.exe -U gm `
  -i https://mirrors.aliyun.com/pypi/simple/
# gm 3.0.193 的运行时还缺 six，需要补装
uv pip install --python .\.venv\Scripts\python.exe six
```

注意：GM SDK 在 Python 3.11 下要求 `pandas<2.0`，安装时会把项目的 pandas 降到 1.5.3。

#### gmtrade (GM 外部交易 sidecar)

`gmtrade` 是独立程序化交易 SDK，不依赖 `gm.api` 的 `run()` 策略上下文；网关的 GM 下单/撤单/资金/持仓/委托已切到它。`gmtrade 3.0.6` 只有 `cp36`–`cp310` wheel，**不能装进 Python 3.11 的 `.venv`**，因此项目单独建 Python 3.10 sidecar：

```powershell
cd D:\codebuddy\jingni-gateway
uv venv --python 3.10 .venv310
uv pip install --python .\.venv310\Scripts\python.exe gmtrade==3.0.6
```

网关启动时自动探测 `.venv310\Scripts\python.exe`；也可用环境变量覆盖：

```dotenv
JINGNI_GMTRADE_PYTHON=D:\codebuddy\jingni-gateway\.venv310\Scripts\python.exe
JINGNI_GMTRADE_ENDPOINT=api.myquant.cn:9000
```

- `gmdata` 行情仍走 `gm.api`；`gmtrade` 只负责交易与交易查询。
- `get_cash/get_position/get_orders/order_volume/order_cancel` 经 `tools/gmtrade_bridge.py` 的 JSON Lines 协议调用，sidecar 只登录一个账户。
- 当前验证：模拟账户 `nav=100000.00`，9.66 限价买入 `accepted`，撤单后 `status=5`，资金不变、无持仓；`/api/v1/gm/health` 会返回 `gmtrade_available`。

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

交易写操作只允许走类型化端点；通用 RPC 仅保留查询。

| 端点 / 函数 | 说明 |
|------|------|
| `POST /api/v1/xtquant/trade/order` | 类型化下单（`client_order_id` 幂等） |
| `POST /api/v1/xtquant/trade/cancel` | 类型化撤单 |
| `GET /api/v1/xtquant/trade/orders` | 查询委托 |
| `GET /api/v1/xtquant/trade/asset` | 查询资金 |
| `GET /api/v1/xtquant/trade/positions` | 查询持仓 |
| `query_stock_asset` / `query_stock_orders` / `query_stock_positions` | 通用 RPC 只读查询 |

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

| 端点 / 函数 | 说明 |
|------|------|
| `POST /api/v1/gm/trade/order` | 类型化按量下单（`client_order_id` 幂等） |
| `POST /api/v1/gm/trade/cancel` | 类型化撤单 |
| `GET /api/v1/gm/trade/orders` | 查询订单 |
| `GET /api/v1/gm/trade/asset` | 查询资金 |
| `GET /api/v1/gm/trade/positions` | 查询持仓 |

GM SDK `3.0.193` 注意：不要调用 `gm.api.set_account_id()`，该全局设置会让后续 `get_cash/get_position` 返回 `1013`。网关现在只 `set_token`，查询时显式传 `account_id`。

GM 交易链路：`/api/v1/gm/trade/*` → `GMTradeService` → `GMTradeProxy` → `.venv310` 的 `tools/gmtrade_bridge.py` → `gmtrade.order_volume/order_cancel`。`/trade/cancel` 接受 `order_id` 或 `cl_ord_id`，传 `order_id` 时网关先按委托列表解析 `cl_ord_id`。

| `get_cash` / `get_position` / `get_orders` | 通用 RPC 只读查询 |

### tdxquant (通达信量化)

| 端点 | 说明 |
|------|------|
| `GET /api/v1/tdxquant/health` | 健康检查（含 `logged_in`） |
| `POST /api/v1/tdxquant/rpc/execute` | 数据 RPC（仅 `tdxdata`） |
| `POST /api/v1/tdxquant/trade/order` | 类型化下单（`client_order_id` 幂等） |
| `POST /api/v1/tdxquant/trade/cancel` | 撤单并做状态对账 |
| `GET /api/v1/tdxquant/trade/orders` | 查询委托 |
| `GET /api/v1/tdxquant/trade/asset` | 查询资金（以 `Cash` 为准） |
| `GET /api/v1/tdxquant/trade/positions` | 查询持仓 |

幂等说明：`client_order_id` 先查进程内缓存，再查 `JINGNI_TDX_IDEMPOTENCY_DB`（默认 `data/tdx_idempotency.sqlite3`）；accepted 与 pending_confirm 都会落盘，网关重启后同 key 返回 `idempotent_replay=true`。`notify=1` 返回 `pending_confirm`，需在通达信客户端手动确认。

数据参数补充：

- `get_stock_list` 的 `market` 是通达信分类编码，不是 `SH/SZ/BJ`。常用值：`5` 全部 A 股、`7` 上证主板、`8` 深证主板、`50` 沪深 A 股、`53` 北交所、`32` 可转债。实测 `market=5` 返回 5584 只、`7` 返回 1700 只、`8` 返回 1494 只、`53` 返回 358 只。
- `get_market_data` 在 tqcenter 本地模式下，分钟线要求客户端已下载对应盘后数据；有 Level2 权限才能取分钟线。当前终端 `1m/5m/15m/30m/1h` 返回空字典，`60m` 返回 `error/msg` 结构，属于终端数据权限/下载问题，不是网关丢数据。
- `get_kzz_info` 只接受可转债代码，例如 `123039.SZ`；传正股代码或终端没有可转债数据包时返回空字典。

---

## 🔧 开发指南

### 代码规范

- 使用 Python 3.10+ 特性
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
