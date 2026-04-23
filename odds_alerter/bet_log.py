"""
Bet history log — parses Eric's pasted bet lines and logs them.

Line formats Eric uses:
  "04/22/2026 10:00 PM — Wild to win (Wild vs. Stars) — +145 — $0.50 — LOST"
  "04/22/2026 — Flyers to win (Flyers vs. Penguins) — +155 — $0.24 → $0.43 — CASHED OUT"
  "04/21/2026 — Lightning to win (Lightning vs. Canadiens) — +200 — $0.50 → $1.50 — WON"

Usage:
    python -m odds_alerter.bet_log add "<pasted line>"
    python -m odds_alerter.bet_log add-many < bets.txt
    python -m odds_alerter.bet_log report            # last 30 days w/ alerts joined
"""
import io
import re
import sys
from datetime import datetime
from db import get_connection

# Windows cp1252 stdin mangles em-dashes; force UTF-8.
if hasattr(sys.stdin, "buffer"):
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")

# Accepts em-dash, en-dash, or hyphen as separator.
SEP = r"\s*[\u2014\u2013\-]\s*"
DATE_RE = r"(?P<date>\d{2}/\d{2}/\d{4})"
TIME_RE = r"(?:\s+(?P<time>\d{1,2}:\d{2}\s*[AP]M))?"
LINE_RE = re.compile(
    DATE_RE + TIME_RE + SEP +
    r"(?P<team>.+?) to win\s*\((?P<matchup>[^)]+)\)" + SEP +
    r"(?P<odds>[+-]\d+)" + SEP +
    r"\$(?P<stake>[\d.]+)(?:\s*[\u2192\->]+\s*\$(?P<payout>[\d.]+))?" + SEP +
    r"(?P<result>WON|LOST|CASHED OUT|CASHED_OUT|PENDING)",
    re.IGNORECASE,
)


def parse_line(line):
    m = LINE_RE.search(line.strip())
    if not m:
        return None
    g = m.groupdict()
    date_s = g["date"]
    time_s = g["time"] or "12:00 PM"
    placed_at = datetime.strptime(f"{date_s} {time_s}", "%m/%d/%Y %I:%M %p")
    result = g["result"].upper().replace(" ", "_")
    return {
        "placed_at": placed_at,
        "team_bet": g["team"].strip(),
        "matchup": g["matchup"].strip(),
        "odds": int(g["odds"]),
        "stake": float(g["stake"]),
        "payout": float(g["payout"]) if g["payout"] else None,
        "result": result,
    }


def insert(bet):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO bet_history (placed_at, team_bet, matchup, odds, stake, payout, result)
           VALUES (%(placed_at)s, %(team_bet)s, %(matchup)s, %(odds)s, %(stake)s, %(payout)s, %(result)s)""",
        bet,
    )
    conn.commit()
    bet_id = cur.lastrowid
    cur.close()
    conn.close()
    return bet_id


def add_line(line):
    bet = parse_line(line)
    if not bet:
        print(f"COULD NOT PARSE: {line}")
        return None
    bid = insert(bet)
    print(f"#{bid}  {bet['placed_at']:%m/%d %I:%M%p}  {bet['team_bet']} {bet['odds']:+d} ${bet['stake']} -> {bet['result']}")
    return bid


def report(days=30):
    """Show recent bets with any flip alerts we fired on the same matchup/date."""
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT * FROM bet_history
            WHERE placed_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            ORDER BY placed_at""",
        (days,),
    )
    bets = cur.fetchall()

    cur.execute(
        """SELECT detected_at, favorite_team, opening_ml, current_ml,
                  home_score, away_score, period
             FROM odds_flip_history
            WHERE detected_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            ORDER BY detected_at""",
        (days,),
    )
    alerts = cur.fetchall()
    cur.close()
    conn.close()

    profit = 0.0
    wins = losses = cashouts = 0
    print(f"\n=== Last {days}d ({len(bets)} bets, {len(alerts)} alerts) ===\n")
    for b in bets:
        # Find alerts same day where favorite_team matches either side of matchup
        day_alerts = [
            a for a in alerts
            if a["detected_at"].date() == b["placed_at"].date()
            and a["favorite_team"].split()[-1].lower() in b["matchup"].lower()
        ]
        if b["result"] == "WON":
            pnl = float(b["payout"] or 0) - float(b["stake"]); wins += 1
        elif b["result"] == "CASHED_OUT":
            pnl = float(b["payout"] or 0) - float(b["stake"]); cashouts += 1
        elif b["result"] == "LOST":
            pnl = -float(b["stake"]); losses += 1
        else:
            pnl = 0
        profit += pnl
        marker = {"WON": "W", "LOST": "L", "CASHED_OUT": "C", "PENDING": "?"}.get(b["result"], "?")
        print(f"[{marker}] {b['placed_at']:%m/%d %I:%M%p}  {b['team_bet']} {b['odds']:+d}  ${b['stake']:.2f}  pnl ${pnl:+.2f}  ({b['matchup']})")
        for a in day_alerts:
            direction = "flipped-up" if a["current_ml"] > 0 and a["opening_ml"] < 0 else "flipped-dn"
            print(f"     alert {a['detected_at']:%I:%M%p} {a['favorite_team'].split()[-1]} {a['opening_ml']:+d}->{a['current_ml']:+d} ({direction})")
    print(f"\nW-L-C: {wins}-{losses}-{cashouts}   Net: ${profit:+.2f}")


def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    cmd = sys.argv[1]
    if cmd == "add":
        add_line(" ".join(sys.argv[2:]))
    elif cmd == "add-many":
        for line in sys.stdin:
            if line.strip():
                add_line(line)
    elif cmd == "report":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        report(days)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
