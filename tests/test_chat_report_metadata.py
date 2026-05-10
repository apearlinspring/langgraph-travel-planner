from types import SimpleNamespace

from app.api.v1.chat import _report_extra_info_from_tool_output


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
