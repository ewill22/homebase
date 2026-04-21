"""
Free pregame signals from the NHL public API.

Everything here is free, no key, no quota — same API that powers CF%.
Goal: give Eric a one-text digest of every public edge available before
puck drop (goalies, rest, form, series state), so he can combine the
data with his eye test instead of dog-chasing plus-money numbers.
"""
import requests
from datetime import datetime, date, timedelta

NHL_BASE = "https://api-web.nhle.com/v1"


def _get(path):
    try:
        r = requests.get(f"{NHL_BASE}{path}", timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


def get_likely_starters(game_id):
    """
    First goalie in 'leaders' is the playoffs series leader in appearances —
    typically the starter. Fallback = whichever has gamesPlayed > 0.
    Returns {home: {name, sv_pct, gaa, gp, record}, away: {...}} or None.
    """
    d = _get(f"/gamecenter/{game_id}/landing")
    if not d:
        return None
    gc = (d.get("matchup") or {}).get("goalieComparison") or {}

    def pick(side):
        leaders = (gc.get(side) or {}).get("leaders") or []
        if not leaders:
            return None
        # Prefer one with gp > 0; else just the first.
        candidate = next((g for g in leaders if (g.get("gamesPlayed") or 0) > 0), leaders[0])
        return {
            "name": (candidate.get("name") or {}).get("default"),
            "sv_pct": candidate.get("savePctg"),
            "gaa": candidate.get("gaa"),
            "gp": candidate.get("gamesPlayed"),
            "record": candidate.get("record"),
        }

    return {"home": pick("homeTeam"), "away": pick("awayTeam")}


def get_series_state(game_id):
    """
    Playoff series record + streak.
    Returns {home_record, away_record, home_streak, away_streak, leader}
    or None for regular-season games.
    """
    d = _get(f"/gamecenter/{game_id}/landing")
    if not d:
        return None
    pr = (d.get("matchup") or {}).get("playoffsRecord") or {}
    home = pr.get("homeTeam") or {}
    away = pr.get("awayTeam") or {}
    if not home and not away:
        return None

    def streak_str(team):
        t, n = team.get("streakType"), team.get("streak")
        if t and n:
            return f"{t}{n}"
        return ""

    # Parse "W-L" records to find leader
    def wins(r):
        try:
            return int((r or "0-0").split("-")[0])
        except (ValueError, IndexError):
            return 0

    hw, aw = wins(home.get("record")), wins(away.get("record"))
    leader = None
    if hw > aw:
        leader = "home"
    elif aw > hw:
        leader = "away"

    return {
        "home_record": home.get("record"),
        "away_record": away.get("record"),
        "home_streak": streak_str(home),
        "away_streak": streak_str(away),
        "leader": leader,
    }


def _parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def get_recent_form(team_abbrev, n=10, before_date=None):
    """
    Last N completed games (regular season + playoffs mixed, which is fine
    for playoff-time 'how are they playing lately' reads).
    Returns {w, l, gf, ga, gd, last5_w, last5_l, streak} or None.
    """
    d = _get(f"/club-schedule-season/{team_abbrev}/now")
    if not d:
        return None
    completed = [g for g in d.get("games", []) if g.get("gameState") in ("OFF", "FINAL")]
    if before_date:
        cutoff = before_date if isinstance(before_date, date) else _parse_date(before_date)
        completed = [g for g in completed if _parse_date(g["gameDate"]) < cutoff]
    recent = completed[-n:]
    if not recent:
        return None

    w = l = gf = ga = 0
    streak_type, streak_len = None, 0
    for g in recent:
        home = g.get("homeTeam", {})
        away = g.get("awayTeam", {})
        if home.get("abbrev") == team_abbrev:
            my, opp = home.get("score", 0), away.get("score", 0)
        else:
            my, opp = away.get("score", 0), home.get("score", 0)
        gf += my
        ga += opp
        outcome = "W" if my > opp else "L"
        if outcome == "W":
            w += 1
        else:
            l += 1

    # Streak = trailing sequence
    for g in reversed(recent):
        home = g.get("homeTeam", {})
        away = g.get("awayTeam", {})
        if home.get("abbrev") == team_abbrev:
            my, opp = home.get("score", 0), away.get("score", 0)
        else:
            my, opp = away.get("score", 0), home.get("score", 0)
        outcome = "W" if my > opp else "L"
        if streak_type is None:
            streak_type, streak_len = outcome, 1
        elif outcome == streak_type:
            streak_len += 1
        else:
            break

    last5 = recent[-5:]
    l5w = sum(1 for g in last5
              if (g.get("homeTeam", {}).get("score", 0) > g.get("awayTeam", {}).get("score", 0))
              == (g.get("homeTeam", {}).get("abbrev") == team_abbrev))
    return {
        "w": w, "l": l, "gf": gf, "ga": ga, "gd": gf - ga,
        "last5_w": l5w, "last5_l": 5 - l5w,
        "streak": f"{streak_type}{streak_len}" if streak_type else "",
    }


def get_rest_days(team_abbrev, game_date_str):
    """
    Days between team's prior completed game and game_date_str.
    Returns (rest_days, back_to_back) — back_to_back = rest_days <= 1.
    """
    d = _get(f"/club-schedule-season/{team_abbrev}/now")
    if not d:
        return (None, False)
    game_date = _parse_date(game_date_str)
    completed = [g for g in d.get("games", []) if g.get("gameState") in ("OFF", "FINAL")
                 and _parse_date(g["gameDate"]) < game_date]
    if not completed:
        return (None, False)
    last_game = completed[-1]
    rest = (game_date - _parse_date(last_game["gameDate"])).days
    return (rest, rest <= 1)


def build_brief(game_id, home_abbrev, away_abbrev, game_date_str):
    """Assemble the full pregame snapshot for one game."""
    return {
        "goalies": get_likely_starters(game_id) or {},
        "series": get_series_state(game_id),
        "home_form": get_recent_form(home_abbrev, before_date=game_date_str),
        "away_form": get_recent_form(away_abbrev, before_date=game_date_str),
        "home_rest": get_rest_days(home_abbrev, game_date_str),
        "away_rest": get_rest_days(away_abbrev, game_date_str),
    }


def format_brief(brief, home_abbrev, away_abbrev):
    """ASCII-safe SMS digest. Targets ~320 chars so Fi gateway delivers cleanly."""
    lines = [f"{away_abbrev} @ {home_abbrev}"]

    s = brief.get("series")
    if s and s.get("leader"):
        lead_abbrev = home_abbrev if s["leader"] == "home" else away_abbrev
        lead_rec = s["home_record"] if s["leader"] == "home" else s["away_record"]
        lines.append(f"Series: {lead_abbrev} leads {lead_rec}")
    elif s:
        lines.append(f"Series: tied {s.get('home_record','')}")

    goalies = brief.get("goalies") or {}
    hg = goalies.get("home") or {}
    ag = goalies.get("away") or {}

    def g_fmt(abbrev, g):
        if not g or not g.get("name"):
            return f"{abbrev} ?"
        sv = g.get("sv_pct")
        gaa = g.get("gaa")
        sv_s = f".{int(round(sv*1000)):03d}" if sv else "?"
        gaa_s = f"{gaa:.2f}" if gaa else "?"
        return f"{abbrev} {g['name']} ({sv_s}/{gaa_s})"

    lines.append(f"G: {g_fmt(home_abbrev, hg)} | {g_fmt(away_abbrev, ag)}")

    hr, hbb = brief.get("home_rest", (None, False))
    ar, abb = brief.get("away_rest", (None, False))
    if hr is not None and ar is not None:
        rest_line = f"Rest: {home_abbrev} {hr}d"
        if hbb:
            rest_line += "(B2B)"
        rest_line += f" | {away_abbrev} {ar}d"
        if abb:
            rest_line += "(B2B)"
        lines.append(rest_line)

    hf = brief.get("home_form") or {}
    af = brief.get("away_form") or {}
    if hf and af:
        lines.append(
            f"L10: {home_abbrev} {hf.get('w',0)}-{hf.get('l',0)} "
            f"({hf.get('gd',0):+d}) {hf.get('streak','')} | "
            f"{away_abbrev} {af.get('w',0)}-{af.get('l',0)} "
            f"({af.get('gd',0):+d}) {af.get('streak','')}"
        )

    return "\n".join(lines)
