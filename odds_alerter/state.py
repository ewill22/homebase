"""MySQL-backed state for the odds alerter. Replaces the spec's state.json."""
from datetime import datetime
from db import get_connection


def month_key(now=None):
    return (now or datetime.now()).strftime("%Y-%m")


def get_api_usage(mkey=None):
    mkey = mkey or month_key()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT IGNORE INTO odds_api_usage (month_key, paid_calls) VALUES (%s, 0)",
        (mkey,),
    )
    conn.commit()
    cur.execute(
        "SELECT paid_calls FROM odds_api_usage WHERE month_key=%s", (mkey,)
    )
    used = cur.fetchone()[0]
    cur.close()
    conn.close()
    return used


def record_api_call(endpoint, credits=1):
    mkey = month_key()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO odds_api_usage (month_key, paid_calls, last_endpoint, last_call_at)
           VALUES (%s, %s, %s, NOW())
           ON DUPLICATE KEY UPDATE
             paid_calls = paid_calls + VALUES(paid_calls),
             last_endpoint = VALUES(last_endpoint),
             last_call_at = NOW()""",
        (mkey, credits, endpoint),
    )
    conn.commit()
    cur.execute("SELECT paid_calls FROM odds_api_usage WHERE month_key=%s", (mkey,))
    used = cur.fetchone()[0]
    cur.close()
    conn.close()
    return used


def upsert_event(event_id, home, away, commence_time):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO odds_games (event_id, home, away, commence_time)
           VALUES (%s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE home=VALUES(home), away=VALUES(away),
             commence_time=VALUES(commence_time)""",
        (event_id, home, away, commence_time),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_game(event_id):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM odds_games WHERE event_id=%s", (event_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def save_opener(event_id, ml_home, ml_away, favorite):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """UPDATE odds_games
             SET opening_ml_home=%s, opening_ml_away=%s, opening_favorite=%s,
                 opening_captured_at=NOW(), current_ml_home=%s, current_ml_away=%s,
                 last_polled_at=NOW()
           WHERE event_id=%s""",
        (ml_home, ml_away, favorite, ml_home, ml_away, event_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def update_current_odds(event_id, ml_home, ml_away):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """UPDATE odds_games
             SET current_ml_home=%s, current_ml_away=%s, last_polled_at=NOW(),
                 status='in_play'
           WHERE event_id=%s""",
        (ml_home, ml_away, event_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def update_score(event_id, period, home_score, away_score, final=False):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """UPDATE odds_games
             SET period=%s, home_score=%s, away_score=%s,
                 final=%s, status=%s
           WHERE event_id=%s""",
        (period, home_score, away_score, final,
         "final" if final else "in_play", event_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def mark_alerted(event_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE odds_games SET alerted=TRUE, alerted_at=NOW() WHERE event_id=%s",
        (event_id,),
    )
    conn.commit()
    cur.close()
    conn.close()


def save_nhl_game_id(event_id, nhl_game_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE odds_games SET nhl_game_id=%s WHERE event_id=%s",
        (nhl_game_id, event_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def update_cf(event_id, cf_home, cf_away, attempts, alert_dir=None):
    """Persist latest CF% snapshot. alert_dir only provided when a threshold alert fired."""
    conn = get_connection()
    cur = conn.cursor()
    if alert_dir is None:
        cur.execute(
            """UPDATE odds_games
                 SET last_cf_home=%s, last_cf_away=%s, last_cf_attempts=%s,
                     last_cf_checked_at=NOW()
               WHERE event_id=%s""",
            (cf_home, cf_away, attempts, event_id),
        )
    else:
        cur.execute(
            """UPDATE odds_games
                 SET last_cf_home=%s, last_cf_away=%s, last_cf_attempts=%s,
                     last_cf_alert_dir=%s, last_cf_checked_at=NOW()
               WHERE event_id=%s""",
            (cf_home, cf_away, attempts, alert_dir, event_id),
        )
    conn.commit()
    cur.close()
    conn.close()


def reset_cf_alert_dir(event_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE odds_games SET last_cf_alert_dir=NULL WHERE event_id=%s",
        (event_id,),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_active_watches():
    """Return list of active watch requests joined to their games."""
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT w.id AS watch_id, w.event_id, w.team_abbrev, w.last_update_sent_at,
                  g.home, g.away, g.commence_time, g.final, g.nhl_game_id,
                  g.opening_favorite
             FROM odds_watch w
             JOIN odds_games g ON g.event_id = w.event_id
            WHERE w.active = TRUE AND g.final = FALSE"""
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def mark_watch_sent(watch_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE odds_watch SET last_update_sent_at=NOW() WHERE id=%s",
        (watch_id,),
    )
    conn.commit()
    cur.close()
    conn.close()


def deactivate_watches_for_event(event_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE odds_watch SET active=FALSE WHERE event_id=%s AND active=TRUE",
        (event_id,),
    )
    conn.commit()
    cur.close()
    conn.close()


def add_watch(event_id, team_abbrev):
    conn = get_connection()
    cur = conn.cursor()
    # deactivate any prior active watches for this event to avoid dupes
    cur.execute(
        "UPDATE odds_watch SET active=FALSE WHERE event_id=%s AND active=TRUE",
        (event_id,),
    )
    cur.execute(
        "INSERT INTO odds_watch (event_id, team_abbrev) VALUES (%s, %s)",
        (event_id, team_abbrev),
    )
    conn.commit()
    cur.close()
    conn.close()


def find_event_today_by_team(abbrev, nhl_tags):
    """
    Given a team abbrev like 'PIT', find today's game in odds_games whose home
    or away matches that team. Returns the row or None.
    """
    # Reverse-map abbrev to full team names
    full_names = [name for name, a in nhl_tags.items() if a == abbrev]
    if not full_names:
        return None
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    placeholders = ",".join(["%s"] * len(full_names))
    q = f"""SELECT * FROM odds_games
             WHERE (home IN ({placeholders}) OR away IN ({placeholders}))
               AND DATE(commence_time) = CURDATE()
             ORDER BY commence_time LIMIT 1"""
    cur.execute(q, tuple(full_names) * 2)
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def log_flip(event_id, favorite_side, favorite_team, opening_ml, current_ml,
             home_score, away_score, period, message, sms_sent):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO odds_flip_history
             (event_id, detected_at, favorite_side, favorite_team,
              opening_ml, current_ml, home_score, away_score, period,
              message, sms_sent)
           VALUES (%s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (event_id, favorite_side, favorite_team, opening_ml, current_ml,
         home_score, away_score, period, message, sms_sent),
    )
    conn.commit()
    cur.close()
    conn.close()
