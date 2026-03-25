"""
steps.py — Step data for the morning email.
iPhone Shortcut writes steps_today.txt to iCloud Drive manually each night.
Subject format: {"date":"YYYY-MM-DD","steps":NNNN}
"""
import json
import glob
import os
from calendar import monthrange
from datetime import date, timedelta

CACHE_PATH   = os.path.expanduser("~/.health_steps_cache.json")
MONTHLY_GOAL = 7_500


def _load_cache():
    if not os.path.isfile(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache):
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)


def get_steps_yesterday():
    """
    Return yesterday's step count.
    Tries iCloud file first, falls back to cache.
    """
    yesterday = str(date.today() - timedelta(days=1))
    icloud_dir = os.path.expanduser("~/iCloudDrive")

    candidates = sorted(
        glob.glob(os.path.join(icloud_dir, "steps_today*.txt")),
        key=os.path.getmtime,
        reverse=True,
    )
    for path in candidates:
        try:
            with open(path) as f:
                data = json.load(f)
            if data.get("date") == yesterday:
                steps = int(float(str(data["steps"]).replace(",", "")))
                if 0 <= steps < 100_000:
                    cache = _load_cache()
                    cache[yesterday] = steps
                    _save_cache(cache)
                    return steps
        except Exception:
            continue

    return _load_cache().get(yesterday)


def get_daily_target():
    """
    Adjusted daily target to hit MONTHLY_GOAL average by end of month.
    """
    today         = date.today()
    days_in_month = monthrange(today.year, today.month)[1]
    month_total   = MONTHLY_GOAL * days_in_month

    cache        = _load_cache()
    prefix       = f"{today.year}-{today.month:02d}-"
    steps_so_far = sum(
        v for k, v in cache.items()
        if k.startswith(prefix) and k < str(today)
    )

    days_remaining = days_in_month - today.day + 1
    if days_remaining <= 0:
        return MONTHLY_GOAL

    return max(0, round((month_total - steps_so_far) / days_remaining))
