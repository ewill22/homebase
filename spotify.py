from db import get_connection
from collections import Counter

def get_weekly_listens():
    """Return a summary of tracks played in the last 7 days from the DB."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT track_name, artist_name, extra_artists,
               album_name, context_type, played_at
        FROM spotify_plays
        WHERE played_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY
        ORDER BY played_at DESC
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    track_counts  = Counter(f"{r['track_name']} \u2014 {r['artist_name']}" for r in rows)
    artist_counts = Counter(r["artist_name"] for r in rows)

    return {
        "total":       len(rows),
        "top_tracks":  track_counts.most_common(5),
        "top_artists": artist_counts.most_common(5),
    }


if __name__ == "__main__":
    data = get_weekly_listens()
    print(f"Total plays (last 7 days): {data['total']}")
    print("\nTop tracks:")
    for track, count in data["top_tracks"]:
        print(f"  {count}x  {track}")
    print("\nTop artists:")
    for artist, count in data["top_artists"]:
        print(f"  {count}x  {artist}")
