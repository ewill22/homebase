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
from spotify import get_weekly_listens
from datetime import datetime, timezone
from dotenv import load_dotenv
import os

load_dotenv()
MY_EMAIL = os.getenv("EMAIL_ADDRESS")
TRUSTED_SENDERS = ["ewill22@gmail.com"]

COMMANDS = {
    "how are things at home": "cmd_home_summary",
    "hows it going at home": "cmd_home_summary",
    "whats up at home": "cmd_home_summary",
}

def cmd_home_summary():
    fetch_and_store()
    cities = fetch_all()
    from zoneinfo import ZoneInfo
    from datetime import date, timedelta
    import random
    tz = ZoneInfo("America/New_York")
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
        listening = get_weekly_listens()
    except Exception:
        listening = None
    all_devils = get_devils_games(days=14)
    devils = [
        e for e in all_devils
        if datetime.fromisoformat(
            e["start"].get("dateTime", e["start"].get("date")).replace("Z", "+00:00")
        ).astimezone(ZoneInfo("America/New_York")).date() == today
    ]

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

    def event_rows(items):
        if not items:
            return '<tr><td colspan="2" style="color:#aeaeb2;font-size:14px;padding:6px 0;">Nothing on the books.</td></tr>'
        rows = ""
        for e in items:
            raw = e["start"].get("dateTime", e["start"].get("date"))
            is_timed = "dateTime" in e["start"]
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            time_str = dt.strftime('%I:%M %p').lstrip('0') if is_timed else "All day"
            rows += (
                '<tr>'
                f'<td style="color:#6e6e73;font-size:14px;padding:7px 20px 7px 0;white-space:nowrap;font-weight:500;">{dt.strftime("%a %b %d")}</td>'
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
            '<p style="font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#aeaeb2;margin:0 0 16px;">Devils</p>'
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
        artists_for_legend = list(listening["top_artists"])
        if any(d["other"] > 0 for d in daily):
            other_total = sum(d["other"] for d in daily)
            artists_for_legend.append(("Other", other_total))

        for j, (name, count) in enumerate(artists_for_legend):
            color = ARTIST_COLORS[j] if j < len(ARTIST_COLORS) else "#9ca3af"
            is_last = (j == len(artists_for_legend) - 1)
            border = "" if is_last else "border-bottom:1px solid #1f1f1f;"
            legend_rows += (
                f'<tr>'
                f'<td style="padding:8px 16px;{border}width:16px;">'
                f'<div style="width:10px;height:10px;border-radius:2px;background:{color};"></div>'
                f'</td>'
                f'<td style="padding:8px 0;{border}font-size:13px;color:#9ca3af;">{safe(name)}</td>'
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

    from datetime import date as date_type
    birthday = date_type(1991, 5, 11)
    day_of_life = (today - birthday).days + 1

    LOGO_URL = "https://ewill22.github.io/guapa-site/assets/guapa_logo_dark.png"
    date_str = datetime.now(ZoneInfo("America/New_York")).strftime('%A, %B %d')
    html = (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,\'Helvetica Neue\',Helvetica,Arial,sans-serif;max-width:540px;margin:0 auto;">'
        # — Guapa nav strip —
        '<div style="background:#0a0a0a;border-bottom:1px solid #1f1f1f;padding:11px 40px;">'
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
        '<div style="background:#ffffff;padding:40px 40px 48px;">'
        f'<p style="font-size:24px;font-weight:600;color:#1d1d1f;margin:0 0 4px;letter-spacing:-0.3px;">{safe(greeting)}</p>'
        f'<p style="font-size:15px;color:#6e6e73;margin:0 0 6px;">{date_str}</p>'
        f'<p style="font-size:12px;color:#aeaeb2;margin:0 0 40px;">Day {day_of_life:,} of your life</p>'
        '<p style="font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#aeaeb2;margin:0 0 16px;">Weather</p>'
        f'<table style="width:100%;border-collapse:collapse;margin-bottom:40px;">{city_rows}</table>'
        + ('<hr style="border:none;border-top:1px solid #f2f2f7;margin:0 0 32px;">'
           '<p style="font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#aeaeb2;margin:0 0 16px;">Workdays</p>'
           f'<table style="width:100%;border-collapse:collapse;margin-bottom:40px;">{event_rows(workday_events)}</table>'
           if workday_events else '')
        + ('<hr style="border:none;border-top:1px solid #f2f2f7;margin:0 0 32px;">'
           '<p style="font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#aeaeb2;margin:0 0 16px;">Weekend</p>'
           f'<table style="width:100%;border-collapse:collapse;margin-bottom:40px;">{event_rows(weekend_events)}</table>'
           if weekend_events else '')
        + f'{devils_section}'
        + listening_section
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
    plain += "WEATHER\n"
    for c in cities:
        plain += f"  {c['name']}: {c['temp']}{c['unit']}, {c['humidity']}% humidity, {c['wind']} {c['wind_unit']}\n"
    plain += "\n"
    if workday_events:
        plain += f"WORKDAYS\n{plain_rows(workday_events)}\n"
    if weekend_events:
        plain += f"WEEKEND\n{plain_rows(weekend_events)}\n"
    if devils:
        plain += f"DEVILS\n{plain_rows(devils)}\n"
    if listening and listening["total"] > 0:
        plain += f"LISTENING ({listening['total']} plays this week)\n"
        for artist, count in listening["top_artists"]:
            plain += f"  {count}x  {artist}\n"

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
                now = datetime.now(ZoneInfo("America/New_York"))
                subject = "homebase | " + now.strftime("%a %b %d, %I:%M %p")
                send_email(
                    subject=subject,
                    body=response,
                    to=reply_to
                )
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

if __name__ == "__main__":
    check_and_respond()
