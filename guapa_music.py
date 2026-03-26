"""
guapa_music.py — Read today's Guapa music enrichment summary for the morning email.
File produced by guapa-data pipeline at 5:00 AM daily.
"""
import os
import re
from datetime import date

REPORTS_DIR = r"C:\Users\eewil\guapa-data\music\reports"


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

    return {
        "date":             today,
        "total_changes":    find_int(r"Total changes:\s+(\d+)"),
        "spotify_added":    find_int(r"Spotify URLs added\s+(\d+)"),
        "wikipedia_added":  find_int(r"Wikipedia URLs added\s+(\d+)"),
        "cover_art_filled": find_int(r"Cover art filled\s+(\d+)"),
        "new_albums":       find_int(r"New albums detected\s+(\d+)"),
        "broken_links":     find_int(r"Broken links found\s+(\d+)"),
        "artists_pruned":   find_int(r"Artists pruned\s+(\d+)"),
        "spotify":          find_coverage("Spotify URLs"),
        "wikipedia":        find_coverage("Wikipedia URLs"),
        "cover_art":        find_coverage("Cover art"),
    }
