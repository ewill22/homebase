"""
NHL public API helpers — free, no key, no quota.

Used to enrich flip alerts with three triangulating shot-attempt metrics:
  - Corsi-For % (CF%)        — raw shot attempts (SOG + missed + blocked + goals)
  - High-danger % (HD%)      — same events filtered to the slot
  - Score-adjusted CF% (aCF) — Corsi weighted to neutralize score effects
                                (trailing teams naturally shoot more)
"""
import math
import requests
from datetime import datetime
from .notify import NHL_TAGS

NHL_BASE = "https://api-web.nhle.com/v1"
SHOT_TYPES = {"shot-on-goal", "missed-shot", "blocked-shot", "goal"}

# High-danger zone: within ~20 ft of goal, between faceoff dots laterally.
# NHL coords: rink is x in [-100, 100], y in [-42.5, 42.5], goals at x = ±89.
HD_RADIUS_FT = 20.0
HD_LATERAL_FT = 22.0

# Score-state weights (shooter's perspective at time of shot).
# Trailing teams shoot more, so their attempts are weighted DOWN; leading
# teams shoot less, so their attempts are weighted UP. Neutralizes the
# "score effect" that flatters losing teams in raw Corsi.
SCORE_WEIGHTS = {
    -3: 0.78, -2: 0.78, -1: 0.85,
     0: 1.00,
     1: 1.18,  2: 1.27,  3: 1.27,
}


def _odds_team_to_abbrev(name):
    """Map Odds API full team name to NHL abbrev ('Pittsburgh Penguins' -> 'PIT')."""
    return NHL_TAGS.get(name)


def _is_high_danger(x, y):
    """True if shot coords land in the slot (close to net, between dots)."""
    if x is None or y is None:
        return False
    # distance from nearer goal mouth
    dist = math.hypot(abs(x) - 89.0, y)
    return dist <= HD_RADIUS_FT and abs(y) <= HD_LATERAL_FT


def _score_weight(shooter_diff):
    """Weight for a shot taken when shooter is up/down `shooter_diff` goals."""
    return SCORE_WEIGHTS.get(max(-3, min(3, shooter_diff)), 1.00)


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
    Return current shot-attempt stats for an NHL game:
        {
          'home_cf', 'away_cf', 'home_cf_pct', 'away_cf_pct', 'total',
          'home_hd', 'away_hd', 'home_hd_pct', 'away_hd_pct', 'hd_total',
          'home_adj', 'away_adj', 'home_adj_pct', 'away_adj_pct',
          'home_abbrev', 'away_abbrev',
          'home_score', 'away_score', 'period', 'clock', 'game_state', 'final',
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
    home_hd = away_hd = 0
    home_adj = away_adj = 0.0
    # Track running score during the play stream so each shot gets the
    # score-state weight that applied at the moment it was taken.
    home_running = away_running = 0

    for p in d.get("plays", []):
        kind = p.get("typeDescKey")
        if kind not in SHOT_TYPES:
            continue
        details = p.get("details", {}) or {}
        owner = details.get("eventOwnerTeamId")
        x = details.get("xCoord")
        y = details.get("yCoord")

        if owner == home_id:
            home_cf += 1
            home_adj += _score_weight(home_running - away_running)
            if _is_high_danger(x, y):
                home_hd += 1
        elif owner == away_id:
            away_cf += 1
            away_adj += _score_weight(away_running - home_running)
            if _is_high_danger(x, y):
                away_hd += 1

        # Goals advance the running score AFTER the shot is counted, so a
        # game-tying goal still weights as "trailing by 1" (which is when
        # the shot was taken).
        if kind == "goal":
            if owner == home_id:
                home_running += 1
            elif owner == away_id:
                away_running += 1

    total = home_cf + away_cf
    hd_total = home_hd + away_hd
    adj_total = home_adj + away_adj

    game_state = d.get("gameState")
    return {
        "home_cf": home_cf,
        "away_cf": away_cf,
        "home_cf_pct": (100.0 * home_cf / total) if total else 0.0,
        "away_cf_pct": (100.0 * away_cf / total) if total else 0.0,
        "total": total,
        "home_hd": home_hd,
        "away_hd": away_hd,
        "home_hd_pct": (100.0 * home_hd / hd_total) if hd_total else 0.0,
        "away_hd_pct": (100.0 * away_hd / hd_total) if hd_total else 0.0,
        "hd_total": hd_total,
        "home_adj": home_adj,
        "away_adj": away_adj,
        "home_adj_pct": (100.0 * home_adj / adj_total) if adj_total else 0.0,
        "away_adj_pct": (100.0 * away_adj / adj_total) if adj_total else 0.0,
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
    """Return raw CF% for whichever side is the favorite ('home' or 'away')."""
    if not corsi:
        return None
    return corsi["home_cf_pct"] if favorite_side == "home" else corsi["away_cf_pct"]


def favorite_hd_pct(corsi, favorite_side):
    """Return high-danger % for the favorite side, or None if no HD attempts yet."""
    if not corsi or not corsi.get("hd_total"):
        return None
    return corsi["home_hd_pct"] if favorite_side == "home" else corsi["away_hd_pct"]


def favorite_adj_cf_pct(corsi, favorite_side):
    """Return score-adjusted CF% for the favorite side."""
    if not corsi:
        return None
    return corsi["home_adj_pct"] if favorite_side == "home" else corsi["away_adj_pct"]
