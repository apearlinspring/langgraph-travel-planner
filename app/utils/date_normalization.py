"""
Small deterministic helpers for user-facing travel dates.
"""
from __future__ import annotations

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


def normalize_travel_date(value: str, *, today: Optional[date] = None) -> str:
    """Normalize common Chinese relative dates or validate an ISO travel date."""

    normalized = str(value).strip()
    base_date = today or date.today()
    for label in sorted(RELATIVE_DATE_OFFSETS, key=len, reverse=True):
        if label in normalized:
            return (base_date + timedelta(days=RELATIVE_DATE_OFFSETS[label])).isoformat()

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
