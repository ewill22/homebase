"""
Command listener — run on a schedule to check for emailed commands.
Checks inbox for unread emails from yourself, acts on them, replies.
"""
import email
import email.utils
import email.header
import unicodedata
from gmail import get_imap
from emailer import send_email
from weather import fetch_and_store, fetch_all
from gcal import get_upcoming_events, get_devils_games
from spotify import get_weekly_listens, get_monthly_recap
from strain_checker import get_all_strain_hits, TRACKED_STRAINS
from steps import get_steps_yesterday, get_daily_target, MONTHLY_GOAL as STEPS_MONTHLY_GOAL
from guapa_music import get_music_summary
from datetime import datetime, timezone
from dotenv import load_dotenv
import os

load_dotenv()
MY_EMAIL = os.getenv("EMAIL_ADDRESS")

from config import get_config as _get_config
TRUSTED_SENDERS = _get_config()["trusted_senders"]

COMMANDS = {
    "how are things at home": "cmd_home_summary",
    "hows it going at home": "cmd_home_summary",
    "whats up at home": "cmd_home_summary",
}

def cmd_home_summary(user_id=1):
    from config import get_config
    cfg  = get_config(user_id)
    user = cfg["user"]

    try:
        fetch_and_store(user_id)
        cities = fetch_all(user_id)
    except Exception:
        cities = []
    from zoneinfo import ZoneInfo
    from datetime import date, timedelta
    import random
    tz = ZoneInfo(user["timezone"])
    now_local = datetime.now(tz)
    hour = now_local.hour
    today = now_local.date()

    # Determine weekend dates: Sat + Sun of the upcoming weekend
    days_until_sat = (5 - today.weekday()) % 7 or 7
    sat = today + timedelta(days=days_until_sat)
    sun = sat + timedelta(days=1)
    weekend_dates = {sat, sun}

    # Check all upcoming events for day-off on a weekday — include that day in weekend
    all_events_raw = get_upcoming_events(days=7)
    day_off_keywords = ("day off", "off", "holiday", "vacation", "pto")
    for e in all_events_raw:
        if "date" in e["start"] and "dateTime" not in e["start"]:
            edate = date.fromisoformat(e["start"]["date"])
            if edate.weekday() < 5 and any(w in e.get("summary", "").lower() for w in day_off_keywords):
                weekend_dates.add(edate)

    # Split timed events into workday vs weekend buckets
    def keep(e):
        return "dateTime" in e["start"] or any(w in e.get("summary", "").lower() for w in ("birthday", "bday"))

    workday_events = []
    weekend_events = []
    for e in all_events_raw:
        if not keep(e):
            continue
        raw = e["start"].get("dateTime", e["start"].get("date"))
        edate = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(tz).date()
        if edate in weekend_dates or edate.weekday() >= 5:
            weekend_events.append(e)
        else:
            workday_events.append(e)
    fortunes = [
        "A smooth sea never made a skilled sailor",
        "The best time to start was yesterday — the second best is now",
        "Doors open for those who forget to knock",
        "You already have what you're looking for",
        "Small moves, quietly, still count",
        "The one who adapts wins without fighting",
        "Rest is not the enemy of progress",
        "Not all who wander are lost — some are just between exits",
        "What you water grows",
        "The answer is usually simpler than the question",
    ]

    if hour < 12:
        small_talk = [
            "Good morning, hope the coffee kicks in soon",
            "Good morning, big day or easy day — either way you got it",
            "Good morning, the world's still warming up too",
            "Good morning, Northfield's quiet out there",
            "Good morning, let's see what today's about",
        ]
    elif hour < 17:
        small_talk = [
            "Good afternoon, you're already halfway through it",
            "Good afternoon, hope the morning treated you well",
            "Good afternoon, still plenty of day left",
            "Good afternoon, hope lunch was worth it",
            "Good afternoon, the day's in full swing",
        ]
    else:
        small_talk = [
            "Good evening, hope the day was good to you",
            "Good evening, almost time to decompress",
            "Good evening, you made it through another one",
            "Good evening, the hard part's done",
            "Good evening, Northfield's winding down",
        ]

    # 40% chance of a fortune, otherwise small talk
    greeting = random.choice(fortunes if random.random() < 0.4 else small_talk)
    today = datetime.now(ZoneInfo("America/New_York")).date()
    try:
        steps_yesterday = get_steps_yesterday()
        steps_target    = get_daily_target()
    except Exception:
        steps_yesterday = None
        steps_target    = None
    try:
        music_summary = get_music_summary()
    except Exception:
        music_summary = None
    try:
        listening = get_weekly_listens()
    except Exception:
        listening = None
    try:
        monthly = get_monthly_recap() if today.day == 1 else None
    except Exception:
        monthly = None
    import concurrent.futures
    strain_hits = None
    tracked_found = []
    try:
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(get_all_strain_hits)
            strain_hits, tracked_found = future.result(timeout=60)
    except Exception:
        pass
    all_devils = get_devils_games(days=14)
    from datetime import timedelta
    tomorrow = today + timedelta(days=1)
    devils_today = [
        e for e in all_devils
        if datetime.fromisoformat(
            e["start"].get("dateTime", e["start"].get("date")).replace("Z", "+00:00")
        ).astimezone(ZoneInfo("America/New_York")).date() == today
    ]
    devils_tomorrow = [
        e for e in all_devils
        if datetime.fromisoformat(
            e["start"].get("dateTime", e["start"].get("date")).replace("Z", "+00:00")
        ).astimezone(ZoneInfo("America/New_York")).date() == tomorrow
    ]
    devils = devils_today or devils_tomorrow
    devils_label = "Devils &mdash; Tonight" if devils_today else "Devils &mdash; Tomorrow"

    # — HTML version —
    import html as html_lib

    def safe(text):
        """Escape all special and non-ASCII chars as HTML entities."""
        import unicodedata
        text = unicodedata.normalize("NFKC", str(text))
        text = html_lib.escape(text)
        return text.encode("ascii", "xmlcharrefreplace").decode("ascii")

    CONDITION_ICON = {
        "Sunny":         "&#9728;",   # ☀
        "Partly Cloudy": "&#9925;",   # ⛅
        "Cloudy":        "&#9729;",   # ☁
        "Rain":          "&#127783;", # 🌧
        "Snow":          "&#10052;",  # ❄
        "Storm":         "&#9928;",   # ⛈
        "Foggy":         "&#127787;", # 🌫
        "Mixed":         "&#127780;", # 🌤
    }

    def deg(val, unit):
        """Format a temperature value with HTML degree entity."""
        return f"{val}&deg;{unit.replace('°', '')}"

    GCAL_COLORS = {
        "1": "#a4bdfc", "2": "#7ae7bf", "3": "#dbadff", "4": "#ff887c",
        "5": "#fbd75b", "6": "#ffb878", "7": "#46d6db", "8": "#e1e1e1",
        "9": "#5484ed", "10": "#51b749", "11": "#dc2127",
    }

    def event_rows(items):
        if not items:
            return '<tr><td colspan="3" style="color:#aeaeb2;font-size:14px;padding:6px 0;">Nothing on the books.</td></tr>'
        rows = ""
        for e in items:
            raw = e["start"].get("dateTime", e["start"].get("date"))
            is_timed = "dateTime" in e["start"]
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            time_str = dt.strftime('%I:%M %p').lstrip('0') if is_timed else "All day"
            color = GCAL_COLORS.get(e.get("colorId", ""), "#d1d1d6")
            dot = f'<td style="padding:7px 10px;vertical-align:middle;width:8px;"><div style="width:8px;height:8px;border-radius:2px;background:{color};"></div></td>'
            rows += (
                f'<tr>'
                f'<td style="color:#6e6e73;font-size:14px;padding:7px 0 7px 0;white-space:nowrap;font-weight:500;">{dt.strftime("%a %b %d")}</td>'
                f'{dot}'
                f'<td style="font-size:14px;color:#1d1d1f;padding:7px 0;">{safe(e["summary"])} <span style="color:#aeaeb2;font-size:13px;">{time_str}</span></td>'
                '</tr>'
            )
        return rows

    city_rows = ""
    for c in cities:
        feels_val = c["feels_f"] if c.get("feels_f") is not None else c["feels"]
        feels_unit = "F" if c.get("feels_f") is not None else c["unit"].replace("°", "")
        icon = CONDITION_ICON.get(c["condition"], "&#9729;")
        city_rows += (
            '<tr>'
            f'<td style="padding:8px 20px 8px 0;vertical-align:top;width:40%;">'
            f'<p style="font-size:13px;font-weight:600;color:#1d1d1f;margin:0 0 2px;">{safe(c["name"])}</p>'
            f'<p style="font-size:24px;font-weight:600;color:#1d1d1f;margin:0;letter-spacing:-0.5px;">{deg(c["temp"], c["unit"])}</p>'
            + (f'<p style="font-size:13px;color:#aeaeb2;margin:2px 0 0;">{deg(c["temp_f"], "F")}</p>' if c.get("temp_f") is not None else "")
            + '</td>'
            f'<td style="padding:8px 0;vertical-align:top;">'
            f'<p style="font-size:13px;color:#6e6e73;margin:0 0 3px;">Feels like {deg(feels_val, feels_unit)}</p>'
            f'<p style="font-size:13px;color:#6e6e73;margin:0 0 3px;">{c["humidity"]}% humidity</p>'
            f'<p style="font-size:13px;color:#6e6e73;margin:0;">{c["wind"]} {c["wind_unit"]}</p>'
            '</td>'
            f'<td style="padding:8px 0 8px 16px;vertical-align:middle;text-align:right;font-size:28px;">{icon}</td>'
            '</tr>'
        )

    devils_section = ""
    if devils:
        devils_section = (
            '<hr style="border:none;border-top:1px solid #f2f2f7;margin:0 0 32px;">'
            f'<p style="font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#aeaeb2;margin:0 0 16px;">{devils_label}</p>'
            f'<table style="width:100%;border-collapse:collapse;">{event_rows(devils)}</table>'
        )

    listening_section = ""
    if listening and listening["total"] > 0:
        from spotify import ARTIST_COLORS, OTHER_COLOR
        top_names   = [a[0] for a in listening["top_artists"]]
        daily       = listening["daily"]
        today_extra = listening["today_extra"]
        MAX_H       = 100

        max_plays = max(
            (d["total"] + (today_extra if i == 6 else 0))
            for i, d in enumerate(daily)
        ) or 1

        def scale(n):
            return round(n * MAX_H / max_plays)

        cols = ""
        for i, d in enumerate(daily):
            is_today  = (i == 6)
            total     = d["total"]
            est_h     = scale(today_extra) if is_today and today_extra > 0 else 0

            # Build segments bottom-up (last in list = bottom of bar)
            segments = []
            if d["other"] > 0:
                segments.append(f'<div style="background:{OTHER_COLOR};height:{scale(d["other"])}px;"></div>')
            for j in range(len(top_names) - 1, -1, -1):
                cnt = d["top"].get(top_names[j], 0)
                if cnt > 0:
                    segments.append(f'<div style="background:{ARTIST_COLORS[j]};height:{scale(cnt)}px;"></div>')

            bar_h    = scale(total)
            spacer_h = MAX_H - bar_h - est_h

            count_label = (
                f'<div style="font-size:11px;color:#9ca3af;text-align:center;margin-bottom:5px;font-weight:500;">{total}</div>'
                if total > 0 else
                '<div style="height:20px;"></div>'
            )
            est_div = (
                f'<div style="border:1px dashed #3a3a3a;height:{est_h}px;box-sizing:border-box;border-radius:3px 3px 0 0;"></div>'
                if est_h > 0 else ""
            )
            spacer_div = f'<div style="height:{spacer_h}px;"></div>' if spacer_h > 0 else ""

            # Rounded top on the bar column (clips topmost segment)
            bar_radius = "border-radius:3px 3px 0 0;overflow:hidden;" if total > 0 else ""

            day_name    = d["date"].strftime("%a")
            day_num     = str(d["date"].day)
            label_color = "#f0c014" if is_today else "#6b7280"

            cols += (
                f'<td style="text-align:center;vertical-align:top;padding:0 3px;">'
                f'{count_label}'
                f'<div style="height:{MAX_H}px;">'
                f'{spacer_div}{est_div}'
                f'<div style="{bar_radius}">{"".join(segments)}</div>'
                f'</div>'
                f'<div style="font-size:11px;color:{label_color};margin-top:7px;font-weight:{"600" if is_today else "400"};">{day_name}</div>'
                f'<div style="font-size:10px;color:{label_color};margin-top:1px;opacity:0.7;">{day_num}</div>'
                f'</td>'
            )

        legend_rows = ""
        artist_ids  = listening.get("artist_ids", {})
        artists_for_legend = list(listening["top_artists"])
        if any(d["other"] > 0 for d in daily):
            other_total = sum(d["other"] for d in daily)
            artists_for_legend.append(("Other", other_total))

        for j, (name, count) in enumerate(artists_for_legend):
            color = ARTIST_COLORS[j] if j < len(ARTIST_COLORS) else "#9ca3af"
            is_last = (j == len(artists_for_legend) - 1)
            border = "" if is_last else "border-bottom:1px solid #1f1f1f;"
            aid = artist_ids.get(name)
            name_html = (
                f'<a href="https://open.spotify.com/artist/{aid}" style="color:#9ca3af;text-decoration:none;">{safe(name)}</a>'
                if aid else safe(name)
            )
            legend_rows += (
                f'<tr>'
                f'<td style="padding:8px 16px;{border}width:16px;">'
                f'<div style="width:10px;height:10px;border-radius:2px;background:{color};"></div>'
                f'</td>'
                f'<td style="padding:8px 0;{border}font-size:13px;color:#9ca3af;">{name_html}</td>'
                f'<td style="padding:8px 16px;{border}text-align:right;font-size:13px;color:#6b7280;font-weight:500;">{count}</td>'
                f'</tr>'
            )

        est_note = f' &middot; ~{listening["weekly_estimate"]} on pace' if today_extra > 0 else ""

        chart = (
            f'<div style="background:#111111;border-radius:8px;overflow:hidden;">'
            f'<div style="padding:20px 16px 16px;">'
            f'<table style="width:100%;border-collapse:collapse;"><tr>{cols}</tr></table>'
            f'</div>'
            f'<div style="border-top:1px solid #1f1f1f;">'
            f'<table style="width:100%;border-collapse:collapse;">{legend_rows}</table>'
            f'</div>'
            f'</div>'
        )

        listening_section = (
            '<hr style="border:none;border-top:1px solid #f2f2f7;margin:0 0 32px;">'
            '<p style="font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#aeaeb2;margin:0 0 4px;">Listening</p>'
            f'<p style="font-size:13px;color:#6e6e73;margin:0 0 16px;">{listening["total"]} plays this week{est_note}</p>'
            f'{chart}'
            '<div style="margin-bottom:40px;"></div>'
        )

    # — Monthly recap section (only on the 1st) —
    monthly_section = ""
    if monthly and monthly["month_total"] > 0:
        max_month = monthly["top_artists"][0][1] if monthly["top_artists"] else 1

        artist_rows = ""
        for j, (name, month_count, ytd_count) in enumerate(monthly["top_artists"]):
            color   = ARTIST_COLORS[j] if listening else "#f0c014"
            bar_pct = round(month_count / max_month * 100)
            artist_rows += (
                f'<tr>'
                f'<td style="padding:7px 14px 7px 16px;font-size:13px;color:#9ca3af;white-space:nowrap;width:1%;">'
                f'<div style="width:10px;height:10px;border-radius:2px;background:{color};display:inline-block;vertical-align:middle;margin-right:6px;"></div>'
                f'{safe(name)}</td>'
                f'<td style="padding:7px 12px 7px 0;">'
                f'<div style="background:#1f1f1f;border-radius:3px;height:6px;width:100%;">'
                f'<div style="background:{color};border-radius:3px;height:6px;width:{bar_pct}%;"></div>'
                f'</div></td>'
                f'<td style="padding:7px 16px 7px 8px;font-size:13px;color:#9ca3af;text-align:right;white-space:nowrap;font-weight:500;">{month_count}</td>'
                f'<td style="padding:7px 16px 7px 0;font-size:11px;color:#6b7280;text-align:right;white-space:nowrap;">{ytd_count} YTD</td>'
                f'</tr>'
            )

        track_rows = ""
        for i, (label, count) in enumerate(monthly["top_tracks"]):
            is_last  = (i == len(monthly["top_tracks"]) - 1)
            border   = "" if is_last else "border-bottom:1px solid #1f1f1f;"
            track_rows += (
                f'<tr>'
                f'<td style="padding:7px 16px;{border}font-size:13px;color:#9ca3af;">{safe(label)}</td>'
                f'<td style="padding:7px 16px 7px 0;{border}font-size:13px;color:#6b7280;text-align:right;font-weight:500;">{count}</td>'
                f'</tr>'
            )

        monthly_section = (
            '<hr style="border:none;border-top:1px solid #f2f2f7;margin:0 0 32px;">'
            '<p style="font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#aeaeb2;margin:0 0 4px;">Monthly Recap</p>'
            f'<p style="font-size:13px;color:#6e6e73;margin:0 0 16px;">'
            f'{monthly["month_total"]} plays in {monthly["month_name"]}'
            f' &middot; {monthly["ytd_total"]} plays {monthly["ytd_year"]} YTD</p>'
            f'<div style="background:#111111;border-radius:8px;overflow:hidden;margin-bottom:40px;">'
            f'<div style="padding:4px 0;">'
            f'<table style="width:100%;border-collapse:collapse;">{artist_rows}</table>'
            f'</div>'
            f'<div style="border-top:1px solid #1f1f1f;padding:8px 0 4px;">'
            f'<p style="font-size:10px;font-weight:600;letter-spacing:0.8px;text-transform:uppercase;color:#6b7280;margin:4px 16px 8px;">Top Tracks</p>'
            f'<table style="width:100%;border-collapse:collapse;">{track_rows}</table>'
            f'</div>'
            f'</div>'
        )

    # — Steps section —
    steps_section = ""
    if steps_yesterday is not None and steps_target is not None:
        pct        = min(100, round(steps_yesterday / steps_target * 100)) if steps_target > 0 else 100
        beat       = steps_yesterday >= steps_target
        bar_color  = "#7ec89b" if beat else "#88a8d4"
        sub        = (
            f'{steps_yesterday:,} yesterday &middot; need {steps_target:,}/day for {STEPS_MONTHLY_GOAL:,} avg'
        )
        steps_section = (
            '<p style="font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#aeaeb2;margin:0 0 4px;">Steps</p>'
            f'<p style="font-size:13px;color:#6e6e73;margin:0 0 12px;">{sub}</p>'
            f'<div style="background:#f2f2f7;border-radius:4px;height:8px;margin-bottom:40px;">'
            f'<div style="background:{bar_color};border-radius:4px;height:8px;width:{pct}%;"></div>'
            f'</div>'
        )

    # — Strain section —
    import urllib.parse
    strain_section = ""
    if strain_hits is not None:
        if strain_hits:
            hit_rows = ""
            for m in strain_hits:
                price_str  = f'<span style="color:#6b7280;font-size:12px;margin-left:6px;">{safe(m["price"])}</span>' if m.get("price") else ""
                maps_url       = "https://maps.google.com/?q=" + urllib.parse.quote(m["dispensary"] + " NJ")
                new_batch_badge = '<span style="font-size:10px;font-weight:600;color:#f0c014;letter-spacing:0.5px;background:#1f1f1f;padding:2px 6px;border-radius:3px;margin-left:8px;">new batch</span>' if m.get("new_batch") else ""
                strain_label = f'<div style="font-size:11px;color:#6b7280;margin-bottom:2px;">{safe(m["strain_name"].title())}</div>'
                listed_today = m.get("listed_at") and hasattr(m["listed_at"], "date") and m["listed_at"].date() >= (today - timedelta(days=1))
                new_border = "border-left:3px solid #f0c014;" if listed_today else "border-left:3px solid transparent;"
                hit_rows += (
                    f'<tr>'
                    f'<td style="padding:8px 12px;border-bottom:1px solid #1f1f1f;font-size:13px;font-weight:500;{new_border}">'
                    f'<a href="{m["url"]}" style="color:#7ec89b;text-decoration:none;">{safe(m["dispensary"])}</a>'
                    f'<a href="{maps_url}" style="color:#6b7280;font-size:10px;font-weight:600;letter-spacing:0.5px;text-decoration:none;margin-left:8px;background:#1f1f1f;padding:2px 6px;border-radius:3px;">nav</a>'
                    f'{new_batch_badge}'
                    f'</td>'
                    f'<td style="padding:8px 12px;border-bottom:1px solid #1f1f1f;font-size:13px;color:#9ca3af;">'
                    f'{strain_label}{safe(m["name"])}{price_str}'
                    f'</td>'
                    f'</tr>'
                )
            found_names = ", ".join(s.title() for s in tracked_found) if tracked_found else "Crops"
            strain_section = (
                '<hr style="border:none;border-top:1px solid #f2f2f7;margin:0 0 32px;">'
                f'<p style="font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#aeaeb2;margin:0 0 4px;">In Stock</p>'
                f'<p style="font-size:13px;color:#6e6e73;margin:0 0 16px;">{safe(found_names)} spotted today</p>'
                f'<div style="background:#111111;border-radius:8px;overflow:hidden;margin-bottom:40px;">'
                f'<table style="width:100%;border-collapse:collapse;">{hit_rows}</table>'
                f'</div>'
            )
        else:
            tracked_str = ", ".join(s.title() for s in TRACKED_STRAINS)
            strain_section = (
                '<hr style="border:none;border-top:1px solid #f2f2f7;margin:0 0 32px;">'
                f'<p style="font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#aeaeb2;margin:0 0 4px;">In Stock</p>'
                f'<p style="font-size:13px;color:#aeaeb2;margin:0 0 40px;">{safe(tracked_str)} &mdash; not in stock today.</p>'
            )

    # — Guapa Music section —
    music_section = ""
    if music_summary:
        cov_colors = {"Spotify": "#f0c014", "Wikipedia": "#88a8d4", "Cover art": "#7ec89b", "Genius": "#e8a0b0", "MB tracks": "#f0a14a"}

        def cov_row(label, cov, added=0, broken=0, is_last=False):
            if not cov:
                return ""
            color  = cov_colors.get(label, "#f0c014")
            border = "" if is_last else "border-bottom:1px solid #1f1f1f;"
            deltas = ""
            if added:
                deltas += f'<span style="color:#7ec89b;font-size:11px;margin-left:6px;">+{added} today</span>'
            if broken:
                deltas += f'<span style="color:#ff887c;font-size:11px;margin-left:6px;">{broken} URL error{"s" if broken != 1 else ""}</span>'
            return (
                f'<tr><td style="padding:10px 16px;{border}">'
                f'<table style="width:100%;border-collapse:collapse;"><tr>'
                f'<td style="font-size:13px;color:#9ca3af;">{label}</td>'
                f'<td style="text-align:right;font-size:13px;color:#9ca3af;font-weight:500;white-space:nowrap;">'
                f'{cov["pct"]}% <span style="color:#6b7280;font-weight:400;font-size:11px;">{cov["have"]:,}/{cov["total"]:,}{deltas}</span>'
                f'</td></tr></table>'
                f'<div style="background:#1f1f1f;border-radius:3px;height:6px;margin-top:6px;">'
                f'<div style="background:{color};border-radius:3px;height:6px;width:{cov["pct"]}%;"></div>'
                f'</div>'
                f'</td></tr>'
            )

        # Build editorial row to include in the same container
        ed = music_summary.get("editorial")
        # Peek ahead: does track enrichment follow editorial? (for border)
        _te_peek = music_summary.get("track_enrichment") or {}
        _te_follows = bool(_te_peek.get("genius_urls") or _te_peek.get("mb_enriched"))
        ed_cov_row = ""
        if ed and ed.get("descriptions"):
            ed_desc = ed["descriptions"]
            ed_deltas = ""
            if ed.get("new_today"):
                ed_deltas += f'<span style="color:#7ec89b;font-size:11px;margin-left:6px;">+{ed["new_today"]} today</span>'
            if ed.get("needs_review"):
                ed_deltas += f'<span style="color:#f0c014;font-size:11px;margin-left:6px;">{ed["needs_review"]} needs review</span>'
            new_artist_list = ""
            for a in ed.get("artists") or []:
                new_artist_list += (
                    f'<p style="margin:4px 0 0;font-size:11px;color:#6b7280;">'
                    f'<span style="color:#7ec89b;">+</span> {safe(a["name"])} — {safe(a["description"])}</p>'
                )
            _ed_border = "border-bottom:1px solid #1f1f1f;" if _te_follows else ""
            ed_cov_row = (
                f'<tr><td style="padding:10px 16px;{_ed_border}">'
                f'<table style="width:100%;border-collapse:collapse;"><tr>'
                f'<td style="font-size:13px;color:#9ca3af;">Descriptions</td>'
                f'<td style="text-align:right;font-size:13px;color:#9ca3af;font-weight:500;white-space:nowrap;">'
                f'{ed_desc["pct"]}% <span style="color:#6b7280;font-weight:400;font-size:11px;">{ed_desc["have"]:,}/{ed_desc["total"]:,}{ed_deltas}</span>'
                f'</td></tr></table>'
                f'<div style="background:#1f1f1f;border-radius:3px;height:6px;margin-top:6px;">'
                f'<div style="background:#d97af2;border-radius:3px;height:6px;width:{ed_desc["pct"]}%;"></div>'
                f'</div>'
                + new_artist_list +
                f'</td></tr>'
            )

        # Track enrichment rows (Genius URLs + MB enriched albums)
        te = music_summary.get("track_enrichment") or {}
        te_totals = te.get("run_totals") or {}
        has_ed = bool(ed_cov_row)
        has_te = bool(te.get("genius_urls") or te.get("mb_enriched"))
        cov_rows = (
            cov_row("Spotify",   music_summary.get("spotify"),   music_summary.get("spotify_added",    0), music_summary.get("broken_spotify",   0))
            + cov_row("Wikipedia", music_summary.get("wikipedia"), music_summary.get("wikipedia_added",  0), music_summary.get("broken_wikipedia", 0))
            + cov_row("Cover art", music_summary.get("cover_art"), music_summary.get("cover_art_filled", 0), music_summary.get("broken_cover_art", 0), is_last=not (has_ed or has_te))
            + ed_cov_row
            + cov_row("Genius",    te.get("genius_urls"),  0, 0)
            + cov_row("MB tracks", te.get("mb_enriched"),  te_totals.get("albums_processed", 0), 0, is_last=True)
        )

        # Artist activity table (only artists that were processed today)
        artist_rows = ""
        for i, a in enumerate(music_summary.get("artists") or []):
            is_last = (i == len(music_summary["artists"]) - 1)
            border  = "" if is_last else "border-bottom:1px solid #1f1f1f;"
            added_str   = f'<span style="color:#7ec89b;">+{a["added"]}</span>/{a["total"]}' if a["added"] else f'0/{a["total"]}'
            no_match_str = f'<span style="color:#6b7280;">{a["no_match"]} no-match</span>' if a["no_match"] else ""
            artist_rows += (
                f'<tr><td style="padding:6px 16px;{border}font-size:12px;color:#9ca3af;">{safe(a["name"])}</td>'
                f'<td style="padding:6px 16px;{border}font-size:12px;color:#9ca3af;text-align:right;white-space:nowrap;">'
                f'{added_str}&nbsp;&nbsp;{no_match_str}</td></tr>'
            )

        artist_table = ""
        if artist_rows:
            artist_table = (
                f'<p style="font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#aeaeb2;margin:16px 0 8px;">Spotify Batch</p>'
                f'<div style="background:#111111;border-radius:8px;overflow:hidden;margin-bottom:16px;">'
                f'<table style="width:100%;border-collapse:collapse;">{artist_rows}</table>'
                f'</div>'
            )

        # Track Enrichment Batch — per-artist MB enrichment activity today
        te_artist_rows = ""
        te_artists_list = (te.get("artists") or []) if te else []
        for i, a in enumerate(te_artists_list):
            is_last = (i == len(te_artists_list) - 1)
            border  = "" if is_last else "border-bottom:1px solid #1f1f1f;"
            alb_s = "album" if a["albums"] == 1 else "albums"
            te_artist_rows += (
                f'<tr><td style="padding:6px 16px;{border}font-size:12px;color:#9ca3af;">{safe(a["name"])}</td>'
                f'<td style="padding:6px 16px;{border}font-size:12px;color:#9ca3af;text-align:right;white-space:nowrap;">'
                f'<span style="color:#f0a14a;">+{a["albums"]}</span> {alb_s} <span style="color:#6b7280;">&middot; {a["tracks"]} tracks</span>'
                f'</td></tr>'
            )

        te_artist_table = ""
        if te_artist_rows:
            # Run totals caption (covers/writers/featured today)
            caption = ""
            if te_totals:
                bits = []
                if te_totals.get("covers_found"):
                    bits.append(f'{te_totals["covers_found"]} covers')
                if te_totals.get("writers_added"):
                    bits.append(f'{te_totals["writers_added"]} writers')
                if te_totals.get("featured_added"):
                    bits.append(f'{te_totals["featured_added"]} featured')
                if bits:
                    caption = (
                        f'<p style="margin:10px 16px 10px;font-size:11px;color:#6b7280;">'
                        f'{" &middot; ".join(bits)}</p>'
                    )
            te_artist_table = (
                f'<p style="font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#aeaeb2;margin:16px 0 8px;">Track Enrichment Batch</p>'
                f'<div style="background:#111111;border-radius:8px;overflow:hidden;margin-bottom:40px;">'
                f'<table style="width:100%;border-collapse:collapse;">{te_artist_rows}</table>'
                f'{caption}'
                f'</div>'
            )
        # If spotify batch was empty but we have a TE batch, drop the bottom margin of the coverage card
        if not artist_rows and te_artist_rows:
            pass  # the coverage card's margin handles it

        _has_batch = bool(artist_table or te_artist_table)
        music_section = (
            '<hr style="border:none;border-top:1px solid #f2f2f7;margin:0 0 32px;">'
            '<p style="font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#aeaeb2;margin:0 0 16px;">Guapa Data Update</p>'
            + f'<div style="background:#111111;border-radius:8px;overflow:hidden;margin-bottom:{"16px" if _has_batch else "40px"};">'
            + f'<div style="padding:4px 0;">'
            + f'<table style="width:100%;border-collapse:collapse;">{cov_rows}</table>'
            + '</div></div>'
            + artist_table
            + te_artist_table
        )

    from datetime import date as date_type
    birthday    = date_type.fromisoformat(str(user["birthday"])) if user.get("birthday") else None
    day_of_life = (today - birthday).days + 1 if birthday else None

    # — Calendar section: dynamic header based on day of week —
    weekday = today.weekday()  # 0=Mon, 6=Sun
    cal_hr = '<hr style="border:none;border-top:1px solid #f2f2f7;margin:0 0 32px;">'
    cal_label = '<p style="font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#aeaeb2;margin:0 0 16px;">{}</p>'
    cal_table = '<table style="width:100%;border-collapse:collapse;margin-bottom:40px;">{}</table>'

    calendar_section = ""
    if weekday <= 2:  # Mon–Wed
        if workday_events:
            calendar_section += cal_hr + cal_label.format("What's up next this week") + cal_table.format(event_rows(workday_events))
        if weekend_events:
            calendar_section += cal_hr + cal_label.format("Weekend") + cal_table.format(event_rows(weekend_events))
    elif weekday <= 5:  # Thu–Sat
        if workday_events and weekday <= 4:
            this_friday = today + timedelta(days=4 - weekday)
            this_week_events = [
                e for e in workday_events
                if datetime.fromisoformat(
                    e["start"].get("dateTime", e["start"].get("date")).replace("Z", "+00:00")
                ).astimezone(tz).date() <= this_friday
            ]
            calendar_section += cal_hr + cal_label.format("What's up next this week") + cal_table.format(event_rows(this_week_events))
        if weekend_events:
            calendar_section += cal_hr + cal_label.format("What's going on this weekend") + cal_table.format(event_rows(weekend_events))
    else:  # Sun
        if workday_events:
            calendar_section += cal_hr + cal_label.format("Next week") + cal_table.format(event_rows(workday_events))

    LOGO_URL = user.get("logo_url") or "https://ewill22.github.io/guapa-site/assets/guapa_logo_dark.png"
    date_str    = datetime.now(ZoneInfo(user["timezone"])).strftime('%A, %B %d')
    day_ol_line = f'<p style="font-size:12px;color:#aeaeb2;margin:0 0 40px;">Day {day_of_life:,} of your life</p>' if day_of_life else ''
    html = (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,\'Helvetica Neue\',Helvetica,Arial,sans-serif;max-width:600px;margin:0 auto;">'
        # — Guapa nav strip —
        '<div style="background:#0a0a0a;border-bottom:1px solid #1f1f1f;padding:11px 28px;">'
        '<table style="width:100%;border-collapse:collapse;"><tr>'
        '<td style="vertical-align:middle;">'
        f'<img src="{LOGO_URL}" height="22" style="display:inline-block;vertical-align:middle;" alt="Guapa" />'
        '<span style="font-size:13px;font-weight:700;letter-spacing:0.08em;color:#ffffff;vertical-align:middle;margin-left:8px;">GUAPA</span>'
        '<span style="font-size:8px;font-weight:400;color:#6b7280;vertical-align:middle;margin-left:3px;">inc</span>'
        '</td>'
        '<td style="text-align:right;vertical-align:middle;">'
        '<span style="font-size:11px;color:#6b7280;letter-spacing:0.5px;font-weight:500;">homebase</span>'
        '</td>'
        '</tr></table>'
        '</div>'
        # — White content area —
        '<div style="background:#ffffff;padding:36px 28px 48px;">'
        f'<p style="font-size:24px;font-weight:600;color:#1d1d1f;margin:0 0 4px;letter-spacing:-0.3px;">{safe(greeting)}</p>'
        f'<p style="font-size:15px;color:#6e6e73;margin:0 0 6px;">{date_str}</p>'
        f'{day_ol_line}'
        + steps_section
        + (
            '<p style="font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#aeaeb2;margin:0 0 16px;">Weather</p>'
            f'<table style="width:100%;border-collapse:collapse;margin-bottom:40px;">{city_rows}</table>'
            if city_rows else ""
        )
        + calendar_section
        + f'{devils_section}'
        + listening_section
        + strain_section
        + monthly_section
        + music_section
        + '</div>'   # end white content
        + '</div>'   # end outer wrapper
    )

    # — plain text fallback —
    def plain_rows(items):
        if not items:
            return "  Nothing on the books.\n"
        out = ""
        for e in items:
            start = e["start"].get("dateTime", e["start"].get("date"))
            dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            out += f"  {dt.strftime('%a %b %d')}  {e['summary']}\n"
        return out

    plain = f"homebase | {now_local.strftime('%A, %B %d')}\n\n"
    if cities:
        plain += "WEATHER\n"
        for c in cities:
            plain += f"  {c['name']}: {c['temp']}{c['unit']}, {c['humidity']}% humidity, {c['wind']} {c['wind_unit']}\n"
        plain += "\n"
    if weekday <= 2:
        if workday_events:
            plain += f"WHAT'S UP NEXT THIS WEEK\n{plain_rows(workday_events)}\n"
        if weekend_events:
            plain += f"WEEKEND\n{plain_rows(weekend_events)}\n"
    elif weekday <= 5:
        if workday_events and weekday <= 4:
            this_friday = today + timedelta(days=4 - weekday)
            this_week_plain = [
                e for e in workday_events
                if datetime.fromisoformat(
                    e["start"].get("dateTime", e["start"].get("date")).replace("Z", "+00:00")
                ).astimezone(tz).date() <= this_friday
            ]
            plain += f"WHAT'S UP NEXT THIS WEEK\n{plain_rows(this_week_plain)}\n"
        if weekend_events:
            plain += f"WHAT'S GOING ON THIS WEEKEND\n{plain_rows(weekend_events)}\n"
    else:
        if workday_events:
            plain += f"NEXT WEEK\n{plain_rows(workday_events)}\n"
    if devils:
        plain += f"{'DEVILS — TONIGHT' if devils_today else 'DEVILS — TOMORROW'}\n{plain_rows(devils)}\n"
    if listening and listening["total"] > 0:
        plain += f"LISTENING ({listening['total']} plays this week)\n"
        for artist, count in listening["top_artists"]:
            plain += f"  {count}x  {artist}\n"
    if steps_yesterday is not None and steps_target is not None:
        plain += f"\nSTEPS\n  {steps_yesterday:,} yesterday  (need {steps_target:,}/day for {STEPS_MONTHLY_GOAL:,} avg)\n"
    if music_summary:
        plain += f"\nGUAPA MUSIC\n  {music_summary.get('total_changes', 0)} changes today\n"
        for label, key in [("Spotify", "spotify"), ("Wikipedia", "wikipedia"), ("Cover art", "cover_art")]:
            cov = music_summary.get(key)
            if cov:
                plain += f"  {label}: {cov['pct']}%  ({cov['have']:,}/{cov['total']:,})\n"
        te = music_summary.get("track_enrichment") or {}
        if te.get("genius_urls"):
            g = te["genius_urls"]
            plain += f"  Genius URLs: {g['pct']}%  ({g['have']:,}/{g['total']:,})\n"
        if te.get("mb_enriched"):
            mb = te["mb_enriched"]
            plain += f"  MB tracks: {mb['pct']}%  ({mb['have']:,}/{mb['total']:,})\n"
        te_totals = te.get("run_totals") or {}
        if te_totals.get("albums_processed"):
            plain += (
                f"  Track enrichment today: {te_totals['albums_processed']} albums, "
                f"{te_totals.get('tracks_enriched', 0)} tracks, "
                f"{te_totals.get('covers_found', 0)} covers, "
                f"{te_totals.get('writers_added', 0)} writers, "
                f"{te_totals.get('featured_added', 0)} featured\n"
            )
        for a in (te.get("artists") or []):
            plain += f"    {a['name']}: +{a['albums']} album{'s' if a['albums'] != 1 else ''}, {a['tracks']} tracks\n"
    if strain_hits is not None:
        plain += f"\nIN STOCK — CROPS\n"
        if strain_hits:
            for m in strain_hits:
                price = f"  {m['price']}" if m.get("price") else ""
                plain += f"  {m['strain_name'].title()} @ {m['dispensary']}{price}\n  {m['url']}\n"
        else:
            plain += "  Not in stock today.\n"
    if monthly and monthly["month_total"] > 0:
        plain += f"\nMONTHLY RECAP — {monthly['month_name']}\n"
        plain += f"  {monthly['month_total']} plays · {monthly['ytd_total']} YTD\n"
        for name, count, ytd in monthly["top_artists"]:
            plain += f"  {count}x  {name}  ({ytd} YTD)\n"

    return {"text": plain, "html": html}

def check_and_respond():
    conn = get_imap()
    conn.select("INBOX")

    # Collect unread emails from all trusted senders
    ids = []
    for sender in TRUSTED_SENDERS:
        _, data = conn.search(None, f'(UNSEEN FROM "{sender}")')
        ids += data[0].split()

    for eid in ids:
        _, msg_data = conn.fetch(eid, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        raw_subject = msg["Subject"] or ""
        decoded_parts = email.header.decode_header(raw_subject)
        subject = "".join(
            part.decode(enc or "utf-8") if isinstance(part, bytes) else part
            for part, enc in decoded_parts
        )
        # Normalize smart quotes/apostrophes to plain ASCII
        subject = unicodedata.normalize("NFKD", subject).encode("ascii", "ignore").decode().strip().lower()
        reply_to = email.utils.parseaddr(msg["From"])[1]

        # Extract plain text body
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode(errors="ignore").strip().lower()
                    break
        else:
            body = msg.get_payload(decode=True).decode(errors="ignore").strip().lower()

        # Check subject first, fall back to body
        text = subject or body

        matched = False
        for trigger, func_name in COMMANDS.items():
            if trigger in text:
                response = globals()[func_name]()
                from datetime import datetime
                from zoneinfo import ZoneInfo
                from logger import log_event
                now = datetime.now(ZoneInfo("America/New_York"))
                subject = "homebase | " + now.strftime("%a %b %d, %I:%M %p")
                send_email(
                    subject=subject,
                    body=response,
                    to=reply_to
                )
                log_event("command", message=f"{func_name} → {reply_to}", detail=trigger)
                matched = True
                break

        if not matched:
            send_email(
                subject=f"Re: {msg['Subject']}",
                body=f"Sorry, I don't know that command yet.\n\nAvailable commands:\n" +
                     "\n".join(f"  - {k}" for k in COMMANDS.keys()),
                to=reply_to
            )

        # Mark as read so we don't process it again
        conn.store(eid, "+FLAGS", "\\Seen")

    conn.logout()
    print(f"Processed {len(ids)} command(s).")

    # — Guapa editorial suggestions —
    check_guapa_suggestions()

def check_guapa_suggestions():
    """Check for unread Formspree submission emails and apply to guapa-site CSVs."""
    import subprocess
    conn = get_imap()
    conn.select("INBOX")
    _, data = conn.search(None, '(UNSEEN FROM "formspree")')
    ids = data[0].split()
    conn.logout()

    if not ids:
        return

    print(f"Found {len(ids)} unread Formspree email(s) — running apply-suggestions...")
    result = subprocess.run(
        ["python", r"C:\Users\eewil\guapa\guapa-site\guapa-site\scripts\apply-suggestions.py"],
        cwd=r"C:\Users\eewil\guapa\guapa-site\guapa-site",
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        print("apply-suggestions error:", result.stderr)

if __name__ == "__main__":
    check_and_respond()
