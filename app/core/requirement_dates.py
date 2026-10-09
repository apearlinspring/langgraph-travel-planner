"""Shared requirement-date confirmation rules for live query tools."""
from __future__ import annotations

from collections.abc import Collection


PENDING_DEPARTURE_DATE_VALUES = frozenset(
    {
        "", "日期", "日期待确认", "出发日期", "出发日期待确认",
        "待确认", "未确认", "待核验", "待核实",
    }
)
PENDING_HOTEL_DATE_VALUES = PENDING_DEPARTURE_DATE_VALUES | {"入住日期", "入住日期待确认"}


def requirement_departure_date_confirmation(
    requirement: dict,
    normalized_date: str,
    *,
    pending_date_values: Collection[str] = PENDING_DEPARTURE_DATE_VALUES,
) -> tuple[bool | None, str]:
    if not requirement:
        return None, ""

    date_text = str(normalized_date or "").strip()
    if date_text in pending_date_values:
        return False, "pending"
    if requirement.get("departure_date_confirmed") is False:
        return False, str(requirement.get("departure_date_source") or "unconfirmed")
    if requirement.get("departure_date_confirmed") is True:
        return True, str(requirement.get("departure_date_source") or "user_confirmed")
    return True, str(requirement.get("departure_date_source") or "legacy_confirmed")
