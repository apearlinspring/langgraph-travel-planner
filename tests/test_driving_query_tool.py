from app.tools.driving_query import _format_duration, _route_summary


def test_format_duration_treats_amap_duration_as_seconds():
    assert _format_duration(48156) == "13小时23分钟"


def test_route_summary_formats_distance_duration_and_costs():
    summary = _route_summary(
        origin_label="北京",
        destination_label="上海",
        route_data={
            "paths": [
                {
                    "distance": "1222435",
                    "duration": "48156",
                    "steps": [
                        {"road": "正义路"},
                        {"road": "G3京台高速"},
                        {"road": "G2京沪高速"},
                    ],
                }
            ]
        },
    )

    assert "1222.4 公里" in summary
    assert "13小时23分钟" in summary
    assert "48小时" not in summary
    assert "G3京台高速" in summary
