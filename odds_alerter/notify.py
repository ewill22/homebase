"""SMS-via-email-gateway (Google Fi) + backup email to ewill22."""
import os
from dotenv import load_dotenv
from emailer import send_email

load_dotenv()

SMS_GATEWAY_DOMAIN = "msg.fi.google.com"   # Google Fi
BACKUP_EMAIL       = "ewill22@gmail.com"


NHL_TAGS = {
    "Anaheim Ducks": "ANA",
    "Boston Bruins": "BOS",
    "Buffalo Sabres": "BUF",
    "Calgary Flames": "CGY",
    "Carolina Hurricanes": "CAR",
    "Chicago Blackhawks": "CHI",
    "Colorado Avalanche": "COL",
    "Columbus Blue Jackets": "CBJ",
    "Dallas Stars": "DAL",
    "Detroit Red Wings": "DET",
    "Edmonton Oilers": "EDM",
    "Florida Panthers": "FLA",
    "Los Angeles Kings": "LAK",
    "Minnesota Wild": "MIN",
    "Montreal Canadiens": "MTL",
    "Montréal Canadiens": "MTL",
    "Nashville Predators": "NSH",
    "New Jersey Devils": "NJD",
    "New York Islanders": "NYI",
    "New York Rangers": "NYR",
    "Ottawa Senators": "OTT",
    "Philadelphia Flyers": "PHI",
    "Pittsburgh Penguins": "PIT",
    "San Jose Sharks": "SJS",
    "Seattle Kraken": "SEA",
    "St Louis Blues": "STL",
    "St. Louis Blues": "STL",
    "Tampa Bay Lightning": "TBL",
    "Toronto Maple Leafs": "TOR",
    "Utah Mammoth": "UTA",
    "Utah Hockey Club": "UTA",
    "Vancouver Canucks": "VAN",
    "Vegas Golden Knights": "VGK",
    "Washington Capitals": "WSH",
    "Winnipeg Jets": "WPG",
}


def _team_tag(team):
    if team in NHL_TAGS:
        return NHL_TAGS[team]
    # Fallback for anything missed: first 3 letters of last word
    parts = team.split()
    return parts[-1][:3].upper()


def compose_flip_message(fav_team, opener_ml, current_ml,
                         home, away, home_score, away_score, period,
                         fav_cf_pct=None):
    """
    Format: 'you watching this? favorite just got scored on, PIT opened -142,
            now +108 live. Down 1-0 2nd. PIT 38% shot share - getting outplayed'
    Stays under ~300 chars so Google Fi gateway delivers cleanly.
    """
    tag = _team_tag(fav_team)
    opener_s  = f"+{opener_ml}" if opener_ml > 0 else str(opener_ml)
    current_s = f"+{current_ml}" if current_ml > 0 else str(current_ml)

    if home_score is not None and away_score is not None:
        if fav_team == home:
            fav_score, opp_score = home_score, away_score
        else:
            fav_score, opp_score = away_score, home_score
        margin = (f"Down {opp_score}-{fav_score}" if opp_score > fav_score
                  else f"Up {fav_score}-{opp_score}" if fav_score > opp_score
                  else f"Tied {fav_score}-{opp_score}")
    else:
        margin = ""

    period_s = {1: "1st", 2: "2nd", 3: "3rd"}.get(period, "")
    context_bits = [b for b in (margin, period_s) if b]
    context = ". " + " ".join(context_bits) if context_bits else ""

    msg = (f"you watching this? favorite just got scored on, "
           f"{tag} opened {opener_s}, now {current_s} live{context}")

    if fav_cf_pct is not None:
        read = ("getting outplayed" if fav_cf_pct < 45
                else "dominating" if fav_cf_pct > 55
                else "game is even")
        msg += f". {tag} {fav_cf_pct:.0f}% shot share - {read}"

    return msg


def compose_cf_alert_message(fav_team, direction, cf_pct, home, away,
                             home_score, away_score, period):
    """
    Fired on CF% threshold crossing - no flip required.
    Three flavors:
      BUY DOG — dominating team is also trailing (value on their ML)
      FADE    — team being outplayed (sell or stay away)
      confirm — dominating + leading/tied (just info)
    'BUY DOG: LAK dominating 57% but down 1-0, 1st - ML has value'
    'OTT being outplayed 44%, down 1-0, 1st - fade signal'
    """
    tag = _team_tag(fav_team)
    period_s = {1: "1st", 2: "2nd", 3: "3rd"}.get(period, "")

    score_state = None   # 'down' | 'up' | 'tied' | None
    score_str = ""
    if home_score is not None and away_score is not None:
        if fav_team == home:
            my_score, opp_score = home_score, away_score
        else:
            my_score, opp_score = away_score, home_score
        if opp_score > my_score:
            score_state = "down"; score_str = f"down {opp_score}-{my_score}"
        elif my_score > opp_score:
            score_state = "up"; score_str = f"up {my_score}-{opp_score}"
        else:
            score_state = "tied"; score_str = f"tied {my_score}-{opp_score}"

    tail_bits = [b for b in (period_s, score_str) if b]
    tail = (", " + ", ".join(tail_bits)) if tail_bits else ""

    if direction == "above" and score_state == "down":
        return f"BUY DOG: {tag} dominating {cf_pct:.0f}%{tail} - ML has value"
    if direction == "below":
        return f"FADE {tag}: being outplayed {cf_pct:.0f}%{tail}"
    # dominating + leading/tied: informational
    return f"{tag} dominating {cf_pct:.0f}%{tail}"


def compose_watch_status(team_abbrev, opp_abbrev, cf_pct, home_score,
                         away_score, period, team_is_home):
    """Per-cycle pulse for 'watch XXX' command."""
    period_s = {1: "1st", 2: "2nd", 3: "3rd", 4: "OT"}.get(period, "")
    if home_score is not None and away_score is not None:
        my_score, opp_score = ((home_score, away_score) if team_is_home
                               else (away_score, home_score))
        score_bit = f"{team_abbrev} {my_score} {opp_abbrev} {opp_score}"
    else:
        score_bit = f"{team_abbrev} vs {opp_abbrev}"
    cf_bit = f"{cf_pct:.0f}% shots" if cf_pct is not None else ""
    parts = [b for b in (score_bit, period_s, cf_bit) if b]
    return " | ".join(parts)


def compose_lock_message(flipped_team, flip_ml, hedge_team, hedge_ml,
                         hedge_ratio, profit_pct):
    """
    'LOCK: BUF +135 earlier -> BOS now +275. Bet 67% of your BUF stake
     on BOS for guaranteed +32%.'
    """
    flip_tag = _team_tag(flipped_team)
    hedge_tag = _team_tag(hedge_team)
    flip_s = f"+{flip_ml}" if flip_ml > 0 else str(flip_ml)
    hedge_s = f"+{hedge_ml}" if hedge_ml > 0 else str(hedge_ml)
    return (f"LOCK: {flip_tag} {flip_s} earlier -> {hedge_tag} now {hedge_s}. "
            f"Bet {hedge_ratio:.0%} of your {flip_tag} stake on {hedge_tag} "
            f"for guaranteed +{profit_pct:.0%}.")


def send_flip_alert(phone_number, message):
    """SMS-only via Google Fi gateway. Returns True on success, False on failure."""
    sms_to = f"{phone_number}@{SMS_GATEWAY_DOMAIN}"
    try:
        send_email(subject="", body=message, to=sms_to)
        return True
    except Exception:
        return False
