# Phase 3 开盘期验证脚本（仅模拟盘）

适用下一交易日 09:30–15:00。所有脚本默认 **dry-run**：只发只读请求，下单 / 撤单写请求只生成拟发送体写入证据 JSON，不真正提交。仅在模拟账户、且显式加 `--confirm-sim` 时才允许调用写端点；不读取、不修改真实账户配置。

- 运行目录：仓库根 `D:\codebuddy\jingni-gateway`
- 解释器：`.venv\Scripts\python.exe`（Python 3.11）
- 网关默认地址：`http://127.0.0.1:8010`（可用 `--base` 覆盖）
- 证据目录：`data/itest/<YYYYMMDD>/phase3_<item>.json`（运行时产物，不入库）

## 四项验证一览

| # | 验证项 | 脚本 | dry-run 命令 | 模拟盘写端点（仅 `--confirm-sim`） | 证据 JSON |
|---|---|---|---|---|---|
| 1 | TDX pending 6 小时 TTL 边界 | `tools/phase3/p3_01_tdx_ttl_boundary.py` | `.\.venv\Scripts\python.exe tools\phase3\p3_01_tdx_ttl_boundary.py` | `POST /api/v1/tdxquant/trade/order`（`notify=1`，含重放） | `data/itest/<date>/phase3_01_tdx_ttl_boundary.json` |
| 2 | 撤单后约 5 分钟现金恢复采样 | `tools/phase3/p3_02_tdx_cash_recovery.py` | `.\.venv\Scripts\python.exe tools\phase3\p3_02_tdx_cash_recovery.py` | `POST /api/v1/tdxquant/trade/order` → `POST /api/v1/tdxquant/trade/cancel`，随后轮询 `/trade/asset` | `data/itest/<date>/phase3_02_tdx_cash_recovery.json` |
| 3 | QMT（xtquant）撤单 NO-GO 复核 | `tools/phase3/p3_03_qmt_cancel_recheck.py` | `.\.venv\Scripts\python.exe tools\phase3\p3_03_qmt_cancel_recheck.py` | `POST /api/v1/xtquant/trade/order` → `POST /api/v1/xtquant/trade/cancel`（后端 `cancel_order_stock`） | `data/itest/<date>/phase3_03_qmt_cancel_recheck.json` |
| 4 | TDX 分钟数据确认 | `tools/phase3/p3_04_tdx_minute_data.py` | `.\.venv\Scripts\python.exe tools\phase3\p3_04_tdx_minute_data.py` | 无写请求（只读 RPC `get_market_data`） | `data/itest/<date>/phase3_04_tdx_minute_data.json` |

## 判断标准

### 1. TDX pending 6 小时 TTL 边界
- `GET /api/v1/tdxquant/health`：`available=true`、`initialized=true`、`logged_in=true`。
- 配置核对：`pending_idempotency_ttl = 21600` 秒（6 小时）；普通 accepted 缓存 600 秒。
- 窗口内同 `client_order_id` 重放：`idempotent_replay=true`、`pending_since` 不变、不新增委托。
- 6 小时过期边界盘中无法等满，以离线单测的 TTL 数学为准；不在盘中做破坏性过期重放。
- 结论口径：`DRY_RUN_READY` / `BLOCKED_TTL_MISMATCH` / `BLOCKED_NOT_LOGGED_IN` / `SKIPPED_GATEWAY_UNREACHABLE`。

### 2. 撤单后 5 分钟现金恢复采样
- 撤单 `cancel_state=confirmed`、`status=0`（以委托状态对账，不信撤单返回值）。
- 撤单瞬间记录 `cash/asset/TotalFreeze`；按 0–6 分钟轮询 `/trade/asset`。
- 恢复判据：`cash` 回升至与 `asset` 一致（差额≈0），`TotalFreeze=0`。
- 若 6 分钟仍未恢复，保留采样曲线并标注为终端异步行为，不误判网关缺陷。

### 3. QMT 撤单 NO-GO 复核
- `GET /api/v1/xtquant/health`：`available=true`、`xttrader_available=true`、`account_configured=true`。
- `GET /api/v1/xtquant/rpc/capabilities`：`cancel_order_stock` 仅出现在类型化交易，不开放通用 RPC。
- 升级条件（模拟盘往返）：先有一笔 accepted 模拟委托，再调 `/trade/cancel`，`cancel_state=confirmed`、`status` 为 53/54/57、`polls>=1`、`request_accepted=true`。
- 结论口径：`NO_GO_STILL_HOLDS`（MiniQMT/账号未就绪）/ `CONDITIONAL_READY`（就绪但未做往返）/ `SKIPPED_GATEWAY_UNREACHABLE`。仅模拟盘往返 `confirmed` 后，才可在联调记录里把 QMT-06 从 NO-GO 升级为通过。

### 4. TDX 分钟数据确认
- 周期：`1m/5m/15m/30m/1h/1d`，标的 `600000.SH`，参数名 `stock_list`。
- `DATA`：`success=true` 且 bar 非空，最新 bar 时间接近当前时间。
- `EMPTY`：`success=true` 但 data 为空，记为终端数据 / 权限限制，不判网关缺陷。
- `ERROR`：`success=false` 或调用异常；`stock_code`（错误参数名）应被入口层拒绝 `INVALID_ARGUMENT`。
- 结论口径：`MINUTE_DATA_AVAILABLE` / `CONFIRMED_EMPTY_MINUTES` / `REVIEW_ERRORS` / `SKIPPED_GATEWAY_UNREACHABLE`。

## 下一交易日执行顺序建议

1. 09:15–09:30：启动网关、登录 GM/TDX 模拟终端；先跑 1、3 的 dry-run 复核健康与配置。
2. 09:35–11:20：项 4 只读抓分钟数据；项 1、2 在模拟盘按 `--confirm-sim` 执行下单→撤单→采样。
3. 13:05–14:50：项 3 视 MiniQMT 就绪情况做模拟往返；项 2 现金恢复曲线补采。
4. 14:45–15:00：收口，确认无在途测试委托，核对证据 JSON 落盘。

> 安全红线：本目录脚本不对接真实资金账户；任何真实账户小额下单需另行明确授权，不在本自动化范围内。
