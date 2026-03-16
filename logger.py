"""
logger.py — Structured event logging to homebase_log.

Event types:
    summary_sent    — daily/on-demand email summary dispatched
    spotify_sync    — spotify_tracker poll completed
    command         — email command received and processed
    release_fetch   — new releases fetch attempt (ok or timeout/error)
    error           — unexpected exception in any scheduled job

Usage:
    from logger import log_event
    log_event("summary_sent", message="OK", detail="42 plays · 3 new releases")
    log_event("error", status="error", message=str(e), detail=traceback.format_exc())
"""
import json
from db import get_connection


def log_event(event_type, status="ok", message=None, detail=None, user_id=1):
    """
    Insert a row into homebase_log.

    detail can be a str or a dict (will be JSON-serialised automatically).
    """
    if isinstance(detail, dict):
        detail = json.dumps(detail)

    try:
        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO homebase_log (user_id, event_type, status, message, detail)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, event_type, status, message, detail)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception:
        # Never let logging crash the caller
        pass
