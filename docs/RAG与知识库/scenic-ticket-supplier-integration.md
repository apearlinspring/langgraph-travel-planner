# 景点票价与预约供应商接入说明

更新时间：2026-05-19

## 当前结论

景点实时票价、库存、预约、下单和核销通常不能只靠公开网页稳定完成，需要接入 OTA（在线旅行社）开放平台、景区票务系统或票务分销平台，并完成商户资质、API（应用程序接口）密钥、沙箱联调、结算、退改、售后和核销规则确认。

第一版先采用 `curated_rag_ticket_catalog`：把公开参考价、预约说明、来源链接和采集日期放进 `data/documents/internal/scenic_tickets/scenic_ticket_reference.md`，由 `scenic_price_lookup_tool` 读取。它能支撑演示和旅行社方案的真实感，但只输出“参考价、待核验、不锁价”。

## 候选供应商

| 候选 | 适用方向 | 接入要点 | 风险 |
|---|---|---|---|
| 携程玩乐开放平台 | 景点门票、玩乐产品分销 | 需要合作资质、API 密钥、沙箱联调、结算和退改规则确认 | 商务准入与接口权限不一定开放给个人项目 |
| 飞猪开放平台门票 API2.0 | 门票商品、价格、库存、订单 | 需要开放平台应用、类目权限和商家/供应链授权 | 接口多与交易闭环绑定，需处理售后和核销 |
| 票付通 | 景区电子票务和分销 | 适合有景区/分销合作后接入库存、下单、核销 | 需要商务开通和供应链关系 |
| 智游宝 | 景区票务系统和分销接口 | 适合景区侧或分销侧对接电子票务 | 需要商务联调和核销流程 |

## 推荐技术路线

1. 保留 `curated_rag_ticket_catalog` 作为兜底参考价来源。
2. 新增 `live_supplier` 适配器时，只把实时票价、库存、预约状态写入短期证据，不覆盖长期 RAG 文档。
3. 工具输出合并规则：实时供应商结果优先；供应商超时或未覆盖时回落到 RAG 参考目录。
4. 所有用户可见输出必须保留：采集/查询时间、来源、待核验、不锁价、不可承诺预约成功。
5. 只有接入真实订单、支付、核销和售后后，才允许进入正式预订流程；当前项目仍只生成规划报告。

## 后续字段预留

`scenic_price_evidence` 可以继续扩展：

```json
{
  "provider": "ctrip_fun|fliggy_ticket|piaofutong|zhiyoubao|curated_rag_ticket_catalog",
  "provider_status": "live_supplier|reference_only|degraded",
  "queried_at": "ISO-8601",
  "items": [],
  "supplier_trace_id": "optional",
  "booking_supported": false,
  "requires_manual_confirmation": true
}
```

## 公开资料入口

- 携程玩乐开放平台：https://ttdstp.ctrip.com/apiplatform/document/channelin.do
- 飞猪开放平台：https://open.alitrip.com/
- 票付通：https://www.piaofutong.com/
- 智游宝：https://www.zhiyoubao.com/
