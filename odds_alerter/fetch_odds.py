"""PAID /odds endpoint — 1 credit per call, returns odds for ALL games in the sport."""
import os
import requests
from dotenv import load_dotenv
from .config import API_BASE, SPORT, BOOKMAKER, REGION, MARKET, ODDS_FORMAT
from . import state

load_dotenv()


def get_slate_odds():
    """
    Return a dict keyed by event_id: {home, away, ml_home, ml_away, bookmaker}.

    ml_home / ml_away are American integer odds (+108, -142). Returns {} on
    bookmaker outage or unexpected structure (caller retries next cycle).
    Records 1 credit of API usage before returning.
    """
    key = os.getenv("ODDS_API_KEY", "").strip()
    url = f"{API_BASE}/sports/{SPORT}/odds"
    params = {
        "apiKey": key,
        "regions": REGION,
        "markets": MARKET,
        "oddsFormat": ODDS_FORMAT,
        "bookmakers": BOOKMAKER,
    }
    r = requests.get(url, params=params, timeout=15)
    state.record_api_call("odds", credits=1)
    r.raise_for_status()
    out = {}
    for g in r.json():
        home = g.get("home_team")
        away = g.get("away_team")
        books = g.get("bookmakers") or []
        if not books:
            continue
        book = next((b for b in books if b.get("key") == BOOKMAKER), books[0])
        markets = {m.get("key"): m for m in book.get("markets", [])}
        h2h = markets.get("h2h")
        if not h2h:
            continue
        ml_home = ml_away = None
        for outcome in h2h.get("outcomes", []):
            if outcome.get("name") == home:
                ml_home = outcome.get("price")
            elif outcome.get("name") == away:
                ml_away = outcome.get("price")
        if ml_home is None or ml_away is None:
            continue
        out[g["id"]] = {
            "home": home,
            "away": away,
            "ml_home": int(ml_home),
            "ml_away": int(ml_away),
            "bookmaker": book.get("key"),
        }
    return out
