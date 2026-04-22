"""
Odds flip alerter orchestrator.

Run from the homebase directory as:
    pythonw.exe -m odds_alerter.main           # production
    python.exe  -m odds_alerter.main --dry-run # preview without sending SMS or paying /odds
"""
import os
import sys
import argparse
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

ET = ZoneInfo("America/New_York")


def nhl_date_str(utc_dt):
    """NHL /schedule files games under their Eastern date, not UTC.
    A 10 PM ET game (02:00 UTC next day) is filed under the ET calendar day."""
    return utc_dt.replace(tzinfo=timezone.utc).astimezone(ET).strftime("%Y-%m-%d")

# Parent dir (homebase) on path so we can import db.py, emailer.py, logger.py
HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from logger import log_event
from .config import (
    POLL_INTERVAL_MIN, PRE_GAME_WINDOW_MIN, MONTHLY_API_BUDGET, BUDGET_WARN_AT,
    SKIP_THIRD_PERIOD, THIRD_PERIOD_ELAPSED_MIN,
    ALERT_ONCE_PER_GAME, CF_LOW_THRESHOLD, CF_HIGH_THRESHOLD,
    CF_MIN_SAMPLE_ATTEMPTS,
)
from . import state, detect_flips, nhl_api, nhl_pregame
from .fetch_events import get_events
from .fetch_odds import get_slate_odds
from .notify import (
    compose_flip_message, compose_cf_alert_message, compose_watch_status,
    send_flip_alert, NHL_TAGS,
)

BRIEF_LEAD_MIN = 45   # send pregame brief when game is within this many min of start

load_dotenv()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def infer_period_from_elapsed(elapsed_min):
    """Rough wall-clock period inference when /scores hasn't been called."""
    if elapsed_min < 35:
        return 1
    if elapsed_min < 75:
        return 2
    return 3


def game_is_in_window(event, now):
    """True if commence_time is within PRE_GAME_WINDOW_MIN in the future or in the past."""
    delta = (event["commence_time_utc"] - now).total_seconds() / 60.0
    return delta <= PRE_GAME_WINDOW_MIN  # past or near-future


def game_is_live(event, now):
    return event["commence_time_utc"] <= now


def run(dry_run=False, verbose=True):
    now = utcnow()
    log = print if verbose else (lambda *a, **k: None)

    # ---- 0. Quiet hours: midnight – 2 PM ET ----
    # Don't text when Eric's asleep and no point polling pre-slate.
    et_hour = datetime.now().hour
    if et_hour < 14:
        log(f"  quiet hours (ET {et_hour}:00) — no-op")
        log_event("odds_alerter", message="quiet_hours", detail=f"ET hour={et_hour}")
        return

    # ---- 1. Free /events call, decide if any work is worth doing ----
    events = get_events()
    log(f"[{now.isoformat()}] {len(events)} events on NHL slate")

    relevant = [e for e in events if game_is_in_window(e, now)]
    # A game isn't relevant once it's clearly over (>3h45m since start)
    relevant = [e for e in relevant if (now - e["commence_time_utc"]).total_seconds() / 60.0 < 225]
    if not relevant:
        log("  no games in window — no-op, 0 paid calls")
        log_event("odds_alerter", message="noop", detail=f"{len(events)} events, 0 in window")
        return

    for e in relevant:
        state.upsert_event(
            e["event_id"], e["home"], e["away"], e["commence_time_utc"]
        )
        # Map to NHL gameId once — /schedule is free
        g = state.get_game(e["event_id"])
        if g and g.get("nhl_game_id") is None:
            date_str = nhl_date_str(e["commence_time_utc"])
            nhl_id = nhl_api.lookup_nhl_game_id(date_str, e["home"], e["away"])
            if nhl_id:
                state.save_nhl_game_id(e["event_id"], nhl_id)

    # ---- 1.5. Auto-brief: text pregame digest ~45 min before puck drop ----
    # Free (NHL API only), idempotent via odds_games.brief_sent_at.
    phone = os.getenv("ALERT_SMS_TO", "").strip()
    for e in relevant:
        mins_to_start = (e["commence_time_utc"] - now).total_seconds() / 60.0
        if mins_to_start <= 0 or mins_to_start > BRIEF_LEAD_MIN:
            continue
        g = state.get_game(e["event_id"])
        if not g or g.get("brief_sent_at"):
            continue
        nhl_id = g.get("nhl_game_id")
        if not nhl_id:
            continue
        home_abbrev = NHL_TAGS.get(e["home"])
        away_abbrev = NHL_TAGS.get(e["away"])
        if not home_abbrev or not away_abbrev:
            continue
        date_str = nhl_date_str(e["commence_time_utc"])
        try:
            brief = nhl_pregame.build_brief(nhl_id, home_abbrev, away_abbrev, date_str)
            msg = nhl_pregame.format_brief(brief, home_abbrev, away_abbrev)
            if dry_run:
                log(f"  DRY RUN brief: {away_abbrev} @ {home_abbrev} ({mins_to_start:.0f} min)")
                continue
            if phone:
                send_flip_alert(phone, msg)
            state.mark_brief_sent(e["event_id"])
            log(f"  BRIEF SENT: {away_abbrev} @ {home_abbrev} ({mins_to_start:.0f} min to start)")
        except Exception as exc:
            log(f"  brief failed for {away_abbrev} @ {home_abbrev}: {exc}")
            log_event("odds_alerter", status="error",
                      message="brief_failed", detail=f"{e['event_id']}: {exc}")

    # ---- 2. Budget guard ----
    used = state.get_api_usage()
    if used >= MONTHLY_API_BUDGET:
        log(f"  BUDGET EXHAUSTED ({used}/{MONTHLY_API_BUDGET}) — no paid calls")
        log_event("odds_alerter", status="error",
                  message="budget_exhausted", detail=f"{used}/{MONTHLY_API_BUDGET}")
        return
    if used >= BUDGET_WARN_AT:
        log(f"  WARN: {used}/{MONTHLY_API_BUDGET} credits used this month")

    # ---- 3. Classify what we need to do ----
    need_opener = []
    live_games  = []
    for e in relevant:
        g = state.get_game(e["event_id"])
        if g is None:
            continue
        live = game_is_live(e, now)
        if not live and g.get("opening_ml_home") is None:
            need_opener.append(e)
            continue
        if live:
            if g.get("alerted") and ALERT_ONCE_PER_GAME:
                continue
            if g.get("final"):
                continue
            live_games.append((e, g))

    log(f"  {len(need_opener)} need opener, {len(live_games)} live eligible")

    if not need_opener and not live_games:
        log("  nothing to poll — 0 paid calls")
        log_event("odds_alerter", message="noop_in_window",
                  detail=f"{len(relevant)} in window, all alerted/final/pickem")
        return

    # ---- 4. Pull score + period + Corsi from NHL play-by-play (free) ----
    # Replaces the paid /scores endpoint. Real-time, no quota, so flip messages
    # don't report stale "Tied 0-0" like they did 2026-04-20.
    corsi_by_event = {}
    for (e, _g) in live_games:
        g = state.get_game(e["event_id"])
        if not g:
            continue
        nhl_id = g.get("nhl_game_id")
        if not nhl_id:
            log(f"  {e['away']} @ {e['home']}: no nhl_game_id yet, CF% unavailable")
            continue
        c = nhl_api.get_corsi(nhl_id)
        if not c:
            log(f"  {e['away']} @ {e['home']}: play-by-play empty (game {nhl_id}), CF% unavailable")
            continue
        corsi_by_event[e["event_id"]] = c
        if c.get("period") is not None:
            state.update_score(
                e["event_id"], c["period"],
                c.get("home_score"), c.get("away_score"),
                final=bool(c.get("final")),
            )

    # ---- 5. Decide whether to call /odds ----
    # We call /odds if either need_opener has entries OR we have live games still pollable.
    pollable_live = []
    for (e, g) in live_games:
        # refresh state post-score-update
        g = state.get_game(e["event_id"]) or g
        if g.get("final"):
            continue
        elapsed = (now - e["commence_time_utc"]).total_seconds() / 60.0
        period_est = g.get("period") or infer_period_from_elapsed(elapsed)

        if SKIP_THIRD_PERIOD and period_est >= 3:
            fav = g.get("opening_favorite")
            fav_score = g.get("home_score") if fav == "home" else g.get("away_score")
            opp_score = g.get("away_score") if fav == "home" else g.get("home_score")
            if (fav_score is not None and opp_score is not None
                    and opp_score - fav_score >= 2):
                log(f"  skip /odds for {e['home']} vs {e['away']}: 3rd period blowout")
                continue
            # Period>=3 but we don't have definitive scores — still check, could be tied
            if (fav_score is None or opp_score is None):
                # Without score info be conservative — skip after 3rd-period threshold
                if elapsed >= THIRD_PERIOD_ELAPSED_MIN:
                    log(f"  skip /odds for {e['home']} vs {e['away']}: 3rd (no score, heuristic)")
                    continue

        # Respect per-game poll interval
        last = g.get("last_polled_at")
        if last and (now - last).total_seconds() / 60.0 < POLL_INTERVAL_MIN:
            continue

        pollable_live.append((e, g))

    should_call_odds = bool(need_opener or pollable_live)
    if not should_call_odds:
        log("  no /odds call needed this cycle")
        log_event("odds_alerter", message="cycle_done_no_odds",
                  detail=f"pollable_live={len(pollable_live)}, openers={len(need_opener)}")
        return

    if dry_run:
        log(f"  DRY RUN: would call /odds (credits used so far {used})")
        return

    # ---- 6. Paid /odds call (1 credit, all games) ----
    try:
        odds = get_slate_odds()
        log(f"  /odds: fetched odds for {len(odds)} games (used={state.get_api_usage()})")
    except Exception as exc:
        log(f"  /odds failed: {exc}")
        log_event("odds_alerter", status="error",
                  message="odds_fetch_failed", detail=str(exc))
        return

    # ---- 7. Capture openers for pre-game events ----
    for e in need_opener:
        row = odds.get(e["event_id"])
        if not row:
            continue
        fav = detect_flips.identify_favorite(row["ml_home"], row["ml_away"])
        if fav is None:
            log(f"  {e['away']} @ {e['home']}: pick-em, skipping")
            # Mark so we don't waste cycles re-checking
            state.save_opener(e["event_id"], row["ml_home"], row["ml_away"], None)
            continue
        state.save_opener(e["event_id"], row["ml_home"], row["ml_away"], fav)
        log(f"  opener captured: {e['away']} @ {e['home']}  "
            f"H={row['ml_home']} A={row['ml_away']} fav={fav}")

    # ---- 9. Check for flips AND CF% threshold crossings on live games ----
    # (CF% already fetched above in step 4 and cached in corsi_by_event)
    flip_alerts = []
    cf_alerts = []

    for (e, g) in pollable_live:
        row = odds.get(e["event_id"])
        if not row:
            continue
        state.update_current_odds(e["event_id"], row["ml_home"], row["ml_away"])

        fav = g.get("opening_favorite")
        if not fav:
            continue

        corsi = corsi_by_event.get(e["event_id"])
        fav_cf = nhl_api.favorite_cf_pct(corsi, fav) if corsi else None
        attempts = corsi["total"] if corsi else 0

        # Persist latest CF% snapshot
        if corsi:
            state.update_cf(e["event_id"], corsi["home_cf_pct"],
                            corsi["away_cf_pct"], attempts)

        # --- Flip check ---
        if detect_flips.is_flip(fav, row["ml_home"], row["ml_away"]):
            g2 = state.get_game(e["event_id"]) or g
            opener_ml = (g.get("opening_ml_home") if fav == "home"
                         else g.get("opening_ml_away"))
            current_ml = row["ml_home"] if fav == "home" else row["ml_away"]
            fav_team = e["home"] if fav == "home" else e["away"]
            msg = compose_flip_message(
                fav_team=fav_team,
                opener_ml=opener_ml, current_ml=current_ml,
                home=e["home"], away=e["away"],
                home_score=g2.get("home_score"),
                away_score=g2.get("away_score"),
                period=g2.get("period"),
                fav_cf_pct=fav_cf,
            )
            flip_alerts.append({
                "event_id": e["event_id"], "favorite_side": fav,
                "favorite_team": fav_team, "opener_ml": opener_ml,
                "current_ml": current_ml,
                "home_score": g2.get("home_score"),
                "away_score": g2.get("away_score"),
                "period": g2.get("period"), "message": msg,
            })

        # --- CF% threshold check (independent of flip) ---
        if (fav_cf is not None and attempts >= CF_MIN_SAMPLE_ATTEMPTS
                and not g.get("alerted")):
            prev_dir = g.get("last_cf_alert_dir")
            if fav_cf < CF_LOW_THRESHOLD and prev_dir != "below":
                g2 = state.get_game(e["event_id"]) or g
                fav_team = e["home"] if fav == "home" else e["away"]
                cf_msg = compose_cf_alert_message(
                    fav_team=fav_team, direction="below", cf_pct=fav_cf,
                    home=e["home"], away=e["away"],
                    home_score=g2.get("home_score"),
                    away_score=g2.get("away_score"),
                    period=g2.get("period"),
                )
                cf_alerts.append({"event_id": e["event_id"], "dir": "below",
                                  "cf_pct": fav_cf, "message": cf_msg,
                                  "attempts": attempts})
            elif fav_cf > CF_HIGH_THRESHOLD and prev_dir != "above":
                g2 = state.get_game(e["event_id"]) or g
                fav_team = e["home"] if fav == "home" else e["away"]
                cf_msg = compose_cf_alert_message(
                    fav_team=fav_team, direction="above", cf_pct=fav_cf,
                    home=e["home"], away=e["away"],
                    home_score=g2.get("home_score"),
                    away_score=g2.get("away_score"),
                    period=g2.get("period"),
                )
                cf_alerts.append({"event_id": e["event_id"], "dir": "above",
                                  "cf_pct": fav_cf, "message": cf_msg,
                                  "attempts": attempts})
            elif CF_LOW_THRESHOLD <= fav_cf <= CF_HIGH_THRESHOLD and prev_dir is not None:
                # Game normalized — reset so next swing can re-alert
                state.reset_cf_alert_dir(e["event_id"])

    # ---- 10. Send flip alerts (one per game max) ----
    for a in flip_alerts:
        sms_ok = send_flip_alert(phone, a["message"])
        state.mark_alerted(a["event_id"])
        state.log_flip(
            event_id=a["event_id"], favorite_side=a["favorite_side"],
            favorite_team=a["favorite_team"], opening_ml=a["opener_ml"],
            current_ml=a["current_ml"], home_score=a["home_score"],
            away_score=a["away_score"], period=a["period"],
            message=a["message"], sms_sent=sms_ok,
        )
        log(f"  FLIP ALERT SENT (sms={sms_ok}): {a['message']}")

    # ---- 11. Send CF% threshold alerts ----
    for a in cf_alerts:
        sms_ok = send_flip_alert(phone, a["message"])
        corsi = corsi_by_event.get(a["event_id"])
        if corsi:
            state.update_cf(a["event_id"], corsi["home_cf_pct"],
                            corsi["away_cf_pct"], corsi["total"],
                            alert_dir=a["dir"])
        log(f"  CF ALERT SENT (sms={sms_ok}): {a['message']}")

    # ---- 12. Watch command updates ----
    watches = state.get_active_watches()
    for w in watches:
        # deactivate if game is over
        g_current = state.get_game(w["event_id"])
        if g_current and g_current.get("final"):
            state.deactivate_watches_for_event(w["event_id"])
            continue
        corsi = corsi_by_event.get(w["event_id"])
        if not corsi:
            continue
        team_abbrev = w["team_abbrev"]
        team_is_home = (team_abbrev == corsi["home_abbrev"])
        opp_abbrev = corsi["away_abbrev"] if team_is_home else corsi["home_abbrev"]
        cf_pct = corsi["home_cf_pct"] if team_is_home else corsi["away_cf_pct"]
        msg = compose_watch_status(
            team_abbrev=team_abbrev, opp_abbrev=opp_abbrev,
            cf_pct=cf_pct,
            home_score=g_current.get("home_score"),
            away_score=g_current.get("away_score"),
            period=g_current.get("period"),
            team_is_home=team_is_home,
        )
        sms_ok = send_flip_alert(phone, msg)
        state.mark_watch_sent(w["watch_id"])
        log(f"  WATCH STATUS SENT (sms={sms_ok}): {msg}")

    log_event(
        "odds_alerter",
        message=f"flip={len(flip_alerts)} cf={len(cf_alerts)} watch={len(watches)}",
        detail=f"used={state.get_api_usage()}/{MONTHLY_API_BUDGET}, "
               f"live={len(pollable_live)}, openers={len(need_opener)}",
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Run the cycle but don't make /odds calls or send SMS")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    try:
        run(dry_run=args.dry_run, verbose=not args.quiet)
    except Exception as exc:
        import traceback
        log_event("odds_alerter", status="error",
                  message=str(exc), detail=traceback.format_exc())
        raise
