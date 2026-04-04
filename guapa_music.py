"""
guapa_music.py — Read today's Guapa music enrichment summary for the morning email.
File produced by guapa-data pipeline at 5:00 AM daily.
"""
import os
import re
from datetime import date

REPORTS_DIR = r"C:\Users\eewil\guapa\guapa-data\music\reports"


def get_music_summary():
    """
    Parse today's summary file. Returns a dict or None if file not available.
    """
    today = date.today().strftime("%Y-%m-%d")
    path  = os.path.join(REPORTS_DIR, f"summary-{today}.txt")

    if not os.path.isfile(path):
        return None

    try:
        with open(path) as f:
            text = f.read()
    except Exception:
        return None

    def find_int(pattern):
        m = re.search(pattern, text)
        return int(m.group(1)) if m else None

    def find_coverage(label):
        m = re.search(rf"{label}\s+([\d,]+)/([\d,]+)\s+\((\d+)%\)(?:\s+\(([+\-]\d+)\))?", text)
        if not m:
            return None
        return {
            "have":  int(m.group(1).replace(",", "")),
            "total": int(m.group(2).replace(",", "")),
            "pct":   int(m.group(3)),
            "delta": int(m.group(4)) if m.group(4) else 0,
        }

    # Parse per-artist activity from the daily log
    artists = []
    log_path = os.path.join(REPORTS_DIR, f"daily-{today}.log")
    if os.path.isfile(log_path):
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                log_text = f.read()
            # Lines like: "  Sam Cooke: +4/11 spotify, 7 marked no-match"
            # or:          "  Beastie Boys: +1/1 spotify"
            for m in re.finditer(
                r"^\s+(.+?):\s+\+(\d+)/(\d+) spotify(?:,\s+(\d+) marked no-match)?",
                log_text, re.MULTILINE
            ):
                artists.append({
                    "name":     m.group(1).strip(),
                    "added":    int(m.group(2)),
                    "total":    int(m.group(3)),
                    "no_match": int(m.group(4)) if m.group(4) else 0,
                })
        except Exception:
            pass

    # Parse editorial content stats
    editorial = None
    ed_desc = find_coverage("Descriptions")
    if ed_desc:
        ed_new = find_int(r"New today\s+(\d+)")
        ed_review = find_int(r"Needs review\s+(\d+)")
        # Parse new descriptions: lines like "    + Artist Name" followed by "      description"
        ed_artists = []
        for m in re.finditer(
            r"^\s+\+\s+(.+?)\n\s{6,}(.+?)$",
            text, re.MULTILINE
        ):
            ed_artists.append({
                "name": m.group(1).strip(),
                "description": m.group(2).strip(),
            })
        # Parse needs-review: lines like "    ~ Artist Name" followed by "      description"
        review_artists = []
        for m in re.finditer(
            r"^\s+~\s+(.+?)\n\s{6,}(.+?)$",
            text, re.MULTILINE
        ):
            review_artists.append({
                "name": m.group(1).strip(),
                "description": m.group(2).strip(),
            })
        editorial = {
            "descriptions": ed_desc,
            "confirmed": find_coverage("Confirmed artists"),
            "remaining": find_int(r"Remaining\s+(\d+)"),
            "needs_review": ed_review or 0,
            "review_artists": review_artists,
            "new_today": ed_new or 0,
            "artists": ed_artists,
        }

    return {
        "date":                  today,
        "total_changes":         find_int(r"Total changes:\s+(\d+)"),
        "spotify_added":         find_int(r"Spotify URLs added\s+(\d+)"),
        "wikipedia_added":       find_int(r"Wikipedia URLs added\s+(\d+)"),
        "cover_art_filled":      find_int(r"Cover art filled\s+(\d+)"),
        "new_albums":            find_int(r"New albums detected\s+(\d+)"),
        "broken_links":          find_int(r"Broken links found\s+(\d+)"),
        "broken_spotify":        find_int(r"Broken spotify\s+(\d+)"),
        "broken_wikipedia":      find_int(r"Broken wikipedia\s+(\d+)"),
        "broken_cover_art":      find_int(r"Broken cover art\s+(\d+)"),
        "artists_pruned":        find_int(r"Artists pruned\s+(\d+)"),
        "spotify":               find_coverage("Spotify URLs"),
        "wikipedia":             find_coverage("Wikipedia URLs"),
        "cover_art":             find_coverage("Cover art"),
        "editorial":             editorial,
        "artists":               artists,
    }
