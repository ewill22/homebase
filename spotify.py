from db import get_connection
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict, Counter

ARTIST_COLORS = ["#f0c014", "#e8a0b0", "#88a8d4", "#7ec89b", "#c89b6a"]
OTHER_COLOR   = "#3a3a3a"

def get_weekly_listens():
    """Return structured weekly listening data from the DB."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT played_at, artist_name
        FROM spotify_plays
        WHERE played_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY
        ORDER BY played_at
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    tz    = ZoneInfo("America/New_York")
    now   = datetime.now(tz)
    today = now.date()
    days  = [(today - timedelta(days=6 - i)) for i in range(7)]

    # Group by (ET date, artist)
    day_artist   = defaultdict(lambda: defaultdict(int))
    artist_total = Counter()
    for row in rows:
        played_et = row["played_at"].replace(tzinfo=timezone.utc).astimezone(tz)
        day_artist[played_et.date()][row["artist_name"]] += 1
        artist_total[row["artist_name"]] += 1

    top_artists = artist_total.most_common(5)
    top_names   = [a[0] for a in top_artists]

    daily = []
    for d in days:
        counts = day_artist.get(d, {})
        daily.append({
            "date":  d,
            "top":   {a: counts.get(a, 0) for a in top_names},
            "other": sum(v for k, v in counts.items() if k not in top_names),
            "total": sum(counts.values()),
        })

    # Today's pace estimate (only meaningful if day is < 80% over)
    hour_frac     = now.hour + now.minute / 60
    today_actual  = daily[-1]["total"]
    if 1 <= hour_frac <= 19.2:  # at least 1h elapsed, less than 80% through day
        today_estimate = round(today_actual * 24 / hour_frac)
    else:
        today_estimate = today_actual
    today_extra = max(0, today_estimate - today_actual)

    weekly_estimate = sum(d["total"] for d in daily[:-1]) + today_estimate

    return {
        "total":           len(rows),
        "top_artists":     top_artists,
        "daily":           daily,
        "today_extra":     today_extra,
        "weekly_estimate": weekly_estimate,
    }


def get_monthly_recap():
    """Return last month's listening stats + YTD counts."""
    from datetime import date
    tz    = ZoneInfo("America/New_York")
    today = datetime.now(tz).date()

    # Last month bounds
    first_of_this_month = today.replace(day=1)
    last_month_end      = first_of_this_month - timedelta(days=1)
    last_month_start    = last_month_end.replace(day=1)

    # YTD bounds
    ytd_start = date(today.year, 1, 1)

    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Last month: per-artist and per-track counts
    cursor.execute("""
        SELECT artist_name, track_name,
               COUNT(*) AS plays
        FROM spotify_plays
        WHERE played_at >= %s AND played_at < %s
        GROUP BY artist_name, track_name
        ORDER BY plays DESC
    """, (last_month_start, first_of_this_month))
    month_rows = cursor.fetchall()

    # YTD: per-artist totals
    cursor.execute("""
        SELECT artist_name, COUNT(*) AS plays
        FROM spotify_plays
        WHERE played_at >= %s AND played_at < %s
        GROUP BY artist_name
        ORDER BY plays DESC
    """, (ytd_start, first_of_this_month))
    ytd_rows = cursor.fetchall()

    cursor.close()
    conn.close()

    # Aggregate
    artist_month  = Counter()
    track_month   = Counter()
    for r in month_rows:
        artist_month[r["artist_name"]] += r["plays"]
        track_month[f"{r['track_name']} \u2014 {r['artist_name']}"] += r["plays"]

    ytd_by_artist = {r["artist_name"]: r["plays"] for r in ytd_rows}
    ytd_total     = sum(ytd_by_artist.values())

    top_artists = artist_month.most_common(5)
    top_tracks  = track_month.most_common(5)

    return {
        "month_name":   last_month_end.strftime("%B %Y"),
        "month_total":  sum(artist_month.values()),
        "ytd_total":    ytd_total,
        "ytd_year":     today.year,
        "top_artists":  [(name, count, ytd_by_artist.get(name, 0)) for name, count in top_artists],
        "top_tracks":   top_tracks,
    }


if __name__ == "__main__":
    data = get_weekly_listens()
    print(f"Total plays (last 7 days): {data['total']}")
    print(f"Weekly estimate: ~{data['weekly_estimate']}")
    print("\nTop artists:")
    for artist, count in data["top_artists"]:
        print(f"  {count}x  {artist}")
    print("\nDaily breakdown:")
    for d in data["daily"]:
        bar = "#" * d["total"]
        print(f"  {d['date'].strftime('%a %b %d')}  {d['total']:>3}  {bar}")
