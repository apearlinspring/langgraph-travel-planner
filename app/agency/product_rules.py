"""Lightweight agency product rules."""
from __future__ import annotations

from typing import Any

from app.agency.models import AgencyProductData, PlanningMode
from app.agency.planning_mode import infer_planning_mode, requirement_text


BUDGET_LEVEL_LABELS = {
    "economy": "经济",
    "comfort": "舒适",
    "luxury": "高端",
}

PRODUCT_CATALOG: dict[str, dict[str, Any]] = {
    "family": {
        "code": "family_light_custom",
        "name": "亲子省心轻定制",
        "product_type": "顾问定制",
        "positioning": "短动线、可午休、少排队，适合带孩子的家庭。",
        "route_rules": [
            "每天保留午休或机动时间，核心体验不超过 1-2 个。",
            "优先选择同区动线、亲子友好住宿和室内 Plan B。",
            "热门项目提前标记预约、排队和儿童身高/年龄限制。",
        ],
        "service_nodes": ["需求确认", "亲子节奏校验", "交通酒店核验", "行前提醒"],
    },
    "senior": {
        "code": "senior_comfort_route",
        "name": "银发舒缓路线",
        "product_type": "顾问定制",
        "positioning": "少步行、少换乘、休息点充足，适合长辈同行。",
        "route_rules": [
            "每天减少跨区移动，优先打车便利和近地铁区域。",
            "景点之间留足休息时间，避免连续高强度步行。",
            "住宿优先考虑电梯、安静度、医疗与餐饮便利性。",
        ],
        "service_nodes": ["需求确认", "低强度动线校验", "住宿便利性核验", "行前提醒"],
    },
    "team": {
        "code": "team_transparent_plan",
        "name": "团建透明预算方案",
        "product_type": "省心方案",
        "positioning": "统一集合、容量稳定、预算透明，适合公司或多人同行。",
        "route_rules": [
            "优先确认集合点、用餐容量、活动空间和统一交通。",
            "预算按人均和总价同时展示，标出可调整的大头费用。",
            "保留备选活动，避免天气或排队影响团队节奏。",
        ],
        "service_nodes": ["需求确认", "团队容量校验", "统一交通核验", "预算说明"],
    },
    "couple": {
        "code": "couple_mood_route",
        "name": "情侣氛围轻路线",
        "product_type": "顾问定制",
        "positioning": "氛围感、夜景、特色餐厅与轻松街区漫步优先。",
        "route_rules": [
            "每天安排一个主体验，搭配夜景、咖啡或特色餐厅。",
            "减少赶路和早起，保留拍照、散步和临时调整空间。",
            "热门餐厅、演出和夜景机位提前标记预约风险。",
        ],
        "service_nodes": ["需求确认", "氛围体验筛选", "餐厅预约提醒", "行前提醒"],
    },
    "standard": {
        "code": "comfort_light_custom",
        "name": "省心轻定制",
        "product_type": "省心方案",
        "positioning": "用成熟路线骨架降低决策成本，兼顾体验、预算和风险。",
        "route_rules": [
            "每天 1 个主体验 + 1 个轻体验，避免景点堆砌。",
            "上午、下午、晚上尽量同区或顺路，减少无效通勤。",
            "室外项目配室内 Plan B，价格波动项出发前复核。",
        ],
        "service_nodes": ["需求确认", "路线初稿", "交通酒店核验", "预算说明", "行前提醒"],
    },
    "free": {
        "code": "free_planning_optimizer",
        "name": "自由行路线优化",
        "product_type": "自由规划",
        "positioning": "保持用户自主预订，提供路线、预算、住宿区域和避坑建议。",
        "route_rules": [
            "不绑定旅行社产品，以可执行路线和透明估算为主。",
            "保留用户自主选择空间，只在高风险项给出核验提醒。",
            "预算仅作规划参考，正式预订以平台实时价格为准。",
        ],
        "service_nodes": ["需求整理", "路线优化", "预算说明", "出发前核验"],
    },
}

DEFAULT_DELIVERABLES = [
    "成熟路线结构与每日动线",
    "交通、住宿、餐饮、景点/体验和其他机动预算拆分",
    "预算置信度、待核验项和可调整方向",
    "天气、预约、体力和价格波动风险提醒",
]

DEFAULT_NON_COMMITMENTS = [
    "不代表真实库存、成团状态或酒店占房。",
    "不承诺交通、酒店、门票或体验项目锁价。",
    "不生成真实支付链接，也不代表已经完成预订。",
]


def _duration_label(requirement: dict[str, Any]) -> str:
    travel_days = requirement.get("travel_days")
    if isinstance(travel_days, int) and travel_days > 0:
        return f"{travel_days}天{max(travel_days - 1, 0)}晚"
    return "天数待确认"


def _budget_level(requirement: dict[str, Any]) -> tuple[str, str]:
    code = str(requirement.get("budget_level") or "待确认")
    return code, BUDGET_LEVEL_LABELS.get(code, code)


def infer_user_segment(
    requirement: dict[str, Any],
    mode: PlanningMode,
    state: dict[str, Any] | None = None,
) -> str:
    if mode == "free_planning":
        return "free"

    text = requirement_text(requirement, state)
    if (requirement.get("children_count") or 0) > 0 or any(
        keyword in text for keyword in ("亲子", "孩子", "儿童", "带娃")
    ):
        return "family"
    if any(keyword in text for keyword in ("银发", "老人", "长辈", "父母")):
        return "senior"
    if any(keyword in text for keyword in ("团建", "公司", "团队", "多人", "部门")):
        return "team"
    if any(keyword in text for keyword in ("情侣", "蜜月", "纪念日")):
        return "couple"
    return "standard"


def _matched_signals(
    requirement: dict[str, Any],
    mode: PlanningMode,
    segment: str,
    state: dict[str, Any] | None = None,
) -> list[str]:
    total_people = (requirement.get("adult_count") or 0) + (
        requirement.get("children_count") or 0
    )
    budget_code, budget_label = _budget_level(requirement)
    signals = [
        (
            "用户表达省心、成熟路线或旅行社方案倾向。"
            if mode == "agency_plan"
            else "用户更适合自由行规划表达，不做旅行社硬推。"
        )
    ]
    if segment == "family":
        signals.append("同行有儿童或亲子需求，路线需要降低强度。")
    elif segment == "senior":
        signals.append("存在长辈或银发友好需求，优先舒缓动线。")
    elif segment == "team":
        signals.append("存在团队同行诉求，报价要同时看人均和总价。")
    if total_people:
        signals.append(f"按 {total_people} 人同行做产品匹配。")
    if requirement.get("travel_days"):
        signals.append(f"按 {requirement['travel_days']} 天行程控制每日体验密度。")
    if budget_code != "待确认":
        signals.append(f"预算档位为{budget_label}档，优先匹配同档住宿和体验。")
    if requirement.get("special_needs"):
        signals.append(f"特殊备注：{requirement['special_needs']}")
    return signals[:6]


def build_light_product(
    requirement: dict[str, Any],
    state: dict[str, Any] | None = None,
) -> AgencyProductData:
    mode = infer_planning_mode(requirement, state)
    segment = infer_user_segment(requirement, mode, state)
    product = PRODUCT_CATALOG[segment]
    budget_code, budget_label = _budget_level(requirement)

    return {
        "mode": mode,
        "segment": segment,
        "code": product["code"],
        "name": product["name"],
        "product_type": product["product_type"],
        "positioning": product["positioning"],
        "duration_label": _duration_label(requirement),
        "budget_level": budget_label,
        "budget_level_code": budget_code,
        "matched_signals": _matched_signals(requirement, mode, segment, state),
        "route_rules": list(product["route_rules"]),
        "service_nodes": list(product["service_nodes"]),
        "deliverables": list(DEFAULT_DELIVERABLES),
        "non_commitments": list(DEFAULT_NON_COMMITMENTS),
    }


def format_light_product_lines(product: AgencyProductData) -> list[str]:
    if not product:
        return ["- 产品匹配待补充。"]
    service_nodes = " → ".join(product.get("service_nodes") or [])
    lines = [
        f"- 产品匹配：{product.get('name', '轻量产品')}（{product.get('product_type', '规划服务')}，{product.get('duration_label', '天数待确认')}，{product.get('budget_level', '预算待确认')}档）",
        f"- 定位：{product.get('positioning', '定位待补充')}",
    ]
    if service_nodes:
        lines.append(f"- 服务节点：{service_nodes}")
    if product.get("route_rules"):
        lines.append("- 路线规则：" + "；".join(product["route_rules"][:3]))
    if product.get("non_commitments"):
        lines.append("- 不承诺项：" + "；".join(product["non_commitments"][:3]))
    return lines

