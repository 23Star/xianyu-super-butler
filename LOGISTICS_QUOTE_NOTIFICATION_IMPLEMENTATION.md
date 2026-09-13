# 物流报价第五步失败/转人工通知与日志实现文档

## 1. 结论与当前状态

**结论：可以接入，但当前代码尚未接入。**

现有“通知与日志”能力已经具备两个可复用出口：

- 系统运行日志：`app/reply_server.py` 的 `log_with_user(...)` 写入系统日志，前端 `frontend/components/NotificationsAndLogs.tsx` 的“系统日志”页可查询（管理员可见）。
- 外部通知：`XianyuAutoAsync.py` 的 `send_system_notification(message)` 会读取当前闲鱼账号绑定且启用的通知渠道，并发送到钉钉、飞书、Bark、邮件、Webhook、企业微信或 Telegram。

物流报价第五步目前只存在于既有报价方案/文档语境中，仓库中没有可检索到的物流报价后端路由、第五步事件发布器或前端 `LogisticsQuotes.tsx` 源文件。因此，失败或转人工不会自动出现在“通知与日志”；需要在第五步的实际执行入口增加事件发布。

## 2. 目标行为

第五步结束时统一产生一个报价事件：

| 结果 | 系统日志 | 外部通知 | 前端展示建议 |
|---|---|---|---|
| 报价成功 | info，可选 | 不发送 | 报价结果页正常展示 |
| 报价失败 | error | 发送 | 显示“报价失败”，保留可重试 |
| 转人工 | warning | 发送 | 显示“需人工处理”，保留原因和上下文 |
| 通知发送失败 | error（独立记录） | 不改变报价结果 | 在系统日志标明渠道和错误 |

报价失败与通知失败必须分开记录：通知渠道不可用时，不能把原本的报价结果误标成“报价失败”。

## 3. 推荐事件模型

在第五步产出结构化结果（示例字段）：

```json
{
  "event": "logistics_quote",
  "stage": 5,
  "status": "failed",
  "action": "quote_failed",
  "account_id": "<cookie_id>",
  "order_id": "<optional>",
  "conversation_id": "<optional>",
  "quote_request_id": "<idempotency key>",
  "reason_code": "CARRIER_TIMEOUT",
  "reason": "承运商报价接口超时",
  "retryable": true,
  "created_at": "<ISO-8601>"
}
```

`status` 取 `failed` 或 `manual_required`；`action` 建议分别取 `quote_failed`、`transfer_manual`。重量、地址、手机号、Cookie、Webhook 密钥等敏感数据不得写入日志或通知正文；只保留脱敏后的订单/会话标识和必要计费摘要。

## 4. 后端接入方案

### 4.1 统一发布函数

在物流报价服务所在模块增加异步发布函数（名称可按实际模块调整）：

```python
async def publish_logistics_quote_event(event: dict, user: dict | None, account_instance=None):
    message = format_logistics_quote_message(event)
    log_with_user(event_level(event), message, user)
    if event["status"] in {"failed", "manual_required"} and account_instance:
        await account_instance.send_system_notification(message)
```

- `log_with_user` 负责“系统日志”可查询性。
- `send_system_notification` 负责账号绑定的外部渠道。
- 只有失败和转人工发送外部通知，成功默认不打扰；如业务需要可增加配置开关。
- 物流报价入口若不在 `XianyuAutoAsync` 实例内，必须通过 `account_id` 找到运行实例；找不到实例时仍写系统日志，并额外记录“无法发送外部通知”的 warning。

### 4.2 发布时机

第五步的所有终止路径都必须经过同一个 `finally`/结果汇总出口，禁止只在异常分支发送：

1. 参数/地址校验失败：`quote_failed`，`retryable=false`。
2. 承运商接口超时、限流、返回不可解析：`quote_failed`，按错误类型设置 `retryable`。
3. 无可用承运商、价格缺失或计费规则冲突：`quote_failed`。
4. 需要客服确认价格、地址或特殊货物：`transfer_manual`。
5. 用户主动选择人工：`transfer_manual`。

同一 `quote_request_id + action` 在冷却窗口内只发布一次，避免重试造成通知轰炸。现有实例通知机制有通知冷却字段，可沿用同样思路，但物流事件应使用独立事件键。

## 5. 通知正文

失败模板：

```text
【物流报价失败】
账号：{account_label}
订单/会话：{masked_order_or_conversation}
阶段：第 5 步
原因：{reason}
错误码：{reason_code}
可重试：{是/否}
报价请求：{quote_request_id}
```

转人工模板：

```text
【物流报价转人工】
账号：{account_label}
订单/会话：{masked_order_or_conversation}
阶段：第 5 步
人工原因：{reason}
待确认项：{required_action}
报价请求：{quote_request_id}
```

正文不包含完整收件地址、电话、Cookie、Token 或渠道密钥；Webhook/邮件等渠道共用同一脱敏模板。

## 6. 前端“通知与日志”展示

现有页面已能展示系统日志，但筛选主要按级别和来源。建议：

- 统一日志 `source=logistics_quote`，消息前缀固定为“物流报价”。
- 系统日志页增加来源快捷筛选“物流报价”（也可先直接使用现有 source 输入框）。
- 风控日志不适合承载报价业务事件；不要把报价失败写入风控日志。
- 账号通知绑定页的说明补充“订单、风控、运行及物流报价事件”。
- 若需要普通用户查看自己的报价事件，应新增按 `user_id/account_id` 隔离的业务日志接口；不要直接放宽管理员系统日志接口权限。

## 7. API/数据变更建议

首期无需新增表：复用系统日志和通知渠道绑定即可。若需要历史报价查询、状态追踪或人工处理闭环，再新增 `logistics_quote_events` 表，至少包含：

`id`、`user_id`、`account_id`、`quote_request_id`、`order_id`、`stage`、`status`、`reason_code`、`reason`、`retryable`、`notification_status`、`created_at`、`resolved_at`。

建议对 `quote_request_id + action` 建唯一约束，或使用应用层幂等键。

## 8. 验证清单

1. 模拟承运商超时：系统日志出现一条 error，绑定渠道收到一条失败通知。
2. 模拟需客服确认：系统日志出现一条 warning，绑定渠道收到一条转人工通知。
3. 未绑定渠道：报价状态仍正确，系统日志记录“无可用通知渠道”，请求不报错。
4. 渠道发送异常：系统日志记录渠道名和错误，报价事件仍保持原状态。
5. 重试同一请求：冷却/幂等生效，不重复发送。
6. 多账号并发：通知只发送到对应 `account_id` 的绑定渠道。
7. 权限验证：普通用户不能读取其他账号或管理员系统日志；敏感字段在日志和通知中均已脱敏。

## 9. 实施顺序

1. 确认第五步真实执行入口及其可获得的 `account_id`、请求 ID 和订单/会话 ID。
2. 增加事件模型、错误码和统一发布函数。
3. 在失败与转人工的全部出口调用发布函数。
4. 接入 `log_with_user` 和 `send_system_notification`，补充实例不存在/渠道失败处理。
5. 增加幂等与脱敏测试，再在前端补充来源筛选和说明文字。
6. 上线后观察系统日志中的 `source=logistics_quote`，确认通知成功率与重复率。

## 10. 风险与待确认项

- 当前仓库缺少物流报价第五步的实际源代码，无法在本文件中指定精确函数名和行号；实施前必须先定位真实入口。
- `send_system_notification` 依赖账号通知绑定和可用的运行实例；报价若由纯前端计算触发，必须新增后端事件接口，不能仅在浏览器 console 记录。
- 现有系统日志接口管理员可见，若产品要求普通用户查看报价失败历史，需要单独的用户隔离查询接口。
