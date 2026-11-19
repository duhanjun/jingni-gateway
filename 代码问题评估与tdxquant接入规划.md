# jingni-gateway 代码问题评估与 tdxquant 接入规划

- 评估日期：2026-11-19
- 评估方式：全量静态代码审读（未运行服务与测试，避免触发真实下单）＋ 三份官方文档核对
- 核对依据：
  - 掘金量化 Python SDK 官方文档（快速开始、交易函数）：https://www.myquant.cn/docs2/sdk/python/
  - 掘金仿真交易 API 官方指引（gmtrade SDK）：https://sim.myquant.cn/sim/help
  - XtQuant（迅投 miniqmt）官方文档：https://dict.thinktrader.net/nativeApi/start_now.html 、xtdata.html 、xttrader.html
  - TdxQuant（通达信）官方文档：https://help.tdx.com.cn/quant/ 及其安装、交易函数、HTTP 调用、TdxAiData、版本更新说明、FAQ 子页
- 范围说明：本文只做问题评估与规划，不包含任何代码改动。

> **2026-11-19 修订（实机验证后，已重写）**：tdxquant 接入改为**只保留 tqcenter 直连**。
> 原 5.2 路径 A（本地 HTTP `127.0.0.1:17709`）作废：实测该方法面只是子集、参数类型零校验，
> 一个类型错误的 `order_id` 即可击穿客户端进程（证据见 `tdx-spike-实测记录.md` 4.3）。
> 5.2–5.6 已按 tqcenter 单通道重写；交易闭环已在模拟账户 `11048389` 验证通过（下单/查委托/撤单），
> 并确认撤单接口存在"返回 `Value=0` 但异步生效"的假失败行为（见实测记录 4.2）。

---

## 一、结论摘要

1. **项目当前有 5 类高危问题**：真实 Token/账号硬编码入库、README 残留 Git 合并冲突标记、xttrader 构造签名违反官方 API、掘金交易通道用错 SDK、WebSocket 推送链路存在线程级致命缺陷。这些问题会导致"看起来能用、实际交易与推送不可靠"。
2. **架构上存在双套并行实现**：`core/rpc.py` 全局模块引用与 `providers/*` 两套初始化/执行路径并存，`api/gm.py`、`api/xtquant.py` 又各自复制了第三套 RPC 执行逻辑，超时机制实际上全部失效（阻塞事件循环 + 线程池无法取消）。新增第三网关前应先收敛为单一执行通道。
3. **tdxquant 可以作为第三网关接入**。原方案曾考虑官方本地 HTTP 接口（`POST http://127.0.0.1:17709/`），但实机验证后已否决：它是 tqcenter 的 MCP 子集、参数类型零校验，错误类型可击穿客户端进程。**最终只保留 tqcenter 直连**；行情后台模式（tdxaidata）可作为可选数据补充，但它**不提供交易功能**，不能替代交易网关。
4. **tdxquant 交易语义与现有两家不同**：实盘下单默认返回"待用户确认"（Value=1），自动下单需券商开通支持 TQ 的版本；网关必须把"待确认/成功/失败"三态透传，不能伪装成同步成交。
5. 建议实施顺序：**阶段 0 安全与冲突清理 → 阶段 1 架构收敛与两网关修复 → 阶段 2 tdxquant 数据接入 → 阶段 3 tdxquant 交易接入 → 阶段 4 测试与加固**。

---

## 二、现状盘点

### 2.1 架构现状

- 技术栈：FastAPI + uvicorn + WebSocket，RPC 白名单 + 线程池执行 + 通用序列化（`providers/base.py:serialize_data`）。
- 两个网关：
  - xtquant：`xtdata`（行情）+ `xttrader`（交易，单例 `XtQuantTrader`），模块需从 QMT 安装目录手工复制。
  - gm：`gmdata` / `gmtrade` 两个逻辑模块，但**都映射到同一个 `gm.api`（策略 SDK）模块**（`providers/gm_provider.py:117`、`core/rpc.py:89`）。
- 三套 RPC 执行路径并存：
  1. `core/rpc.py:execute_rpc_call`（WebSocket 用）；
  2. `api/gm.py:_execute_gm_rpc_call`（GM HTTP 用，独立复制）；
  3. `api/xtquant.py:_execute_xtquant_rpc_call`（XtQuant HTTP 用，再复制一份，还带 inspect 参数过滤）。
- Provider 抽象（`providers/base.py:BaseProvider`）定义了 `initialize/cleanup/get_rpc_whitelist/get_module_reference`，但 `main.py` 生命周期并不统一管理：xtquant provider 从未在 lifespan 初始化，trader 实例实际由 `core/rpc.py` 的全局变量持有。
- 版本口径混乱：`main.py`/README 称 v2.0.0，`pyproject.toml` 为 1.0.0，`api/gm.py` 根端点自称 1.0.0。

### 2.2 关键事实（代码证据）

| 位置 | 事实 |
|---|---|
| `README.md:1、460-462` | 残留冲突标记（2026-11-19 已清理） |
| `config.py:53-55、105、115、157-161` | 原硬编码掘金 Token、strategy_id、GM account_id、QMT 资金账号、弱 API Key（2026-11-19 已全部改为 env，旧 Token 已由用户轮换） |
| `config.py:120` | 原默认监听 `0.0.0.0`（2026-11-19 已改为 `127.0.0.1`） |
| `core/rpc.py:139-141` | `XtQuantTrader(mini_qmt_path, int(account))`：把资金账号当 session_id |
| `providers/xtquant_provider.py:188` | `XtQuantTrader(mini_qmt_path, int(account), callback)`：官方构造器只有 2 参（见三-2） |
| `core/rpc.py:370-375`、`api/gm.py:311-316`、`api/xtquant.py:160-162` | `with ThreadPoolExecutor(...)` + `future.result(timeout)`：超时后 with 退出仍会等线程跑完，超时形同虚设且阻塞事件循环 |
| `core/websocket.py:383、416` | 在 SDK 回调线程里 `asyncio.create_task(...)`，无运行中事件循环时抛异常被吞掉 → 行情推送静默丢失 |
| `main.py:427` | `subscribe_whole_quote(code_list=code_list)` 未传 callback → 订阅成功但无数据推送 |
| `core/websocket.py:232-235` | 清理订阅时读 `sub['seq']`，但登记时存的是 `id`（`main.py:379-383`）→ 断线后行情订阅永不反订阅 |
| `api/gm.py:259-261` | `gmtrade.run` 自动注入 strategy_id —— 把策略 SDK 的阻塞式 `run()` 当交易初始化用 |
| `core/whitelist.py` | 白名单含 `run`、`stop`、`set_token`、`set_serv_addr`、`fund_transfer`、`bank_transfer_*`、`export_data`（任意路径写文件）、`order_close_all` 等高危函数 |

---

## 三、问题清单（按优先级）

> 优先级定义：P0＝立即处理（安全/根本不可用）；P1＝接入第三网关前必须修复（正确性/稳定性）；P2＝应尽快修复（一致性/工程质量）。
> 标注"定性判断"的条目是工程推断，非官方文档明文规定。

### P0 安全与仓库卫生

| 编号 | 问题 | 位置 | 影响 | 修复方向 |
|---|---|---|---|---|
| A1 | 疑似真实凭据硬编码并已入库：掘金 Token、策略 ID、GM/QMT 账号、弱 API Key | `config.py:53-55、101-115、157-161`；git 历史 | Token 等同账号密码（掘金官方明确提示），任何拿到仓库的人可操作账户；弱 Key+0.0.0.0 监听放大风险 | 立即在掘金/QMT 侧作废重发相关凭据；配置全部改环境变量/.env（python-dotenv 已在依赖里但未使用）；默认监听改 127.0.0.1；历史清理需用户确认后另行处理 |
| A2 | README 合并冲突标记残留 | `README.md:1、460-462` | 文档不可读，说明合并流程失控，其他文件可能也有隐性冲突残留（本次审读未发现代码文件冲突标记） | 解决冲突、保留完整版 README；全库扫描冲突标记 |
| A3 | 白名单暴露服务级破坏与资金划转函数 | `core/whitelist.py`（gmtrade: run/stop/set_token/set_serv_addr；xttrader: run_forever/stop/fund_transfer/bank_transfer_*/export_data/query_data；gmtrade: order_close_all） | 任一持有 API Key 的客户端可：阻塞 RPC 工作线程（run/run_forever）、改全局 Token 与服务地址、发起银证转账、向服务器任意路径写 CSV、一键清仓 | 白名单分级：数据类/查询类/交易类/管理类；交易类默认关闭需显式开启；run/stop/set_* 一律移出 RPC 面；export_data 路径限制或移除 |
| A4 | 测试即真实交易：TestClient 直连真实配置，用例包含真实下单、撤单、资金划拨、银证转账 | `tests/test_gm_trader.py`、`tests/test_xtquant_trader.py`（TestXtTraderFund/TestXtTraderOrder） | 跑一次 pytest 就可能对真实账户下单/转账；`test_set_token("test_token")` 还会把运行中服务的全局 Token 改成无效值 | 测试分层：离线单测（mock SDK）+ 仿真环境集成测试（显式开关）；资金类用例默认禁用；测试配置与生产配置隔离 |
| A5 | 交易类 RPC 无审计、无二次确认、无幂等 | `api/gm.py`、`api/xtquant.py`、`main.py:_handle_rpc_call` | 误调用/重放即真实委托；无法事后追溯 | 交易调用强制审计日志（谁、何时、参数、结果）；幂等键（order_remark/cl_ord_id 约束）；危险操作确认机制 |

### P1 正确性与稳定性

| 编号 | 问题 | 位置 | 官方依据 / 说明 | 修复方向 |
|---|---|---|---|---|
| B1 | **xttrader 构造签名错误**：`XtQuantTrader(path, session_id, callback)` 三参调用 | `providers/xtquant_provider.py:188` | 官方：`XtQuantTrader(path, session_id)` 仅 2 参，回调须 `register_callback(callback)` 单独注册 | 改为两参构造 + register_callback；`core/rpc.py` 路径已是正确写法，两处统一 |
| B2 | **资金账号被当 session_id**：`int(account)` | `core/rpc.py:139-141` | 官方：session_id 是"与 MiniQMT 通信的会话 ID，不同会话要保证不重"，与资金账号无关；账号应通过 `StockAccount` 传入各接口 | 独立配置 session_id（随机/时间戳生成并持久化），账号走 `StockAccount`；`int(account)` 对非数字账号直接崩溃 |
| B3 | **XtQuantTrader 第三参传法在另一处也不一致**：provider 与 core.rpc 各建一套 trader，`XtQuantProvider._trader_instance` 实际是死代码 | `providers/xtquant_provider.py:164-224` vs `core/rpc.py:105-150` | 定性判断：双实例路径会造成连接/回调混乱 | 收敛为单一 trader 管理器（见阶段 1） |
| B4 | **掘金交易通道用错 SDK**：gmtrade 模块实际指向 `gm.api`（策略 SDK），靠 RPC 调 `run(strategy_id=…)` 初始化 | `providers/gm_provider.py:117`、`api/gm.py:259-261`、`core/whitelist.py` gmtrade 列表 | 官方策略 SDK 的交易函数运行在 `run()` 驱动的策略上下文内；独立程序化交易应使用 **gmtrade SDK**：`pip install gmtrade` → `set_token` → `set_endpoint("api.myquant.cn:9000")`（接终端则空串）→ `account()/login()` → `order_volume/order_cancel/get_cash/get_position` → `start()` 消息泵接收 `on_order_status/on_execution_report` 等推送（掘金仿真官方 API 指引） | gmtrade 通道整体切换到 gmtrade SDK 并实现 login 生命周期；`run/stop/schedule/timer/universe_*` 等策略函数移出白名单；`set_serv_addr` 等 gm.api 独有函数与官方 gmtrade 接口名不符，需按 SDK 实测校正 |
| B5 | **gm.api 初始化调用存疑**：`set_account_id(...)` | `providers/gm_provider.py:80` | 已核对的官方快速开始/交易函数页未出现该函数；gmtrade 官方指引中账户是 `account()+login()` 传入。⚠️ 待实机验证 gm.api 是否导出此函数 | 实测确认；不存在则移除，改由 gmtrade login 流程承担 |
| B6 | **超时机制全线失效且阻塞事件循环**：async 端点内 `with ThreadPoolExecutor` + `future.result(timeout)` | `core/rpc.py:370`、`api/gm.py:311`、`api/xtquant.py:160` | with 上下文退出时 `shutdown(wait=True)` 会等慢调用跑完：超时既不生效，还把整个 asyncio 事件循环卡住（定性判断，Python 标准库语义） | 全局共享线程池 + `asyncio.wait_for(loop.run_in_executor(...))`；xttrader 同步调用同样入池；明确"超时后调用仍在后台执行"的语义并在响应中说明 |
| B7 | **WebSocket 行情回调跨线程断裂**：SDK 回调线程内 `asyncio.create_task` | `core/websocket.py:383、416` | create_task 需要运行中的事件循环；xtdata 回调来自 SDK 线程，异常被 except 吞掉 → 推送静默丢失（定性判断） | 启动时捕获主 loop，回调里用 `loop.call_soon_threadsafe(queue.put_nowait, msg)`；队列设上限与丢弃策略 |
| B8 | **subscribe_whole_quote 未传 callback** | `main.py:427` | 官方：`subscribe_whole_quote(code_list, callback=None)`，数据推送从 callback 返回 | 传入与单股订阅一致的回调工厂 |
| B9 | **订阅清理键名不匹配**：登记用 `id`，清理读 `seq` | `main.py:379-383` vs `core/websocket.py:232-235` | 断线后 `unsubscribe_quote` 永不执行 → 订阅泄漏，且 whole_quote 类型完全不清理 | 统一键名；按 sub_type 分别清理 quote/whole_quote；补断线清理测试 |
| B10 | **交易主推未接通**：注册的是基类 `XtQuantTraderCallback()`，未实现任何 on_* 方法；`create_trade_callback` 工厂无人调用；初始化后未 `subscribe(StockAccount)` | `core/rpc.py:138`、`core/websocket.py:393`、`main.py:_init_xttrader` | 官方：需继承回调类实现 on_stock_order/on_stock_trade/on_order_error/on_cancel_error/on_disconnected 等，并 `subscribe(account)` 后才有主推；connect 是一次性连接，断开不自动重连 | 实现 GatewayXtCallback 把事件桥接进 WS 队列；初始化流程补 subscribe；on_disconnected 触发重连与状态广播 |
| B11 | **start/connect 假成功**：RPC 对 start/connect 一律返回"已在初始化时执行"，即使初始化失败 | `core/rpc.py:175-176` | 定性判断：掩盖故障，客户端误以为交易通道可用 | 返回真实连接状态；提供 reconnect 能力；健康检查反映 trader 连接态而非仅模块可导入 |
| B12 | **重连令牌机制无效**：令牌可预测（client_id+时间戳）、disconnect 不清理、_handle_reconnect 只回 ack 不恢复任何状态 | `core/websocket.py:97-100`、`main.py:519-534` | 定性判断：安全性与功能性都不成立 | 要么实现完整会话恢复（secrets 令牌+订阅恢复），要么先移除该特性 |
| B13 | **同 client_id 重连覆盖旧连接**：旧 socket 与分发任务泄漏 | `core/websocket.py:87-88` | 定性判断 | 连接时检测同 ID 旧连接并主动关闭；分发任务随连接生命周期取消 |

### P2 一致性与工程质量

| 编号 | 问题 | 位置 | 修复方向 |
|---|---|---|---|
| C1 | 三套 RPC 执行逻辑、两套模块初始化并存，白名单/适配/超时行为不一致 | `core/rpc.py`、`api/gm.py`、`api/xtquant.py`、`main.py` | 收敛为 ProviderRegistry + 单一 RpcExecutor（阶段 1 核心） |
| C2 | README 宣称的端点不存在：`POST /api/v1/rpc/execute`、`GET /api/v1/rpc/methods`、`GET /api/v1/rpc/whitelist`（实际只有 /api/v1/gm/* 与 /api/v1/xtquant/*） | `README.md:214-297` | 统一路由规划后重写 README；或补统一入口 `/api/v1/rpc/execute`（带 provider 字段） |
| C3 | 响应结构不统一：xtquant 用 `elapsed`（秒）、gm/core 用 `execution_time_ms`（毫秒）；xtquant 请求模型缺 args/timeout（timeout 走 query 参数） | `api/xtquant.py:65-76、120-123` vs `models/common.py` | 统一 RpcExecuteRequest/响应模型，统一毫秒口径 |
| C4 | `serialize_data` 用 `dir()` 全量反射对象属性：可能触发 SDK 对象的 property 副作用、性能差、输出不稳定 | `providers/base.py:156-171` | 对 XtAsset/XtOrder 等已知结构用显式字段映射（dataclass/dict），未知类型降级 str |
| C5 | 配置项声明未使用：LOG_FILE（basicConfig 只输出控制台）、WS_HEARTBEAT_INTERVAL、MAX_CONNECTIONS、RPC_DEFAULT_TIMEOUT、CONNECT_TIMEOUT；GMConfig 无 mode/serv_addr 字段但代码多处 getattr 探测 | `config.py`、`main.py:31-34` | 配置清理：要么实现要么删除；补 GM endpoint、TDX 配置段 |
| C6 | 环境变量覆盖不全：JINGNI_ACCOUNT_ID、JINGNI_MINI_QMT_PATH、GM account_id 无覆盖入口（tests/README 却宣称支持）；`int(os.getenv("JINGNI_API_PORT"))` 无容错 | `config.py:189-208` | 统一 pydantic-settings 或补齐覆盖项与校验 |
| C7 | 依赖口径分裂：pyproject（>=范围）与 requirements（==锁定）不一致；requirements 重复列 pytest 三件套；**gm 与 gmtrade 均未列入依赖**；xtquant 手工复制无版本记录 | `pyproject.toml`、`requirements.txt` | 以 pyproject 为准单一来源；gm/gmtrade 入可选依赖组；记录 xtquant 来源版本 |
| C8 | 测试有效性差：大量 `data.get("success", False) or True` 恒真断言；依赖真实 SDK/终端在线；TestClient 有的触发 lifespan 有的不触发，行为不一致；`test_gm_data.py` 硬编码 2026 日期 | `tests/*` | 离线 mock 单测保底；集成测试显式标记（pytest marker + 环境开关）；断言真实化 |
| C9 | WebSocket 消息无 schema 校验、无大小限制；json.loads 失败直接断连；未知类型仅回错误 | `main.py:309-346` | pydantic 校验入站消息；非法消息回错误不断连 |
| C10 | GM 初始化重复执行（lifespan 里 _init_gm 后又 get/set 一遍）；`main.py` 导入 `_xttrader_instance as rpc_xttrader_instance` 是导入时快照，永远为 None（未使用的死代码） | `main.py:28、149-152` | 生命周期统一由 ProviderRegistry 管理 |
| C11 | 白名单含疑似不存在/过时函数名（如 gmtrade 的 `set_serv_addr`、`get_account_id`、`timer`；xtdata 的 `get_trading_time` 为 2024 年改名后函数，需按客户端版本核对） | `core/whitelist.py` | 启动时用 `getattr` 实测生成"可用函数清单"，白名单与之取交集并在 /rpc/methods 暴露真实可用集 |
| C12 | 无 CI、无 lint 门禁、无 .env.example、无部署/风控文档 | 仓库根 | 阶段 4 补齐 |

---

## 四、修复规划（阶段 0 / 1）

### 阶段 0：安全与仓库卫生（先决条件，改动小、收益大）

1. 作废并轮换已泄露的掘金 Token、检查 QMT/GM 账号安全（用户侧操作）。
2. 配置外置：`.env` + 环境变量（API_KEY、GM token/strategy_id/account_id/endpoint、MINI_QMT_PATH、ACCOUNT_ID、SESSION_ID），提供 `.env.example`；默认监听 127.0.0.1。
3. 解决 README 合并冲突；全库扫描冲突标记。
4. 白名单分级与裁剪：移除 run/stop/run_forever/set_token/set_serv_addr/schedule/timer/universe_*；资金划转、银证转账、export_data、order_close_all 归入"高危组"默认禁用。
5. 测试安全化：资金/下单类用例默认跳过（需 `JINGNI_ENABLE_LIVE_TESTS=1` + 仿真账户才执行）；移除 `set_token("test_token")` 这类污染全局状态的用例。

### 阶段 1：架构收敛 + 两网关正确性修复（tdxquant 接入的地基）

1. **ProviderRegistry 统一生命周期**：`main.py` lifespan 统一 initialize/cleanup 所有 provider；删除 `core/rpc.py` 全局模块变量与 `api/*` 私有执行函数，全部走 `BaseProvider.get_module_reference` + 单一 `RpcExecutor`。
2. **RpcExecutor 重写**：全局共享线程池；`asyncio.wait_for(run_in_executor)` 实现真异步超时；统一响应模型（success/data/error/execution_time_ms）；交易类调用审计钩子。
3. **XtQuant 修复包**（对应 B1/B2/B3/B10/B11）：
   - 两参构造 + register_callback；独立 session_id 配置；
   - 实现 `GatewayXtCallback(XtQuantTraderCallback)`：on_stock_order/on_stock_trade/on_order_error/on_cancel_error/on_order_stock_async_response/on_account_status/on_disconnected → 线程安全桥接 WS；
   - 初始化流程：create → register_callback → start → connect（校验返回 0）→ subscribe(StockAccount)；失败如实上报；
   - on_disconnected 触发受控重连（官方：connect 为一次性连接）。
4. **GM 修复包**（对应 B4/B5）：
   - gmdata 保持 gm.api + set_token（数据研究模式，官方支持）；
   - gmtrade 切换为独立 gmtrade SDK：set_token → set_endpoint → account/login → start 消息泵；on_order_status/on_execution_report 桥接 WS；
   - 登录态纳入健康检查；`order_cancel` 参数按官方 `wait_cancel_orders=[{cl_ord_id, account_id}]` 结构做适配与校验（现有测试传 `cl_ord_id="test_order_id"` 不符合官方签名）。
5. **WebSocket 修复包**（对应 B7/B8/B9/B12/B13/C9）：
   - 回调桥接改 `loop.call_soon_threadsafe`；队列上限+背压策略；
   - whole_quote 补 callback；订阅键名统一；断线全量反订阅；
   - 同 ID 重连处理；重连令牌要么完整实现要么移除；入站消息 pydantic 校验。
6. **序列化与白名单实测化**（C4/C11）：已知 SDK 对象显式字段映射；启动时生成真实可用函数清单。

阶段 1 验收：离线单测全绿；仿真环境下 xtquant/gm 各自完成"查询→下单→主推接收→撤单→断线清理"闭环；README 端点与实现一致。

---

## 五、tdxquant 接入评估与规划

### 5.1 平台事实（均来自官方文档，2026-11-19 核对）

1. **定位**：TdxQuant（TQ）是财富趋势（通达信）官方 Python 量化框架，2026-01-17 正式发布，迭代频繁（截至 2026-11-13 tqcenter 1.3.3）。
2. **两种核心模式**：
   - `tqcenter`（依赖客户端）：需预先启动支持 TQ 策略的通达信金融终端/专业研究/量化模拟版/期货通；核心文件为安装目录 `PYPlugins/user/tqcenter.py`（官方明示勿删改）；外部 IDE 调用需 `sys.path.append('<安装目录>/PYPlugins/user')` 后 `from tqcenter import tq`，且**必须 `tq.initialize(__file__)` 初始化**，结束 `tq.close()`。
   - `tqserver`（即 tdxaidata，不依赖客户端）：`pip install tdxaidata`，`from tdxaidata import tqs`；需在 TdxAiData.ini 配置付费数据服务 Key（通达信商城创建）；跨平台（Win/macOS/Linux）。**官方明确：不提供交易功能、不提供客户端交互、不支持本地自选板块**。
3. **（已否决）本地 HTTP**：客户端模式下可直接 `POST http://127.0.0.1:17709/`，请求体 `{"id":1,"method":"<TdxQuant函数名>","params":{…}}`，返回 `{"id":1,"result":{…}}`；result 内含 `ErrorId`（"0" 为成功）、`Value`、分页字段（stock_page_index/stock_page_size/has_more 等），数值多为字符串。**本机实测：它是 tqcenter 的 MCP 子集，参数类型零校验，整数 `order_id` 可直接击穿客户端进程，已从本方案删除（见 `tdx-spike-实测记录.md` 4.3 / 4.5）。**
4. **交易 API**（tqcenter）：
   - `tq.stock_account(account="资金账号", account_type="STOCK")` → 返回 int 账户句柄；
   - `tq.order_stock(account_id, stock_code, order_type, order_volume, price_type, price, notify)` → 返回 `{Value, Wtbh, Msg, ErrorId}`；**Value：0 失败 / 1 待用户确认 / 2 成功**；Wtbh 为委托编号（字符串）；
   - `order_type`：STOCK_BUY=0、STOCK_SELL=1（另有信用/ETF/期货/期权类型）；`price_type`：PRICE_MY=0 自填价、PRICE_SJ=1 市价、PRICE_ZTJ=2 涨停价、PRICE_DTJ=3 跌停价；市价具体方式在客户端系统设置中配置；沪深可转债不支持市价；
   - **实盘账户默认弹窗让用户确认；自动下单需联系开户券商开通并使用支持 TQ 的版本**；模拟账户自动下单（2026-03-27 版本说明）；
   - `tq.cancel_order_stock(account_id, stock_code, order_id)` → 官方文档：Value 0 失败 / 1 成功；**本机实测 `Value=0` 可能是假失败，撤单会异步生效，必须以委托状态对账**（见 5.4 第 4 条）；
   - 查询：`query_stock_asset`、`query_stock_orders`（2026-06-25 起支持只查可撤委托）、`query_stock_positions`、`query_history_trade`（2026-09-20 新增）。
5. **数据 API**（tq 与 tqs 大部分同名通用）：`get_market_data(field_list, stock_list, period, start_time, end_time, count, dividend_type, fill_data)`（返回 dict{字段: DataFrame}，字段名首字母大写 Open/High/Low/Close/Volume/Amount/ForwardFactor）、`get_market_snapshot`、`get_financial_data`、`get_trading_dates`、`get_divid_factors`、`get_stock_list`、`get_sector_list`、`get_stock_list_in_sector`、`get_kzz_info`（原 get_cb_info 改名）等；tqs 特有 `subscribe/unsubscribe`、`get_tick_data`、`get_call_auction` 等。
6. **代码格式**：`600000.SH / 000001.SZ`，与 xtquant 完全一致 → SymbolConverter 无需新增映射，直接复用 xtquant 格式。
7. **环境**：64 位 Python 3.7–3.14（官方建议 3.13）；本项目 requires-python>=3.9，兼容。依赖 DLL：`TPythClient.dll`、`tdxrpcx64.dll`（官方 FAQ：杀毒软件误杀会导致初始化失败，需白名单）。
8. **稳定性风险**：版本说明显示函数频繁改名/新增（get_report_data→get_full_tick→get_market_snapshot；get_cb_info→get_kzz_info；返回字段 Data→Value），白名单与适配层必须版本化。
9. **前复权口径**：官方 FAQ 明确——取某日前复权值需 `count=-1` 取全量数据再定位，截取区间会导致复权因子不一致（与掘金定点复权语义不同，文档需向调用方说明）。

### 5.2 接入路径：tqcenter 单通道

| 路径 | 形态 | 结论 |
|---|---|---|
| A. 本地 HTTP 桥接（127.0.0.1:17709） | POST method/params | **删除，不采用**：方法子集、参数类型零校验、整数 `order_id` 可击穿客户端进程（实测崩溃，见实测记录 4.3） |
| B. tqcenter 直连 | `sys.path` + `tq.initialize` | **唯一通道**：数据 + 交易全链路已实测通过 |
| C. tdxaidata（tqs） | pip 包 + 付费 Key | 仅作可选数据冗余，**无交易功能** |

**为什么删除 HTTP**：除 4.3 的进程崩溃外，HTTP 还是 tqcenter 的裁剪子集——`get_version`、tick/分钟线、订阅、`query_history_trade` 等均返回"不支持"；`field_list` 被忽略、周期名与数值类型另有偏差。把交易押在它上面，等于同时承担"能力缺失 + 进程崩溃 + 参数无校验"三重风险。

**tqcenter 直连的代价**：DLL 依赖（`TPythClient.dll`、`tdxrpcx64.dll` 需杀软白名单）、必须 `tq.initialize(__file__)`、与终端版本强耦合、同机"已存在运行策略"冲突。这些是可控的工程约束，优于不可控的进程崩溃。

### 5.3 模块设计（对齐阶段 1 收敛后的架构）

```
providers/tdx_provider.py        TdxProvider(BaseProvider)
  ├─ transport: TqCenterTransport（唯一实现）
  ├─ name="tdxquant"；模块划分：tdxdata / tdxtrade
  ├─ initialize(): sys.path + tq.initialize(__file__)；记录终端与 tqcenter 版本
  ├─ cleanup(): tq.close()
  └─ get_module_reference(): 返回适配器对象

core/tdx_adapter.py（新增）
  ├─ 请求归一化：kwargs → 显式参数；ErrorId≠"0" → error（区分 2/6/7/9）
  ├─ 响应归一化：dict / DataFrame → 统一 JSON；保留 Date/Time/Wtbh/Code 为字符串
  ├─ 账户句柄管理：account_id(str) → handle(int) 缓存；句柄失效(ErrorId=9)时重建
  └─ 交易对账：委托状态轮询（Status 0/4/5）+ Cash 变化，判定真实结果

api/tdxquant.py                  /api/v1/tdxquant/*（health、rpc/execute、rpc/methods、rpc/whitelist）
core/whitelist.py                新增 tdxdata / tdxtrade 两组白名单（分级）
config.py                        TDXConfig：enabled、tdx_install_path、python_dll_dir、
                                 account、account_type、timeout、cancel_reconcile_timeout
```

白名单初版建议（以官方已核对函数为准，启动时实测交集）：

- tdxdata：get_market_data、get_market_snapshot、get_market_snapshot_batch、get_stock_info、get_more_info、get_financial_data、get_financial_data_by_date、get_trading_dates、get_divid_factors、get_stock_list、get_sector_list、get_stock_list_in_sector、get_kzz_info、get_zdt_data、get_gb_info、get_version
- tdxtrade（默认关闭，显式开启）：stock_account、query_stock_asset、query_stock_orders、query_stock_positions、query_history_trade、order_stock、cancel_order_stock
- 明确不入白名单：exec_to_tdx（操控客户端界面）、send_warn/send_user_block 等交互类（二期评估）、公式写入类

### 5.4 关键语义适配（必须向调用方透传的差异）

1. **下单三态**：`Value=0` 失败 / `1` 待用户确认 / `2` 已受理（**不等于成交**）；响应增加 `order_state: failed|pending_confirm|accepted`，并保留 `Msg`、`Wtbh`。实盘自动确认依赖券商 TQ 版本，`auto_confirm_policy` 只做展示与校验，不假装能绕过确认。
2. **委托编号为字符串（Wtbh）**：与 xtquant 的 int order_id、gm 的 cl_ord_id 不同，统一交易响应模型中 `order_id` 用 str 承载。
3. **撤单参数必须精确**：`account_id` 只能是 `stock_account` 返回的 **int 句柄**（传资金账号会报"账户句柄不存在" ErrorId=9）；`stock_code` 必须带后缀（传 `600000` 报 `codestr error` ErrorId=2）；`order_id` 必须是 `Wtbh` 字符串。
4. **撤单"假失败、真异步"（本方案最重要的修正）**：`cancel_order_stock` 返回 `Value=0`「撤单提交失败」时，委托可能已在 5 秒内变为 `Status=0`、25 秒后资金解冻。**禁止以返回值判定失败，更禁止据此重试**；唯一可信判据是轮询 `query_stock_orders` 的 `Status ∈ {0,4,5}` 且 `Cash` 恢复，超时（建议 30s）未变才判失败。
5. **查询过滤失效**：`query_stock_orders(account_id, stock_code=...)` 在本机返回 `[]`，必须查全量再本地过滤；`cancelable_only=True` 正常可用（实测只返回可撤委托）。
6. **资产字段口径不可靠**：`MarketValue` 持仓 100 股时仍为 `0.00`、`TotalFreeze` 冻结资金时仍为 `0.00`、`Asset` 与 `Cash` 变动不同步；**风控只用 `Cash`，市值自行按行情估值**。
7. **下单最终一致**：`order_stock` 返回后委托可能几秒后才出现在查询中、冻结资金约 30 秒后才反映；网关需有"已提交待确认"中间态，不能立即断言成功/失败。
8. **行情订阅推送**：tqcenter 的 `subscribe`/回调形态官方页面未完整覆盖，列为阶段 2 验证项；验证前先用主动查询（`get_market_snapshot`/`get_market_data`），WS 推送可用"定时快照轮询"降级并明确标注。
9. **复权口径**：官方 FAQ 明确取某日前复权值需 `count=-1` 取全量再定位，截取区间会导致复权因子不一致（与掘金定点复权语义不同，文档需向调用方说明）。

### 5.5 实施阶段与验收

**阶段 2：tdxquant 数据接入（tqcenter 单通道）**
1. 环境与版本固化：启动支持 TQ 的终端并登录；记录终端版本 + tqcenter 版本；`TPythClient.dll`/`tdxrpcx64.dll` 加杀软白名单。
2. 实现 `TdxProvider` + `TdxTradeService` + `/api/v1/tdxquant/*` 路由 + 白名单 + `TDXConfig`；不引入 HTTP transport。
3. 数据验收：日线/快照/板块/交易日经网关可调；`1m/5m` 是否需客户端下载后非空、`1min/5min/60m` 报 `ErrorId=5`、`field_list` 被忽略——逐项实测并在文档标注。
4. 客户端未启动/未登录时健康检查如实报 OFF 且错误可读；离线单测（mock tqcenter）全绿。

**阶段 3：tdxquant 交易接入**
1. 四件套：`stock_account` / `order_stock` / `cancel_order_stock` / 三类查询。
2. **交易对账器**：下单后轮询委托出现（几秒延迟）；撤单后轮询 `Status 0/4/5` + `Cash` 解冻，超时 30s 才判失败；`Value=0` 先查状态，仍为 1 时有界重试提交（最多 5 次），禁止不看状态的无脑重试。
3. 三态语义、审计、高危开关、幂等（`Wtbh` 去重）落地。
4. **模拟账户 `11048389` 闭环已通过**：下单 `227988`（Value=2）→ 查委托 `Status=1` → 撤单返回 `Value=0`，5s 后 `Status=0`、25s 后资金解冻；对照单 `231867` 3 分钟不撤保持 `Status=1`。
5. 实盘仅验证"待确认"链路，自动下单能力以券商开通为准，文档明示。
6. 验收：模拟闭环通过；实盘待确认语义正确透传；断连/终端退出时错误可读、不悬挂。

**当前落地进度（2026-11-19）**

| 项 | 状态 | 证据 |
|---|---|---|
| `TdxProvider`（import/initialize 分离、句柄缓存、health/cleanup） | 完成 | `providers/tdx_provider.py` |
| `TdxTradeService`（下单三态、撤单对账+重试、查询归一化） | 完成 | `core/tdx_trade.py` |
| `/api/v1/tdxquant/*` 路由（数据 RPC + 类型化交易） | 完成 | `api/tdxquant.py` |
| `TDXConfig` + `.env` 覆盖 | 完成 | `config.py`、`.env`（已 gitignore） |
| 数据 RPC 严格参数校验、`tdxtrade` 通用 RPC 拒绝 | 完成 | `core/rpc.py`、`api/tdxquant.py` |
| 网关真实下单/撤单 | 完成 | 委托 `274203`：`Value=2` → 撤单 3 次轮询内 `Status=0`，`Cash` 回到 `998908.59` |
| mock 单测 | 完成 | `tests/test_tdx_trade.py` 6 例；全量 `23 passed, 7 skipped` |
| `notify=1`、分钟周期、`field_list`、实盘自动下单 | 部分完成 | `notify=1` 已验证 `pending_confirm`；`get_stock_list` 正确参数已复核；分钟线受本地终端盘后数据/Level2 限制为空；实盘自动下单待交易时段/小额验证 |

**阶段 4：测试与工程加固**
1. 三网关统一离线单测（mock SDK/tqcenter）+ 仿真集成测试（显式开关）；
2. CI（lint + 离线单测）、.env.example、部署文档（含杀软白名单、客户端版本要求、tqcenter 版本记录）；
3. README 重写：三网关能力矩阵、端点、语义差异表（下单返回、代码格式、复权口径、推送机制）。

### 5.6 风险与开放问题

| 风险 | 等级 | 应对 |
|---|---|---|
| tqcenter/终端接口迭代快（官方版本说明几乎每周一更，函数改名有先例） | 高 | 白名单启动实测交集；适配器集中收敛字段映射；记录终端+tqcenter 版本；升级前跑回归 |
| 实盘自动下单受券商版本限制 | 高 | 产品语义上承认"待确认"为正常态；不承诺无人值守实盘 |
| 撤单返回 `Value=0` 假失败、查询过滤失效、资产字段不全 | 高 | 交易对账器（轮询 `Status` + `Cash`）；查询全量再本地过滤；风控只用 `Cash`；不依赖接口返回值 |
| DLL 被杀软误杀、多客户端 TQ 冲突、"已存在运行策略"报错 | 中 | 部署文档列官方 FAQ 处置步骤；initialize 失败给出可读诊断 |
| tdxaidata 为付费数据服务 | 中 | 不纳入默认依赖；单独立项评估 |
| 三网关语义差异导致调用方误用 | 中 | 统一响应模型 + 能力矩阵文档 + 代码格式/枚举映射表 |

### 5.7 P0 / P1 落地进度（2026-11-19）

| 项 | 状态 | 说明 |
|---|---|---|
| P0 阻塞函数黑名单 | 完成 | `xtdata.run`/`xttrader.run_forever`/`gmtrade.run` 已移除并加黑名单 |
| P0 统一串行执行器 + 超时 | 完成 | `core/executor.py` 按 `data/trade/bulk` lane 分池；tdxquant 因单客户端特性收敛为单串行 |
| P0 RPC 参数严格校验 | 完成 | 未知参数/缺必填报 `INVALID_ARGUMENT`，不再静默丢弃 |
| P0 凭据收口 | 完成 | `config.py` 已移除 GM token/strategy/account、QMT 账号、默认 API Key；全部走 env；API Key 未配置时返回 503；监听默认 `127.0.0.1` |
| P0 健康检查语义 | 完成 | main/xtquant/gm/tdx 均返回 `healthy/degraded`；tdx `/health` 增加 `logged_in` 与资产探测 |
| P0 tdx 下单幂等 | 完成 | `client_order_id` 进程内缓存 10 分钟/1000 条；重启丢失，需持久化时再升级 |
| P0 README/版本 | 完成 | 冲突标记已清理；`pyproject.toml`、`main.py`、`api/gm.py` 统一 `2.0.0` |
| P1 xtquant 类型化交易 | 完成（离线） | `/api/v1/xtquant/trade/*`；下单/撤单从通用 RPC 白名单移除；mock 4 例 |
| P1 GM 类型化交易 | 完成（模拟闭环） | `/api/v1/gm/trade/*`；订单写操作从通用 RPC 移除；GM SDK `3.0.193` 仅保留行情/数据；交易切到 `gmtrade==3.0.6`（项目 `.venv310`，Python 3.10）；`gmtrade_bridge.py` + `gmtrade_proxy.py` 已接入。模拟账户 `100000.00`：9.66 限价买入 `accepted`，撤单后 `status=5`，资金不变、无持仓、无活动委托 |
| P1 WebSocket 限额/心跳 | 完成 | `MAX_CONNECTIONS`、同 client_id 替换、心跳超时关闭、`ping/pong` |
| P1 数据契约测试 | 完成 | DataFrame 序列化 + tdx 日线黄金样本 |
| P1 TDX notify 与跨重启幂等 | 完成（模拟验证） | `notify=1` 返回 `pending_confirm`；pending 也缓存；SQLite 持久化，新进程同 key 返回 `idempotent_replay=true` |
| 实盘验证 | 待办 | TDX 模拟登录态已恢复（`logged_in=true`、cash `998908.59`）；收盘后 OMS 返回 `服务未就绪(OMS)`，真实 accepted 委托闭环需交易时段；GM 模拟账户 gmtrade 闭环已通过，实盘小额验证待做；xtquant 无 SDK（`D:\gjzq` 只有 ptrade，无 QMT）；实盘自动下单需小额验证 |

---

## 六、需要用户确认/提供的事项

1. GM Token/strategy_id/account_id 已在 `.env` 配置，`JINGNI_GM_ENABLED=1`；GM SDK `3.0.193` 已装入项目 `.venv`，`six` 已补装。`get_instruments/history_n` 与 `get_cash/get_position/get_orders` 真实通过；已定位并移除导致 1013 的 `api.set_account_id()`。当前为模拟账户（`nav=100000.00`）。交易侧已改用 `gmtrade 3.0.6`：因无 cp311 wheel，装在项目 `.venv310`（Python 3.10），由 `tools/gmtrade_bridge.py` 提供 JSON Lines sidecar；网关 `/api/v1/gm/trade/order` 和 `/cancel` 已在模拟账户完成 `accepted → canceled` 闭环，资金不变、无持仓。
2. D1 已拍板"网关管交易"；P0/P1 已按阶段实施，类型化交易端点已落地，通用 RPC 不再暴露下单/撤单。
3. tdxquant 环境已确认：本机终端 + 模拟账户 `11048389`，下单/查委托/撤单闭环已验证；2026-11-19 16:36 重新登录后 `logged_in=true`、资产可查；`notify=1` 已验证为 `pending_confirm`，跨重启幂等已用 SQLite 验证。收盘后 OMS 返回“服务未就绪”，真实委托闭环需交易时段。实盘 TQ 自动下单权限已确认开放，仍建议先做小额实盘验证。
4. 高危函数（资金划转、银证转账、一键清仓、export_data）已从通用 RPC 白名单移除，类型化端点也未开放这些能力。
5. Git 历史中的旧凭据清理（filter-repo 等）属破坏性操作，需单独授权；当前代码已不含旧值。

---

## 附：核对来源

- 掘金 SDK 快速开始（set_token/history/策略 run 模式）：https://www.myquant.cn/docs2/sdk/python/%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B.html
- 掘金交易函数（order_volume/order_cancel 签名与注意点）：https://www.myquant.cn/docs2/sdk/python/API%E4%BB%8B%E7%BB%8D/%E4%BA%A4%E6%98%93%E5%87%BD%E6%95%B0.html
- 掘金仿真 API 接入指引（gmtrade SDK：set_endpoint/account/login/start 与事件）：https://sim.myquant.cn/sim/help
- XtQuant 总览：https://dict.thinktrader.net/nativeApi/start_now.html
- XtQuant 行情模块（subscribe_quote/subscribe_whole_quote/get_market_data/get_financial_data 签名）：https://dict.thinktrader.net/nativeApi/xtdata.html
- XtQuant 交易模块（XtQuantTrader(path, session_id)/register_callback/connect 一次性/subscribe(account)/回调类/枚举）：https://dict.thinktrader.net/nativeApi/xttrader.html
- TdxQuant 简介（双模式/Python 版本/客户端要求）：https://help.tdx.com.cn/quant/
- TdxQuant 安装终端（PYPlugins/user/tqcenter.py、initialize、盘后数据下载）：https://help.tdx.com.cn/quant/docs/markdown/mindoc-1cfsjkbf8f3is/mindoc-1d00kk3jsibbc.html
- TdxQuant 外部调用 FAQ（sys.path、DLL 依赖、前复权口径、策略冲突）：https://help.tdx.com.cn/quant/docs/markdown/mindoc-tdxpy.html
- TdxQuant 交易执行函数 order_stock（参数/三态返回/实盘确认）：https://help.tdx.com.cn/quant/docs/markdown/mindoc-1h7k4iqb1grk4/mindoc-1h7k5j4drr928.html
- TdxQuant 撤单 cancel_order_stock：https://help.tdx.com.cn/quant/docs/markdown/mindoc-1h7k4iqb1grk4/mindoc-1h84elp5atr6o.html
- TdxQuant HTTP 方式调用（127.0.0.1:17709、请求/响应/分页结构）：https://help.tdx.com.cn/quant/docs/markdown/mindoc-1hdhbmi50d038.html
- TdxAiData 后台接口（tqs、付费 Key、无交易功能、支持函数清单）：https://help.tdx.com.cn/quant/docs/markdown/mindoc-1hjbgqpdhv114.html
- TdxQuant 版本更新说明（发布时间/函数改名史/交易功能演进）：https://help.tdx.com.cn/quant/docs/markdown/mindoc-1cfsjkbf8f3is/TdxQuantVersion.html
