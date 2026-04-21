"""PAID /scores endpoint — 1 credit per call (without daysFrom), returns all sport scores."""
import os
import requests
from dotenv import load_dotenv
from .config import API_BASE, SPORT
from . import state

load_dotenv()


def get_slate_scores():
    """
    Return dict keyed by event_id: {home, away, home_score, away_score, completed, period}.

    The Odds API scores endpoint doesn't expose period directly — it gives
    `last_update` and `scores`. We infer period from elapsed time at the
    caller level. Records 1 credit.
    """
    key = os.getenv("ODDS_API_KEY", "").strip()
    url = f"{API_BASE}/sports/{SPORT}/scores"
    r = requests.get(url, params={"apiKey": key}, timeout=15)
    state.record_api_call("scores", credits=1)
    r.raise_for_status()
    out = {}
    for g in r.json():
        home = g.get("home_team")
        away = g.get("away_team")
        scores_list = g.get("scores") or []
        home_score = away_score = None
        for s in scores_list:
            try:
                v = int(s.get("score"))
            except (TypeError, ValueError):
                continue
            if s.get("name") == home:
                home_score = v
            elif s.get("name") == away:
                away_score = v
        out[g["id"]] = {
            "home": home,
            "away": away,
            "home_score": home_score,
            "away_score": away_score,
            "completed": bool(g.get("completed")),
        }
    return out
