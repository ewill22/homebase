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
    'PIT is being outplayed - 38% shot share, 2nd period, tied 1-1'
    """
    tag = _team_tag(fav_team)
    head = ("is being outplayed" if direction == "below"
            else "is dominating")
    period_s = {1: "1st", 2: "2nd", 3: "3rd"}.get(period, "")

    if home_score is not None and away_score is not None:
        if fav_team == home:
            fav_score, opp_score = home_score, away_score
        else:
            fav_score, opp_score = away_score, home_score
        score_bit = (f"down {opp_score}-{fav_score}" if opp_score > fav_score
                     else f"up {fav_score}-{opp_score}" if fav_score > opp_score
                     else f"tied {fav_score}-{opp_score}")
    else:
        score_bit = ""

    tail_bits = [b for b in (period_s, score_bit) if b]
    tail = (", " + ", ".join(tail_bits)) if tail_bits else ""
    return f"{tag} {head} - {cf_pct:.0f}% shot share{tail}"


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


def send_flip_alert(phone_number, message):
    """
    Sends to Google Fi SMS gateway + backup to ewill22@gmail.com.
    Returns True on SMS attempt, False on failure (email backup still attempts).
    """
    sms_to = f"{phone_number}@{SMS_GATEWAY_DOMAIN}"
    sms_ok = False
    try:
        # Blank subject - some gateways prepend subject to body
        send_email(subject="", body=message, to=sms_to)
        sms_ok = True
    except Exception:
        pass

    # Always send a backup email so a missed SMS is recoverable
    try:
        send_email(
            subject="odds alert",
            body=message,
            to=BACKUP_EMAIL,
        )
    except Exception:
        pass

    return sms_ok
