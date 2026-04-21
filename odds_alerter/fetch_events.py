"""FREE /events endpoint — does NOT count against the 500/month quota."""
import os
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from .config import API_BASE, SPORT

load_dotenv()


def get_events():
    """Return list of dicts: {event_id, home, away, commence_time_utc}."""
    key = os.getenv("ODDS_API_KEY", "").strip()
    url = f"{API_BASE}/sports/{SPORT}/events"
    r = requests.get(url, params={"apiKey": key}, timeout=15)
    r.raise_for_status()
    out = []
    for e in r.json():
        ct = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
        out.append({
            "event_id": e["id"],
            "home": e["home_team"],
            "away": e["away_team"],
            "commence_time_utc": ct.astimezone(timezone.utc).replace(tzinfo=None),
        })
    return out
