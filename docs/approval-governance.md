# HITL（人类在环）与审批治理轻量版

## 目标

本模块只建立敏感动作治理契约，不接真实供应链、不做真实支付、不生成真实客服或支付链接。

当前实现提供：

- 敏感动作权限策略。
- 进程内轻量审批记录。
- TravelState（旅行规划状态）审批字段。
- API（应用程序接口）契约：标记、查询、批准、拒绝、过期。
- 最终报告中的治理边界说明。

## 敏感动作策略

策略定义在 `app/core/permissions.py`。

| 动作 | 当前策略 | 说明 |
|---|---|---|
| `generate_order_id` | 记录型，不阻塞 | 生成项目内模拟订单号；不代表真实支付、真实预订、锁价、占库存或履约。 |
| `export_final_report` | 记录型，不阻塞 | 导出当前结构化旅行报告；不代表已经完成支付、预订、出票或酒店确认。 |
| `real_booking` | 强制审批 | 未来接入真实供应链、库存或订单履约前必须审批。 |
| `real_payment` | 强制审批 | 未来接入支付网关前必须审批。 |
| `send_sms` | 强制审批 | 未来向用户或供应商发送短信前必须审批。 |
| `export_customer_profile` | 强制审批 | 未来导出客户资料或行程画像前必须审批，并最小化字段。 |

`generate_order_id` 仍被视为敏感动作，但当前只是记录治理边界，不阻塞报告交付。未来只要动作会触发真实支付、真实预订、短信发送或客户资料导出，就必须走 `pending -> approved` 后才能执行。

## 状态字段

`TravelState` 新增或补齐以下字段：

```python
approval_pending: bool
approval_reason: str
approval_action: str
approval_expires_at: float | None
approval_status: Literal["none", "pending", "approved", "rejected", "expired"]
approval_record_id: str
approval_required: bool
approval_governance: dict
```

状态含义：

- `none`：当前动作无需审批或只是记录型治理边界。
- `pending`：等待人工审批，过期前可批准或拒绝。
- `approved`：审批通过，未来真实动作可在有效边界内继续。
- `rejected`：审批拒绝，不应继续执行对应真实动作。
- `expired`：审批超时，不应继续执行对应真实动作。

## API 契约

路由挂载在 `/api/v1/approvals`，当前复用登录用户鉴权。

- `GET /api/v1/approvals/policies`：查看敏感动作策略。
- `POST /api/v1/approvals`：标记敏感动作；强制审批动作会生成 `pending` 记录，记录型动作会生成 `none` 记录。
- `GET /api/v1/approvals`：查询当前用户审批记录，支持 `status`、`action`、`conversation_id` 过滤。
- `GET /api/v1/approvals/{approval_id}`：查询单条审批记录。
- `POST /api/v1/approvals/{approval_id}/approve`：批准 `pending` 记录。
- `POST /api/v1/approvals/{approval_id}/reject`：拒绝 `pending` 记录。
- `POST /api/v1/approvals/{approval_id}/expire`：手动过期 `pending` 记录。

审批记录当前是进程内轻量存储，适合开发验证和契约稳定，不作为生产级审计账本。后续接真实支付、短信或供应链前，应迁移到数据库并补充不可篡改审计日志。

## 订单号治理边界

`generate_order_tool` 会继续生成 `ORDER-` 开头的项目内模拟订单号，不因为审批未完成而阻塞当前最终报告。但它会同步写入：

- `approval_action="generate_order_id"`。
- `approval_status="none"`。
- `approval_pending=False`。
- `approval_required=False`。
- `approval_governance.boundary`：说明当前订单号不代表真实支付、预订、锁价或履约。
- `report_data.tool_audit_summary.approval`。
- `report_data.evidence_bundle.approval_governance`。

最终报告和工具返回消息继续明确：

- 当前项目未接入真实支付服务，不生成支付链接。
- 不承诺真实库存、真实锁价或真实预订成功。
- 未来接入真实支付或真实预订时必须先完成人工审批。

## 数据与隐私边界

审批 metadata（元数据）会做浅层脱敏：`token`、`secret`、`api_key`、`phone`、`id_card` 等疑似密钥或 PII（个人可识别信息）字段会被替换为 `[REDACTED]`。

当前文档、测试和提交说明不写入真实密钥、真实手机号、真实身份证号或真实客户资料。

## 未覆盖范围

- 不提供后台审批 UI（用户界面）。
- 不接真实库存、支付、短信、客服或供应链。
- 不生成支付链接、客服链接、预订凭证或出票凭证。
- 不承诺锁价、余位、成团、酒店确认或订单履约。
- 不做分布式一致性和不可篡改审计日志。

这些能力需要在未来真实业务接入前单独设计数据库表、权限模型、审计日志和失败补偿机制。
