---
source_type: agency_internal
category: products
visibility: internal
source: public_pattern_abstraction
source_kind: public_pattern_abstraction
inventory_status: reference_only
external_product_ref: null
applicable_modes:
  - agency_plan
  - free_planning
evidence_level: reference
last_reviewed: "2026-05-11"
title: 真实旅行社产品结构参考
product_id: ZX-PROD-PATTERN-REFERENCE
destination: general
theme: public_product_pattern_abstraction
duration: varied
audience:
  - family
  - couple
  - senior
  - team
  - general
persona_tags:
  - reference
  - product_structure
  - compliance_boundary
service_level: reference
price_band: varied
demo_price_label: 公开产品结构抽象，不含真实价格
price_basis:
  - 仅抽象公开页面常见结构
  - 不复制第三方价格、库存或文案
included:
  - 产品结构字段示例
  - 费用包含和不含拆分方法
  - 每日行程节奏抽象
  - 核验和合规边界
excluded:
  - 第三方品牌文案
  - 真实库存
  - 实时价格
  - 供应商联系方式
transport_lodging_basis:
  - 只抽象交通和住宿表达字段
  - 不落真实供应商资源
  - 后续真实库存接入时通过 external_product_ref 映射
verification_items:
  - 合同口径
  - 价格波动
  - 库存状态
  - 版权与品牌边界
evidence_type: public_reference_abstraction
---

# 真实旅行社产品结构参考

> 资料用途：把公开旅行平台和旅行社的真实业务表达，抽象成知行内部产品设计规则。本文不是库存承诺，也不代表任何第三方产品价格。

## 公开参考资料

- 文化和旅游部、市场监管总局《2026 年版团队旅游合同（示范文本）》通知：https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/wjs/art/2026/art_f64b8fb278254974a1f587f2fc64b971.html
- 途牛《国内旅游预订须知》：https://tuniu.com/help/domestic.shtml
- 携程 AI 行程助手产品页：https://www.ctrip.com/tripplanner
- 中青旅遨游网定制旅游页：https://www.aoyou.com/dingzhi/

## 真实产品页常见结构

成熟旅行产品通常不是只写“去哪玩”，而是把服务拆成几个可确认模块：

- 行程模块：出发地、目的地、天数、每日路线、核心景点、自由活动时间。
- 资源模块：大交通、住宿区域、用车或市内交通、门票或体验项目、餐饮建议。
- 服务模块：顾问规划、行前提醒、行中响应、异常协助、最终交付物。
- 价格模块：已包含项目、可选项目、个人自理项目、价格波动和退改风险。
- 适配模块：亲子、情侣、银发、团建、研学等不同人群的节奏和风险控制。

## 产品匹配字段

| field | value |
|---|---|
| product_id | ZX-PROD-PATTERN-REFERENCE |
| destination | general |
| theme | public_product_pattern_abstraction |
| duration | varied |
| audience | family / couple / senior / team / general |
| service_level | reference |
| price_band | varied |
| source | public_pattern_abstraction |
| category | products |
| evidence_type | public_reference_abstraction |

这些字段只用于抽象产品表达结构，不能被解释为第三方平台的真实产品复制或库存承诺。

## 知行产品化规则

- 当用户说“省心一点”“你帮我安排”“旅行社方案”时，优先按产品化路线输出：先给路线骨架，再补资源组合，最后形成可交付报告。
- 当用户只想自由行时，保持中立规划，不强调托管服务，但仍可引用成熟路线结构提高可落地性。
- 方案中要自然说明为什么这样安排，例如“首日不塞满，先入住和适应”“同区动线减少折返”“每天保留弹性时间”。
- 不要把“顾问优势”写成硬广告。更好的表达是“按成熟路线结构降低决策成本”“费用边界会单独列清”“出发前需要复核实时库存和价格”。

## 景点票价与预约字段

成熟产品页通常不会只写“含景点”，而会拆分到用户能理解的票务字段：

- 门票参考：成人票、优惠票、套票、演出票、船票或区间车是否另计。
- 预约说明：实名预约、放票窗口、团队预约、闭馆日、停止入园时间。
- 来源与日期：景区官方页或公开票务页；必须标注采集日期。当前无商务资质，不把 OTA（在线旅行社）或票务供应商接口作为可用能力承诺。
- 不承诺项：不锁价、不承诺预约成功、不承诺库存，不把公开参考价写成合同价。

示例表达：`灵隐飞来峰成人参考票 45 元，采集日期 2026-05-19，热门时段需实名预约；正式预订以官方购票页或公开票务页为准，不锁价。`

## 产品化表达示例

- 交通口径：以“出发地到目的地的大交通 + 目的地内接驳”拆开说明，例如“西安到杭州优先高铁或航班，抵达后以地铁/网约车串联西湖、灵隐和西溪，正式票价按出发日期复核”。
- 住宿商圈/档次：写成可决策的商圈和档次，例如“湖滨/武林/西湖东线舒适型酒店，优先早餐、地铁便利和晚归打车便利，房型和取消政策待核验”。
- 景点票价参考：灵隐飞来峰成人参考票 45 元，采集日期 2026-05-19；来源为景区官方页或公开票务页，实名预约、优惠政策和场次待核验，不锁价。
- 餐饮/服务边界：写清“推荐餐饮方向、预约提醒、费用包含/不含、人工确认边界”，不把样例表达成已成团、已占房或已出票。
