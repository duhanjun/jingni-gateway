# tdxquant 接入实测记录（最终：tqcenter 单通道）

- 实测时间：2026-11-19 11:25–13:30
- 环境：`<TDX_HOME>`，通达信金融终端（量化模拟）V7.73，模拟资金账户 `11048389`
- 方式：先探测 HTTP `127.0.0.1:17709`（已否决并删除），最终只保留 `tqcenter` 直连
- 状态：数据面 + 交易面（下单 / 查委托 / 撤单）全链路已验证

---

## 一、结论先行

1. **HTTP 不是"全量 tqcenter"**，而是一个方法子集；参数类型无校验、可击穿客户端进程，已决定整个删除（见 4.5）。
2. **HTTP 模式没有推送、没有 tick/分钟线**（`subscribe`/`unsubscribe`/`get_tick_data`/`get_minute_data` 均不在服务端方法表内）。
3. **参数命名与官方文档不完全一致**：`account_type` 大小写敏感、`get_stock_list` 的参数名对不上、`field_list` 被忽略。
4. **缺参时存在"成功但空结果"**：`query_stock_asset` 不传账户返回 `ErrorId=0 + Value=[]`，不能作为"无持仓/无资金"的判据。
5. **撤单是"假失败、真异步"**：`cancel_order_stock` 返回 `Value=0`，但 5s 内委托变 `Status=0`、25s 后资金解冻；对照单 3 分钟不撤始终保持 `Status=1`。
6. **查询过滤与资产字段不可靠**：`query_stock_orders(stock_code=...)` 返回空，必须查全量本地过滤；`MarketValue`/`TotalFreeze` 恒为 0，只有 `Cash` 可信。

---

## 二、HTTP 方法支持矩阵（已废弃，仅作证据留存）

| 方法 | HTTP 是否支持 | 实测表现 |
|---|---|---|
| `get_market_data` | 支持 | 日线正常；`count=-1` 返回 12001 根、104KB、54ms |
| `get_market_snapshot` | 支持 | 单标的快照正常，字段全为字符串 |
| `get_sector_list` | 支持 | 返回板块代码列表 |
| `get_stock_list_in_sector` | 支持 | 缺 `block_code` 时报错，补参可用 |
| `get_stock_list` | 支持（参数待定） | 传 `market`/`list_type`（int 或 str）均报"参数缺少:market/list_type" |
| `get_trading_dates` | 支持 | 不带参数返回全量历史（20210802 起），无分页/区间约束 |
| `get_divid_factors` | 支持 | 缺 `stock_code` 报 `ErrorId=2` |
| `get_stock_info` / `get_more_info` / `get_kzz_info` | 支持 | 缺代码报 `ErrorId=2` |
| `get_financial_data` | 支持 | 必须带 `table_list`，否则报错 |
| `stock_account` | 支持 | 见第四节 |
| `query_stock_asset` | 支持 | 无账户 → `ErrorId=0, Value=[]` |
| `query_stock_orders` | 支持 | 同上 |
| `query_stock_positions` | 支持 | 同上 |
| `get_version` | **不支持** | `MCP不支持该tqcenter方法名` |
| `get_tick_data` | **不支持** | 同上 |
| `get_minute_data` | **不支持** | 同上 |
| `get_call_auction` | **不支持** | 同上 |
| `query_history_trade` | **不支持** | 同上 |
| `query_account_infos` | **不支持** | 同上 |
| `subscribe` / `unsubscribe` | **不支持** | 同上 |
| `tools/list` | **不支持** | 同上 |

> 服务端错误分两类：`{"error":{"code":-32601,"message":"MCP不支持该tqcenter方法名"}}` 表示方法不在白名单；`result.ErrorId` 非 0 表示方法在、参数或数据有问题。

---

## 三、HTTP 行情行为细节（已废弃）

| 项 | 实测 |
|---|---|
| 日线 | `period="1d"` 正常；`600000.SH` 最近 5 根 Close = 9.00 / 9.16 / 10.63 … |
| 全量 | `count=-1` 返回 12001 根，响应约 104KB，54ms |
| 多标的 | 支持，`KlineTotal` 按标的分别计数 |
| 15m / 30m / 1h | 能识别，但只返回 1 根 |
| 1m / 5m | 能识别，但 `Value=[]`（本地无分钟数据） |
| 1min / 5min / 60m / day | `ErrorId=5`（周期名不合法） |
| `field_list` / `fields` | **均被忽略**，始终返回全部字段 |
| 字段形态 | 全部字符串；`Date="20261119"`、`Time="0"`、`Volume="27562050.00"` |
| 前复权 | `ForwardFactor` 随数据返回；`000001.SZ` 样本出现 `0.000000`，需核查口径 |
| 分页 | `KlinePaged=true`、`has_more=false`、`stock_page_*`、`KlineTotal` |

**含义**：若网关要提供分钟线/tick/实时推送，HTTP 不够，必须走 tqcenter 直连（方案里的路径 B），
且 tqcenter 与本机终端版本绑定，需要版本记录与回归。

---

## 四、交易面

### 4.1 账户与查询（HTTP 时代，已废弃）

| 测试 | 结果 |
|---|---|
| `stock_account(account="11048389", account_type="stock")` | `ErrorId=0, Value=1`（句柄 = 1） |
| `stock_account` + `account_type="STOCK"` | `ErrorId=9, "account_type error:"` |
| `stock_account` 空账号 | `ErrorId=9, "资金账户未登录或不存在。"` |
| `query_stock_asset(account_id=1)` | 总资产 1000112.59，可用 998908.59 |
| `query_stock_positions(account_id=1)` | 000001.SZ，TotalVol 100，CanUseVol 100 |
| `query_stock_asset` 不传账户 | `ErrorId=0, Value=[]`（成功但空，危险） |

**关键差异（HTTP 时代）**：官方文档示例写 `account_type="STOCK"`，HTTP 层对大写直接报参数错；**tqcenter 直连不区分大小写**（4.4 已复测）。参数取值必须逐版本、逐通道实测。

### 4.2 下单与撤单（tqcenter 直连，已验证）

| 步骤 | 调用 | 结果 |
|---|---|---|
| 下单 | `order_stock(1, "600000.SH", STOCK_BUY, 100, PRICE_MY, 9.70, notify=0)` | `Value=2`、`Wtbh="227988"`、`Msg="提交交易成功！"` |
| 查委托 | `query_stock_orders(1)` | `Status=1`、`BSFlag=0`、`WtVol=100` |
| 可撤查询 | `query_stock_orders(1, cancelable_only=True)` | 只返回 `227988`，过滤正确 |
| 撤单 | `cancel_order_stock(1, "600000.SH", "227988")` | **`Value=0`「撤单提交失败」**，但随后 `Status=0`、`BSFlag=-1`，资金解冻 |

**关键结论：撤单是"假失败、真异步"。** 对照实验（委托 `231867`，3 分钟不撤）：

| 时点 | Status | Cash |
|---|---|---|
| 下单后 0–180s（未撤单） | 1（始终有效） | 冻结后稳定在 997895.29 |
| 调用撤单 | — | 返回 `Value=0`、`Msg=撤单提交失败` |
| 撤单后 5s | **0 / BSFlag=-1** | 仍冻结 |
| 撤单后 25s | 0 | **解冻回 998908.59** |

因此：**`cancel_order_stock` 的返回值不能作为撤单成功判据**；唯一可信判据是 `query_stock_orders` 中 `Status ∈ {0,4,5}` 且冻结资金释放。对照单 3 分钟不撤始终保持 `Status=1`，排除"委托到期自动失效"。

查询/撤单侧的三个异常（疑似客户端 DLL 的过滤与字段实现问题）：

- `query_stock_orders(acct, stock_code="600000.SH")` 返回 `[]`，必须查全量再本地过滤；传 `600000` 同样无效。
- `query_stock_orders(acct, cancelable_only=True)` 正常。
- 撤单 `stock_code` 必须是 `600000.SH`：传 `600000` 报 `codestr error:600000`（ErrorId=2）；传 `account_id=11048389` 报"账户句柄不存在"（ErrorId=9），确认必须传 `stock_account` 返回的句柄。

HTTP 时代的对照：同样返回 `Value=2`、`Wtbh="211428"`，但整数 `order_id` 直接击穿客户端（见 4.3），故 HTTP 废弃。

**`Status` 枚举（从本机 `tqcenter.py` 源码提取）**

| 值 | 含义 |
|---|---|
| 0 | 无效单 |
| 1 | 未成交 |
| 2 | 部分成交 |
| 3 | 全部成交 |
| 4 | 部分撤单 |
| 5 | 全部撤单 |

### 4.3 客户端崩溃（重要）

- 12:45:50 发送 `order_id` 为整数的撤单请求后，HTTP 连接先报发送错误，随后 `127.0.0.1:17709` 拒绝连接，`TdxW` 与 `tdxcef` 进程全部消失。
- Windows 事件日志：
  - 12:45:50 `tdxw.exe` 崩溃，模块 `MSVCR100.dll`，异常码 `0x40000015`
  - 12:46:00 `tdxw.exe` 再次崩溃，模块 `KERNELBASE.dll`，异常码 `0xe06d7363`（未捕获 C++ 异常）
- 时间与请求完全吻合，**高度疑似由参数类型不匹配触发**，非终端自身不稳定。

**含义**：17709 是一个无参数类型校验的明文桥接层，错误类型可以直接击穿客户端进程。
这比"返回错误码"严重一个量级，直接否定把交易主通道押在 HTTP 上的可行性。

### 4.4 tqcenter 直连：登录前后对比

| 测试 | 未登录（12:50） | 已登录（13:05） |
|---|---|---|
| `tq.initialize(__file__)` | 成功 | 成功 |
| `stock_account("11048389", "stock"/"STOCK")` | 句柄 `1` | 句柄 `1` |
| `query_stock_asset(1)` | `{"ErrorId":"0","Value":[]}` | Asset `1000111.59` / Cash `998908.59` |
| `query_stock_positions(1)` | `[]` | `000001.SZ`，`TotalVol=100`、`CanUseVol=100` |
| `query_stock_orders(1)` | `[]` | 空（下单后出现 `227988`） |

**判定**：`stock_account` 返回句柄**不代表账户已登录**；必须用"资产非空 + 持仓/委托可查"做二次判定。未登录时查询返回 `ErrorId=0 + 空`，无法与"空账户"区分。

**资产字段口径异常（不可直接用于风控）**：

| 字段 | 实测 | 结论 |
|---|---|---|
| `MarketValue` | 持仓 `000001.SZ` 100 股，但恒为 `0.00` | 市值不计算，需自行用行情估值 |
| `TotalFreeze` | 买入冻结 1,013.30 时仍为 `0.00` | 冻结额不可信，需用 `Cash` 变化推断 |
| `Asset` | 冻结期间保持 `1000111.59`，与 `Cash` 变动不同步 | 总资产口径不一致，不能做风控基准 |
| `Cash` | 冻结时 `997895.29` → 撤单后 `998908.59` | **唯一可用的资金字段** |

### 4.5 决定：删除 HTTP 通道

- 依据：4.3 的客户端崩溃 + 4.1/4.2 的方法子集与参数类型问题。
- 结论：**tdxquant 只保留 tqcenter 直连**，17709 HTTP 不进入网关实现。
- 影响：方案 5.2/5.3/5.4/5.5 已按 tqcenter 单通道重写（HTTP 相关设计全部删除）。

---

## 五、对《代码问题评估与tdxquant接入规划》的修正（已按决定收敛为单通道）

| 方案原文 | 修正 |
|---|---|
| 5.2 路径 A「HTTP 主通道（推荐）」 | **删除**。依据见 4.3：方法子集、参数类型无校验、可击穿客户端进程 |
| 5.2 路径 B「tqcenter 备选/二期」 | **升为唯一通道**；C（tdxaidata）仅作可选数据冗余，仍不承担交易 |
| 5.3 `TdxHttpTransport（主）/ TdxCenterTransport（备）` | 只保留 `TqCenterTransport`；删除 HTTP host/port、分页聚合、字符串数值归一化 |
| 5.3 配置段 `mode(http|tqcenter)、http_host/http_port` | 删除；改为 `tdx_install_path`、`python_dll_dir`、`account`、`account_type`、`timeout` |
| 5.4「字符串数值 → float/int、分页聚合」 | 不再需要（tqcenter 返回原生类型/DataFrame）；改为显式 `serialize_data` 字段映射 |
| 5.4「账户句柄 HTTP 模式待验证」 | 已验证：`tq.stock_account(account, "stock")` 返回 int 句柄；未登录时也返回句柄，需二次校验 |
| 5.5 阶段 2/3 的「A 或 B」二选一 | 取消二选一，直接按 tqcenter 实施 |
| 5.4「撤单返回 `Value=0` 即失败」 | **修正**：`Value=0` 是假失败，撤单异步生效（5s 状态变 0、25s 资金解冻）；必须以委托状态对账 |

**保留且仍然成立的部分**：5.1 的平台事实（除 HTTP 一条改为"已实测、不采用"）、5.4 的下单三态、`Wtbh` 字符串、撤单需 `stock_code + order_id`、复权口径提醒。

---

## 六、下一步

**已完成**

- 登录 `11048389`，资产/持仓非空；
- 下单 → 查委托 → 撤单全链路跑通（`227988` / `229869` / `231867`）；
- 确认撤单异步生效、返回值是假失败；
- 确认 `cancelable_only=True` 过滤正确；
- 网关 `TdxProvider` + `TdxTradeService` + `/api/v1/tdxquant/*` 端点落地，网关真实下单 `274203`、撤单确认 `Status=0`、资金回到 `998908.59`。

**待补**

1. `notify=1` 的行为（可能弹确认框，风险高，暂不做）；
2. 周期映射：`1d` 正常、`1m/5m` 是否需客户端下载后才非空、`1min/5min/60m` 为何报 `ErrorId=5`；
3. `field_list` 被忽略、`ForwardFactor=0` 的复权口径；
4. 多笔并发/长时间挂单下的顺序与限流（TQ 是单线程同步 C API）。

---

## 七、对网关设计的硬性要求（由本次实测得出）

1. **参数类型强校验**：所有 provider 参数先过 schema 校验，`order_id` 一律字符串、`account_id` 一律整数；类型不符直接 400，绝不透传。
2. **初始化是一等状态**：`tq.initialize()` 失败、终端未启动、账户未登录、账户已登录但无数据，必须对应四个不同状态；`stock_account` 返回句柄不代表已登录。
3. **进程级故障可观测**：`CLIENT_CRASHED`、`INIT_FAILED` 要进错误码枚举；健康检查要同时探测"终端进程存活 + 初始化成功 + 账户可查"。
4. **禁止盲目重试**：下单、撤单失败后先查委托状态，再决定动作，避免重复报单。
5. **单通道不等于无线程约束**：tqcenter 是同步 C API，仍应放在独立串行执行器里，不要直接在事件循环调用。
6. **撤单结果必须对账**：`Value=0` 一律视为"未知"，先查委托状态（0/4/5）与 `Cash` 解冻；若状态仍为 1，允许**有界重试提交**（当前最多 5 次，每次观察 3 个 poll），超时未变才判定失败；**禁止**不看状态的无脑重试。
7. **不要依赖服务端过滤**：`query_stock_orders(stock_code=...)` 不可用，统一查全量再本地过滤；风控只用 `Cash`，市值自行按行情计算。
8. **下单也是最终一致**：`order_stock` 返回后委托可能几秒后才出现在查询里、冻结资金约 30s 后才反映，网关要有"已提交待确认"中间态。

---

## 八、网关端点实测（2026-11-19，已完成）

环境：项目 `.venv`（Python 3.11.14），用 FastAPI `TestClient` 走真实 `/api/v1/tdxquant/*` 端点。

| 端点 | 实测结果 |
|---|---|
| `GET /health` | `enabled=true`、`available=true`、`initialized=true`（探测后回填）、`logged_in=true`、`cash=998908.59` |
| `GET /trade/asset` | `cash=998908.59`、`asset=1000109.59`、`market_value=0.00`（资产字段仍不可信） |
| `GET /trade/positions` | `000001.SZ`，`total_volume=100`、`available_volume=100`、`cost=10.914` |
| `GET /trade/orders` | 4 笔历史委托均 `Status=0`；`BSFlag=-1` 归一化为 `side=unknown` |
| `POST /rpc/execute`（`tdxdata.get_market_data`） | `600000.SH` / `1d` / `count=3` → `Close` 10.86/10.72/10.64，`Volume` 92524744/65527092/39843896，`ForwardFactor` 1.0 |
| `POST /rpc/execute`（`tdxtrade.order_stock`） | 被拒，`error_code=USE_TRADE_ENDPOINT` |
| `POST /trade/order` | `600000.SH` 买 100 股 @10.13 → `Value=2`、`order_id=274203`、`state=accepted` |
| `POST /trade/cancel` | 下单 0.5s 后撤单 → `raw_value=0`，3 次轮询内 `Status=0`，`cancel_state=confirmed`，`cash` 998908.59 → 998908.59 |

**撤单新发现（补充 4.2）**

- 委托 `272727`：下单后 0.5s 撤单，`Value=0` 且 30s 轮询始终 `Status=1`、资金冻结；隔几分钟用独立进程再撤同一笔，3s 后 `Status=0`。
- 委托 `274203`：同样 0.5s 后撤单，首次提交后 3 次轮询即 `Status=0`。
- 结论：`Value=0` 至少有两种语义——**提交被拒** 或 **已提交但异步生效**。网关不能只提交一次然后干等，必须在状态仍为 1 时有界重试提交，再以 `Status ∈ {0,4,5}` 收口。当前 `core/tdx_trade.py` 已按此实现（最多 5 次，每次观察 3 个 poll）。

**测试基线**：`78 passed, 5 skipped`（GM SDK 安装后新增 GM 数据/交易 mock 用例；xtquant 因本机无 QMT SDK 仍 skip）。

---

## 九、网关功能矩阵复测（2026-11-19 16:10，模拟账户）

环境：项目 `.venv`（Python 3.11.14）、tdx 模拟终端 `<TDX_HOME>`、账户 `11048389`；GM SDK `3.0.193` 已安装。

### 9.1 tdx 数据接口

| 函数 | 结果 |
|---|---|
| `get_market_data` / `1d` | 通过，`600000.SH` 返回 3 根日线 |
| `get_market_data` / `1m`、`5m`、`15m`、`30m`、`1h` | 返回空字典，并提示 `Close` 字段不存在 |
| `get_market_data` / `60m`、`day`、`1min`、`5min` | 参数错误 `-5`；服务端支持 `5m/15m/30m/1h/1d/1w/1mon/1m/10m/45d/1q/1y` |
| `get_market_snapshot` | 通过，返回 `LastClose/Open/Max/Min/Now/Volume` |
| `get_sector_list` | 通过，返回 489 个板块代码 |
| `get_stock_list_in_sector` / `880081.SH` | 通过，返回 2 只 ETF；无效板块代码返回空 |
| `get_trading_dates` | 通过，返回 14 个交易日 |
| `get_divid_factors` | 通过，DataFrame 序列化正常 |
| `get_stock_info` / `get_more_info` | 通过 |
| `get_financial_data` | 通过（约 3 秒） |
| `get_kzz_info` | 对 `600000.SH`、`113050.SH` 均返回空；服务端打印“获取可转债信息异常” |
| `get_stock_list` | 不传 `market` 返回 5584 只；传 `SH/SZ/BJ` 过滤结果异常（`SH` 为空、`SZ` 仅 1 条），说明服务端市场过滤不可靠 |
| `refresh_cache` | 通过，返回 `Refresh Cache Success` |
| `get_version` | `tq` 对象不存在该函数；已从 `tdxdata` 白名单移除，避免暴露不存在的接口 |

### 9.2 tdx 交易接口

本次复测时 `GET /health` 返回 `logged_in=false`、`reason=账户未登录或资产为空`，`asset` 返回 `Value=[]`，`positions/orders` 为空。因此**没有下单**，避免在登录态不明时产生委托。

同时修复：资产为空时 `GET /trade/asset` 现在返回 `success=false`、`error_code=TDX_NOT_LOGGED_IN`，不再把 `cash=null` 当成功返回。需要重新登录模拟账户后，才能复跑下单/撤单闭环。

### 9.3 GM SDK

- `gm 3.0.193` 已安装到项目 `.venv`；首次导入缺 `six`，已补装 `six==1.17.0`。
- 当前 `.env` 没有 `JINGNI_GM_TOKEN`/`JINGNI_GM_STRATEGY_ID`/`JINGNI_GM_ACCOUNT_ID`，`JINGNI_GM_ENABLED=0`。
- `GET /api/v1/gm/health` 返回 `degraded`、`token_configured=false`、`account_configured=false`。
- `gmdata.get_instruments` 实测返回 `{"status":1000,"message":"错误或无效的token"}`；`get_cash` 返回 `1010 无法获取掘金服务器地址列表`。
- GM 类型化交易接口在 Token 缺失时直接返回 `GM_TRADE: GM Token 未配置`，不会透传到 SDK 下单。

### 9.4 本次代码修正

1. `core/whitelist.py` 移除 `tdxdata.get_version`。
2. `providers/gm_provider.py` 增加 `token_configured` / `account_configured`。
3. `api/gm.py` health 改为按 Token 是否配置返回 `healthy/degraded`；`main.py` 启动摘要不再把空 Token 显示为 OK。
4. `core/gm_trade.py` 在 Token 缺失时拒绝交易调用。
5. `core/tdx_trade.py` 资产为空时抛出 `TdxNotLoggedInError`，`api/tdxquant.py` 返回 `TDX_NOT_LOGGED_IN`。

---

## 十、GM 配置后与 TDX notify/重启幂等复测（2026-11-19 16:36–16:50）

环境：项目 `.venv`、tdx 模拟终端 `<TDX_HOME>`、账户 `11048389`、GM 终端 `<GM_TERMINAL_HOME>`。

### 10.1 GM 配置与真实接口

| 项目 | 结果 |
|---|---|
| `.env` GM Token / strategy_id / account_id | 已配置（长度 40 / 36 / 36，account_id 为 UUID 格式），`JINGNI_GM_ENABLED=1` |
| `GET /api/v1/gm/health` | `healthy`，`token_configured=true`，`account_configured=true` |
| `gmdata.get_instruments` | 通过，`SHSE.600000` 返回浦发银行合约信息 |
| `gmdata.history_n` | 通过，`SHSE.600000` / `1d` / `count=3` 返回 3 根日线 |
| `get_cash(account_id=...)` | 通过（模拟账户）：`nav=100000.00`、`available=100000.00`、`balance=100000.00` |
| `get_position` | 通过，空列表（无持仓） |
| `get_orders()` | 通过，空列表（无委托） |
| GM 类型化交易查询 | 通过，网关返回模拟账户资金/持仓，不再 500 |

**关键根因**：`gm.api.set_account_id()` 是问题源。gm 3.0.193 中先调用该全局设置、再调用 `get_cash/get_position` 会返回 `1013 交易服务调用错误`；只 `set_token`、查询时显式传 `account_id` 则正常。已移除 `GMProvider.initialize()` 中的 `set_account_id` 调用。

本次同时修正了 GM 类型化交易的参数错误：

- `get_cash` / `get_position` 使用 `account_id`，不是 `account`；
- `get_orders()` 不接受账号参数；
- `order_cancel` 接收 `cl_ord_id/account_id` dict，不是 `order_id/account`。

账户已从 7400 元实盘切换为模拟账户；模拟账户资金 `100000.00`，当前无持仓、无委托。

### 10.1.1 GM 下单模式限制

17:20 尝试通过网关下模拟买单：

```json
{
  "symbol": "SHSE.600000",
  "volume": 100,
  "side": 0,
  "order_type": 0,
  "price": 9.00,
  "position_effect": 1,
  "client_order_id": "gm-sim-20261119-1"
}
```

返回：

```json
{
  "status": 1030,
  "message": "该函数不支持在当前策略运行模式",
  "function": "_inner_place_order"
}
```

原因：`gm.api` 是策略 SDK，外部进程没有 `run()` 策略上下文时，`order_volume` 会被终端拒绝；外部纯交易应使用 `gmtrade` SDK（`gm` 与 `gmtrade` 是两个 SDK，`gmtrade` 当前未安装，且其最新版主要支持 Python 3.6–3.10）。当前网关已验证 GM 的行情、资金、持仓、委托查询；GM 下单尚未打通。

### 10.2 TDX notify=1

16:41 通过网关提交模拟买单：

```json
{
  "stock_code": "600000.SH",
  "order_type": 0,
  "order_volume": 100,
  "price_type": 0,
  "price": 9.00,
  "notify": 1,
  "client_order_id": "notify-test-20261119-1"
}
```

返回：

```json
{
  "state": "pending_confirm",
  "success": true,
  "raw_value": 1,
  "message": "已发送信号至客户端，待用户确认！",
  "order_id": null
}
```

结论：

- `notify=1` 的 `Value=1` 只表示**确认信号已发送到客户端**，不是已生成委托；`order_id` 为空，`/trade/orders` 仍为空，现金未冻结。
- 需要用户在通达信客户端点“确认”后，才会进入 OMS；点“取消”则不产生委托。
- 已修复待确认信号的幂等缺口：`pending_confirm` 现在也缓存，同一 `client_order_id` 不会重复发送确认信号。

### 10.3 TDX 非交易时段下单

16:39 普通 `notify=0` 买单（`600000.SH` 买 100 @9.00）返回：

```json
{
  "state": "failed",
  "success": false,
  "raw_value": 0,
  "message": "提交交易失败：(-7353)通讯超时!S7617(-7353):服务未就绪(OMS)(4)"
}
```

说明：

- 16:36 复测时 `GET /health` 已恢复 `logged_in=true`、`cash=998908.59`，资产查询正常。
- 因此“账户显示未登录”不是单纯由非开盘时间造成，而是此前交易登录态失效；重新登录后登录态恢复。
- 但收盘后 OMS 未就绪，**资产查询可用、委托提交不可用**。要验证真实下单/撤单闭环，需要等到交易时段或 OMS 恢复。

### 10.4 重启后幂等

- 增加 SQLite 持久化：`data/tdx_idempotency.sqlite3`，表 `tdx_order_idempotency`，TTL 600 秒。
- 实测 `notify=1` 的 `client_order_id=restart-notify-20261119-1`：
  - 同进程第一次：`pending_confirm`，`idempotent_replay=false`；
  - 同进程第二次：`pending_confirm`，`idempotent_replay=true`；
  - **新进程（模拟网关重启）第三次**：`pending_confirm`，`idempotent_replay=true`，未再次发送信号。
- SQLite 中已落盘该 key；新进程能读取并重放。
- 已受理订单的跨重启重放由 `tests/test_tdx_trade.py::test_idempotency_survives_service_restart` 覆盖；当前收盘后 OMS 不可用，未做真实 accepted 订单的跨重启重放。

### 10.5 本轮代码修正

1. `core/gm_trade.py`：修正 `get_cash/get_position` 的 `account_id`、`get_orders()` 无参、`order_cancel` 的 `cl_ord_id/account_id`；空资金抛 `GMNotLoggedInError`；GM SDK 异常统一转 `GMTradeError`，避免 500。
2. `providers/gm_provider.py`：移除 `api.set_account_id()` 全局设置；gm 3.0.193 中它会导致 `get_cash/get_position` 报 1013。
3. `api/gm.py`：资产为空返回 `GM_NOT_LOGGED_IN`；GM 交易异常返回结构化错误。
4. `core/tdx_trade.py`：`pending_confirm` 纳入幂等缓存；新增 SQLite 持久化，跨重启按 `client_order_id` 重放。
5. `config.py` / `.env.example`：新增 `JINGNI_TDX_IDEMPOTENCY_DB`，默认 `data/tdx_idempotency.sqlite3`。
6. `.gitignore`：忽略 `data/*.sqlite3`，避免委托流水入库。

**测试基线**：`84 passed, 5 skipped`（新增 GM 空资金、TDX 待确认幂等、跨重启幂等、GMProvider 不调用 set_account_id、gmtrade proxy 映射用例）。

### 10.6 数据接口复核（2026-11-19 17:47）

用网关 `/api/v1/tdxquant/rpc/execute` 复核：

| 调用 | 结果 | 结论 |
|---|---|---|
| `get_stock_list(market='5', list_type=0)` | 5584 只，首 `000001.SZ` | 全 A 股正常 |
| `get_stock_list(market='7')` | 1700 只，首 `600000.SH` | 上证主板正常 |
| `get_stock_list(market='8')` | 1494 只，首 `000001.SZ` | 深证主板正常 |
| `get_stock_list(market='53')` | 358 只，首 `920000.BJ` | 北交所正常 |
| `get_market_data(period='1m/5m/15m/30m/1h', count=10)` | `{}` | 本地终端无分钟数据 |
| `get_market_data(period='60m', count=10)` | `{'error','msg'}` | 该终端/版本不认 60m |
| `get_kzz_info(stock_code='123039.SZ')` | `{}` | 终端无可转债数据包 |

说明：

- `market` 的正确取值是通达信分类编码（`5` 全 A、`7` 沪主板、`8` 深主板、`53` 北交所），不是 `SH/SZ/BJ`。此前“市场过滤异常”是调用参数用错，不是网关过滤逻辑错误。
- 本地 tqcenter 分钟线依赖客户端盘后数据下载，且有 Level2 权限才能取；当前终端只支持日线以上，分钟线为空。要补齐需在通达信客户端下载盘后分钟数据/开通 Level2，或改用 tqserver/tdxaidata 数据源（需另评估积分成本）。
- `get_kzz_info` 只接受可转债代码；正股代码和没有可转债数据包时返回空。`123039.SZ` 也空说明当前终端没有可转债数据。

---

## 十一、gmtrade 3.0.6 外部交易 SDK 实测（2026-11-19 17:20–17:40）

### 11.1 安装位置

`gmtrade 3.0.6` 只发布 `cp36m/cp37m/cp38/cp39/cp310` wheel，没有 `cp311`，无法装进项目 Python 3.11 的 `.venv`。已创建项目内 Python 3.10 sidecar（以下命令在项目根目录执行）：

```powershell
uv venv --python 3.10 .venv310
uv pip install --python .\.venv310\Scripts\python.exe gmtrade==3.0.6
```

`.venv310` 已加入 `.gitignore`；`.venv` 仍不安装 `gmtrade`，这是 ABI 限制，不是依赖解析失败。

### 11.2 直接调用

登录顺序：`set_token` → `set_endpoint('api.myquant.cn:9000')` → `account(account_id=...)` → `login(a)`。实测：

- `get_cash()`：`nav=100000.0`、`available=100000.0`、`balance=100000.0`；
- `get_positions()`：空；
- `order_volume('SHSE.600000', 100, Buy, Limit, Open, price=9.00)`：`status=8`，拒绝原因“委托价超出涨跌停范围”；
- `order_volume(... price=9.66)`：`status=1`（已受理）；`order_cancel([{'cl_ord_id':..., 'account_id':...}])` 后 `status=5`（已撤）；
- 撤单后资金仍为 `100000.0`，无持仓。

结论：`gmtrade` 不受 `gm.api.order_volume` 的 `1030 该函数不支持在当前策略运行模式` 限制，外部进程可直接交易。

### 11.3 网关接入

新增：

- `tools/gmtrade_bridge.py`：Python 3.10 JSON Lines sidecar，支持 `ping/cash/positions/orders/place/cancel/shutdown`；
- `core/gmtrade_proxy.py`：Python 3.11 网关侧代理，管理 `.venv310` 子进程、超时和重连；
- `config.py`：`GMConfig.gmtrade_python`、`GMConfig.gmtrade_endpoint`；
- `providers/gm_provider.py`：`gmtrade` 模块返回代理；`cleanup()` 关闭 sidecar；
- `api/gm.py`：health 增加 `gmtrade_available`；撤单接受 `order_id` 或 `cl_ord_id`，传 `order_id` 时先查委托列表解析 `cl_ord_id`；
- `main.py`：shutdown 调用 `gm_provider.cleanup()`。

网关实测：

```text
POST /api/v1/gm/trade/order  side=0 buy, price=9.66
→ state=accepted, order_id=ded45923-...
POST /api/v1/gm/trade/cancel {"order_id":"ded45923-..."}
→ success=true, cancel_state=confirmed
GET /api/v1/gm/trade/orders
→ 目标委托 status=5
GET /api/v1/gm/trade/asset
→ nav=100000.0, available=100000.0
```

映射修正：网关 `GMTradeService` 传的是 gmtrade 常量 `side 1=买/2=卖`、`order_type 1=限价/2=市价`；bridge 不能按 API 的 `0/1` 解释，否则会把买单发成卖单、限价发成市价。已在 `tools/gmtrade_bridge.py` 中兼容两套枚举。

### 11.4 仍待完成

- TDX 真实 `accepted` 委托/撤单闭环：模拟账户已在 2026-11-20 开盘时段完成，真实账户仍需实盘小额验证。
- TDX 实盘小额验证：实盘 TQ 自动下单权限已确认开放，但尚未下单。
- TDX 分钟数据、`get_stock_list` 市场过滤、`get_kzz_info` 仍是终端/数据层遗留。
- GM 实盘小额验证：当前 `.env` 仍是模拟账户；实盘端点/账户需切换后单独验证。
- GM `gmtrade.start()` 消息泵未接入；已在 2026-11-20 用完整模块路径复测，hosted 端点仍返回 `-1`，本地终端端点返回 `1020`（hosted 模拟账户不被本地终端识别），网关继续使用 `get_orders()` 轮询。查询/下单/撤单不受影响。

---

## 十二、2026-11-20 开盘及收盘后补测

### 12.1 TDX 模拟账户（10:55–10:59）

- 账户登录态：`logged_in=true`，`cash=998908.59`，`account_handle=1`
- `600000.SH` 100 股限价买入 `10.20`：`accepted`，委托号 `167424`，状态 `1`（有效）
- 撤单：`cancel_state=confirmed`，状态变为 `0`；资金先冻结约 1020 元，随后恢复为 `998908.59`
- 第二笔同参数委托：`accepted`，委托号 `168405`
- 网关重启后同 `client_order_id` 重放：`idempotent_replay=true`，未重复报单
- 重启后撤单：状态 `0`，资金恢复为 `998908.59`
- 持仓：原有 `000001.SZ` 100 股未变动；无新增持仓

结论：TDX 模拟账户在开盘时段完成了 `accepted → 查询 → 撤单 → 资金恢复`，以及 accepted 跨网关重启幂等。

### 12.2 GM 模拟账户（10:56、15:31）

- 开盘时段 `SHSE.600000` 100 股限价买入 `10.20`：`accepted`
- 撤单：委托状态变为 `5`（已撤）
- 资金：`nav=100000.00`、`available=100000.00`、`balance=100000.00`
- 持仓：空
- 同 `client_order_id` 重放：`idempotent_replay=true`

收盘后补充验证：

- 限价买入 `10.20`：`accepted`，按 `cl_ord_id` 撤单成功，状态 `5`
- 市价买入 100 股：`accepted`，因收盘后未成交；按 `cl_ord_id` 撤单成功，状态 `5`
- 撤单后 `order_frozen` 归零，`available` 恢复为 `100000.00`

结论：GM 的限价、市价、按 `order_id` 撤单、按 `cl_ord_id` 撤单均完成模拟验证；市价单只验证到“接受/撤单”，未形成成交与持仓。

### 12.3 仍受外部条件限制的项

- GM 卖出/平仓、`position_effect=2/3`：需要开盘成交形成持仓后验证；本次收盘后市价单未成交，无法构造持仓。
- TDX 卖出、市价/涨停/跌停价委托：需要下一交易时段验证。
- TDX `notify=1` 的真实客户端确认：目前只验证到 `pending_confirm`，需要人工在通达信客户端确认后跟踪委托生命周期。
- GM 多账户：当前只有一个模拟账户，无法做多账户路由验收。
- TDX 分钟线 `1m/5m/15m/30m/1h` 仍为空，`get_kzz_info` 仍为空；属于终端数据/Level2 权限限制。
- GM `gmtrade.start()`：hosted 端点 `-1`，本地终端端点 `1020`；事件回调未打通，轮询路径正常。

---

## 十三、2026-11-23 盘中 GM 补测

### 13.1 成交与持仓

- `SHSE.601398` 100 股市价买入：`accepted`，随后 `status=3`（已成交），成交价 `9.17`，成交金额 `917.00`，佣金 `5.00`
- 持仓查询：`SHSE.601398` 100 股，`available=100`、`available_today=100`、`vwap=9.17`
- 账户：`nav=99991.00`、`pnl=-9.00`、`order_frozen=1070.00`、`available=98007.99`
- 同 `client_order_id` 重放：`idempotent_replay=true`，未重复成交

### 13.2 撤单

- `SHSE.601398` 100 股限价买入 `9.00`：`accepted`，`status=1`
- 按 `cl_ord_id` 撤单：`cancel_state=confirmed`，委托 `status=5`
- 撤单后没有新增冻结资金；`order_frozen` 仍为既有委托的 `1070.00`

### 13.3 卖出/平仓限制

- 对当日买入的 100 股发起市价卖出，分别使用 `position_effect=3`（平今）和 `position_effect=2`（平仓）
- 两次均被柜台拒绝：`status=8`，`ord_rej_reason_detail="[GMBROKER] 仓位不足: 委托冻结(100) > 可用持仓(0)"`
- 持仓查询仍显示 `available=100`、`available_today=100`，但 GM 模拟柜台按 T+1 计算可卖持仓为 0
- 结论：**当日买入的 GM 模拟持仓不能当日卖出**；卖出/平仓需下一交易日用隔日持仓验证

### 13.4 现场状态

- 另有一笔此前已存在的 `SHSE.600000` 100 股限价买单（价格 `10.65`）仍为 `status=1`，`order_frozen=1070.00`；非本次测试下单，未做撤单操作
- TDX 当前 `logged_in=false`，`query_stock_asset` 返回空资产；TDX 卖出/订单类型/`notify=1` 本轮未能继续

---

## 十四、2026-11-23 盘中 TDX 补测

### 14.1 账户与持仓

- 用户登录 TDX 模拟账户后：`logged_in=true`、`account_handle=1`、`cash=998908.59`、`status=healthy`
- 持仓：`000001.SZ` 100 股，`available_volume=100`，成本 `10.914`

### 14.2 卖出与撤单

- 限价卖出 `000001.SZ` 100 股 @ `12.60`：`accepted`，`order_id=259539`，状态 `1`
- 下单后持仓 `available_volume` 变为 `0`（卖出冻结）
- 撤单：`cancel_state=confirmed`，状态 `0`；`available_volume` 恢复 `100`
- 市价卖出 `000001.SZ` 100 股：`accepted`，`order_id=260019`
- 约 20 秒后委托变为 `status=3`（filled），持仓变为 0；`cash` 从 `998908.59` 增至 `1000147.22`
- 成交后一段时间内 `query_stock_orders` 仍可能显示 `status=1`、`filled_volume=0`；以持仓和资金对账为准

### 14.3 价格类型矩阵

- `600000.SH` 买入 100 股 `price_type=3`（跌停/笼子下限）：`accepted`，`order_id=261024`，委托价 `10.530`，状态 `1`；撤单后 `status=0`
- `600000.SH` 买入 100 股 `price_type=2`（涨停/笼子上限）：`accepted`，`order_id=286164`，委托价 `10.920`，状态 `1`；未成交，撤单后 `status=0`
- 观察：TDX 的 `price_type=2/3` 实际取的是**价格笼子上/下限**，不一定是 ±10% 涨跌停价；委托价由客户端计算
- `price_type=0` 限价、`price_type=1` 市价均已验证；市价卖出可成交

### 14.4 `notify=1` 人工确认

- `600000.SH` 买入 100 股限价 `10.50`、`notify=1`：返回 `pending_confirm`，无 `order_id`
- 用户在通达信客户端确认后，生成 `order_id=285234`，状态 `1`（open）；随后按 `order_id` 撤单，`cancel_state=confirmed`，状态 `0`
- 发现 pending 缓存 TTL 问题：
  - 下单时间约 `14:00:41`，用户确认时间约 `14:29:22`
  - 在 `14:31:10` 用同一 `client_order_id` 重放，返回 `idempotent_replay=false`，再次发送 `pending_confirm` 信号
  - 原因是 pending 结果只在内存缓存 10 分钟，人工确认可能晚于 TTL
  - 本次重放没有生成重复真实委托；但这是重复确认信号风险，建议把 pending 状态持久化到确认/拒绝为止，或延长 TTL（已在第十五节修复）

### 14.5 收口状态

- TDX 当前无 `status=1` 的未完成委托
- TDX 持仓为 0（`000001.SZ` 已卖出），`cash=1000147.22`
- GM 仍持有 `SHSE.601398` 100 股（当日买入，受 T+1 限制）；另有此前 `600000` 100 股限价买单 `status=1`，非本轮测试单

---

## 十五、2026-11-23 修复与盘中验证

### 15.1 TDX pending 幂等 TTL

- `core/tdx_trade.py` 新增 pending 专用 TTL `_pending_order_cache_ttl`；pending 结果命中时使用该窗口，普通 accepted 仍用 600 秒。
- `config.py` 新增 `JINGNI_TDX_PENDING_IDEMPOTENCY_TTL`，默认 `1800` 秒；`.env.example` 和 README 已补。
- SQLite 持久化读取也按结果状态选择 TTL，不再统一用 600 秒。
- 新增 3 个单测：
  - pending 幂等窗口长于 accepted；
  - pending 内存缓存跨过 accepted TTL 后仍可重放；
  - pending SQLite 持久化跨服务实例仍可重放。
- `tests/test_tdx_trade.py`：`13 passed`。

### 15.2 重启后 TDX 实盘模拟回归

- 网关重启加载新代码后，`600000.SH` 买入 100 股限价 `10.20`：`accepted`，委托号 `298272`
- 撤单：`cancel_state=confirmed`，状态 `0`；`cash` 保持 `1000147.22`
- TDX health：`healthy`、`logged_in=true`

### 15.3 GM 立即拒单识别

- `core/gm_trade.py` 在下单后做一次短延迟 `get_orders()` 查询：
  - 若目标委托 `status=8`（已拒绝），返回 `state=rejected`、`success=false`，并带 `reject_reason`；
  - 若仍为 `status=1`，保持 `accepted`，并回填 `status`。
- 实测 `SHSE.510300` 卖出 100 股（当日买入，T+1）：返回 `success=false`、`state=rejected`、`status=8`、原因 `[GMBROKER] 仓位不足: 委托冻结(100) > 可用持仓(0)`。
- 对照：`SHSE.601398` 限价买入 100 股 `9.00` 返回 `accepted`、`status=1`，按 `cl_ord_id` 撤单后 `status=5`。
- 新增 1 个单测覆盖立即拒单映射；`tests/test_gm_trade.py` 通过。

### 15.4 本轮收口

- TDX：无未完成委托，持仓 0，`cash=1000147.22`；网关重启后 health `healthy`、`logged_in=true`。
- GM：新增 `SHSE.510300` 100 股持仓（当日买入，T+1 拒绝卖出），原有 `SHSE.601398` 100 股持仓；两笔均为模拟账户。
- GM 旧 `600000` 100 股限价买单仍为 `status=1`，未操作。
- 全量自动化：`87 passed, 5 skipped, 1 warning`；5 个 skip 均为 QMT/xtquant SDK 缺失。





