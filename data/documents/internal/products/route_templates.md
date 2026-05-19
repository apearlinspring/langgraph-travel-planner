---
source_type: agency_internal
category: products
visibility: internal
source: fictional_internal_catalog
source_kind: demo_catalog
inventory_status: demo_only
external_product_ref: null
applicable_modes:
  - agency_plan
  - free_planning
evidence_level: standard
last_reviewed: "2026-05-11"
title: 知行旅行社产品路线模板
product_id: ZX-PROD-CATALOG-OVERVIEW
destination: general
theme: product_line_overview
duration: varied
audience:
  - family
  - couple
  - senior
  - team
  - free_planning
persona_tags:
  - catalog_overview
  - low_decision_cost
  - route_template
service_level: route_template
price_band: varied
demo_price_label: 按具体路线样板选择（演示口径）
price_basis:
  - 不同目的地和人群采用不同路线样板
  - 动态交通住宿门票均需二次核验
included:
  - 产品线分类
  - 人群和风格匹配口径
  - 费用边界模板
  - 待核验项模板
excluded:
  - 真实库存
  - 真实锁价
  - 支付或履约承诺
  - 第三方供应商资料
transport_lodging_basis:
  - 按产品样板记录交通和住宿口径
  - 实际出行日期必须二次核验
  - 后续可映射真实库存 API
verification_items:
  - 目的地季节
  - 交通住宿资源
  - 人群适配风险
  - 报价边界
evidence_type: fictional_product_catalog
---

# 知行旅行社产品路线模板

> 示例内部文档，用于演示旅行社智能顾问如何参考自家产品标准。文档内容为虚构业务资料，不代表真实库存或价格承诺。

## 产品定位

知行的路线产品分为两类：

- 自由规划型：用户自己出行，需要清晰路线、预算、住宿区域和避坑提醒，不强调旅行社托管。
- 省心方案型：用户希望减少决策成本，由顾问按成熟路线、服务标准和预算档位整合为可落地方案。

## 产品匹配字段

| field | value |
|---|---|
| product_id | ZX-PROD-CATALOG-OVERVIEW |
| destination | general |
| theme | product_line_overview |
| duration | varied |
| audience | family / couple / senior / team / free_planning |
| service_level | route_template |
| price_band | varied |
| source | fictional_internal_catalog |
| category | products |
| evidence_type | fictional_product_catalog |

上述字段用于检索和匹配，不代表真实库存、真实供应商报价或客户资料。

## 轻量产品线

- 亲子省心轻定制：适合带娃家庭，强调短动线、可午休、亲子友好住宿、少排队和室内备选。
- 银发舒缓路线：适合长辈同行，强调少步行、少换乘、近地铁或打车方便、休息点和医疗便利。
- 团建透明预算方案：适合公司或多人同行，强调统一集合、餐饮容量、团队活动空间、人均和总价同时透明。
- 情侣氛围轻路线：适合情侣或纪念日出行，强调夜景、特色餐厅、轻松街区漫步和弹性留白。
- 通用省心轻定制：适合没有强人群标签但希望省心的用户，强调成熟路线结构、同区动线、预算拆分和风险预案。
- 自由行路线优化：适合明确不跟团、自己预订的用户，只提供路线、预算、住宿区域和核验建议，不做旅行社方案推销。
- 长线目的地样板：西藏、新疆、云南等长线产品可以按目的地弱匹配先给省心路线方向，再根据用户画像和预算调整。
- 合作产品候选：未来接入真实产品服务后，`external_product_ref` 可映射到供应商产品；当前演示目录统一为 `demo_only`，不得承诺真实库存。

## 主推路线结构

成熟路线必须包含：

- 出发与抵达安排：明确首日不要塞满，优先保证入住和适应节奏。
- 核心体验：每天 1 个主体验 + 1 个轻体验，避免景点堆砌。
- 同区动线：上午、下午、晚上尽量在同一区域或顺路区域。
- 弹性留白：每天至少预留 1 段机动时间，适合天气变化、排队、临时休息。
- 备选方案：室外景点必须准备室内 Plan B。

## 景点票价模板

旅行社方案必须把景点/体验费用拆成“公开参考价、预约/开放说明、来源、采集日期、待核验边界”五个要素。2026-05-19 第一版参考目录覆盖杭州、西安、厦门、长沙、苏州、云南、新疆、西藏、桂林等常见样板目的地；目录未覆盖时只从公网搜索官方/公开票务页作为参考。当前无商务资质，OTA（在线旅行社）和票务供应商实时接口接入先搁置；正式报价前仍要以景区官方购票页或公开票务页二次核验。

| 产品线 | 门票表达口径 | 用户可见说法 |
|---|---|---|
| 亲子/银发 | 少排队、可预约、可替代，比低价更重要 | “这些票价是参考价，我会把预约窗口和备选方案列出来。” |
| 情侣/轻松 | 氛围体验、演出、船票和夜游价格浮动大 | “演出/船票按日期和座席浮动，先按样例价估算。” |
| 团建/小团 | 团队票、讲解、区间车、包车需单独核验 | “团队容量和票务政策要行前确认，不做锁价承诺。” |
| 自由规划 | 只给核验清单，不表达代订或托管 | “你可以自己订，我把官方核验点和预算边界列清。” |

## 适合人群模板

- 亲子游：优先短动线、亲子友好酒店、可午休、少排队、少换乘。
- 情侣游：优先氛围感、夜景、特色餐厅、轻松街区漫步。
- 银发游：优先少步行、低强度、近地铁或打车方便、医疗和休息点充足。
- 团建游：优先统一集合、餐饮容量、团队活动空间、预算透明。

## 报告表达要求

报告中可以自然说明“采用成熟路线结构”“已按人群降低强度”“预留天气备选”，但不要硬性推销，不要制造焦虑。

## 产品边界

- 轻量产品只代表规划方法和服务口径，不代表真实库存、成团状态、酒店占房或票务锁价。
- 如果用户选择自由行路线优化，报告应保持中立实用，避免暗示必须购买旅行社服务。
- 如果用户选择省心方案型，报告可以体现顾问价值，但必须把待核验价格和正式预订边界说清楚。
