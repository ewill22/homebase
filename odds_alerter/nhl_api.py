"""
NHL public API helpers — free, no key, no quota.

Used to enrich flip alerts with Corsi-For percentage (CF%), the standard
shot-share proxy for "is this team actually outplaying the other?"
"""
import requests
from datetime import datetime
from .notify import NHL_TAGS

NHL_BASE = "https://api-web.nhle.com/v1"
SHOT_TYPES = {"shot-on-goal", "missed-shot", "blocked-shot", "goal"}


def _odds_team_to_abbrev(name):
    """Map Odds API full team name to NHL abbrev ('Pittsburgh Penguins' -> 'PIT')."""
    return NHL_TAGS.get(name)


def lookup_nhl_game_id(date_str, home_team_name, away_team_name):
    """
    Given an ISO date (YYYY-MM-DD) and Odds API full team names, return the NHL
    gameId (int) or None if not found.
    """
    home_abbrev = _odds_team_to_abbrev(home_team_name)
    away_abbrev = _odds_team_to_abbrev(away_team_name)
    if not home_abbrev or not away_abbrev:
        return None
    try:
        r = requests.get(f"{NHL_BASE}/schedule/{date_str}", timeout=10)
        r.raise_for_status()
    except requests.RequestException:
        return None
    for day in r.json().get("gameWeek", []):
        if day.get("date") != date_str:
            continue
        for g in day.get("games", []):
            if (g.get("homeTeam", {}).get("abbrev") == home_abbrev and
                    g.get("awayTeam", {}).get("abbrev") == away_abbrev):
                return g.get("id")
    return None


def get_corsi(nhl_game_id):
    """
    Return current Corsi stats for an NHL game:
        {
          'home_cf': int, 'away_cf': int,
          'home_cf_pct': float, 'away_cf_pct': float,
          'total': int,
          'home_abbrev': str, 'away_abbrev': str,
          'period': int, 'clock': str, 'game_state': str,
        }
    Returns None on API error or if game has no play data yet.
    """
    try:
        r = requests.get(f"{NHL_BASE}/gamecenter/{nhl_game_id}/play-by-play", timeout=10)
        r.raise_for_status()
    except requests.RequestException:
        return None
    d = r.json()
    home_id = d.get("homeTeam", {}).get("id")
    away_id = d.get("awayTeam", {}).get("id")
    if home_id is None or away_id is None:
        return None

    home_cf = away_cf = 0
    for p in d.get("plays", []):
        if p.get("typeDescKey") not in SHOT_TYPES:
            continue
        owner = p.get("details", {}).get("eventOwnerTeamId")
        if owner == home_id:
            home_cf += 1
        elif owner == away_id:
            away_cf += 1
    total = home_cf + away_cf

    game_state = d.get("gameState")
    return {
        "home_cf": home_cf,
        "away_cf": away_cf,
        "home_cf_pct": (100.0 * home_cf / total) if total else 0.0,
        "away_cf_pct": (100.0 * away_cf / total) if total else 0.0,
        "total": total,
        "home_abbrev": d.get("homeTeam", {}).get("abbrev"),
        "away_abbrev": d.get("awayTeam", {}).get("abbrev"),
        "home_score": d.get("homeTeam", {}).get("score"),
        "away_score": d.get("awayTeam", {}).get("score"),
        "period": (d.get("periodDescriptor") or {}).get("number"),
        "clock": (d.get("clock") or {}).get("timeRemaining"),
        "game_state": game_state,
        "final": game_state in ("OFF", "FINAL"),
    }


def favorite_cf_pct(corsi, favorite_side):
    """Return the CF% for whichever side is the favorite ('home' or 'away')."""
    if not corsi:
        return None
    return corsi["home_cf_pct"] if favorite_side == "home" else corsi["away_cf_pct"]
