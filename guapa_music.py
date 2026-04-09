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
    track_enriched_artists = []
    track_run_totals = None
    log_path = os.path.join(REPORTS_DIR, f"daily-{today}.log")
    if os.path.isfile(log_path):
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                log_text = f.read()
            # Spotify lines: "  Sam Cooke: +4/11 spotify, 7 marked no-match"
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

            # Track enrichment per-album lines, isolated to the Step 2 block:
            #   Rick Nelson — Ricky (1957)
            #     12 tracks enriched
            step2 = re.search(
                r"Step 2: Track enrichment(.*?)(?:Step 3:|\Z)",
                log_text, re.DOTALL
            )
            if step2:
                block = step2.group(1)
                # Aggregate by artist name
                by_artist = {}
                for m in re.finditer(
                    r"^  (.+?) \u2014 .+?\n    (\d+) tracks enriched",
                    block, re.MULTILINE
                ):
                    name = m.group(1).strip()
                    tracks = int(m.group(2))
                    entry = by_artist.setdefault(name, {"name": name, "albums": 0, "tracks": 0})
                    entry["albums"] += 1
                    entry["tracks"] += tracks
                track_enriched_artists = list(by_artist.values())

                # Run summary totals
                def _find(pat):
                    m = re.search(pat, block)
                    return int(m.group(1)) if m else None
                albums_processed = _find(r"Albums processed:\s+(\d+)")
                if albums_processed is not None:
                    track_run_totals = {
                        "albums_processed": albums_processed,
                        "tracks_enriched":  _find(r"Tracks enriched:\s+(\d+)") or 0,
                        "covers_found":     _find(r"Covers found:\s+(\d+)") or 0,
                        "featured_added":   _find(r"Featured artists:\s+(\d+)") or 0,
                        "writers_added":    _find(r"External writers:\s+(\d+)") or 0,
                    }
        except Exception:
            pass

    # Parse TRACK ENRICHMENT section from the summary
    track_enrichment = None
    genius_cov = find_coverage("Genius URLs")
    mb_cov = find_coverage("MB enriched albums")
    if genius_cov or mb_cov:
        track_enrichment = {
            "genius_urls":       genius_cov,
            "mb_enriched":       mb_cov,
            "covers_flagged":    find_int(r"Covers flagged\s+(\d+)"),
            "writer_credits":    find_int(r"Writer credits\s+(\d+)"),
            "featured_artists":  find_int(r"Featured artists\s+(\d+)"),
            "run_totals":        track_run_totals,
            "artists":           track_enriched_artists,
        }

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
        "track_enrichment":      track_enrichment,
    }
