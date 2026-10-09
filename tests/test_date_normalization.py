from datetime import date

import pytest

from app.utils.date_normalization import normalize_travel_date


def test_normalize_travel_date_supports_chinese_relative_dates():
    today = date(2026, 4, 29)

    assert normalize_travel_date("今天", today=today) == "2026-04-29"
    assert normalize_travel_date("明天", today=today) == "2026-04-30"
    assert normalize_travel_date("明天出发", today=today) == "2026-04-30"
    assert normalize_travel_date("后天", today=today) == "2026-05-01"
    assert normalize_travel_date("大后天上午", today=today) == "2026-05-02"


def test_normalize_travel_date_supports_next_weekday_from_2026_05_19():
    assert normalize_travel_date("下周三", today=date(2026, 5, 19)) == "2026-05-27"


def test_normalize_travel_date_rejects_past_dates():
    with pytest.raises(ValueError, match="早于今天"):
        normalize_travel_date("2023-11-22", today=date(2026, 4, 29))
