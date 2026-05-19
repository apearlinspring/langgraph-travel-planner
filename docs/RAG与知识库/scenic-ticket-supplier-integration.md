# 景点票价与预约供应商接入说明

更新时间：2026-05-19

## 当前结论

景点实时票价、库存、预约、下单和核销通常不能只靠公开网页稳定完成，需要接入 OTA（在线旅行社）开放平台、景区票务系统或票务分销平台，并完成商户资质、API（应用程序接口）密钥、沙箱联调、结算、退改、售后和核销规则确认。

当前没有商务资质，因此实时供应商接入先搁置。短期只走公开网页路径：`scenic_price_lookup_tool` 优先读取 `data/documents/internal/scenic_tickets/scenic_ticket_reference.md` 中已整理的公开参考价；目录未覆盖时调用 `search_travel_info` 做公网搜索，返回来源链接、查询/采集时间、预约/开放说明、待核验和不锁价边界。

## 已搁置的供应商路线

| 候选 | 适用方向 | 接入要点 | 风险 |
|---|---|---|---|
| 携程玩乐开放平台 | 景点门票、玩乐产品分销 | 需要合作资质、API 密钥、沙箱联调、结算和退改规则确认 | 当前无商务准入，搁置 |
| 飞猪开放平台门票 API2.0 | 门票商品、价格、库存、订单 | 需要开放平台应用、类目权限和商家/供应链授权 | 当前无商家/供应链授权，搁置 |
| 票付通 | 景区电子票务和分销 | 适合有景区/分销合作后接入库存、下单和核销 | 当前无景区/分销商务关系，搁置 |
| 智游宝 | 景区票务系统和分销接口 | 适合景区侧或分销侧对接电子票务 | 当前无供应链侧授权，搁置 |

## 当前公开搜索路线

1. 保留 `curated_rag_ticket_catalog` 作为已审阅的公开参考价目录。
2. 目录覆盖目的地/景点时，直接返回公开参考价、来源链接和采集日期，避免每轮都依赖外部搜索。
3. 目录未覆盖时，调用 `search_travel_info` 搜索“目的地 + 景点 + 门票 + 票价 + 预约 + 开放时间 + 官方”。
4. 公网搜索只做证据入口和参考价抽取；若无法稳定识别具体价格，用户可见口径必须写“请打开来源页核验”。
5. 所有用户可见输出必须保留：采集/查询时间、来源、待核验、不锁价、不可承诺预约成功。
6. 只有未来接入真实订单、支付、核销和售后后，才允许进入正式预订流程；当前项目仍只生成规划报告。

## 后续字段预留

`scenic_price_evidence` 可以继续扩展：

```json
{
  "provider": "curated_rag_ticket_catalog|public_web_search",
  "provider_status": "public_reference_only|public_search|public_search_unavailable|degraded",
  "queried_at": "ISO-8601",
  "public_search_query": "optional",
  "items": [],
  "booking_supported": false,
  "requires_manual_confirmation": true
}
```

## 公开资料入口

- 携程玩乐开放平台：https://ttdstp.ctrip.com/apiplatform/document/channelin.do
- 飞猪开放平台：https://open.alitrip.com/
- 票付通：https://www.piaofutong.com/
- 智游宝：https://www.zhiyoubao.com/
