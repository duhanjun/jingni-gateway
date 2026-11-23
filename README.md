# JingNiGateway

基于 FastAPI + WebSocket 的多源量化数据与交易网关，统一接入：

- **xtquant / MiniQMT**：行情与类型化交易
- **GM / 掘金量化**：`gm.api` 行情 + `gmtrade` 外部交易 sidecar
- **tdxquant / 通达信量化**：`tqcenter` 直连行情与类型化交易

当前版本：`2.0.0`

---

## 最新功能

### 统一接入层

- 三个 Provider：`xtquant`、`gm`、`tdxquant`
- HTTP 类型化交易端点 + 通用数据 RPC
- 通用 RPC **不再暴露下单/撤单**，交易写操作只走 `/trade/*`
- API Key 认证，支持 `X-API-Key` Header 和 `api_key` Query 参数
- 默认监听 `127.0.0.1`，避免无意暴露到局域网

### 执行与稳定性

- `data` / `trade` / `bulk` 三条执行 lane，避免长任务饿死交易
- 全局共享执行器 + 真异步超时；超时后明确返回，不再阻塞事件循环
- RPC 参数严格校验：未知参数、缺必填参数直接返回 `INVALID_ARGUMENT`
- 阻塞函数黑名单：`xtdata.run`、`xttrader.run_forever`、`gmtrade.run` 等不再进入 RPC
- DataFrame / NumPy / NaN / Inf / datetime 统一序列化

### 交易能力

| Provider | 下单 | 撤单 | 资金/持仓/委托 | 说明 |
|---|---|---|---|---|
| xtquant | `POST /api/v1/xtquant/trade/order` | `/trade/cancel` | `/trade/asset`、`/trade/positions`、`/trade/orders` | 代码已接入；本机未安装 xtquant SDK，尚未真实联调 |
| GM | `POST /api/v1/gm/trade/order` | `/trade/cancel` | 同上 | `gmtrade` sidecar；模拟账户限价/市价、成交、撤单、幂等、立即拒单识别已验证；卖出受 T+1 限制 |
| tdxquant | `POST /api/v1/tdxquant/trade/order` | `/trade/cancel` | 同上 | `tqcenter` 直连；模拟账户买卖、限价/市价/涨跌停价、`notify=1`、撤单、跨重启幂等已验证；真实账户待实盘 |

### 幂等与交易状态

- xtquant / GM：`client_order_id` 进程内幂等缓存
- TDX：`client_order_id` 进程内缓存 + SQLite 持久化，网关重启后同 key 返回 `idempotent_replay=true`
- TDX `notify=1` 如实返回 `pending_confirm`，不会伪装成已成交；需要在通达信客户端人工确认
- TDX 撤单做状态对账，处理“返回 `Value=0` 但异步生效”的情况

### WebSocket

- 行情订阅、全量行情订阅、取消订阅
- `ping/pong` 心跳、心跳超时关闭
- 最大连接数限制、同 `client_id` 重连替换
- 交易事件推送接口已预留；当前 GM 交易以轮询查询为主

### GM 外部交易 sidecar

`gmtrade 3.0.6` 只有 `cp36`–`cp310` wheel，不能装进 Python 3.11 的 `.venv`。因此项目使用独立的 Python 3.10 sidecar：

```text
网关(Python 3.11)
  → GMTradeProxy
    → tools/gmtrade_bridge.py (Python 3.10)
      → gmtrade.order_volume / order_cancel / get_cash / get_positions / get_orders
```

- `gm.api` 继续负责行情/数据
- `gmtrade` 负责 GM 交易与交易查询
- sidecar 通过 JSON Lines 通信，网关退出时自动关闭
- 当前 sidecar 只登录一个 GM 账户

---

## 当前验证状态

| 能力 | 状态 |
|---|---|
| xtquant 数据/交易代码 | 已完成接入；本机没有 xtquant SDK，未真实联调 |
| GM `gm.api` 行情 | 真实接口可用 |
| GM `gmtrade` 模拟账户 | 限价/市价、成交、持仓、撤单、幂等、立即拒单识别已验证；卖出受 T+1 限制 |
| GM 实盘 | 未切换、未下实盘单 |
| TDX tqcenter 登录与资产 | 模拟账户 `logged_in=true`，资产可查 |
| TDX 模拟交易 | 登录、买入/卖出、限价/市价/涨跌停价、`notify=1` 人工确认、撤单已验证；市价成交状态查询有延迟 |
| TDX 实盘 | 券商已开放 TQ 自动下单权限，尚未做实盘小额验证 |
| TDX 分钟数据 | 当前终端无分钟数据/Level2，`1m/5m/15m/30m/1h` 为空 |
| 自动化测试 | `87 passed, 5 skipped` |

> TDX 收盘后提交委托会返回 `(-7353) 服务未就绪(OMS)`，这是终端 OMS 时段限制，不是网关异常。真实 `accepted → 撤单` 闭环需在交易时段复验。

---

## 项目结构

```text
jingni-gateway/
├── main.py                     # FastAPI 入口、生命周期、WebSocket
├── config.py                   # 环境变量驱动的配置
├── .env.example                # 环境变量模板
├── requirements.txt            # 主环境依赖
├── api/
│   ├── deps.py                 # API Key 依赖
│   ├── xtquant.py              # /api/v1/xtquant/*
│   ├── gm.py                   # /api/v1/gm/*
│   └── tdxquant.py             # /api/v1/tdxquant/*
├── core/
│   ├── executor.py             # data/trade/bulk 执行器
│   ├── rpc.py                  # 通用 RPC、参数校验
│   ├── whitelist.py            # 函数白名单
│   ├── websocket.py            # WebSocket 连接/订阅/心跳
│   ├── xt_trade.py             # xtquant 类型化交易
│   ├── gm_trade.py             # GM 类型化交易
│   ├── tdx_trade.py            # TDX 类型化交易、幂等、对账
│   └── gmtrade_proxy.py        # gmtrade sidecar 客户端
├── providers/
│   ├── base.py                 # Provider 基类、序列化、代码转换
│   ├── xtquant_provider.py
│   ├── gm_provider.py
│   └── tdx_provider.py
├── models/
│   └── common.py
├── tools/
│   ├── gmtrade_bridge.py       # Python 3.10 JSON Lines sidecar
│   └── requirements-gmtrade310.txt
├── spikes/                     # TDX 实测脚本
├── tests/                      # 单元/契约/接口测试
├── tdx-spike-实测记录.md
└── 代码问题评估与tdxquant接入规划.md
```

---

## 安装

> 路径约定：项目内路径均相对项目根目录；`<QMT_HOME>`、`<TDX_HOME>` 为外部终端安装目录占位符，按本机环境替换。

### 1. 前置要求

| 组件 | 要求 |
|---|---|
| Python | 3.10 - 3.12 |
| 迅投 QMT | 可选；使用 xtquant 时需要 |
| 掘金量化 | 可选；使用 GM 数据/交易时需要 |
| 通达信金融终端 | 可选；使用 tdxquant 时需要，且需支持 TQ |

### 2. 主环境

以下命令均在项目根目录执行：

```powershell
uv venv --python 3.11 .venv
uv pip install --python .\.venv\Scripts\python.exe -r requirements.txt
```

不使用 uv 时也可以：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. xtquant（可选）

从 QMT 安装目录复制 `xtquant` 到项目虚拟环境：

```powershell
copy "<QMT_HOME>\bin.x64\Lib\site-packages\xtquant" ".venv\Lib\site-packages\"
```

当前机器 QMT 安装目录下没有 `xtquant`，只有 `ptrade`，因此 xtquant 尚未联调。

### 4. GM（可选）

```powershell
uv pip install --python .\.venv\Scripts\python.exe -U gm six
```

注意：GM SDK 在 Python 3.11 下可能要求 `pandas<2.0`；若安装时发生降级，以实际依赖解析结果为准。

### 5. gmtrade sidecar（GM 交易必需）

```powershell
uv venv --python 3.10 .venv310
uv pip install --python .\.venv310\Scripts\python.exe -r tools\requirements-gmtrade310.txt
```

验证：

```powershell
.\.venv310\Scripts\python.exe -c "import gmtrade; print(gmtrade.__version__)"
```

### 6. TDX

确认通达信终端已启动并登录，且安装目录下存在：

```text
<TDX_HOME>\PYPlugins\user\tqcenter
```

配置 `JINGNI_TDX_HOME` 指向该安装目录。交易还需要配置 `JINGNI_TDX_ACCOUNT`。

---

## 配置

不要修改 `config.py` 写死凭据。复制模板并填写 `.env`：

```powershell
copy .env.example .env
```

### 核心环境变量

| 变量 | 说明 |
|---|---|
| `JINGNI_API_KEY` | API 认证密钥；为空时受保护接口拒绝访问 |
| `JINGNI_API_HOST` | 监听地址，默认 `127.0.0.1` |
| `JINGNI_API_PORT` | 端口，默认 `8000` |
| `JINGNI_LOG_LEVEL` | 日志级别 |
| `JINGNI_QMT_PATH` | MiniQMT `userdata_mini` 路径 |
| `JINGNI_QMT_ACCOUNT` | QMT 资金账号 |
| `JINGNI_GM_ENABLED` | `1/0` 是否启用 GM |
| `JINGNI_GM_TOKEN` | 掘金 Token |
| `JINGNI_GM_STRATEGY_ID` | 掘金策略 ID |
| `JINGNI_GM_ACCOUNT_ID` | GM 资金账户 ID |
| `JINGNI_GMTRADE_PYTHON` | gmtrade sidecar Python；默认 `.venv310\Scripts\python.exe` |
| `JINGNI_GMTRADE_ENDPOINT` | 默认 `api.myquant.cn:9000`；实盘按掘金/券商指引调整 |
| `JINGNI_TDX_ENABLED` | `1/0` 是否启用 TDX |
| `JINGNI_TDX_HOME` | 通达信安装目录 |
| `JINGNI_TDX_ACCOUNT` | TDX 资金账户 |
| `JINGNI_TDX_ACCOUNT_TYPE` | 默认 `stock` |
| `JINGNI_TDX_TIMEOUT` | 数据/交易调用超时，默认 `30` 秒 |
| `JINGNI_TDX_CANCEL_RECONCILE_TIMEOUT` | 撤单对账超时，默认 `30` 秒 |
| `JINGNI_TDX_POLL_INTERVAL` | 委托状态轮询间隔，默认 `1.0` 秒 |
| `JINGNI_TDX_PENDING_IDEMPOTENCY_TTL` | `pending_confirm` 人工确认幂等窗口，默认 `1800` 秒 |
| `JINGNI_TDX_IDEMPOTENCY_DB` | 默认 `data/tdx_idempotency.sqlite3` |

`.env` 已在 `.gitignore` 中；不要提交 Token、API Key、账号。

---

## 启动

```powershell
python main.py
```

或：

```powershell
uvicorn main:app --host 127.0.0.1 --port 8000
```

访问：

| 地址 | 说明 |
|---|---|
| `http://127.0.0.1:8000/` | 服务信息 |
| `http://127.0.0.1:8000/health` | 总健康检查 |
| `http://127.0.0.1:8000/docs` | Swagger UI |
| `http://127.0.0.1:8000/redoc` | ReDoc |
| `ws://127.0.0.1:8000/ws?client_id=xxx&api_key=xxx` | WebSocket |

---

## API

所有受保护接口都需要：

```http
X-API-Key: <JINGNI_API_KEY>
```

### 通用端点

| 方法 | 端点 | 说明 |
|---|---|---|
| GET | `/` | 服务信息与 Provider 状态 |
| GET | `/health` | 总健康检查 |
| GET | `/api/v1/stats` | 连接统计与白名单 |
| WS | `/ws` | 行情/交易事件 WebSocket |

### xtquant

| 方法 | 端点 | 说明 |
|---|---|---|
| GET | `/api/v1/xtquant/health` | 健康检查 |
| POST | `/api/v1/xtquant/rpc/execute` | 白名单内 RPC，模块 `xtdata` 或 `xttrader`；交易写操作只走 `/trade/*` |
| GET | `/api/v1/xtquant/rpc/methods` | 可用方法 |
| GET | `/api/v1/xtquant/rpc/whitelist` | 白名单 |
| POST | `/api/v1/xtquant/symbol/convert` | 代码格式转换 |
| POST | `/api/v1/xtquant/trade/order` | 类型化下单 |
| POST | `/api/v1/xtquant/trade/cancel` | 类型化撤单 |
| GET | `/api/v1/xtquant/trade/orders` | 委托查询 |
| GET | `/api/v1/xtquant/trade/asset` | 资金查询 |
| GET | `/api/v1/xtquant/trade/positions` | 持仓查询 |

### GM

| 方法 | 端点 | 说明 |
|---|---|---|
| GET | `/api/v1/gm/health` | 健康检查，含 `gmtrade_available` |
| POST | `/api/v1/gm/rpc/execute` | 白名单内 RPC，模块 `gmdata` 或 `gmtrade`；交易写操作只走 `/trade/*` |
| GET | `/api/v1/gm/rpc/methods` | 可用方法 |
| GET | `/api/v1/gm/rpc/whitelist` | 白名单 |
| POST | `/api/v1/gm/trade/order` | 类型化按量下单 |
| POST | `/api/v1/gm/trade/cancel` | 撤单，支持 `order_id` 或 `cl_ord_id` |
| GET | `/api/v1/gm/trade/orders` | 委托查询 |
| GET | `/api/v1/gm/trade/asset` | 资金查询 |
| GET | `/api/v1/gm/trade/positions` | 持仓查询 |

GM 注意：

- 不要调用 `gm.api.set_account_id()`；它会导致 `get_cash/get_position` 返回 `1013`。
- 网关只 `set_token`，查询时显式传 `account_id`。
- 交易链路为 `GMTradeService → GMTradeProxy → gmtrade_bridge → gmtrade`。

### tdxquant

| 方法 | 端点 | 说明 |
|---|---|---|
| GET | `/api/v1/tdxquant/health` | 健康检查，含 `logged_in` |
| POST | `/api/v1/tdxquant/rpc/execute` | 白名单内 RPC，模块 `tdxdata` 或 `tdxtrade`；交易写操作只走 `/trade/*` |
| GET | `/api/v1/tdxquant/rpc/methods` | 可用方法 |
| GET | `/api/v1/tdxquant/rpc/whitelist` | 白名单 |
| POST | `/api/v1/tdxquant/trade/order` | 类型化下单，`notify` 三态 |
| POST | `/api/v1/tdxquant/trade/cancel` | 撤单并做状态对账 |
| GET | `/api/v1/tdxquant/trade/orders` | 委托查询 |
| GET | `/api/v1/tdxquant/trade/asset` | 资金查询 |
| GET | `/api/v1/tdxquant/trade/positions` | 持仓查询 |

TDX 数据参数：

- `get_stock_list` 的 `market` 是分类编码，不是 `SH/SZ/BJ`：
  - `5` 全部 A 股
  - `7` 上证主板
  - `8` 深证主板
  - `53` 北交所
  - 其他分类值以当前终端返回为准
- `get_market_data` 的分钟线依赖终端已下载盘后数据/Level2；当前终端 `1m/5m/15m/30m/1h` 为空，`60m` 返回错误结构。
- `get_kzz_info` 只接受可转债代码，例如 `123039.SZ`；终端无数据包时返回空。

---

## 请求示例

### 数据 RPC

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/tdxquant/rpc/execute" `
  -H "X-API-Key: your-api-key" `
  -H "Content-Type: application/json" `
  -d '{
    "module": "tdxdata",
    "function": "get_market_data",
    "kwargs": {
      "stock_list": ["600000.SH"],
      "period": "1d",
      "count": 10
    },
    "timeout": 30
  }'
```

### TDX 类型化下单

```json
{
  "stock_code": "600000.SH",
  "order_type": 0,
  "order_volume": 100,
  "price_type": 0,
  "price": 9.66,
  "notify": 0,
  "client_order_id": "demo-tdx-001"
}
```

`order_type`：`0` 买入 / `1` 卖出；`price_type`：`0` 限价 / `1` 市价 / `2` 涨停 / `3` 跌停。

### GM 类型化下单

```json
{
  "symbol": "SHSE.600000",
  "volume": 100,
  "side": 0,
  "order_type": 0,
  "price": 9.66,
  "position_effect": 1,
  "client_order_id": "demo-gm-001"
}
```

`side`：`0` 买入 / `1` 卖出；`order_type`：`0` 限价 / `1` 市价；`position_effect`：`1` 开仓 / `2` 平仓 / `3` 平今。

---

## WebSocket

连接：

```text
ws://127.0.0.1:8000/ws?client_id=demo&api_key=<JINGNI_API_KEY>
```

订阅行情：

```json
{
  "type": "subscribe_quote",
  "stock_code": "000001.SZ",
  "period": "tick"
}
```

消息类型：

| 类型 | 方向 | 说明 |
|---|---|---|
| `connected` | 服务端 → 客户端 | 连接成功 |
| `subscribe_quote` | 客户端 → 服务端 | 单标的订阅 |
| `subscribe_whole_quote` | 客户端 → 服务端 | 全量行情订阅 |
| `unsubscribe_quote` | 客户端 → 服务端 | 取消订阅 |
| `subscribed` | 服务端 → 客户端 | 订阅成功 |
| `whole_quote` | 服务端 → 客户端 | 全量行情推送 |
| `quote_data` | 服务端 → 客户端 | 行情数据 |
| `rpc_call` / `rpc_response` | 双向 | WebSocket RPC |
| `ping` / `pong` | 双向 | 心跳 |
| `reconnect` | 客户端 → 服务端 | 重连令牌 |
| `trade_event` | 服务端 → 客户端 | 交易事件（预留） |
| `error` | 服务端 → 客户端 | 错误信息 |

当前行情推送依赖 xtquant；本机没有 xtquant SDK 时，订阅会返回 `xtdata 模块不可用`。

---

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

当前基线：

```text
87 passed, 5 skipped
```

按模块：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_tdx_trade.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_gm_trade.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_gmtrade_proxy.py -q
```

测试不会主动下实盘单；TDX/GM 真实交易需要交易时段和显式配置。

---

## 已知限制

1. **xtquant 未真实联调**：本机 QMT 安装目录下只有 `ptrade`，没有 QMT/xtquant。
2. **GM 事件回调未启用**：`gmtrade.start()` 在仿真端点返回 `-1`，当前交易状态通过 `get_orders()` 轮询。
3. **GM sidecar 单账户**：当前只登录一个 `JINGNI_GM_ACCOUNT_ID`；多账户需要改成按账户路由。
4. **TDX 分钟数据缺失**：依赖终端盘后数据/Level2，网关无法凭空补齐。
5. **TDX 收盘后 OMS 不可用**：真实委托验收需交易时段。
6. **TDX `notify=1` 需人工确认**：已验证 `pending_confirm` → 客户端确认 → `open` → 撤单；pending 幂等窗口独立配置为 30 分钟，避免超时重放重复发送确认信号。
7. **TDX 委托状态查询有延迟**：市价卖出成交后约 20 秒内查询仍可能显示 `open`，应以持仓和资金变化对账，不能只看委托状态。
8. **未推送远端、未改写 Git 历史**：旧凭据清理需单独授权。

---

## 相关文档

- `tdx-spike-实测记录.md`：TDX tqcenter、notify、幂等、gmtrade sidecar 实测记录
- `代码问题评估与tdxquant接入规划.md`：历史问题评估与接入规划
- `方案复核意见与优化建议.md`：对评估方案的外部复核意见

---

## License

MIT License
