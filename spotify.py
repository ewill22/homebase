from db import get_connection
from spotify_auth import get_spotify
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict, Counter

ARTIST_COLORS = ["#f0c014", "#e8a0b0", "#88a8d4", "#7ec89b", "#c89b6a"]
OTHER_COLOR   = "#3a3a3a"

def _last_friday():
    """Return the most recent Friday (today if it is Friday)."""
    from datetime import date
    today = date.today()
    days_since = (today.weekday() - 4) % 7  # 0 if today is Friday
    return today - timedelta(days=days_since)

def get_weekly_listens():
    """Return structured weekly listening data from the DB."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT played_at, artist_name, artist_id
        FROM spotify_plays
        WHERE played_at >= NOW() - INTERVAL 7 DAY
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
    artist_ids   = {}
    for row in rows:
        day_artist[row["played_at"].date()][row["artist_name"]] += 1
        artist_total[row["artist_name"]] += 1
        if row.get("artist_id"):
            artist_ids[row["artist_name"]] = row["artist_id"]

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
        "artist_ids":      artist_ids,
        "daily":           daily,
        "today_extra":     today_extra,
        "weekly_estimate": weekly_estimate,
    }


def get_new_releases():
    """Return new albums/singles (since last Friday) from artists in listening history."""
    cutoff = _last_friday()

    # Get top artist IDs from recent listening history (last 60 days)
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT artist_id, artist_name, COUNT(*) AS plays
        FROM spotify_plays
        WHERE played_at >= NOW() - INTERVAL 60 DAY
          AND artist_id IS NOT NULL
        GROUP BY artist_id, artist_name
        ORDER BY plays DESC
        LIMIT 30
    """)
    artists = cursor.fetchall()
    cursor.close()
    conn.close()

    sp       = get_spotify()
    releases = []
    seen_ids = set()

    for artist in artists:
        try:
            result = sp.artist_albums(
                artist["artist_id"],
                album_type="album,single",
                limit=5
            )
            for album in result.get("items", []):
                if album["id"] in seen_ids:
                    continue
                rel_date = album.get("release_date", "")
                # release_date can be YYYY, YYYY-MM, or YYYY-MM-DD
                if len(rel_date) < 10:
                    continue
                if rel_date >= cutoff.isoformat():
                    seen_ids.add(album["id"])
                    releases.append({
                        "artist":    artist["artist_name"],
                        "album":     album["name"],
                        "type":      album["album_type"],   # album / single / ep
                        "date":      rel_date,
                        "url":       album["external_urls"].get("spotify", ""),
                        "image_url": album["images"][1]["url"] if len(album["images"]) > 1 else "",
                    })
        except Exception:
            continue

    releases.sort(key=lambda r: r["date"], reverse=True)
    return releases


def get_top_artist_new_releases(exclude_ids=None, limit=10):
    """Return new releases (since last Friday) from Spotify's all-time top artists."""
    cutoff     = _last_friday().isoformat()
    exclude    = exclude_ids or set()
    sp         = get_spotify()

    top = sp.current_user_top_artists(time_range="long_term", limit=50)
    artists = top.get("items", [])

    releases = []
    seen_ids = set(exclude)

    for artist in artists:
        try:
            result = sp.artist_albums(artist["id"], album_type="album,single", limit=5)
            for album in result.get("items", []):
                if album["id"] in seen_ids:
                    continue
                rel_date = album.get("release_date", "")
                if len(rel_date) < 10 or rel_date < cutoff:
                    continue
                seen_ids.add(album["id"])
                releases.append({
                    "artist":    artist["name"],
                    "album":     album["name"],
                    "type":      album["album_type"],
                    "date":      rel_date,
                    "url":       album["external_urls"].get("spotify", ""),
                    "image_url": album["images"][1]["url"] if len(album["images"]) > 1 else "",
                })
        except Exception:
            continue
        if len(releases) >= limit:
            break

    releases.sort(key=lambda r: r["date"], reverse=True)
    return releases


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
