"""
spotify_tracker.py — poll recently played tracks and upsert into spotify_plays.
Run on a schedule (every 5 min) to build a complete listening history.
"""
from spotify_auth import get_spotify
from db import get_connection
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

def sync_recent_plays():
    sp = get_spotify()
    conn = get_connection()
    cursor = conn.cursor()

    results = sp.current_user_recently_played(limit=50)
    items = results.get("items", [])

    new_count = 0
    for item in items:
        track   = item["track"]
        album   = track["album"]
        artists = track["artists"]
        context = item.get("context")

        played_at = datetime.fromisoformat(
            item["played_at"].replace("Z", "+00:00")
        ).astimezone(ET).replace(tzinfo=None)  # store as ET naive

        primary_artist  = artists[0] if artists else {}
        extra_artists   = ", ".join(a["name"] for a in artists[1:]) or None

        cursor.execute("""
            INSERT IGNORE INTO spotify_plays (
                played_at, track_id, track_name, duration_ms, explicit,
                popularity, track_number, disc_number, track_uri,
                artist_id, artist_name, extra_artists,
                album_id, album_name, album_type, album_release, album_tracks, album_uri,
                context_type, context_uri
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s
            )
        """, (
            played_at,
            track.get("id"),
            track.get("name"),
            track.get("duration_ms"),
            int(track.get("explicit", False)),
            track.get("popularity"),
            track.get("track_number"),
            track.get("disc_number"),
            track.get("uri"),
            primary_artist.get("id"),
            primary_artist.get("name"),
            extra_artists,
            album.get("id"),
            album.get("name"),
            album.get("album_type"),
            album.get("release_date"),
            album.get("total_tracks"),
            album.get("uri"),
            context.get("type") if context else None,
            context.get("uri")  if context else None,
        ))
        if cursor.rowcount == 1:
            new_count += 1

    conn.commit()
    cursor.close()
    conn.close()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] synced — {new_count} new plays, {len(items) - new_count} already stored")

if __name__ == "__main__":
    sync_recent_plays()
