"""
Small deterministic helpers for user-facing travel dates.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional


RELATIVE_DATE_OFFSETS = {
    "今天": 0,
    "今日": 0,
    "明天": 1,
    "明日": 1,
    "后天": 2,
    "大后天": 3,
}

CN_WEEKDAY_TO_INDEX = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}


def _normalize_relative_weekday(value: str, *, today: date) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None

    weekend_match = re.search(r"(下下周|下周|这周|本周)?\s*周末", normalized)
    if weekend_match:
        prefix = weekend_match.group(1) or "这周"
        target = 5
    else:
        weekday_match = re.search(
            r"(下下周|下周|这周|本周)?\s*(?:周|星期|礼拜)?([一二三四五六日天])",
            normalized,
        )
        if not weekday_match:
            return None
        prefix = weekday_match.group(1) or "这周"
        target = CN_WEEKDAY_TO_INDEX[weekday_match.group(2)]

    current_monday = today - timedelta(days=today.weekday())
    week_offset = 2 if prefix == "下下周" else 1 if prefix == "下周" else 0
    candidate = current_monday + timedelta(days=week_offset * 7 + target)
    if candidate < today and week_offset == 0:
        candidate += timedelta(days=7)
    return candidate.isoformat()


def normalize_travel_date(value: str, *, today: Optional[date] = None) -> str:
    """Normalize common Chinese relative dates or validate an ISO travel date."""

    normalized = str(value).strip()
    base_date = today or date.today()
    for label in sorted(RELATIVE_DATE_OFFSETS, key=len, reverse=True):
        if label in normalized:
            return (base_date + timedelta(days=RELATIVE_DATE_OFFSETS[label])).isoformat()

    relative_weekday = _normalize_relative_weekday(normalized, today=base_date)
    if relative_weekday:
        return relative_weekday

    try:
        parsed_date = datetime.strptime(normalized, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(
            "日期格式无法识别，请使用 YYYY-MM-DD，或使用今天/明天/后天这类相对日期。"
        ) from exc

    if parsed_date < base_date:
        raise ValueError(
            f"日期 {parsed_date.isoformat()} 早于今天 {base_date.isoformat()}，请重新确认出发日期。"
        )
    return parsed_date.isoformat()
