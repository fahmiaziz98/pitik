from __future__ import annotations

from datetime import date, timedelta


def get_date_range(scope: str) -> tuple[date, date]:
    """
    Resolve a named scope string to a concrete start/end date pair.

    Args:
        scope: One of 'today', 'current_week', 'current_month', 'last_month'.

    Returns:
        Tuple of (start_date, end_date), both inclusive.
    """
    today = date.today()

    if scope == "today":
        return today, today

    if scope == "current_week":
        start = today - timedelta(days=today.weekday())
        return start, today

    if scope == "current_month":
        start = today.replace(day=1)
        return start, today

    if scope == "last_month":
        first_of_this_month = today.replace(day=1)
        last_day_prev = first_of_this_month - timedelta(days=1)
        start = last_day_prev.replace(day=1)
        return start, last_day_prev

    # Fallback to current month
    return today.replace(day=1), today
