---
source_type: agency_internal
category: scenic_tickets
visibility: internal
source: curated_public_scenic_ticket_reference
provider: curated_rag_ticket_catalog
provider_status: public_reference_only
public_search_fallback: true
supplier_integration_status: deferred_no_business_qualification
applicable_modes:
  - agency_plan
  - free_planning
evidence_level: reference
last_reviewed: "2026-05-11"
title: 景点门票与预约公开参考价目录
price_collected_at: "2026-05-19"
deferred_supplier_candidates:
  - name: 携程玩乐开放平台
    role: OTA 门票/玩乐分销接口候选
    access_note: 当前无商务资质，接入搁置；未来需商户或合作资质、API 密钥、沙箱联调和结算/退改规则确认
    docs_url: https://ttdstp.ctrip.com/apiplatform/document/channelin.do
  - name: 飞猪开放平台门票 API2.0
    role: 门票商品、价格、库存和订单接口候选
    access_note: 当前无商务资质，接入搁置；未来需淘宝/飞猪开放平台应用、类目权限和商家合作授权
    docs_url: https://open.alitrip.com/
  - name: 票付通
    role: 景区票务系统和分销对接候选
    access_note: 当前无景区/分销商务关系，接入搁置；未来适合已有合作后做库存、下单和核销联调
    docs_url: https://www.piaofutong.com/
  - name: 智游宝
    role: 景区电子票务和分销接口候选
    access_note: 当前无供应链侧授权，接入搁置；未来需商务开通和接口联调
    docs_url: https://www.zhiyoubao.com/
ticket_items:
  - destination: 杭州
    region: 浙江
    name: 西湖
    aliases: [西湖风景名胜区]
    adult_price: 0
    price_label: 开放式湖区免费；游船、雷峰塔、演出等单项另计
    reservation_note: 开放式湖区为主，收费场馆和游船按官方购票页二次核验
    open_note: 开放区域较多，具体场馆和船班时间以出发前公告为准
    source: 杭州西湖风景名胜区公开信息
    source_url: https://westlake.hangzhou.gov.cn/
  - destination: 杭州
    region: 浙江
    name: 灵隐飞来峰
    aliases: [飞来峰, 灵隐寺]
    adult_price: 45
    price_label: 飞来峰景区成人参考票 45 元；寺院香花券另计
    reservation_note: 热门时段建议提前实名预约，寺院票务规则独立核验
    open_note: 开放时间随季节和管理公告调整
    source: 杭州西湖风景名胜区公开票务信息
    source_url: https://westlake.hangzhou.gov.cn/
  - destination: 杭州
    region: 浙江
    name: 西溪湿地
    aliases: [西溪国家湿地公园]
    adult_price: 80
    price_label: 成人门票常见公开参考 80 元；电瓶船/摇橹船另计
    reservation_note: 门船组合、优惠票和闭园时间以景区购票页为准
    open_note: 入园和船票停止售检时间需出发前复核
    source: 杭州西溪国家湿地公园公开信息
    source_url: https://www.xixiwetland.com.cn/
  - destination: 杭州
    region: 浙江
    name: 宋城
    aliases: [宋城千古情]
    adult_price: 320
    price_label: 演艺套票价格按日期和座席浮动，以官方购票页实时价为准
    reservation_note: 演出场次、座席和节假日价格变化较大，必须二次核验
    open_note: 演出日程和入园时间以当天公告为准
    source: 宋城演艺/景区公开信息
    source_url: https://www.songcn.com/
  - destination: 西安
    region: 陕西
    name: 秦始皇兵马俑
    aliases: [兵马俑, 秦始皇帝陵博物院]
    adult_price: 120
    price_label: 成人参考票 120 元，讲解和优惠政策另计
    reservation_note: 热门假期建议提前实名预约
    open_note: 开放时间和停止入园时间以官方公告为准
    source: 秦始皇帝陵博物院公开票务信息
    source_url: https://www.bmy.com.cn/
  - destination: 西安
    region: 陕西
    name: 西安城墙
    aliases: [明城墙]
    adult_price: 54
    price_label: 成人参考票 54 元，骑行和演出项目另计
    reservation_note: 登城口开放、夜游和骑行项目需出发前复核
    open_note: 开放口和闭城时间可能按季节调整
    source: 西安城墙景区公开票务信息
    source_url: https://www.chinaxiancitywall.com/
  - destination: 西安
    region: 陕西
    name: 陕西历史博物馆
    aliases: [陕历博]
    adult_price: 0
    price_label: 基本陈列免费预约；特展可能收费
    reservation_note: 实名预约难度较高，热门日期需提前关注放票
    open_note: 闭馆和特展规则以官方公告为准
    source: 陕西历史博物馆公开预约信息
    source_url: https://www.sxhm.com/
  - destination: 厦门
    region: 福建
    name: 鼓浪屿核心景点
    aliases: [日光岩, 菽庄花园, 皓月园]
    adult_price: 90
    price_label: 核心景点联票常见参考 90 元；单点票和轮渡另计
    reservation_note: 鼓浪屿船票、景点联票和节假日放票需分别核验
    open_note: 场馆开放和停止入园时间以官方公告为准
    source: 鼓浪屿文化旅游公开信息
    source_url: https://www.gly.cn/
  - destination: 厦门
    region: 福建
    name: 厦门园林植物园
    aliases: [万石植物园]
    adult_price: 30
    price_label: 成人参考票 30 元，观光车另计
    reservation_note: 优惠票、观光车和热门园区客流需二次核验
    open_note: 开放时间按景区公告调整
    source: 厦门园林植物园公开信息
    source_url: https://www.xiamenbg.com/
  - destination: 长沙
    region: 湖南
    name: 岳麓书院
    aliases: [岳麓山岳麓书院]
    adult_price: 40
    price_label: 成人参考票 40 元；岳麓山开放区域多为免费
    reservation_note: 书院门票、讲解和团队入园需出发前核验
    open_note: 开放时间以湖南大学岳麓书院公告为准
    source: 湖南大学岳麓书院公开信息
    source_url: https://ylsy.hnu.edu.cn/
  - destination: 长沙
    region: 湖南
    name: 湖南博物院
    aliases: [湖南省博物馆]
    adult_price: 0
    price_label: 基本陈列免费预约；特展可能收费
    reservation_note: 热门日期预约紧张，团队需提前核验预约规则
    open_note: 闭馆日和夜场安排以官方公告为准
    source: 湖南博物院公开预约信息
    source_url: https://www.hnmuseum.com/
  - destination: 苏州
    region: 江苏
    name: 拙政园
    aliases: [苏州园林拙政园]
    adult_price: 80
    price_label: 旺季成人参考票 80 元；淡季和优惠票以官方页为准
    reservation_note: 热门园林建议提前预约，节假日限流需核验
    open_note: 开放和停止入园时间按季节调整
    source: 苏州园林旅游公开信息
    source_url: https://www.szzzy.cn/
  - destination: 苏州
    region: 江苏
    name: 留园
    aliases: [苏州留园]
    adult_price: 55
    price_label: 旺季成人参考票 55 元；淡季和优惠票以官方页为准
    reservation_note: 团队和长辈同行需核验预约、讲解和入园规则
    open_note: 开放时间按景区公告调整
    source: 苏州园林旅游公开信息
    source_url: https://www.szzzy.cn/
  - destination: 云南
    city: 昆明
    region: 云南
    name: 石林风景区
    aliases: [昆明石林]
    adult_price: 130
    price_label: 成人门票常见参考 130 元；电瓶车另计
    reservation_note: 门票、车票组合和优惠政策以官方购票页为准
    open_note: 开放时间和节假日客流需二次核验
    source: 石林风景区公开信息
    source_url: http://www.chinastoneforest.com/
  - destination: 云南
    city: 大理
    region: 云南
    name: 崇圣寺三塔
    aliases: [大理三塔]
    adult_price: 75
    price_label: 成人门票常见参考 75 元，电瓶车另计
    reservation_note: 优惠政策和团队票需以景区购票页为准
    open_note: 开放时间按景区公告调整
    source: 大理崇圣寺三塔公开信息
    source_url: https://www.dalisanta.com/
  - destination: 云南
    city: 丽江
    region: 云南
    name: 玉龙雪山
    aliases: [玉龙雪山冰川公园]
    adult_price: 100
    price_label: 进山费常见参考 100 元；索道、环保车和演出另计
    reservation_note: 索道票和进山政策强依赖日期、天气和实名预约
    open_note: 大风、雪季和维护可能临时调整开放
    source: 丽江玉龙雪山公开信息
    source_url: https://www.lijiangtour.com/
  - destination: 新疆
    city: 阿勒泰
    region: 新疆
    name: 喀纳斯
    aliases: [喀纳斯景区]
    adult_price: 160
    price_label: 门票常见参考 160 元；区间车和多日票另计
    reservation_note: 门车组合、旺季限流和住宿接驳需二次核验
    open_note: 开放受季节、天气和道路影响明显
    source: 喀纳斯景区公开信息
    source_url: https://www.kns.gov.cn/
  - destination: 新疆
    city: 博乐
    region: 新疆
    name: 赛里木湖
    aliases: [赛湖]
    adult_price: 145
    price_label: 门票和区间车组合常见参考 145 元；自驾政策另计核验
    reservation_note: 自驾、区间车和旺季入园规则需出发前确认
    open_note: 湖区天气和道路情况可能影响游览
    source: 赛里木湖景区公开信息
    source_url: https://www.xjslmh.com/
  - destination: 西藏
    city: 拉萨
    region: 西藏
    name: 布达拉宫
    aliases: [布宫]
    adult_price: 200
    price_label: 旺季成人参考票 200 元；淡季和预约规则以官方公告为准
    reservation_note: 实名预约严格，旺季需提前关注放票和参观时段
    open_note: 开放时间、参观线路和临时管控需二次核验
    source: 布达拉宫官方网站公开信息
    source_url: https://www.potalapalace.cn/
  - destination: 西藏
    city: 拉萨
    region: 西藏
    name: 大昭寺
    aliases: [大昭寺广场]
    adult_price: 85
    price_label: 成人参考票 85 元，讲解和特殊活动另计
    reservation_note: 宗教活动、团队入寺和优惠政策需提前核验
    open_note: 开放时间可能因法会或临时管控调整
    source: 西藏文旅公开信息
    source_url: https://wlt.xizang.gov.cn/
  - destination: 桂林
    region: 广西
    name: 漓江游船
    aliases: [漓江, 桂林漓江]
    adult_price: 215
    price_label: 桂林至阳朔游船常见参考 215 元起；船型、码头和餐标另计
    reservation_note: 船班、水位、码头和实名信息需出发前核验
    open_note: 水位、天气和航道管制会影响开航
    source: 桂林漓江景区公开信息
    source_url: https://www.liriver.com.cn/
  - destination: 桂林
    region: 广西
    name: 象鼻山
    aliases: [象山景区]
    adult_price: 0
    price_label: 常见为免费预约，具体预约规则以官方公告为准
    reservation_note: 节假日客流和预约规则需二次核验
    open_note: 开放时间以景区公告为准
    source: 桂林文旅公开信息
    source_url: https://wglj.guilin.gov.cn/
---

# 景点门票与预约公开参考价目录

本目录为知行旅行顾问的第一版票价知识底座，用于把旅行社方案里的“景点/体验费用”从代码静态字典迁移到可审计知识文档。所有价格均为公开参考价或常见票价口径，不代表实时库存、预约成功、优惠政策或锁价。

## 接入判断

- 实时门票、库存、预约、下单和核销需要接入 OTA、景区票务系统或分销平台，并完成商务资质、API 密钥、沙箱联调、结算、退改和售后规则确认。
- 当前目录先服务演示和方案报价边界：可展示“样例价、采集日期、来源、待核验、不锁价”，不能承诺出票或预约。
- 后续只有在补齐商务资质、接口授权、结算、售后和核销流程后，`provider_status` 才可升级为 `live_supplier`；当前统一保持公开目录或公网搜索参考，不承诺预约成功或锁价。

## 输出规则

- 面向用户说“门票参考价”“预约提醒”“出发前核验”，不要说内部知识库、RAG 或工具名。
- 门票和体验费用应进入预算明细和出发前确认项，但不能作为正式合同锁价。
- 对热门预约类景点，如布达拉宫、陕西历史博物馆、湖南博物院、灵隐飞来峰、鼓浪屿船票，应优先提示实名预约和放票窗口。

## 票价样例表

| 目的地 | 景点/体验 | 公开参考价 | 预约/开放说明 | 来源 |
|---|---|---:|---|---|
| 杭州 | 西湖开放式湖区 | 免费，游船/登塔/演出另计 | 收费场馆和船班按官方信息复核 | 杭州西湖风景名胜区 |
| 杭州 | 灵隐飞来峰 | 成人约 45 元，寺院香花券另计 | 热门时段建议提前实名预约 | 杭州西湖风景名胜区 |
| 杭州 | 西溪湿地 | 成人约 80 元，船票另计 | 门船组合、优惠票、闭园时间需确认 | 西溪国家湿地公园 |
| 杭州 | 宋城/千古情演艺 | 套票常见约 320 元起 | 场次和座席按日期浮动 | 宋城演艺 |
| 西安 | 秦始皇兵马俑 | 成人约 120 元 | 节假日建议实名预约 | 秦始皇帝陵博物院 |
| 西安 | 西安城墙 | 成人约 54 元 | 登城口、夜游和骑行项目需复核 | 西安城墙景区 |
| 西安 | 陕西历史博物馆 | 基本陈列免费预约，特展可能收费 | 热门日期需提前关注放票 | 陕西历史博物馆 |
| 厦门 | 鼓浪屿核心景点联票 | 常见参考约 90 元，轮渡另计 | 船票和景点票需分别核验 | 鼓浪屿文化旅游 |
| 厦门 | 厦门园林植物园 | 成人约 30 元 | 观光车和热门园区客流需确认 | 厦门园林植物园 |
| 长沙 | 岳麓书院 | 成人约 40 元 | 团队入园和讲解需核验 | 湖南大学岳麓书院 |
| 长沙 | 湖南博物院 | 基本陈列免费预约，特展可能收费 | 团队预约和放票需提前确认 | 湖南博物院 |
| 苏州 | 拙政园 | 旺季成人约 80 元 | 热门园林建议提前预约 | 苏州园林旅游 |
| 苏州 | 留园 | 旺季成人约 55 元 | 团队、讲解和入园时段需核验 | 苏州园林旅游 |
| 云南 | 石林风景区 | 成人约 130 元，电瓶车另计 | 门票、车票组合和优惠政策需确认 | 石林风景区 |
| 云南 | 崇圣寺三塔 | 成人约 75 元，电瓶车另计 | 团队票和优惠政策需核验 | 大理崇圣寺三塔 |
| 云南 | 玉龙雪山 | 进山费约 100 元，索道/环保车另计 | 索道票依赖日期、天气和实名预约 | 丽江玉龙雪山 |
| 新疆 | 喀纳斯 | 门票约 160 元，区间车另计 | 旺季限流和门车组合需二次核验 | 喀纳斯景区 |
| 新疆 | 赛里木湖 | 门票和区间车组合约 145 元 | 自驾政策和旺季入园规则需确认 | 赛里木湖景区 |
| 西藏 | 布达拉宫 | 旺季成人约 200 元 | 实名预约严格，需关注放票时段 | 布达拉宫官方网站 |
| 西藏 | 大昭寺 | 成人约 85 元 | 宗教活动和团队入寺需提前核验 | 西藏文旅公开信息 |
| 桂林 | 漓江游船 | 常见约 215 元起，船型/码头/餐标另计 | 船班、水位和实名信息需核验 | 桂林漓江景区 |
| 桂林 | 象鼻山 | 常见为免费预约 | 节假日客流和预约规则需核验 | 桂林文旅 |
