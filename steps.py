"""
steps.py — Step data from the health_steps cache for the morning email.
Cache is written by health_steps.py --sync (runs at 6:50 AM via Task Scheduler).
"""
import json
import os
from calendar import monthrange
from datetime import date, timedelta

CACHE_PATH   = os.path.expanduser("~/.health_steps_cache.json")
MONTHLY_GOAL = 7_500   # target average steps/day for the month


def _load_cache():
    if not os.path.isfile(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def get_steps_yesterday():
    """Return yesterday's step count from cache, or None."""
    cache = _load_cache()
    return cache.get(str(date.today() - timedelta(days=1)))


def get_daily_target():
    """
    Adjusted daily target to hit MONTHLY_GOAL average by end of month.
    Takes into account steps already logged this month so far.
    Returns an int.
    """
    today          = date.today()
    days_in_month  = monthrange(today.year, today.month)[1]
    month_total    = MONTHLY_GOAL * days_in_month

    cache          = _load_cache()
    prefix         = f"{today.year}-{today.month:02d}-"
    steps_so_far   = sum(
        v for k, v in cache.items()
        if k.startswith(prefix) and k < str(today)
    )

    days_remaining = days_in_month - today.day + 1
    if days_remaining <= 0:
        return MONTHLY_GOAL

    return max(0, round((month_total - steps_so_far) / days_remaining))
