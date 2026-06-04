import pytest
import inspect
from pathlib import Path
from langchain.tools import ToolRuntime
from langchain_core.messages import HumanMessage

from app.agents.handoffs import step_config as step_config_module
from app.agents.subagents.transport_coordinator import create_transport_coordinator
from app.agency import product_rules as product_rules_module
from app.core.state import create_initial_state
from app.core.workflow import (
    AGENCY_STEPS,
    FINAL_PLANNING_STEP,
    INITIAL_AGENCY_STEP,
    INITIAL_PLANNING_STEP,
    PLANNING_STEPS,
    STEP_LABELS,
    STEP_STATE_FIELDS,
)
from app.reports import render_report_markdown, validate_report_data
from app.tools import state_transition as state_transition_module
from app.tools.state_transition import (
    check_current_progress,
    confirm_planning_mode_tool,
    generate_itinerary_tool,
    generate_order_tool,
    go_back_to_step,
    record_evidence_bundle_tool,
    record_requirement_tool,
    scenic_price_lookup_tool,
    select_accommodation_tool,
    select_food_tool,
    select_transport_tool,
    set_planning_mode_tool,
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


def _mark_report_ready(state, *, destination=None):
    requirement = state.setdefault("user_requirement", {})
    requirement.setdefault("departure_date", "2026-06-01")
    requirement["departure_date_confirmed"] = True
    requirement.setdefault("travel_days", 3)
    requirement.setdefault("adult_count", 2)
    requirement.setdefault("children_count", 0)
    requirement.setdefault("budget_max", 8000.0)
    destination = destination or state.get("selected_destination") or requirement.get("destination") or "上海"
    requirement.setdefault("destination", destination)
    state.setdefault("selected_destination", destination)
    state.setdefault("selected_transport", "train")
    state.setdefault("selected_accommodation_types", ["star_hotel"])
    state.setdefault("selected_food_types", ["local"])
    state.setdefault(
        "itinerary",
        [
            {
                "day_number": 1,
                "theme": "抵达与轻松适应",
                "activities": [destination],
                "meals": ["本地小吃"],
                "accommodation": "住宿待二次核验",
            }
        ],
    )
    state.setdefault(
        "budget",
        {
            "transport": 0.0,
            "accommodation": 0.0,
            "food": 0.0,
            "attractions": 0.0,
            "misc": 0.0,
            "total": 0.0,
            "per_person": 0.0,
            "assumptions": ["测试报告前置数据"],
        },
    )
    return state


def test_internal_doc_evidence_falls_back_when_documents_unavailable(monkeypatch):
    product_rules_module.internal_doc_evidence.cache_clear()
    monkeypatch.setattr(
        product_rules_module.DocumentManager,
        "load_internal_documents",
        lambda self, category=None: [],
    )

    evidence = product_rules_module.internal_doc_evidence("pricing", 1)

    assert len(evidence) == 1
    item = evidence[0]
    assert item["source"] == "agency_rules/pricing"
    assert item["source_type"] == "agency_internal"
    assert item["category"] == "pricing"
    assert "agency_plan" in item["applicable_modes"]
    assert item["constraints"]
    product_rules_module.internal_doc_evidence.cache_clear()


def test_workflow_metadata_covers_every_planning_step():
    assert set(STEP_LABELS) == set(PLANNING_STEPS)
    assert set(STEP_STATE_FIELDS) == set(PLANNING_STEPS)
    assert FINAL_PLANNING_STEP == PLANNING_STEPS[-1]


def test_create_initial_state_uses_shared_entry_step():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    assert state["current_step"] == INITIAL_PLANNING_STEP
    assert state["agency_step"] == INITIAL_AGENCY_STEP
    assert state["key_history_turns"] == []
    assert state["context_layer_boundaries"] == {}
    assert state["tool_loop_guard"] == {}


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

    for tool_loader_name in (
        "get_hotel_followup_tools",
        "get_search_tools",
        "get_date_tools",
    ):
        if hasattr(step_config_module, tool_loader_name):
            monkeypatch.setattr(step_config_module, tool_loader_name, empty_tools)

    config = await step_config_module.get_step_config()

    assert tuple(key for key in config if key in PLANNING_STEPS) == PLANNING_STEPS
    assert tuple(key for key in config if key in AGENCY_STEPS) == AGENCY_STEPS
    assert "可以引导用户关注公众号" not in config["order_generation"]["prompt"]
    assert "不要添加没有事实来源" in config["order_generation"]["prompt"]
    assert "不要直接生成订单" in config["order_generation"]["prompt"]
    assert "不要编造支付链接" in config["order_generation"]["prompt"]
    assert "weather_info" in config["destination_recommendation"]["prompt"]
    assert "attractions" in config["destination_recommendation"]["prompt"]
    assert "最高优先级执行规则" in config["transport_planning"]["prompt"]
    assert "最高优先级执行规则" in config["accommodation_planning"]["prompt"]
    assert "只有日期已明确/确认时" in config["transport_planning"]["prompt"]
    assert "不得调用 query_transport_options" in config["transport_planning"]["prompt"]
    assert "只有日期已明确/确认时" in config["accommodation_planning"]["prompt"]
    assert "不得调用 query_hotel_options" in config["accommodation_planning"]["prompt"]
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
    assert "预算置信度详情" in config["order_generation"]["prompt"]
    assert "结构化 report_data 内部证据" in config["order_generation"]["prompt"]
    assert "酒店 MCP 或交通 API 失败" in config["order_generation"]["prompt"]
    assert "以工具返回的 report 作为最终报告正文" in config["order_generation"]["prompt"]
    assert "不要输出" in config["order_generation"]["prompt"]
    assert "[根据之前的对话填写]" in config["order_generation"]["prompt"]
    assert "先用一句自然话术承接目的地" in config["requirement_collection"]["prompt"]
    assert "memory_scope（记忆作用域参数）" in config["requirement_collection"]["prompt"]
    assert "不写入长期画像" in config["destination_recommendation"]["prompt"]
    assert 'memory_scope="temporary"' in config["accommodation_planning"]["prompt"]
    assert "不要污染长期记忆" in config["food_planning"]["prompt"]
    requirement_tool_names = {tool.name for tool in config["requirement_collection"]["tools"]}
    assert "set_planning_mode_tool" in requirement_tool_names
    assert "confirm_planning_mode_tool" in requirement_tool_names
    assert "record_evidence_bundle_tool" in requirement_tool_names
    agency_tool_names = {tool.name for tool in config["agency_product_match"]["tools"]}
    assert "query_transport_options" not in agency_tool_names
    assert "query_hotel_options" not in agency_tool_names
    assert "select_transport_tool" not in agency_tool_names
    assert "search_agency_product_templates" in agency_tool_names
    assert "generate_itinerary_tool" in {tool.name for tool in config["agency_plan_draft"]["tools"]}
    assert "generate_itinerary_tool" in {tool.name for tool in config["agency_feedback"]["tools"]}
    assert "generate_itinerary_tool" in {tool.name for tool in config["agency_report"]["tools"]}
    assert "summarize_budget_tool" in {tool.name for tool in config["agency_plan_draft"]["tools"]}
    assert "summarize_budget_tool" in {tool.name for tool in config["agency_feedback"]["tools"]}
    assert "summarize_budget_tool" in {tool.name for tool in config["agency_report"]["tools"]}
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


def test_planning_mode_tools_persist_mode_reason_and_confirmation():
    state = create_initial_state(user_id="user-1", session_id="session-1")

    command = set_planning_mode_tool.invoke(
        {
            "mode": "自由行",
            "reason": "用户想自己订酒店机票，只需要攻略建议",
            "runtime": _build_runtime(state),
        }
    )
    state.update(command.update)

    assert command.update["planning_mode"] == "free_planning"
    assert command.update["active_workflow"] == "free_planning"
    assert command.update["planning_mode_confirmed"] is False
    assert "个性化旅游规划" in command.update["messages"][0].content

    command = confirm_planning_mode_tool.invoke(
        {
            "mode": "省心方案",
            "reason": "用户改为希望省心安排",
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["planning_mode"] == "agency_plan"
    assert command.update["active_workflow"] == "agency_plan"
    assert command.update["planning_mode_confirmed"] is True
    assert command.update["planning_mode_reason"] == "用户改为希望省心安排"


def test_record_evidence_bundle_tool_persists_structured_bundle():
    state = create_initial_state(user_id="user-1", session_id="session-1")

    command = record_evidence_bundle_tool.invoke(
        {
            "evidence_bundle": {
                "pricing": [{"source": "pricing_rules", "summary": "预算需区分估算和待核验"}],
            },
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["evidence_bundle"]["pricing"][0]["source"] == "pricing_rules"


def test_record_evidence_bundle_tool_merges_existing_categories():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state["evidence_bundle"] = {
        "transport": {
            "mode": "flight",
            "summary": "去程航班待二次核验",
        },
        "pricing": [{"source": "pricing_rules", "summary": "旧报价依据"}],
    }

    command = record_evidence_bundle_tool.invoke(
        {
            "evidence_bundle": {
                "pricing": [{"source": "pricing_rules", "summary": "新报价依据"}],
                "budget_summary": {
                    "budget_summary_confirmed": True,
                    "budget_total": "¥6800-7600",
                },
            },
            "runtime": _build_runtime(state),
        }
    )

    merged = command.update["evidence_bundle"]
    assert merged["transport"]["mode"] == "flight"
    assert merged["pricing"][0]["summary"] == "新报价依据"
    assert merged["budget_summary"]["budget_summary_confirmed"] is True


def test_generate_order_tool_accepts_confirmed_budget_from_evidence_bundle():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "planning_mode": "agency_plan",
            "active_workflow": "agency_plan",
            "planning_mode_confirmed": True,
            "current_step": "requirement_collection",
            "agency_step": "agency_product_match",
            "user_requirement": {
                "departure_city": "成都",
                "destination": "重庆",
                "departure_date": "2026-06-20",
                "departure_date_confirmed": True,
                "travel_days": 3,
                "adult_count": 4,
                "children_count": 0,
                "budget_min": 1500.0,
                "budget_max": 2500.0,
                "travel_styles": ["culture", "food"],
                "special_needs": "省心方案",
            },
            "selected_destination": "重庆",
            "selected_transport": "train",
            "selected_transport_option": {
                "transport_type": "train",
                "details": "成都东 -> 重庆北 高铁往返待核验",
                "source": "agency_plan_productized_policy",
            },
            "selected_accommodation_types": ["star_hotel"],
            "selected_accommodation_option": {
                "name": "重庆核心商圈舒适型酒店",
                "type": "star_hotel",
                "location": "解放碑",
            },
            "selected_food_types": ["local", "specialty"],
            "itinerary": [
                {
                    "day_number": 1,
                    "theme": "抵达与夜景",
                    "activities": ["解放碑", "洪崖洞"],
                    "meals": ["本地小吃"],
                    "accommodation": "重庆核心商圈舒适型酒店",
                },
                {
                    "day_number": 2,
                    "theme": "经典地标",
                    "activities": ["磁器口", "长江索道"],
                    "meals": ["火锅"],
                    "accommodation": "重庆核心商圈舒适型酒店",
                },
                {
                    "day_number": 3,
                    "theme": "返程",
                    "activities": ["黄桷坪", "返程"],
                    "meals": ["重庆小面"],
                    "accommodation": "返程日不住宿",
                },
            ],
            "evidence_bundle": {
                "budget_summary_confirmed": True,
                "budget_per_capita": 1850,
                "budget_total": 7400,
                "budget_breakdown": {
                    "transport_est": 1200,
                    "accommodation_est": 1500,
                    "activities_est": 400,
                    "local_transport_est": 600,
                    "dining_est": 1700,
                    "service_buffer_est": 2000,
                },
                "verification_items": [
                    "高铁班次与票价",
                    "酒店房价与库存",
                    "接送车档期",
                ],
                "confidence_level": "high",
            },
        }
    )

    command = generate_order_tool.invoke({"runtime": _build_runtime(state)})

    assert "report_data" in command.update
    assert command.update["budget"]["per_person"] == 1850
    assert command.update["budget"]["budget_confidence"]["verification_items"]
    assert command.update["report_data"]["budget"]["per_person"] == 1850


def test_agency_guard_allows_itinerary_and_budget_tools():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "planning_mode": "agency_plan",
            "active_workflow": "agency_plan",
            "planning_mode_confirmed": True,
            "agency_step": "agency_plan_draft",
            "current_step": "requirement_collection",
            "user_requirement": {
                "departure_city": "成都",
                "destination": "重庆",
                "departure_date": "2026-06-20",
                "travel_days": 3,
                "adult_count": 4,
                "children_count": 0,
                "budget_min": 1500,
                "budget_max": 2500,
                "travel_styles": ["文化探索"],
            },
            "selected_destination": "重庆",
            "selected_transport": "train",
            "selected_transport_option": {"transport_type": "train", "details": "高铁往返"},
            "selected_accommodation_types": ["star_hotel"],
            "selected_accommodation_option": {"name": "解放碑舒适型酒店", "location": "解放碑"},
        }
    )

    itinerary_command = generate_itinerary_tool.invoke({"runtime": _build_runtime(state)})
    assert itinerary_command.update.get("itinerary")
    assert itinerary_command.update.get("current_step") == "budget_summarization"

    state.update(itinerary_command.update)
    budget_command = summarize_budget_tool.invoke({"runtime": _build_runtime(state)})
    assert budget_command.update.get("budget")
    assert budget_command.update.get("current_step") == "order_generation"


def test_scenic_price_lookup_persists_ticket_evidence_with_sources():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state["selected_destination"] = "杭州"

    command = scenic_price_lookup_tool.invoke(
        {
            "destination": "杭州",
            "scenic_names": ["灵隐飞来峰", "西溪湿地"],
            "runtime": _build_runtime(state),
        }
    )

    evidence = command.update["scenic_price_evidence"]
    assert evidence["destination"] == "杭州"
    assert evidence["collected_at"] == "2026-05-19"
    assert evidence["provider"] == "curated_rag_ticket_catalog"
    assert evidence["provider_status"] == "public_reference_only"
    assert evidence["catalog_source"].endswith("scenic_ticket_reference.md")
    assert evidence["public_search_status"] == "not_needed_catalog_match"
    assert "门票" in evidence["public_search_query"]
    assert {item["name"] for item in evidence["items"]} == {"灵隐飞来峰", "西溪湿地"}
    assert all(item["source_url"].startswith("https://") for item in evidence["items"])
    assert "不锁价" in evidence["disclaimer"]


def test_scenic_price_lookup_uses_public_search_when_catalog_misses(monkeypatch):
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state["selected_destination"] = "黄山"

    def fake_public_search(destination, scenic_names=None, max_results=5):
        assert destination == "黄山"
        assert scenic_names == ["黄山风景区"]
        assert max_results == 5
        return {
            "provider": "public_web_search",
            "provider_status": "public_search",
            "destination": destination,
            "query": "黄山 黄山风景区 门票 票价 预约 开放时间 官方",
            "queried_at": "2026-05-19T12:00:00",
            "collected_at": "2026-05-19",
            "items": [
                {
                    "destination": "黄山",
                    "name": "黄山风景区",
                    "price_label": "成人票 190 元",
                    "reservation_note": "按来源页实名预约规则二次核验",
                    "open_note": "开放时间以景区公告为准",
                    "source": "黄山风景区公开票务页",
                    "source_url": "https://www.huangshan.com.cn/",
                    "provider": "public_web_search",
                    "provider_status": "public_search",
                    "requires_verification": True,
                }
            ],
            "disclaimer": "公网搜索结果仅作参考，不锁价。",
        }

    monkeypatch.setattr(
        state_transition_module,
        "search_public_scenic_ticket_references_sync",
        fake_public_search,
    )

    command = scenic_price_lookup_tool.invoke(
        {
            "destination": "黄山",
            "scenic_names": ["黄山风景区"],
            "runtime": _build_runtime(state),
        }
    )

    evidence = command.update["scenic_price_evidence"]
    assert evidence["provider"] == "public_web_search"
    assert evidence["provider_status"] == "public_search"
    assert evidence["public_search"]["query"].startswith("黄山")
    assert evidence["items"][0]["price_label"] == "成人票 190 元"
    assert "不锁价" in evidence["disclaimer"]
    assert "公网搜索结果" in command.update["messages"][0].content


def test_xian_to_hangzhou_product_sample_has_realistic_price_boundaries():
    product_path = (
        PROJECT_ROOT
        / "data"
        / "documents"
        / "internal"
        / "products"
        / "xian_to_hangzhou_5d_agency_sample.md"
    )
    content = product_path.read_text(encoding="utf-8")

    assert "ZX-PROD-XIAN-HANGZHOU-5D-5000" in content
    assert "西安" in content and "杭州" in content
    assert "5天4晚" in content
    assert "5000 元/人" in content
    assert "采集日期 2026-05-19" in content
    assert "https://www.12306.cn/" in content
    assert "https://westlake.hangzhou.gov.cn/" in content
    assert "杭州西湖湖滨银泰亚朵酒店" in content
    assert "住宿示例候选" in content
    assert "https://www.trip.com/hotels/v2/hangzhou-hotel-detail-15083387/atour-hotel-hangzhou-west-lake-lakeside-yintai/" in content
    assert "待核验" in content and "不锁价" in content


def test_record_requirement_persists_planning_mode():
    state = create_initial_state(user_id="user-1", session_id="session-1")

    command = record_requirement_tool.invoke(
        {
            "departure_city": "上海",
            "destination": "成都",
            "departure_date": "2026-06-01",
            "travel_days": 4,
            "adult_count": 2,
            "children_count": 0,
            "budget_min": 3000.0,
            "budget_max": 6000.0,
            "travel_styles": ["culture", "food"],
            "special_needs": "想要省心一点，按旅行社成熟路线走",
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["planning_mode"] == "agency_plan"
    assert command.update["active_workflow"] == "agency_plan"
    assert command.update["matched_product"]["name"]
    assert command.update["planning_mode_confirmed"] is True
    assert command.update["user_requirement"]["planning_mode"] == "agency_plan"
    assert command.update["user_requirement"]["planning_mode_reason"]
    assert "规划模式：省心方案" in command.update["messages"][0].content


def test_record_requirement_confirms_relative_date_once_and_reuses_it(monkeypatch):
    class FixedDate(state_transition_module.date):
        @classmethod
        def today(cls):
            return cls(2026, 5, 19)

    monkeypatch.setattr(state_transition_module, "date", FixedDate)
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state["messages"] = [
        HumanMessage(content="下周三从西安去杭州5天，每人5000，想要旅行社省心方案。")
    ]

    command = record_requirement_tool.invoke(
        {
            "departure_city": "西安",
            "destination": "杭州",
            "departure_date": "下周三",
            "travel_days": 5,
            "adult_count": 2,
            "children_count": 0,
            "budget_min": 4500.0,
            "budget_max": 5500.0,
            "travel_styles": ["culture", "food"],
            "special_needs": "旅行社省心方案",
            "runtime": _build_runtime(state),
        }
    )
    state.update(command.update)

    assert command.update["user_requirement"]["departure_date"] == "2026-05-27"
    assert command.update["confirmed_facts"]["departure_date"] == "2026-05-27"
    assert command.update["confirmed_facts"]["check_in_date"] == "2026-05-27"
    assert command.update["confirmed_facts"]["check_out_date"] == "2026-05-31"
    assert any(item["key"] == "departure_date" for item in command.update["confirmation_history"])

    repeated = record_requirement_tool.invoke(
        {
            "departure_city": "西安",
            "destination": "杭州",
            "departure_date": "日期待确认",
            "travel_days": "待确认",
            "adult_count": 2,
            "children_count": 0,
            "budget_min": 4500.0,
            "budget_max": 5500.0,
            "travel_styles": ["culture"],
            "special_needs": "继续按刚才确认的日期查交通住宿",
            "runtime": _build_runtime(state),
        }
    )

    assert repeated.update["user_requirement"]["departure_date"] == "2026-05-27"
    assert repeated.update["confirmed_facts"]["check_out_date"] == "2026-05-31"
    assert repeated.update["departure_date_confirmed"] is True


def test_record_requirement_uses_recent_user_agency_signal_when_tool_args_are_plain():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state["messages"] = [
        HumanMessage(
            content="我们4个大人从成都去重庆3天2晚，想要省心方案，费用包含和不包含都要说明。"
        )
    ]

    command = record_requirement_tool.invoke(
        {
            "departure_city": "成都",
            "destination": "重庆",
            "departure_date": "2026-06-01",
            "travel_days": 3,
            "adult_count": 4,
            "children_count": 0,
            "budget_min": 1500.0,
            "budget_max": 3500.0,
            "travel_styles": ["relaxation"],
            "special_needs": "",
            "planning_mode": "free_planning",
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["planning_mode"] == "agency_plan"
    assert command.update["user_requirement"]["planning_mode"] == "agency_plan"
    assert "省心方案" in command.update["planning_mode_reason"]


def test_record_requirement_keeps_hotel_fallback_in_free_planning_without_agency_signal():
    state = create_initial_state(user_id="user-1", session_id="session-1")

    command = record_requirement_tool.invoke(
        {
            "departure_city": "上海",
            "destination": "长沙",
            "departure_date": "2026-06-01",
            "travel_days": 4,
            "adult_count": 2,
            "children_count": 0,
            "budget_min": 2000.0,
            "budget_max": 3500.0,
            "travel_styles": ["relaxation", "food"],
            "special_needs": "住湘江边江景房，如果查不到具体酒店也给可执行兜底方案",
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["planning_mode"] == "free_planning"
    assert command.update["user_requirement"]["planning_mode"] == "free_planning"


def test_record_requirement_keeps_weak_free_mode_when_hotel_fallback_is_requested():
    state = create_initial_state(user_id="user-1", session_id="session-1")

    command = record_requirement_tool.invoke(
        {
            "departure_city": "上海",
            "destination": "长沙",
            "departure_date": "2026-06-01",
            "travel_days": 4,
            "adult_count": 2,
            "children_count": 0,
            "budget_min": 2000.0,
            "budget_max": 3500.0,
            "travel_styles": ["relaxation", "food"],
            "special_needs": "住湘江边江景房，如果查不到具体酒店也给可执行兜底方案",
            "planning_mode": "free_planning",
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["planning_mode"] == "free_planning"
    assert "修正为旅行社顾问方案" not in command.update["planning_mode_reason"]


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


def test_select_destination_tool_accepts_structured_attraction_payloads():
    from app.tools.state_transition import select_destination_tool

    state = create_initial_state(user_id="user-1", session_id="session-1")

    command = select_destination_tool.invoke(
        {
            "destination": "重庆",
            "description": {"summary": "短途省心，适合轻松节奏。"},
            "weather_info": ["天气需出发前二次核验"],
            "attractions": [
                {"name": "洪崖洞", "reason": "夜景"},
                "解放碑",
            ],
            "estimated_cost": "约 2500 元/人",
            "runtime": _build_runtime(state),
        }
    )

    option = command.update["destination_options"][0]
    assert option["description"] == "短途省心，适合轻松节奏。"
    assert option["weather_info"] == "天气需出发前二次核验"
    assert option["attractions"] == ["洪崖洞", "解放碑"]
    assert option["estimated_cost"] == 2500.0


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
            "accommodation_types": ["重庆核心商圈的舒适型酒店"],
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
            "food_types": ["本地小吃加特色餐厅，照顾轻松节奏"],
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["selected_food_types"] == ["specialty", "local"]
    assert command.update["current_step"] == "itinerary_generation"


def test_select_food_tool_accepts_model_string_argument():
    state = create_initial_state(user_id="user-1", session_id="session-1")

    command = select_food_tool.invoke(
        {
            "food_types": "本地小吃加特色餐厅，照顾轻松节奏",
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["selected_food_types"] == ["specialty", "local"]
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
    assert "方案依据" in order_command.update["report"]
    assert "预算明细" in order_command.update["report"]
    assert "预算匹配" in order_command.update["report"]
    assert "费用依据" in order_command.update["report"]
    assert "天气与风险提醒" in order_command.update["report"]
    assert "出发前确认" in order_command.update["report"]
    assert "后续可调整" in order_command.update["report"]
    assert "预算置信度与待核验项" not in order_command.update["report"]
    assert "顾问交付清单" not in order_command.update["report"]
    assert "顾问核验清单" not in order_command.update["report"]
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
    assert report_data["agency_context"]["source_type"] == "agency_internal"
    assert report_data["agency_context"]["highlights"]
    assert len(report_data["agency_context"]["evidence"]) >= 3
    assert {
        item["category"] for item in report_data["agency_context"]["evidence"]
    }.issuperset({"products", "pricing", "risk"})
    assert all(
        item["constraints"] for item in report_data["agency_context"]["evidence"]
    )
    assert report_data["budget"]["items"]
    assert report_data["evidence_bundle"]["source_type"] == "structured_state"
    assert report_data["tool_audit_summary"]["readiness"] == "可交付，预订前需核验"
    assert report_data["tool_audit_summary"]["pending_checks"]
    assert "budget_confidence" in report_data["advisor_sections"]
    assert "tool_audit_summary" in report_data["advisor_sections"]
    assert "budget_confidence" not in report_data["customer_sections"]
    assert "tool_audit_summary" not in report_data["customer_sections"]
    assert any(
        section["id"] == "tool_audit_summary"
        for section in report_data["sections"]
    )
    assert validate_report_data(report_data).ok is True
    assert order_command.update["report"] == render_report_markdown(report_data)
    assert [
        day["route"]["summary"] for day in report_data["itinerary"]
    ] == [
        route["summary"] for route in report_data["map_routes"]
    ]
    assert "pay.example.com" not in order_command.update["messages"][0].content
    assert "未接入真实支付服务" in order_command.update["messages"][0].content


def test_generate_itinerary_persists_safe_accommodation_type_fallback():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "itinerary_generation",
            "user_requirement": {
                "departure_city": "西安",
                "destination": "北京",
                "departure_date": "2026-05-10",
                "travel_days": 2,
                "adult_count": 2,
                "children_count": 0,
                "budget_max": 5000.0,
                "travel_styles": ["relaxation"],
            },
            "selected_destination": "北京",
            "selected_transport": "train",
            "selected_accommodation_option": {
                "name": "北京核心区舒适酒店",
                "type": "comfort_hotel",
                "location": "核心区",
            },
            "selected_food_types": ["local"],
        }
    )

    command = generate_itinerary_tool.invoke({"runtime": _build_runtime(state)})

    assert command.update["current_step"] == "budget_summarization"
    assert command.update["selected_accommodation_types"] == ["star_hotel"]
    assert command.update["itinerary"][0]["accommodation"] == "北京核心区舒适酒店"


def test_generate_itinerary_tool_defaults_missing_food_preference():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "itinerary_generation",
            "user_requirement": {
                "departure_city": "北京",
                "destination": "南京",
                "departure_date": "日期待确认",
                "departure_date_confirmed": False,
                "travel_days": 2,
                "adult_count": 2,
                "children_count": 0,
                "budget_min": 1500.0,
                "budget_max": 3000.0,
                "budget_level": "comfort",
                "travel_styles": ["culture"],
                "special_needs": None,
            },
            "selected_destination": "南京",
            "selected_transport": "train",
            "selected_accommodation_types": ["star_hotel"],
        }
    )

    itinerary_command = generate_itinerary_tool.invoke({"runtime": _build_runtime(state)})

    assert itinerary_command.update["current_step"] == "budget_summarization"
    assert itinerary_command.update["selected_food_types"] == ["local", "specialty"]
    assert len(itinerary_command.update["itinerary"]) == 2
    all_meal_text = "\n".join(
        meal
        for day in itinerary_command.update["itinerary"]
        for meal in day["meals"]
    )
    assert "本地" in all_meal_text


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
    assert "返程" in state["itinerary"][3]["theme"]
    assert "补漏" in state["itinerary"][3]["theme"]
    assert len(state["budget"]["line_items"]) == 5

    order_command = generate_order_tool.invoke({"runtime": _build_runtime(state)})
    report = order_command.update["report"]
    report_data = order_command.update["report_data"]

    assert "4天3晚" in report
    for day_number in range(1, 5):
        assert f"Day {day_number}：" in report
    assert "天气风险" in report
    assert "方案依据" in report
    assert "费用依据" in report
    assert "出发前确认" in report
    assert "预算置信度" not in report
    assert "budget_confidence" in report_data["advisor_sections"]
    assert len(report_data["itinerary"]) == 4
    assert len(report_data["map_routes"]) == 4
    assert report_data["agency_context"]["mode"] == "free_planning"
    assert "返程" in report_data["itinerary"][3]["title"]
    assert "补漏" in report_data["itinerary"][3]["title"]
    assert [
        day["route"]["summary"] for day in report_data["itinerary"]
    ] == [
        route["summary"] for route in report_data["map_routes"]
    ]


def test_generate_order_tool_blocks_pending_report_from_basic_requirement():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "destination_recommendation",
            "user_requirement": {
                "departure_city": "\u5317\u4eac",
                "destination": "\u4e0a\u6d77",
                "departure_date": "2026-06-19",
                "travel_days": 3,
                "adult_count": 2,
                "children_count": 0,
                "budget_min": 3000.0,
                "budget_max": 8000.0,
                "travel_styles": ["\u6587\u5316", "\u7f8e\u98df"],
            },
            "selected_transport": "train",
            "selected_food_types": ["local"],
        }
    )
    order_command = generate_order_tool.invoke({"runtime": _build_runtime(state)})

    assert "report" not in order_command.update
    assert "report_data" not in order_command.update
    message = order_command.update["messages"][0].content
    assert "住宿方案" in message
    assert "完整行程" in message
    assert "预算汇总" in message
    assert "不会在目的地或产品框架阶段提前生成 report_data" in message


def test_generate_order_tool_allows_pending_date_as_verification_item():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    _mark_report_ready(state, destination="南京")
    state["user_requirement"].update(
        {
            "departure_city": "出发地待确认",
            "departure_date": "日期待确认",
            "departure_date_confirmed": False,
            "destination": "南京",
        }
    )

    order_command = generate_order_tool.invoke({"runtime": _build_runtime(state)})

    assert "report_data" in order_command.update
    report_data = order_command.update["report_data"]
    verification_items = report_data["budget_confidence"]["verification_items"]
    assert any("出发日期" in item and "日期待确认" in item for item in verification_items)
    assert validate_report_data(report_data).ok is True


def test_generate_order_tool_adds_changsha_route_nodes_for_map_export():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "destination_recommendation",
            "user_requirement": {
                "departure_city": "\u897f\u5b89",
                "destination": "\u957f\u6c99",
                "departure_date": "2026-05-23",
                "departure_date_confirmed": True,
                "travel_days": 4,
                "adult_count": 2,
                "children_count": 0,
                "budget_max": 3500.0,
                "travel_styles": ["\u7f8e\u98df", "\u6587\u5316", "\u4f11\u95f2"],
                "special_needs": "\u7701\u5fc3\u65b9\u6848",
            },
            "selected_destination": "\u957f\u6c99",
            "selected_transport": "train",
            "selected_accommodation_types": ["star_hotel"],
            "selected_food_types": ["local", "specialty"],
            "itinerary": [
                {
                    "day_number": 1,
                    "theme": "\u62b5\u8fbe\u4e0e\u8f7b\u677e\u9002\u5e94",
                    "activities": ["\u4e94\u4e00\u5e7f\u573a"],
                    "meals": ["\u957f\u6c99\u5c0f\u5403"],
                    "accommodation": "\u4e94\u4e00\u5e7f\u573a\u9644\u8fd1\u9152\u5e97",
                }
            ],
            "budget": {
                "transport": 700.0,
                "accommodation": 1200.0,
                "food": 900.0,
                "attractions": 200.0,
                "misc": 300.0,
                "total": 3300.0,
                "per_person": 1650.0,
                "assumptions": ["\u6d4b\u8bd5\u9884\u7b97"],
            },
            "messages": [
                HumanMessage(
                    content=(
                        "\u5e2e\u6211\u6309\u65c5\u884c\u793e\u7701\u5fc3"
                        "\u65b9\u6848\u5b89\u6392\u957f\u6c994\u59293\u665a\u3002"
                    )
                )
            ],
        }
    )
    _mark_report_ready(state, destination="\u4e0a\u6d77")

    order_command = generate_order_tool.invoke({"runtime": _build_runtime(state)})
    report_data = order_command.update["report_data"]

    assert len(report_data["itinerary"]) == 4
    assert len(report_data["map_routes"]) == 4
    assert all(len(route["route_points"]) >= 2 for route in report_data["map_routes"])
    route_text = "\n".join(route["summary"] for route in report_data["map_routes"])
    assert "\u6a58\u5b50\u6d32\u5934" in route_text or "\u5cb3\u9e93\u5c71" in route_text
    meals_text = "\n".join(
        "\n".join(day["meals"]) for day in report_data["itinerary"]
    )
    assert "\u8336\u989c\u60a6\u8272" in meals_text or "\u7b28\u841d\u535c" in meals_text
    assert "\u57ce\u968d\u5e99" not in meals_text


def test_generate_order_tool_repairs_weak_changsha_model_route_points():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "itinerary_generation",
            "user_requirement": {
                "departure_city": "\u897f\u5b89",
                "destination": "\u957f\u6c99",
                "departure_date": "2026-05-23",
                "departure_date_confirmed": True,
                "travel_days": 4,
                "adult_count": 2,
                "children_count": 0,
                "budget_max": 3500.0,
                "travel_styles": ["\u7f8e\u98df", "\u6587\u5316", "\u4f11\u95f2"],
                "special_needs": "\u7701\u5fc3\u65b9\u6848",
            },
            "selected_destination": "\u957f\u6c99",
            "selected_transport": "train",
            "selected_accommodation_types": ["star_hotel"],
            "selected_food_types": ["local", "specialty"],
            "budget": {
                "transport": 700.0,
                "accommodation": 1200.0,
                "food": 900.0,
                "attractions": 200.0,
                "misc": 300.0,
                "total": 3300.0,
                "per_person": 1650.0,
                "assumptions": ["\u6d4b\u8bd5\u9884\u7b97"],
            },
            "itinerary": [
                {
                    "day_number": 1,
                    "theme": "\u62b5\u8fbe\u4e0e\u8f7b\u677e\u9002\u5e94",
                    "route_points": ["\u897f\u5b89", "\u957f\u6c99"],
                },
                {
                    "day_number": 2,
                    "theme": "\u957f\u6c99 \u6df1\u5ea6\u4f53\u9a8c",
                    "route_points": ["\u957f\u6c99"],
                },
                {
                    "day_number": 3,
                    "theme": "\u957f\u6c99 \u6df1\u5ea6\u4f53\u9a8c",
                    "route_points": ["\u957f\u6c99"],
                },
                {
                    "day_number": 4,
                    "theme": "\u6536\u5c3e\u4e0e\u8fd4\u7a0b\u5f39\u6027",
                    "route_points": ["\u8fd4\u7a0b\u4ea4\u901a", "\u957f\u6c99"],
                },
            ],
            "messages": [
                HumanMessage(
                    content=(
                        "\u8bf7\u6309\u5f53\u524d\u4fe1\u606f\u751f\u6210"
                        "\u957f\u6c994\u59293\u665a\u6700\u7ec8\u62a5\u544a\u3002"
                    )
                )
            ],
        }
    )
    _mark_report_ready(state, destination="\u4e0a\u6d77")

    order_command = generate_order_tool.invoke({"runtime": _build_runtime(state)})
    report_data = order_command.update["report_data"]

    assert len(report_data["map_routes"]) == 4
    assert all(len(route["route_points"]) >= 2 for route in report_data["map_routes"])
    route_text = "\n".join(route["summary"] for route in report_data["map_routes"])
    assert "\u6a58\u5b50\u6d32\u5934" in route_text
    assert "\u5cb3\u9e93\u5c71" in route_text or "\u6e56\u5357\u535a\u7269\u9662" in route_text


def test_final_report_infers_agency_mode_from_recent_human_messages():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "destination_recommendation",
            "user_requirement": {
                "departure_city": "\u5317\u4eac",
                "destination": "\u4e0a\u6d77",
                "travel_days": 3,
                "adult_count": 2,
                "children_count": 0,
                "budget_max": 8000,
                "travel_styles": ["\u6587\u5316\u63a2\u7d22", "\u7f8e\u98df\u4e4b\u65c5"],
                "special_needs": "\u4ea4\u901a\u4f18\u5148\u9ad8\u94c1",
            },
            "selected_destination": "\u4e0a\u6d77",
            "messages": [
                HumanMessage(
                    content=(
                        "\u6211\u60f3\u505a\u4e00\u4e2a\u65c5\u884c\u793e"
                        "\u7701\u5fc3\u65b9\u6848\uff0c\u6309\u6210\u719f"
                        "\u8def\u7ebf\u548c\u987e\u95ee\u65b9\u6848\u6765\u3002"
                    )
                )
            ],
        }
    )
    _mark_report_ready(state, destination="\u4e0a\u6d77")

    order_command = generate_order_tool.invoke({"runtime": _build_runtime(state)})
    report_data = order_command.update["report_data"]

    assert report_data["agency_context"]["mode"] == "agency_plan"
    assert "\u65c5\u884c\u793e\u987e\u95ee\u65b9\u6848" in report_data["agency_context"]["summary"]


def test_final_report_prefers_persisted_planning_mode_over_recent_messages():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "destination_recommendation",
            "planning_mode": "agency_plan",
            "planning_mode_reason": "用户已确认按旅行社顾问方案交付",
            "planning_mode_confirmed": True,
            "user_requirement": {
                "departure_city": "\u5317\u4eac",
                "destination": "\u4e0a\u6d77",
                "travel_days": 3,
                "adult_count": 2,
                "children_count": 0,
                "budget_max": 8000,
                "travel_styles": ["\u6587\u5316\u63a2\u7d22"],
                "special_needs": "\u4ea4\u901a\u4f18\u5148\u9ad8\u94c1",
                "planning_mode": "agency_plan",
                "planning_mode_reason": "用户已确认按旅行社顾问方案交付",
                "planning_mode_confirmed": True,
            },
            "selected_destination": "\u4e0a\u6d77",
            "messages": [
                HumanMessage(content="\u53ea\u8981\u81ea\u7531\u884c\u653b\u7565\uff0c\u6211\u81ea\u5df1\u8ba2\u3002")
            ],
        }
    )

    _mark_report_ready(state, destination="\u4e0a\u6d77")
    order_command = generate_order_tool.invoke({"runtime": _build_runtime(state)})
    report_data = order_command.update["report_data"]

    assert report_data["agency_context"]["mode"] == "agency_plan"
    assert report_data["agency_context"]["mode_reason"] == "用户已确认按旅行社顾问方案交付"
    assert report_data["agency_context"]["mode_confirmed"] is True


def test_agency_itinerary_auto_seeds_productized_selection_state():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "requirement_collection",
            "planning_mode": "agency_plan",
            "active_workflow": "agency_plan",
            "planning_mode_confirmed": True,
            "agency_step": "agency_report",
            "user_requirement": {
                "departure_city": "成都",
                "destination": "重庆",
                "departure_date": "2026-06-20",
                "travel_days": 3,
                "adult_count": 4,
                "children_count": 0,
                "budget_min": 1500.0,
                "budget_max": 2500.0,
                "budget_level": "comfort",
                "special_needs": "交通确认按高铁省心优先记录推荐方式；住宿确认按重庆核心商圈、干净省心、动线方便的舒适型酒店记录。",
                "planning_mode": "agency_plan",
                "planning_mode_confirmed": True,
            },
            "messages": [
                HumanMessage(content="交通确认按高铁省心优先记录推荐方式；真实班次和价格没有锁定时写待二次核验。"),
                HumanMessage(content="住宿确认按重庆核心商圈、干净省心、动线方便的舒适型酒店记录；真实酒店价格没有锁定时写待二次核验。"),
            ],
        }
    )

    command = generate_itinerary_tool.invoke({"runtime": _build_runtime(state)})

    assert command.update["selected_destination"] == "重庆"
    assert command.update["selected_food_types"] == ["local", "specialty"]
    assert command.update["selected_accommodation_types"]
    assert command.update["current_step"] == "budget_summarization"
    assert len(command.update["itinerary"]) == 3
    assert state["selected_transport"] == "train"
    assert state["selected_transport_option"]["transport_type"] == "train"


def test_summarize_budget_tolerates_missing_children_count():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "budget_summarization",
            "active_workflow": "agency_plan",
            "planning_mode": "agency_plan",
            "agency_step": "agency_report",
            "user_requirement": {
                "departure_city": "成都",
                "destination": "重庆",
                "departure_date": "2026-06-20",
                "travel_days": 3,
                "adult_count": 4,
                "budget_min": 1500.0,
                "budget_max": 2500.0,
                "budget_level": "comfort",
                "travel_styles": ["relaxation"],
                "special_needs": "省心方案",
            },
            "selected_destination": "重庆",
            "selected_transport": "train",
            "selected_transport_option": {
                "transport_type": "train",
                "price": 280.0,
                "details": "成都东 -> 重庆北",
            },
            "selected_accommodation_option": {
                "name": "解放碑商圈酒店",
                "price_per_night": 420.0,
                "room_count": 2,
            },
            "selected_food_types": ["local"],
            "selected_accommodation_types": ["star_hotel"],
            "itinerary": [
                {
                    "day_number": 1,
                    "theme": "抵达重庆",
                    "activities": ["抵达解放碑", "洪崖洞夜景"],
                    "time_blocks": ["上午/交通：高铁抵达", "晚上/夜景：洪崖洞"],
                    "meals": ["午餐：重庆小面", "晚餐：火锅"],
                    "accommodation": "解放碑商圈酒店",
                    "route_note": "首日以市区轻松适应为主。",
                }
            ],
        }
    )

    budget_command = summarize_budget_tool.invoke({"runtime": _build_runtime(state)})

    assert budget_command.update["budget"]["travel_days"] == 3
    assert budget_command.update["budget"]["per_person"] > 0
    assert budget_command.update["current_step"] == "order_generation"


def test_final_report_keeps_budget_confidence_contract_when_prices_are_missing():
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
            "selected_transport": "train",
            "selected_transport_option": {
                "transport_type": "train",
                "details": "高铁车次待二次核实",
            },
            "selected_accommodation_types": ["economy_hotel"],
            "selected_accommodation_option": {
                "name": "人民广场附近酒店待确认",
                "type": "economy_hotel",
                "location": "人民广场",
                "rating": None,
                "amenities": ["近地铁"],
            },
            "selected_food_types": ["local"],
            "itinerary": [
                {
                    "day_number": 1,
                    "theme": "抵达",
                    "activities": ["抵达上海", "人民广场周边散步"],
                    "time_blocks": ["上午/出发：高铁车次待二次核实", "晚上/轻松：人民广场周边"],
                    "meals": ["早餐：自理", "午餐：就近简餐", "晚餐：本地小吃"],
                    "accommodation": "人民广场附近酒店待确认",
                    "route_note": "抵达后围绕人民广场轻量活动。",
                },
                {
                    "day_number": 2,
                    "theme": "城市文化",
                    "activities": ["上海博物馆", "南京路步行街"],
                    "time_blocks": ["上午/文化：上海博物馆", "下午/街区：南京路步行街"],
                    "meals": ["早餐：酒店周边", "午餐：就近简餐", "晚餐：本地小吃"],
                    "accommodation": "人民广场附近酒店待确认",
                    "route_note": "当天围绕人民广场和南京路活动。",
                },
                {
                    "day_number": 3,
                    "theme": "园林与老城",
                    "activities": ["豫园", "城隍庙"],
                    "time_blocks": ["上午/园林：豫园", "下午/小吃：城隍庙"],
                    "meals": ["早餐：酒店周边", "午餐：就近简餐", "晚餐：本地小吃"],
                    "accommodation": "人民广场附近酒店待确认",
                    "route_note": "当天围绕老城厢活动。",
                },
            ],
        }
    )

    budget_command = summarize_budget_tool.invoke({"runtime": _build_runtime(state)})
    state.update(budget_command.update)

    order_command = generate_order_tool.invoke({"runtime": _build_runtime(state)})
    report = order_command.update["report"]
    report_data = order_command.update["report_data"]

    assert "出发前确认" in report
    assert "预算置信度与待核验项" not in report
    assert "已确认/可追溯价格" not in report
    assert "估算项" not in report
    assert "顾问交付清单" not in report
    for day_number in range(1, 5):
        assert f"Day {day_number}" in report

    assert report_data["budget_confidence"]["level"] == "偏低"
    assert not report_data["budget_confidence"]["confirmed_items"]
    assert any(
        "交通 API 未提供具体票价" in item
        for item in report_data["budget_confidence"]["estimated_items"]
    )
    assert any(
        "酒店 MCP 未提供可追溯价格" in item
        for item in report_data["budget_confidence"]["estimated_items"]
    )
    assert report_data["budget"]["confidence"] == report_data["budget_confidence"]
    assert any(
        "交通 API 未提供具体票价" in item
        for item in report_data["tool_audit_summary"]["pending_checks"]
    )
    assert report_data["evidence_bundle"]["price_evidence"]["estimated"]
    assert validate_report_data(report_data).ok is True
    assert any(
        section["title"] == "预算置信度与待核验项"
        for section in report_data["sections"]
    )
    assert any(
        section["title"] == "顾问交付清单"
        for section in report_data["sections"]
    )


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
