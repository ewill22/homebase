"""
steps.py — Read today's step count from the health_steps cache.
The cache is written by health_steps.py --sync (runs at 6:50 AM via Task Scheduler).
"""
import json
import os
from datetime import date

CACHE_PATH = os.path.expanduser("~/.health_steps_cache.json")
GOAL = 10_000


def get_steps_today():
    """Return today's step count from cache, or None if not available."""
    if not os.path.isfile(CACHE_PATH):
        return None
    try:
        with open(CACHE_PATH) as f:
            cache = json.load(f)
        return cache.get(str(date.today()))
    except Exception:
        return None
