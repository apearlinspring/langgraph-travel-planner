from types import SimpleNamespace

from app.api.v1.chat import (
    _report_content_from_tool_output,
    _report_extra_info_from_tool_output,
)


def test_report_extra_info_from_command_output():
    report_data = {
        "version": "travel_report.v1",
        "overview": {"route_label": "北京 -> 上海"},
    }
    output = SimpleNamespace(
        update={
            "order_id": "ORDER-1234",
            "report_data": report_data,
        }
    )

    extra_info = _report_extra_info_from_tool_output(output)

    assert extra_info["message_type"] == "travel_report"
    assert extra_info["order_id"] == "ORDER-1234"
    assert extra_info["report_data"] == report_data


def test_report_extra_info_ignores_non_report_tool_output():
    assert _report_extra_info_from_tool_output(SimpleNamespace(update={})) == {}
    assert _report_extra_info_from_tool_output({"content": "plain text"}) == {}


def test_report_content_from_command_output_prefers_report_field():
    output = SimpleNamespace(update={"report": "# 完整报告", "messages": []})

    assert _report_content_from_tool_output(output) == "# 完整报告"


def test_report_content_from_command_output_falls_back_to_tool_message():
    output = SimpleNamespace(
        update={
            "messages": [
                SimpleNamespace(content=""),
                SimpleNamespace(content="工具消息报告"),
            ],
        }
    )

    assert _report_content_from_tool_output(output) == "工具消息报告"
