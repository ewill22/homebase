"""
config.py — Load per-user configuration from the DB.

Usage:
    from config import get_config
    cfg = get_config()          # defaults to user_id=1
    cfg["user"]["send_to_email"]
    cfg["cities"]               # list of city dicts
    cfg["personal_cal_ids"]     # list of Google Calendar IDs (personal only)
    cfg["sports_cal_ids"]       # list of Google Calendar IDs (sports)
"""
from db import get_connection

_cache = {}


def get_config(user_id=1, refresh=False):
    """Return config dict for a user, cached per process."""
    if not refresh and user_id in _cache:
        return _cache[user_id]

    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    user = cursor.fetchone()
    if not user:
        raise ValueError(f"No user found with user_id={user_id}")

    cursor.execute(
        "SELECT * FROM user_cities WHERE user_id = %s ORDER BY display_order",
        (user_id,)
    )
    cities = cursor.fetchall()

    cursor.execute(
        "SELECT * FROM user_calendars WHERE user_id = %s",
        (user_id,)
    )
    calendars = cursor.fetchall()

    cursor.close()
    conn.close()

    personal_cal_ids = [c["calendar_id"] for c in calendars]
    trusted_senders  = [s.strip() for s in (user.get("trusted_senders") or "").split(",") if s.strip()]

    cfg = {
        "user":             user,
        "cities":           cities,
        "calendars":        calendars,
        "personal_cal_ids": personal_cal_ids,
        "trusted_senders":  trusted_senders,
    }
    _cache[user_id] = cfg
    return cfg
