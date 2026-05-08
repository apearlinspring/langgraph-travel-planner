import pytest
import inspect
from pathlib import Path
from langchain.tools import ToolRuntime

from app.agents.handoffs import step_config as step_config_module
from app.agents.subagents.transport_coordinator import create_transport_coordinator
from app.core.state import create_initial_state
from app.core.workflow import (
    FINAL_PLANNING_STEP,
    INITIAL_PLANNING_STEP,
    PLANNING_STEPS,
    STEP_LABELS,
    STEP_STATE_FIELDS,
)
from app.tools.state_transition import (
    check_current_progress,
    generate_itinerary_tool,
    generate_order_tool,
    go_back_to_step,
    select_accommodation_tool,
    select_food_tool,
    select_transport_tool,
    summarize_budget_tool,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _build_runtime(state):
    return ToolRuntime(
        state=state,
        context=None,
        config={},
        stream_writer=lambda _: None,
        tool_call_id="tool-call-1",
        store=None,
    )


def test_workflow_metadata_covers_every_planning_step():
    assert set(STEP_LABELS) == set(PLANNING_STEPS)
    assert set(STEP_STATE_FIELDS) == set(PLANNING_STEPS)
    assert FINAL_PLANNING_STEP == PLANNING_STEPS[-1]


def test_create_initial_state_uses_shared_entry_step():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    assert state["current_step"] == INITIAL_PLANNING_STEP


def test_transport_coordinator_prompt_guards_real_recommendation_quality():
    source = inspect.getsource(create_transport_coordinator)

    assert 'profile="transport"' in source
    assert "temperature=0.2" in source
    assert "不要重复查询" in source
    assert "带孩子、老人、行李多" in source
    assert "明显超长距离" in source
    assert "当前无票、仅无座、只有高价商务座" in source
    assert "正式购票或出发前需要再次核实" in source


def test_qwen_entrypoints_use_shared_compatible_mode_factory():
    direct_factory_users = [
        "app/agents/handoffs/travel_agent.py",
        "app/agents/routers/destination_router.py",
        "app/agents/subagents/transport_coordinator.py",
        "app/agents/subagents/flight_agent.py",
        "app/agents/subagents/train_agent.py",
        "app/agents/subagents/driving_agent.py",
        "app/rag/query_optimizer.py",
        "app/rag/reranker.py",
        "tests/test_rag_agent_autonomous.py",
        "scripts/test_llm.py",
        "test1.py",
    ]

    for relative_path in direct_factory_users:
        path = PROJECT_ROOT / relative_path
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        assert "build_chat_model" in content, relative_path

    no_chat_tongyi_files = direct_factory_users + ["test2.py"]
    for relative_path in no_chat_tongyi_files:
        path = PROJECT_ROOT / relative_path
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        assert "ChatTongyi" not in content, relative_path


@pytest.mark.asyncio
async def test_step_config_covers_all_planning_steps(monkeypatch):
    async def empty_tools():
        return []

    monkeypatch.setattr(step_config_module, "get_hotel_followup_tools", empty_tools)
    monkeypatch.setattr(step_config_module, "get_search_tools", empty_tools)
    monkeypatch.setattr(step_config_module, "get_date_tools", empty_tools)

    config = await step_config_module.get_step_config()

    assert tuple(config) == PLANNING_STEPS
    assert "可以引导用户关注公众号" not in config["order_generation"]["prompt"]
    assert "不要添加没有事实来源" in config["order_generation"]["prompt"]
    assert "不要直接生成订单" in config["order_generation"]["prompt"]
    assert "不要编造支付链接" in config["order_generation"]["prompt"]
    assert "weather_info" in config["destination_recommendation"]["prompt"]
    assert "attractions" in config["destination_recommendation"]["prompt"]
    assert "最高优先级执行规则" in config["transport_planning"]["prompt"]
    assert "最高优先级执行规则" in config["accommodation_planning"]["prompt"]
    assert "必须立刻调用 query_transport_options" in config["transport_planning"]["prompt"]
    assert "必须立刻调用 query_hotel_options" in config["accommodation_planning"]["prompt"]
    assert "必须先调用 generate_itinerary_tool" in config["itinerary_generation"]["prompt"]
    assert "不要先输出长篇自然语言行程草案" in config["itinerary_generation"]["prompt"]
    assert "4天3晚 必须有 Day 1、Day 2、Day 3、Day 4" in config["itinerary_generation"]["prompt"]
    assert "必须调用 summarize_budget_tool" in config["budget_summarization"]["prompt"]
    assert "费用依据" in config["budget_summarization"]["prompt"]
    assert "预算置信度" in config["budget_summarization"]["prompt"]
    assert "预算匹配" in config["budget_summarization"]["prompt"]
    assert "关键假设" in config["budget_summarization"]["prompt"]
    assert "已确认方案摘要" in config["order_generation"]["prompt"]
    assert "{budget_summary}" in config["order_generation"]["prompt"]
    assert "每日行程”里的当天地图路线摘要保持一致" in config["order_generation"]["prompt"]
    assert "report_data" in config["order_generation"]["prompt"]
    assert "不要输出" in config["order_generation"]["prompt"]
    assert "[根据之前的对话填写]" in config["order_generation"]["prompt"]
    assert all(tool.name != "add_travel_record_tool" for tool in config["order_generation"]["tools"])


def test_go_back_to_step_clears_fields_from_shared_workflow_metadata():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "budget_summarization",
            "user_requirement": {
                "departure_city": "上海",
                "destination": "西安",
                "departure_date": "2026-05-01",
                "travel_days": 3,
                "adult_count": 2,
                "children_count": 1,
                "budget_min": 1000.0,
                "budget_max": 2000.0,
                "budget_level": "comfort",
                "travel_styles": ["culture"],
                "special_needs": None,
            },
            "selected_destination": "西安",
            "destination_options": [{"name": "西安"}],
            "selected_transport": "train",
            "selected_transport_option": {
                "transport_type": "train",
                "details": "G1 北京南 -> 上海虹桥",
                "price": 626.0,
            },
            "transport_options": [{"transport_type": "train"}],
            "selected_accommodation_types": ["star_hotel"],
            "selected_accommodation_option": {
                "hotel_id": 43615,
                "name": "酒店A",
                "type": "star_hotel",
                "location": "市中心",
                "price_per_night": 888.0,
                "rating": 4.5,
                "amenities": ["亲子酒店"],
            },
            "accommodation_options": [{"name": "酒店A"}],
            "selected_food_types": ["local"],
            "food_options": [{"type": "local"}],
            "itinerary": [{"day_number": 1}],
            "budget": {"total": 1000.0},
            "order_id": "ORDER-1234",
            "report": "最终旅行方案报告",
        }
    )

    command = go_back_to_step.invoke(
        {
            "target_step": "transport_planning",
            "reason": "调整交通方案",
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["current_step"] == "transport_planning"
    assert command.update["selected_transport"] is None
    assert command.update["selected_transport_option"] is None
    assert command.update["transport_options"] is None
    assert command.update["selected_accommodation_types"] is None
    assert command.update["selected_accommodation_option"] is None
    assert command.update["accommodation_options"] is None
    assert command.update["selected_food_types"] is None
    assert command.update["food_options"] is None
    assert command.update["itinerary"] is None
    assert command.update["budget"] is None
    assert command.update["order_id"] is None
    assert command.update["report"] is None
    assert "交通规划" in command.update["messages"][0].content


def test_select_transport_tool_can_persist_concrete_transport_option():
    state = create_initial_state(user_id="user-1", session_id="session-1")

    command = select_transport_tool.invoke(
        {
            "transport_type": "train",
            "details": "G1 北京南 -> 上海虹桥",
            "departure_time": "06:30",
            "arrival_time": "11:24",
            "duration": "04:54",
            "price": 626.0,
            "source": "12306",
            "runtime": _build_runtime(state),
        }
    )

    selected_option = command.update["selected_transport_option"]
    assert command.update["current_step"] == "accommodation_planning"
    assert command.update["selected_transport"] == "train"
    assert selected_option["details"] == "G1 北京南 -> 上海虹桥"
    assert selected_option["price"] == 626.0
    assert "G1 北京南" in command.update["messages"][0].content


def test_select_destination_tool_can_persist_destination_context():
    from app.tools.state_transition import select_destination_tool

    state = create_initial_state(user_id="user-1", session_id="session-1")

    command = select_destination_tool.invoke(
        {
            "destination": "上海",
            "description": "城市文化和美食都很集中，适合短途慢游",
            "weather_info": "可能有阵雨，建议准备室内备选",
            "attractions": ["外滩", "上海博物馆", "田子坊"],
            "estimated_cost": 1800.0,
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["selected_destination"] == "上海"
    assert command.update["current_step"] == "transport_planning"
    assert command.update["destination_options"][0]["weather_info"] == "可能有阵雨，建议准备室内备选"
    assert "上海博物馆" in command.update["destination_options"][0]["attractions"]


def test_select_transport_tool_normalizes_common_chinese_labels():
    state = create_initial_state(user_id="user-1", session_id="session-1")

    command = select_transport_tool.invoke(
        {
            "transport_type": "高铁",
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["selected_transport"] == "train"
    assert command.update["current_step"] == "accommodation_planning"


def test_select_accommodation_tool_can_persist_concrete_hotel_option():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "accommodation_options": [
                {
                    "hotel_id": 43615,
                    "name": "北京王府井天伦王朝酒店",
                    "type": "star_hotel",
                    "location": "王府井大街50号",
                    "price_per_night": 1740.0,
                    "rating": 5.0,
                    "amenities": ["亲子酒店", "提供家庭房"],
                    "booking_url": "https://example.com/hotel/43615",
                }
            ]
        }
    )

    command = select_accommodation_tool.invoke(
        {
            "accommodation_types": ["star_hotel"],
            "hotel_id": 43615,
            "runtime": _build_runtime(state),
        }
    )

    selected_option = command.update["selected_accommodation_option"]
    assert command.update["current_step"] == "food_planning"
    assert command.update["selected_accommodation_types"] == ["star_hotel"]
    assert selected_option["hotel_id"] == 43615
    assert selected_option["name"] == "北京王府井天伦王朝酒店"
    assert selected_option["price_per_night"] == 1740.0
    assert "北京王府井天伦王朝酒店" in command.update["messages"][0].content


def test_select_accommodation_tool_normalizes_common_chinese_labels():
    state = create_initial_state(user_id="user-1", session_id="session-1")

    command = select_accommodation_tool.invoke(
        {
            "accommodation_types": ["酒店"],
            "hotel_name": "上海城市酒店",
            "price_per_night": 1308.0,
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["selected_accommodation_types"] == ["star_hotel"]
    assert command.update["selected_accommodation_option"]["type"] == "star_hotel"
    assert command.update["current_step"] == "food_planning"


def test_select_food_tool_normalizes_common_chinese_labels():
    state = create_initial_state(user_id="user-1", session_id="session-1")

    command = select_food_tool.invoke(
        {
            "food_types": ["本地小吃/夜市", "特色餐厅/名店"],
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["selected_food_types"] == ["local", "specialty"]
    assert command.update["current_step"] == "itinerary_generation"


def test_check_current_progress_uses_shared_step_labels():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "food_planning",
            "user_requirement": {
                "departure_city": "上海",
                "destination": "西安",
                "departure_date": "2026-05-01",
                "travel_days": 3,
                "adult_count": 2,
                "children_count": 1,
                "budget_min": 1000.0,
                "budget_max": 2000.0,
                "budget_level": "comfort",
                "travel_styles": ["culture"],
                "special_needs": None,
            },
            "selected_destination": "西安",
            "selected_transport": "train",
            "selected_transport_option": {
                "transport_type": "train",
                "details": "G1 北京南 -> 上海虹桥",
                "price": 626.0,
            },
            "selected_accommodation_types": ["star_hotel"],
            "selected_accommodation_option": {"name": "西安市中心酒店"},
            "selected_food_types": ["local"],
        }
    )

    progress_text = check_current_progress.invoke({"runtime": _build_runtime(state)})

    assert STEP_LABELS["food_planning"] in progress_text
    assert STEP_LABELS["order_generation"] in progress_text
    assert "当前步骤" in progress_text
    assert "G1 北京南" in progress_text
    assert "西安市中心酒店" in progress_text


def test_itinerary_budget_and_order_report_use_selected_real_options():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "itinerary_generation",
            "user_requirement": {
                "departure_city": "北京",
                "destination": "上海",
                "departure_date": "2026-05-10",
                "travel_days": 3,
                "adult_count": 2,
                "children_count": 0,
                "budget_min": 1500.0,
                "budget_max": 3000.0,
                "budget_level": "comfort",
                "travel_styles": ["culture", "food"],
                "special_needs": None,
            },
            "selected_destination": "上海",
            "destination_options": [
                {
                    "name": "上海",
                    "description": "城市文化和美食集中",
                    "weather_info": "可能有阵雨，建议准备室内备选",
                    "attractions": ["外滩", "上海博物馆", "田子坊"],
                    "attraction_pois": [
                        {
                            "name": "外滩",
                            "area": "黄浦江沿岸",
                            "best_time": "晚上",
                            "duration_hours": 1.5,
                            "reservation_required": False,
                            "indoor": False,
                            "estimated_cost": 0.0,
                            "tags": ["夜景", "免费"],
                        },
                        {
                            "name": "上海博物馆",
                            "area": "人民广场",
                            "best_time": "上午",
                            "duration_hours": 2.5,
                            "reservation_required": True,
                            "indoor": True,
                            "estimated_cost": 0.0,
                            "tags": ["文化", "室内"],
                        },
                        {
                            "name": "豫园",
                            "area": "老城厢",
                            "best_time": "下午",
                            "duration_hours": 2.0,
                            "reservation_required": True,
                            "indoor": False,
                            "estimated_cost": 40.0,
                            "tags": ["园林", "门票"],
                        },
                    ],
                    "estimated_cost": 1800.0,
                }
            ],
            "selected_transport": "train",
            "selected_transport_option": {
                "transport_type": "train",
                "details": "G1 北京南 -> 上海虹桥",
                "departure_time": "06:30",
                "arrival_time": "11:24",
                "duration": "04:54",
                "price": 626.0,
            },
            "selected_accommodation_types": ["star_hotel"],
            "selected_accommodation_option": {
                "hotel_id": 123,
                "name": "上海市中心酒店",
                "type": "star_hotel",
                "location": "人民广场",
                "price_per_night": 800.0,
                "rating": 4.7,
                "amenities": ["近地铁"],
            },
            "selected_food_types": ["local"],
            "selected_food_pois": [
                {
                    "name": "南京路小吃",
                    "type": "local",
                    "area": "南京路/人民广场",
                    "meal_time": "晚餐",
                    "average_cost": 80.0,
                    "reservation_required": False,
                    "queue_risk": "中",
                    "suitable_for": ["小吃扫街"],
                    "tags": ["本地小吃"],
                },
                {
                    "name": "本帮菜餐厅",
                    "type": "specialty",
                    "area": "人民广场/南京路周边",
                    "meal_time": "晚餐",
                    "average_cost": 180.0,
                    "reservation_required": True,
                    "queue_risk": "中",
                    "suitable_for": ["特色餐厅"],
                    "tags": ["本帮菜"],
                },
            ],
        }
    )

    itinerary_command = generate_itinerary_tool.invoke({"runtime": _build_runtime(state)})
    state.update(itinerary_command.update)
    assert state["current_step"] == "budget_summarization"
    assert state["itinerary"][0]["accommodation"] == "上海市中心酒店"
    assert "G1 北京南" in state["itinerary"][0]["transport_note"]
    itinerary_text = "\n".join(
        activity
        for day in state["itinerary"]
        for activity in day["activities"]
    )
    assert "外滩" in itinerary_text
    assert "上海博物馆" in itinerary_text
    assert "上午/" in "\n".join(state["itinerary"][0]["time_blocks"])
    all_time_blocks = "\n".join(
        block
        for day in state["itinerary"]
        for block in day["time_blocks"]
    )
    assert "人民广场" in all_time_blocks
    assert "预约/费用提醒" in all_time_blocks
    assert "约 40 元/人" in all_time_blocks
    assert "室内备选" in all_time_blocks
    assert "餐饮提醒" in all_time_blocks
    assert "本帮菜餐厅 建议提前预约" in all_time_blocks
    assert state["itinerary"][0]["route_note"]
    route_notes = "\n".join(day["route_note"] for day in state["itinerary"])
    assert "当日主区域" in route_notes
    assert "餐饮优先匹配" in route_notes
    assert state["itinerary"][0]["risk_notes"]
    meal_text = "\n".join(
        meal
        for day in state["itinerary"]
        for meal in day["meals"]
    )
    assert "南京路小吃" in meal_text
    assert "人均约 80 元" in meal_text
    assert "本帮菜餐厅" in meal_text
    assert "人均约 180 元" in meal_text
    assert "阵雨" in state["itinerary"][0]["plan_b"]
    assert state["itinerary"][0]["plan_b"]

    budget_command = summarize_budget_tool.invoke({"runtime": _build_runtime(state)})
    state.update(budget_command.update)
    assert state["current_step"] == "order_generation"
    assert state["budget"]["transport"] == 626.0 * 2
    assert state["budget"]["accommodation"] == 800.0 * 2
    assert state["budget"]["food"] == (30.0 + 80.0 + 180.0) * 3 * 2
    assert state["budget"]["attractions"] == 40.0 * 2
    assert state["budget"]["per_person"] > 0
    assert state["budget"]["confidence_level"] == "中高"
    assert state["budget"]["currency"] == "CNY"
    assert state["budget"]["travel_days"] == 3
    assert len(state["budget"]["line_items"]) == 5
    assert any(item["key"] == "accommodation" and "2 晚" in item["basis"] for item in state["budget"]["line_items"])
    assert any(item["key"] == "food" and "南京路小吃" in item["basis"] for item in state["budget"]["line_items"])
    assert any("交通" in item for item in state["budget"]["confirmed_items"])
    assert any("住宿" in item for item in state["budget"]["confirmed_items"])
    assert any("餐饮" in item for item in state["budget"]["estimated_items"])
    assert any("景点" in item for item in state["budget"]["estimated_items"])
    assert any("正式购票" in item for item in state["budget"]["verification_items"])
    budget_message = budget_command.update["messages"][0].content
    assert "\u9884\u7b97\u5339\u914d" in budget_message
    assert "预算明细" in budget_message
    assert "费用依据" in budget_message
    assert "\u5173\u952e\u5047\u8bbe" in budget_message
    assert "预算置信度" in budget_message
    assert "出发前待核验" in budget_message
    assert "依据：" in budget_message
    assert "南京路小吃" in budget_message
    assert "本帮菜餐厅" in budget_message
    assert "豫园 40 元/人" in budget_message

    order_command = generate_order_tool.invoke({"runtime": _build_runtime(state)})
    assert "report" in order_command.update
    assert "report_data" in order_command.update
    assert "# 个性化旅游规划报告" in order_command.update["report"]
    assert "最终旅行方案报告" in order_command.update["report"]
    assert "行程概览：北京 → 上海" in order_command.update["report"]
    assert "G1 北京南" in order_command.update["report"]
    assert "上海市中心酒店" in order_command.update["report"]
    assert "行程亮点" in order_command.update["report"]
    assert "每日行程" in order_command.update["report"]
    assert "景点地图" in order_command.update["report"]
    assert "预算明细" in order_command.update["report"]
    assert "预算匹配" in order_command.update["report"]
    assert "费用依据" in order_command.update["report"]
    assert "预算置信度与待核验项" in order_command.update["report"]
    assert "已确认/可追溯价格" in order_command.update["report"]
    assert "估算项" in order_command.update["report"]
    assert "天气与风险提醒" in order_command.update["report"]
    assert "后续可调整" in order_command.update["report"]
    assert "Day 1" in order_command.update["report"]
    assert "Day 1：" in order_command.update["report"]
    assert "上午/" in order_command.update["report"]
    assert "Plan B" in order_command.update["report"]
    assert "人民广场" in order_command.update["report"]
    assert "约 40 元/人" in order_command.update["report"]
    assert "南京路小吃" in order_command.update["report"]
    assert "本帮菜餐厅" in order_command.update["report"]
    report_data = order_command.update["report_data"]
    assert report_data["version"] == "travel_report.v1"
    assert len(report_data["itinerary"]) == 3
    assert len(report_data["map_routes"]) == 3
    assert report_data["budget"]["items"]
    assert [
        day["route"]["summary"] for day in report_data["itinerary"]
    ] == [
        route["summary"] for route in report_data["map_routes"]
    ]
    assert "pay.example.com" not in order_command.update["messages"][0].content
    assert "未接入真实支付服务" in order_command.update["messages"][0].content


def test_final_report_pads_four_day_trip_and_exports_route_bound_data():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "budget_summarization",
            "user_requirement": {
                "departure_city": "北京",
                "destination": "上海",
                "departure_date": "2026-05-10",
                "travel_days": 4,
                "adult_count": 2,
                "children_count": 0,
                "budget_min": 2000.0,
                "budget_max": 5000.0,
                "budget_level": "comfort",
                "travel_styles": ["culture", "food"],
                "special_needs": None,
            },
            "selected_destination": "上海",
            "destination_options": [
                {
                    "name": "上海",
                    "description": "城市文化和美食集中",
                    "weather_info": "午后可能有阵雨，建议保留室内备选",
                    "attractions": ["外滩", "上海博物馆", "豫园"],
                    "attraction_pois": [
                        {"name": "外滩", "area": "黄浦江沿岸", "estimated_cost": 0.0},
                        {"name": "上海博物馆", "area": "人民广场", "indoor": True, "estimated_cost": 0.0},
                        {"name": "豫园", "area": "老城厢", "estimated_cost": 40.0},
                    ],
                    "estimated_cost": 1800.0,
                }
            ],
            "selected_transport": "train",
            "selected_transport_option": {
                "transport_type": "train",
                "details": "G1 北京南 -> 上海虹桥",
                "price": 626.0,
            },
            "selected_accommodation_types": ["star_hotel"],
            "selected_accommodation_option": {
                "name": "上海市中心酒店",
                "type": "star_hotel",
                "location": "人民广场",
                "price_per_night": 800.0,
                "rating": 4.7,
                "amenities": ["近地铁"],
            },
            "selected_food_types": ["local"],
            "selected_food_pois": [
                {
                    "name": "南京路小吃",
                    "type": "local",
                    "area": "南京路/人民广场",
                    "average_cost": 80.0,
                }
            ],
            "itinerary": [
                {
                    "day_number": 1,
                    "theme": "抵达",
                    "activities": ["抵达上海", "外滩散步"],
                    "time_blocks": ["上午/出发：G1 北京南 -> 上海虹桥", "晚上/夜景：外滩"],
                    "meals": ["早餐：自理", "午餐：南京路小吃", "晚餐：南京路小吃"],
                    "accommodation": "上海市中心酒店",
                    "route_note": "抵达后住人民广场，晚上去外滩。",
                },
                {
                    "day_number": 2,
                    "theme": "城市文化",
                    "activities": ["上海博物馆", "人民广场"],
                    "time_blocks": ["上午/文化：上海博物馆", "下午/街区：人民广场"],
                    "meals": ["早餐：酒店", "午餐：南京路小吃", "晚餐：南京路小吃"],
                    "accommodation": "上海市中心酒店",
                    "route_note": "当天围绕人民广场活动。",
                },
                {
                    "day_number": 3,
                    "theme": "园林与小吃",
                    "activities": ["豫园", "城隍庙"],
                    "time_blocks": ["上午/园林：豫园", "下午/小吃：城隍庙"],
                    "meals": ["早餐：酒店", "午餐：南京路小吃", "晚餐：南京路小吃"],
                    "accommodation": "上海市中心酒店",
                    "route_note": "当天围绕老城厢活动。",
                },
            ],
        }
    )

    budget_command = summarize_budget_tool.invoke({"runtime": _build_runtime(state)})
    state.update(budget_command.update)

    assert len(state["itinerary"]) == 4
    assert state["itinerary"][3]["day_number"] == 4
    assert state["itinerary"][3]["theme"] == "返程缓冲与补漏"
    assert len(state["budget"]["line_items"]) == 5

    order_command = generate_order_tool.invoke({"runtime": _build_runtime(state)})
    report = order_command.update["report"]
    report_data = order_command.update["report_data"]

    assert "4天3晚" in report
    for day_number in range(1, 5):
        assert f"Day {day_number}：" in report
    assert "天气风险" in report
    assert "费用依据" in report
    assert "预算置信度" in report
    assert len(report_data["itinerary"]) == 4
    assert len(report_data["map_routes"]) == 4
    assert report_data["itinerary"][3]["title"] == "返程缓冲与补漏"
    assert [
        day["route"]["summary"] for day in report_data["itinerary"]
    ] == [
        route["summary"] for route in report_data["map_routes"]
    ]


def test_itinerary_prefers_same_area_pois_and_food():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "itinerary_generation",
            "user_requirement": {
                "departure_city": "北京",
                "destination": "上海",
                "departure_date": "2026-05-10",
                "travel_days": 3,
                "adult_count": 2,
                "children_count": 0,
                "budget_min": 1500.0,
                "budget_max": 3000.0,
                "budget_level": "comfort",
                "travel_styles": ["culture", "food"],
                "special_needs": None,
            },
            "selected_destination": "上海",
            "destination_options": [
                {
                    "name": "上海",
                    "description": "城市文化和美食集中",
                    "weather_info": None,
                    "attractions": ["外滩", "上海博物馆", "人民公园", "豫园"],
                    "attraction_pois": [
                        {"name": "外滩", "area": "黄浦江沿岸", "best_time": "晚上"},
                        {"name": "上海博物馆", "area": "人民广场", "best_time": "上午"},
                        {"name": "人民公园", "area": "人民广场", "best_time": "下午"},
                        {"name": "豫园", "area": "老城厢", "best_time": "下午"},
                    ],
                    "estimated_cost": 1800.0,
                }
            ],
            "selected_transport": "train",
            "selected_transport_option": {
                "transport_type": "train",
                "details": "G1 北京南 -> 上海虹桥",
                "price": 626.0,
            },
            "selected_accommodation_types": ["star_hotel"],
            "selected_accommodation_option": {
                "name": "上海市中心酒店",
                "type": "star_hotel",
                "location": "人民广场",
                "price_per_night": 800.0,
                "rating": 4.7,
                "amenities": ["近地铁"],
            },
            "selected_food_types": ["local", "specialty"],
            "selected_food_pois": [
                {
                    "name": "人民广场简餐",
                    "type": "chain",
                    "area": "人民广场",
                    "meal_time": "午餐",
                    "average_cost": 75.0,
                    "reservation_required": False,
                    "queue_risk": "低",
                    "tags": ["省心"],
                },
                {
                    "name": "本帮菜餐厅",
                    "type": "specialty",
                    "area": "人民广场",
                    "meal_time": "晚餐",
                    "average_cost": 180.0,
                    "reservation_required": True,
                    "queue_risk": "中",
                    "tags": ["本帮菜"],
                },
            ],
        }
    )

    itinerary_command = generate_itinerary_tool.invoke({"runtime": _build_runtime(state)})
    state.update(itinerary_command.update)

    day_two_text = "\n".join(state["itinerary"][1]["time_blocks"])
    assert "上海博物馆" in day_two_text
    assert "人民公园" in day_two_text
    assert "当日主区域：人民广场" in state["itinerary"][1]["route_note"]
    assert "餐饮优先匹配 人民广场" in state["itinerary"][1]["route_note"]
    assert "人民广场简餐" in "\n".join(state["itinerary"][1]["meals"])
    assert "本帮菜餐厅" in "\n".join(state["itinerary"][1]["meals"])


def test_budget_confidence_marks_fallback_estimates():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "budget_summarization",
            "user_requirement": {
                "departure_city": "北京",
                "destination": "上海",
                "departure_date": "2026-05-10",
                "travel_days": 2,
                "adult_count": 1,
                "children_count": 0,
                "budget_min": 1000.0,
                "budget_max": 2500.0,
                "budget_level": "comfort",
                "travel_styles": ["culture"],
                "special_needs": None,
            },
            "selected_destination": "上海",
            "selected_transport": "train",
            "selected_accommodation_types": ["economy_hotel"],
            "selected_food_types": ["local"],
            "itinerary": [
                {
                    "day_number": 1,
                    "theme": "抵达",
                    "activities": ["抵达上海"],
                    "meals": ["早餐：自理", "午餐：结合当日动线就近安排", "晚餐：本地小吃"],
                    "accommodation": "待确认",
                    "time_blocks": ["上午/出发：待确认"],
                }
            ],
        }
    )

    budget_command = summarize_budget_tool.invoke({"runtime": _build_runtime(state)})
    state.update(budget_command.update)

    assert state["budget"]["confidence_level"] == "偏低"
    assert not state["budget"]["confirmed_items"]
    assert any("缺少具体票价" in item for item in state["budget"]["estimated_items"])
    assert any("缺少已选酒店价格" in item for item in state["budget"]["estimated_items"])
    assert any("正式购票" in item for item in state["budget"]["verification_items"])
    assert "预算置信度" in budget_command.update["messages"][0].content
