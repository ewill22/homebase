"""
guapa_pm.py — Guapa Daily PM Automation

Runs after daily pipelines (7:15 AM, after Homebase morning summary).
Reads git logs from both Guapa repos, calculates coverage metrics, compares
against the roadmap, and generates a prioritized daily briefing.

Lives in homebase/ so it can do clean sibling imports from emailer + config.
Operational output (briefing + task queue + log) stays under
C:\\Users\\eewil\\guapa\\guapa-pm\\.

Output:
  - C:\\Users\\eewil\\guapa\\guapa-pm\\pm-reports\\pm-YYYY-MM-DD.md  (daily briefing)
  - C:\\Users\\eewil\\guapa\\guapa-pm\\pm-reports\\task-queue.md      (running task queue)
  - C:\\Users\\eewil\\guapa\\guapa-pm\\guapa_pm.log                   (scheduled-run log)

Usage:
  python guapa_pm.py                # Full daily run
  python guapa_pm.py --dry-run      # Preview without writing files
  python guapa_pm.py --days 7       # Look back 7 days instead of default 1
  python guapa_pm.py --email        # Also send the HTML-styled briefing as its own email
"""

import subprocess
import json
import os
import sys
import re
import csv
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# ─── Configuration ──────────────────────────────────────────────────────────

GUAPA_ROOT = Path(r"C:\Users\eewil\guapa")
BACKEND_REPO = GUAPA_ROOT / "guapa-data"
FRONTEND_REPO = GUAPA_ROOT / "guapa-site"
# Operational output dir (gitignored, local-only). Script lives in homebase
# but output stays at the historical guapa-pm/ path so existing reports +
# the log aren't orphaned by the move.
PM_OUTPUT_DIR = GUAPA_ROOT / "guapa-pm"
PM_REPORTS_DIR = PM_OUTPUT_DIR / "pm-reports"
TASK_QUEUE_FILE = PM_REPORTS_DIR / "task-queue.md"
LOG_FILE = PM_OUTPUT_DIR / "guapa_pm.log"

# Files to parse for metrics
MUSIC_CATALOG = FRONTEND_REPO / "public" / "data" / "music-catalog.json"
MUSIC_SOURCE = BACKEND_REPO / "music" / "data" / "music-data.json"
COFFEE_OFFERINGS = FRONTEND_REPO / "src" / "data" / "coffee-offerings.js"
COFFEE_HISTORY = BACKEND_REPO / "coffee" / "data" / "coffee-offerings-history.json"
ARTIST_EDITORIAL = FRONTEND_REPO / "public" / "data" / "artist-editorial.csv"
DQ_REPORTS_DIR = BACKEND_REPO / "music" / "reports"

# ─── Roadmap Items ──────────────────────────────────────────────────────────
# Each item has: id, name, tier, status, team, metric_key (optional),
#                target (optional), blocked_by (optional)
#
# Tiers:
#   1 = Complete what's started (highest priority)
#   2 = Strengthen the Third Space
#   3 = Real Estate (blocked on MLS)
#   4 = Future / backlog
#
# Status: active, blocked, done, parked

ROADMAP = [
    # ── Tier 1: Complete what's started ──
    # `auto_shipping: True` means: this is actually running daily without
    # human intervention. The briefing's [SHIPPING] pill is reserved for
    # these. Anything else that's "active" displays as [TODO] — honest
    # signal that it's waiting on someone.
    {
        "id": "spotify-enrich",
        "name": "Spotify URL enrichment (full catalog)",
        "tier": 1,
        "status": "active",
        "auto_shipping": True,
        "team": "backend",
        "metric_key": "spotify_coverage_catalog",
        "target": 80,
        "notes": "Running daily, ~75-300/day. Autonomous — no decisions needed."
    },
    {
        "id": "release-date-backfill",
        "name": "Release date backfill (MusicBrainz CC0)",
        "tier": 1,
        "status": "active",
        "auto_shipping": True,
        "team": "backend",
        "metric_key": "release_date_coverage",
        "target": 100,
        "notes": "50/day from MusicBrainz. ~9 months to complete. Autonomous."
    },
    {
        "id": "genre-classification",
        "name": "Genre classification (remaining artists)",
        "tier": 1,
        "status": "active",
        "auto_shipping": True,
        "team": "backend",
        "metric_key": "genre_coverage",
        "target": 100,
        "notes": "Wikidata P136 auto-classifies discovered artists. Human review for edge cases."
    },
    {
        "id": "track-enrichment",
        "name": "Track-level enrichment (Genius, writers, covers)",
        "tier": 1,
        "status": "active",
        "auto_shipping": True,
        "team": "backend",
        "metric_key": "track_enrichment_albums",
        "target": None,  # ongoing
        "notes": "50 albums/day via MusicBrainz. Genius URLs at 100% coverage."
    },

    # ── Tier 2: Strengthen the Third Space ──
    {
        "id": "coffee-brazil-drilldown",
        "name": "Brazil coffee drill-down (Conab data)",
        "tier": 2,
        "status": "active",
        "team": "frontend",
        "notes": "Same recipe as Colombia. Biggest leverage — Brazil is ~40% global share."
    },
    {
        "id": "coffee-v2-rendering",
        "name": "Render coffee schema v2 fields in frontend",
        "tier": 2,
        "status": "active",
        "team": "frontend",
        "metric_key": "coffee_v2_coverage",
        "notes": "Backend ships structured fields; frontend partially renders them."
    },
    {
        "id": "sports-lens",
        "name": "Sports lens content (beyond placeholder)",
        "tier": 2,
        "status": "active",
        "team": "frontend",
        "notes": "Placeholder only. Needs data source + counter-bottom + blurbs."
    },
    {
        "id": "guapa-score",
        "name": "Music rankings pipeline (Guapa Score)",
        "tier": 2,
        "status": "parked",
        "team": "backend",
        "notes": "Designed, not built. Last.fm + Genius + Spotify + Billboard."
    },
    {
        "id": "now-playing-tile",
        "name": "Now Playing broadcast clock (product brief)",
        "tier": 2,
        "status": "parked",
        "team": "frontend",
        "notes": "Broadcast clock from GUAPA_MUSIC_PRODUCT_BRIEF.md."
    },

    # ── Tier 3: Real Estate ──
    {
        "id": "mls-access",
        "name": "MLS access from SJSRMLS",
        "tier": 3,
        "status": "blocked",
        "team": "external",
        "blocked_by": "Maria must initiate IDX request through SJSRMLS",
        "notes": "Blocking item for all RE work beyond public data."
    },
    {
        "id": "re-historical-db",
        "name": "Rutgers Historical DB ingest",
        "tier": 3,
        "status": "parked",
        "team": "backend",
        "notes": "Pre-MLS work. 30+ years of parcel data."
    },

    # ── Tier 4: Future ──
    {
        "id": "llc-filing",
        "name": "File NJ LLC ($125)",
        "tier": 4,
        "status": "active",
        "team": "eric",
        "since": "2026-05-16",  # day-counter on the top-of-briefing nag
        "notes": "njportal.com. Blocks EIN, bank account, trademark filing. Nagged daily in the top banner."
    },
    {
        "id": "trademark-filing",
        "name": "File trademark (Guapa Data)",
        "tier": 4,
        "status": "blocked",
        "team": "eric",
        "since": "2026-05-16",
        "blocked_by": "LLC filing (entity must exist first)",
        "notes": "Final step in the chain: LLC -> EIN -> bank account -> trademark. Nagged daily."
    },
    {
        "id": "pm-automation",
        "name": "PM automation (this script + Agent Teams)",
        "tier": 4,
        "status": "active",
        "team": "eric",
        "notes": "Daily briefing + task queue for Claude Code sessions."
    },

    # Backend hardening backlog — source: guapa-pm/backend-hardening-v2.md (2026-05-16)
    {
        "id": "harden-pydantic-settings",
        "name": "Backend hardening: centralize config (pydantic-settings)",
        "tier": 4,
        "status": "active",
        "team": "backend",
        "notes": "Priority #1 (~1 session, foundation for the other hardening tasks). Single Settings class loaded from .env -> env -> defaults. Required vars (ANTHROPIC_API_KEY, EMAIL_ADDRESS, MySQL creds) fail at startup with a clear error instead of mid-pipeline. Spec: guapa-pm/backend-hardening-v2.md (TASK-2)."
    },
    {
        "id": "harden-narrow-excepts",
        "name": "Backend hardening: narrow broad excepts in ingestion paths",
        "tier": 4,
        "status": "active",
        "team": "backend",
        "notes": "Priority #2 (~1-2 sessions). Goal: zero `except Exception` inside ingestion/enrichment modules. Orchestrator-level catches are OK if they log AND notify (existing _notify_enrichment is the model). Each fix tends to surface a real bug. Ship incrementally. Spec: guapa-pm/backend-hardening-v2.md (TASK-3)."
    },
    {
        "id": "harden-pydantic-external-apis",
        "name": "Backend hardening: pydantic models for external API responses",
        "tier": 4,
        "status": "active",
        "team": "backend",
        "notes": "Priority #3 (~3 sessions, one per service). Validate at the network boundary; eliminate defensive .get('k', {}).get('n') chains. Order: MusicBrainz first (ingest_musicbrainz / enrich_tracks / enrich_members), then Wikidata SPARQL (classify_wikidata), then Shopify /products.json. Spec: guapa-pm/backend-hardening-v2.md (TASK-1)."
    },
    {
        "id": "harden-json-logging",
        "name": "Backend hardening: JSON logging",
        "tier": 4,
        "status": "parked",
        "team": "backend",
        "notes": "Explicitly deferred per the memo author. Revisit only if more log consumers join (alerting service, dashboard, eval harness) or cross-run queryability becomes needed ('all MusicBrainz 503s in May'). Spec: guapa-pm/backend-hardening-v2.md (TASK-4)."
    },
]

# ─── Autonomy Tiers ─────────────────────────────────────────────────────────
# What can ship without asking Eric:
AUTONOMOUS_PATTERNS = [
    # Backend autonomous work (pre-approved, no review needed)
    "daily enrichment", "spotify url", "cover art", "release_date",
    "track enrichment", "genius url", "coffee offerings refresh",
    "dq_enrich", "export_from_json", "wikidata classification",
    # Frontend autonomous work
    "[auto]",  # backend auto-pushes
]

# What needs Eric's review before shipping:
REVIEW_REQUIRED_PATTERNS = [
    "new artist", "editorial", "genre override", "album-level tag",
    "schema change", "new data source", "design change", "new component",
    "api endpoint", "legal", "coffee schema",
]

# What needs a conversation:
DECISION_REQUIRED = [
    "new product", "new lens", "architecture change", "third-party service",
    "pricing", "mls", "partnership", "llc", "trademark",
]


# ─── Git Log Parsing ────────────────────────────────────────────────────────

def get_git_log(repo_path: Path, days: int = 1) -> list[dict]:
    """Get git commits from the last N days."""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        result = subprocess.run(
            ["git", "log", f"--since={since}", "--pretty=format:%H|%an|%ai|%s",
             "--no-merges"],
            cwd=str(repo_path),
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return []

        commits = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append({
                    "hash": parts[0][:8],
                    "author": parts[1],
                    "date": parts[2][:10],
                    "message": parts[3],
                    "repo": repo_path.name,
                    "is_auto": "[auto]" in parts[3].lower(),
                })
        return commits
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def get_files_changed(repo_path: Path, days: int = 1) -> list[str]:
    """Get list of files changed in the last N days."""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        result = subprocess.run(
            ["git", "log", f"--since={since}", "--name-only",
             "--pretty=format:", "--no-merges"],
            cwd=str(repo_path),
            capture_output=True, text=True, timeout=30
        )
        files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        return list(set(files))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


# ─── Metrics Extraction ─────────────────────────────────────────────────────

def get_music_metrics() -> dict:
    """Extract coverage metrics from the music catalog and source data."""
    metrics = {}

    # Parse catalog for frontend-visible stats
    if MUSIC_CATALOG.exists():
        try:
            with open(MUSIC_CATALOG, "r", encoding="utf-8") as f:
                catalog = json.load(f)

            if isinstance(catalog, list):
                artists = catalog
            elif isinstance(catalog, dict):
                # Catalog shape: {artist_slug: artist_obj, ...}
                artists = list(catalog.values())
            else:
                artists = []
            total_artists = len(artists)
            total_albums = sum(len(a.get("albums", [])) for a in artists)

            # Spotify coverage
            albums_with_spotify = 0
            albums_with_release_date = 0
            albums_with_cover = 0
            genres_seen = set()
            subgenres_seen = set()

            for artist in artists:
                g = artist.get("genre")
                sg = artist.get("subgenre")
                if g:
                    genres_seen.add(g)
                if sg:
                    subgenres_seen.add(sg)
                for album in artist.get("albums", []):
                    if album.get("url_spotify"):
                        albums_with_spotify += 1
                    if album.get("release_date"):
                        albums_with_release_date += 1
                    if album.get("cover_art_small") or album.get("cover_art_large"):
                        albums_with_cover += 1

            metrics["total_artists"] = total_artists
            metrics["total_albums"] = total_albums
            metrics["spotify_coverage_catalog"] = round(
                albums_with_spotify / total_albums * 100, 1) if total_albums else 0
            metrics["release_date_coverage"] = round(
                albums_with_release_date / total_albums * 100, 1) if total_albums else 0
            metrics["cover_art_coverage"] = round(
                albums_with_cover / total_albums * 100, 1) if total_albums else 0
            metrics["genres"] = len(genres_seen)
            metrics["subgenres"] = len(subgenres_seen)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            metrics["catalog_error"] = str(e)

    # Editorial artist count
    if ARTIST_EDITORIAL.exists():
        try:
            with open(ARTIST_EDITORIAL, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                confirmed = sum(1 for r in rows if r.get("confirmed", "").lower() == "yes")
                drafted = sum(1 for r in rows if r.get("drafted", "").lower() == "yes")
                metrics["editorial_confirmed"] = confirmed
                metrics["editorial_drafted"] = drafted
                metrics["editorial_total"] = len(rows)
        except Exception:
            pass

    return metrics


def get_coffee_metrics() -> dict:
    """Extract coffee pipeline metrics."""
    metrics = {}

    # Count offerings from history file
    if COFFEE_HISTORY.exists():
        try:
            with open(COFFEE_HISTORY, "r", encoding="utf-8") as f:
                history = json.load(f)
            if isinstance(history, dict):
                metrics["coffee_total_offerings_ever"] = len(history)
                # Count currently active (last_seen within 7 days)
                week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
                active = sum(1 for v in history.values()
                             if v.get("last_seen", "") >= week_ago)
                metrics["coffee_active_offerings"] = active
            elif isinstance(history, list):
                metrics["coffee_total_offerings_ever"] = len(history)
        except (json.JSONDecodeError, TypeError):
            pass

    # Try to count v2 schema coverage from offerings JS file
    if COFFEE_OFFERINGS.exists():
        try:
            content = COFFEE_OFFERINGS.read_text(encoding="utf-8")
            # coffee-offerings.js is a JS module — properties are barewords
            # (e.g. `handle: 'foo',`), not JSON-quoted. Count those.
            total = len(re.findall(r"^\s*handle:\s", content, flags=re.MULTILINE))
            # v2 fields: variety populated when list is non-empty;
            # altitude_masl and cupping_score populated when not null.
            with_variety = len(re.findall(r"^\s*variety:\s*\[[^\]]+\]", content, flags=re.MULTILINE))
            with_altitude = len(re.findall(r"^\s*altitude_masl:\s*'", content, flags=re.MULTILINE))
            with_cupping = len(re.findall(r"^\s*cupping_score:\s*\d", content, flags=re.MULTILINE))
            metrics["coffee_live_offerings"] = total
            if total > 0:
                metrics["coffee_v2_coverage"] = round(
                    ((with_variety + with_altitude + with_cupping) / (total * 3)) * 100, 1)
        except Exception:
            pass

    return metrics


def get_latest_dq_report() -> str | None:
    """Find and read the most recent DQ report."""
    if not DQ_REPORTS_DIR.exists():
        return None
    dq_files = sorted(DQ_REPORTS_DIR.glob("dq-*.txt"), reverse=True)
    if dq_files:
        try:
            return dq_files[0].read_text(encoding="utf-8")[:2000]  # first 2000 chars
        except Exception:
            return None
    return None


def parse_enrichment_highlights(summary: str) -> dict:
    """Extract headline numbers from the enrichment summary text.

    Returns an empty dict if nothing matches — caller can fall back to
    omitting the section entirely. We don't need every stat; the METRICS
    table already carries coverage %, so this picks out the bits METRICS
    doesn't: today's deltas + track-level enrichment.
    """
    h: dict = {}
    if not summary:
        return h

    m = re.search(r"Total changes:\s*(\d+)", summary)
    if m:
        h["total"] = int(m.group(1))

    for key, pat in (
        ("spotify_added",  r"Spotify URLs added\s+(\d+)"),
        ("release_dates",  r"Release dates filled\s+(\d+)"),
        ("cover_art",      r"Cover art filled\s+(\d+)"),
        ("wiki_added",     r"Wikipedia URLs added\s+(\d+)"),
        ("broken_links",   r"Broken links found\s+(\d+)"),
    ):
        m = re.search(pat, summary)
        if m and int(m.group(1)) > 0:
            h[key] = int(m.group(1))

    m = re.search(r"MB enriched albums\s+(\d+)/(\d+)\s+\((\d+)%\)", summary)
    if m:
        h["mb_done"] = int(m.group(1))
        h["mb_total"] = int(m.group(2))
        h["mb_pct"] = int(m.group(3))

    m = re.search(r"Genius URLs\s+\d+/\d+\s+\((\d+)%\)", summary)
    if m:
        h["genius_pct"] = int(m.group(1))

    return h


def get_latest_summary() -> str | None:
    """Find and read the most recent enrichment summary."""
    if not DQ_REPORTS_DIR.exists():
        return None
    summary_files = sorted(DQ_REPORTS_DIR.glob("summary-*.txt"), reverse=True)
    if summary_files:
        try:
            return summary_files[0].read_text(encoding="utf-8")[:2000]
        except Exception:
            return None
    return None


# ─── Roadmap Diffing ─────────────────────────────────────────────────────────

def classify_commits(commits: list[dict]) -> dict:
    """Classify commits by roadmap item and autonomy tier."""
    classified = {
        "autonomous": [],
        "review_needed": [],
        "unclassified": [],
        "by_roadmap_item": defaultdict(list),
    }

    for commit in commits:
        msg = commit["message"].lower()

        # Check if autonomous
        is_auto = any(p in msg for p in AUTONOMOUS_PATTERNS)
        needs_review = any(p in msg for p in REVIEW_REQUIRED_PATTERNS)

        if is_auto and not needs_review:
            classified["autonomous"].append(commit)
        elif needs_review:
            classified["review_needed"].append(commit)
        else:
            classified["unclassified"].append(commit)

        # Map to roadmap items by keyword matching
        for item in ROADMAP:
            item_keywords = item["name"].lower().split()
            if any(kw in msg for kw in item_keywords if len(kw) > 3):
                classified["by_roadmap_item"][item["id"]].append(commit)

    return classified


def calculate_roadmap_progress(metrics: dict) -> list[dict]:
    """Calculate progress for each roadmap item that has a metric."""
    progress = []
    for item in ROADMAP:
        entry = {**item}
        mk = item.get("metric_key")
        if mk and mk in metrics:
            entry["current_value"] = metrics[mk]
            if item.get("target"):
                entry["progress_pct"] = round(
                    metrics[mk] / item["target"] * 100, 1)
            else:
                entry["progress_pct"] = None
        progress.append(entry)
    return progress


# ─── Report Generation ───────────────────────────────────────────────────────

def generate_briefing(days: int = 1) -> str:
    """Generate the full daily PM briefing."""
    today = datetime.now().strftime("%Y-%m-%d")
    day_name = datetime.now().strftime("%A")

    # Gather data
    backend_commits = get_git_log(BACKEND_REPO, days)
    frontend_commits = get_git_log(FRONTEND_REPO, days)
    all_commits = backend_commits + frontend_commits

    backend_files = get_files_changed(BACKEND_REPO, days)
    frontend_files = get_files_changed(FRONTEND_REPO, days)

    music_metrics = get_music_metrics()
    coffee_metrics = get_coffee_metrics()
    all_metrics = {**music_metrics, **coffee_metrics}

    classified = classify_commits(all_commits)
    roadmap_progress = calculate_roadmap_progress(all_metrics)

    latest_dq = get_latest_dq_report()
    latest_summary = get_latest_summary()

    # ── Build the briefing ──
    lines = []
    lines.append(f"# Guapa PM Briefing — {day_name} {today}")
    lines.append(f"")
    lines.append(f"Lookback: {days} day(s) | Generated: {datetime.now().strftime('%H:%M')}")
    lines.append(f"")

    # ── Top-of-briefing nag for Eric-owned filings ──
    # Renders only when there are open eric items. Day-counter on `since`
    # is the lever — the older it gets, the more this stares back.
    today_date = datetime.now().date()
    eric_open = [
        r for r in ROADMAP
        if r.get("team") == "eric" and r.get("status") in ("active", "blocked")
        and r.get("since")
    ]
    if eric_open:
        lines.append("---")
        lines.append("## ⚠️ ERIC: STILL OPEN")
        lines.append("")
        for item in eric_open:
            since_date = datetime.strptime(item["since"], "%Y-%m-%d").date()
            days_open = (today_date - since_date).days
            day_label = "today" if days_open == 0 else f"{days_open} day{'s' if days_open != 1 else ''}"
            blocker = f" — blocked by {item['blocked_by']}" if item.get("blocked_by") else ""
            lines.append(f"- **{item['name']}** — open {day_label}{blocker}")
            if item.get("notes"):
                lines.append(f"  - {item['notes']}")
        lines.append("")

    # ── Section 1: What Shipped ──
    lines.append("---")
    lines.append("## SHIPPED")
    lines.append("")

    human_commits = [c for c in all_commits if not c["is_auto"]]
    auto_commits = [c for c in all_commits if c["is_auto"]]

    if human_commits:
        lines.append(f"### Human commits ({len(human_commits)})")
        for c in human_commits:
            tag = "BE" if c["repo"] == "guapa-data" else "FE"
            lines.append(f"- [{tag}] `{c['hash']}` {c['message']}")
        lines.append("")

    if auto_commits:
        lines.append(f"### Auto-pipeline commits ({len(auto_commits)})")
        lines.append(f"- {len(auto_commits)} automated pushes (catalog, coffee, enrichment)")
        lines.append("")

    if not all_commits:
        lines.append("No commits in the lookback window.")
        lines.append("")

    # ── Section 2: Coverage Metrics ──
    lines.append("---")
    lines.append("## METRICS")
    lines.append("")

    if music_metrics:
        lines.append("### Music")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        if "total_artists" in music_metrics:
            lines.append(f"| Artists in catalog | {music_metrics['total_artists']} |")
        if "total_albums" in music_metrics:
            lines.append(f"| Albums in catalog | {music_metrics['total_albums']:,} |")
        if "spotify_coverage_catalog" in music_metrics:
            lines.append(f"| Spotify URL coverage | {music_metrics['spotify_coverage_catalog']}% |")
        if "release_date_coverage" in music_metrics:
            lines.append(f"| Release date coverage | {music_metrics['release_date_coverage']}% |")
        if "cover_art_coverage" in music_metrics:
            lines.append(f"| Cover art coverage | {music_metrics['cover_art_coverage']}% |")
        if "editorial_confirmed" in music_metrics:
            lines.append(f"| Editorial confirmed | {music_metrics['editorial_confirmed']} |")
        if "editorial_drafted" in music_metrics:
            lines.append(f"| Editorial drafted | {music_metrics['editorial_drafted']} |")
        if "genres" in music_metrics:
            lines.append(f"| Genres / Subgenres | {music_metrics['genres']} / {music_metrics['subgenres']} |")
        lines.append("")

    if coffee_metrics:
        lines.append("### Coffee")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        if "coffee_live_offerings" in coffee_metrics:
            lines.append(f"| Live offerings | {coffee_metrics['coffee_live_offerings']} |")
        if "coffee_total_offerings_ever" in coffee_metrics:
            lines.append(f"| Total offerings (history) | {coffee_metrics['coffee_total_offerings_ever']} |")
        if "coffee_v2_coverage" in coffee_metrics:
            lines.append(f"| Schema v2 coverage | {coffee_metrics['coffee_v2_coverage']}% |")
        lines.append("")

    # ── Section 3: Roadmap Progress ──
    lines.append("---")
    lines.append("## ROADMAP")
    lines.append("")

    for tier in [1, 2, 3, 4]:
        tier_items = [r for r in roadmap_progress if r["tier"] == tier]
        if not tier_items:
            continue

        tier_labels = {1: "Complete What's Started", 2: "Strengthen the Third Space",
                       3: "Real Estate", 4: "Future / Ops"}
        lines.append(f"### Tier {tier} — {tier_labels[tier]}")
        for item in tier_items:
            # Honest status: SHIPPING is reserved for items actually running
            # daily (auto_shipping=True). Anything else "active" is TODO —
            # makes the human-time backlog visible instead of pretending
            # every roadmap line is in motion.
            st = item["status"]
            if st == "done":
                label = "DONE"
            elif st == "blocked":
                label = "BLOCKED"
            elif st == "parked":
                label = "PARKED"
            elif st == "active" and item.get("auto_shipping"):
                label = "SHIPPING"
            elif st == "active":
                label = "TODO"
            else:
                label = st.upper()

            progress_str = ""
            if "current_value" in item:
                if item.get("target"):
                    progress_str = f" — {item['current_value']}% → {item['target']}%"
                else:
                    progress_str = f" — {item['current_value']}%"

            lines.append(f"- [{label}] **{item['name']}**{progress_str}")
            if item.get("blocked_by"):
                lines.append(f"  - Blocked: {item['blocked_by']}")
            if item.get("notes"):
                lines.append(f"  - {item['notes']}")
        lines.append("")

    # ── Section 4: Recommended Next Actions ──
    lines.append("---")
    lines.append("## RECOMMENDED NEXT")
    lines.append("")
    lines.append("*Work the AI dev team can pick up. Eric-owned items live in the top nag, auto-shipping items in ROADMAP.*")
    lines.append("")

    # AI-dev-team-actionable only:
    #   - skip auto_shipping items (continuously running, not a decision)
    #   - skip team=external (someone else's job)
    #   - skip team=eric (already on the top yellow nag — don't repeat)
    recommended = [
        item for item in ROADMAP
        if item["status"] == "active"
        and not item.get("auto_shipping")
        and item.get("team") not in ("external", "eric")
    ]
    recommended.sort(key=lambda x: x["tier"])

    for i, item in enumerate(recommended, 1):
        team_tag = item.get("team", "???").upper()
        lines.append(f"{i}. [{team_tag}] {item['name']}")
        if item.get("notes"):
            lines.append(f"   {item['notes']}")
    lines.append("")

    # ── Section 5: Needs Your Decision ──
    lines.append("---")
    lines.append("## NEEDS YOUR DECISION")
    lines.append("")

    # Only surface blocked items where Eric can actually decide something.
    # Items where someone else is the blocker (team=external) belong in
    # status updates, not in a decision queue. Eric-team items are already
    # shouted at the top of the briefing, so don't repeat them here.
    decision_blocked = [
        r for r in ROADMAP
        if r["status"] == "blocked"
        and r.get("team") not in ("external", "eric")
    ]
    review_commits = classified["review_needed"]

    if not decision_blocked and not review_commits:
        lines.append("Nothing today.")
        lines.append("")
    else:
        if decision_blocked:
            for item in decision_blocked:
                lines.append(f"- **{item['name']}**: {item.get('blocked_by', 'Unknown blocker')}")
            lines.append("")
        if review_commits:
            lines.append("### Commits needing review")
            for c in review_commits:
                tag = "BE" if c["repo"] == "guapa-data" else "FE"
                lines.append(f"- [{tag}] `{c['hash']}` {c['message']}")
            lines.append("")

    # ── Section 6: Latest Pipeline Output ──
    if latest_summary:
        h = parse_enrichment_highlights(latest_summary)
        if h:
            lines.append("---")
            lines.append("## LATEST ENRICHMENT")
            lines.append("")

            # Today's deltas — one tight line
            deltas = []
            if h.get("spotify_added"):
                deltas.append(f"+{h['spotify_added']} Spotify URLs")
            if h.get("release_dates"):
                deltas.append(f"+{h['release_dates']} release dates")
            if h.get("cover_art"):
                deltas.append(f"+{h['cover_art']} cover art")
            if h.get("wiki_added"):
                deltas.append(f"+{h['wiki_added']} Wikipedia URLs")
            if h.get("total"):
                head = f"**Today:** {h['total']} total changes"
                if deltas:
                    head += " — " + ", ".join(deltas)
                lines.append(head)
                lines.append("")
            elif deltas:
                lines.append(f"**Today:** {', '.join(deltas)}")
                lines.append("")

            # Track-level enrichment (not in METRICS section)
            track_bits = []
            if h.get("mb_pct") is not None:
                track_bits.append(
                    f"MB-enriched albums: {h['mb_pct']}% "
                    f"({h['mb_done']:,}/{h['mb_total']:,})"
                )
            if h.get("genius_pct") is not None:
                track_bits.append(f"Genius URLs: {h['genius_pct']}%")
            if h.get("broken_links"):
                track_bits.append(f"⚠️ {h['broken_links']} broken link(s) flagged")
            for b in track_bits:
                lines.append(f"- {b}")
            if track_bits:
                lines.append("")

            lines.append(
                "*Full report: `guapa-data/music/reports/summary-YYYY-MM-DD.txt`*"
            )
            lines.append("")

    # ── Footer ──
    lines.append("---")
    lines.append(f"*Generated by guapa_pm.py at {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append(f"*Backend commits: {len(backend_commits)} | Frontend commits: {len(frontend_commits)}*")
    lines.append(f"*Files changed: BE={len(backend_files)}, FE={len(frontend_files)}*")

    return "\n".join(lines)


def generate_task_queue() -> str:
    """Generate a task queue file for Claude Code sessions to read."""
    today = datetime.now().strftime("%Y-%m-%d")

    lines = []
    lines.append(f"# Guapa Task Queue — Updated {today}")
    lines.append("")
    lines.append("Claude Code: read this at the start of any work session.")
    lines.append("Items marked APPROVED can be executed without asking Eric.")
    lines.append("Items marked REVIEW need Eric's sign-off before merge/push.")
    lines.append("Items marked DECISION need a conversation first.")
    lines.append("")

    # Autonomous work (always approved)
    lines.append("## APPROVED (autonomous, ship it)")
    lines.append("")
    auto_items = [r for r in ROADMAP if r["status"] == "active"
                  and r.get("team") in ("backend",)
                  and any(kw in r["name"].lower()
                          for kw in ["enrichment", "backfill", "coverage", "classification"])]
    for item in auto_items:
        lines.append(f"- [ ] {item['name']}")
        if item.get("notes"):
            lines.append(f"      {item['notes']}")
    lines.append("")

    # Needs review
    lines.append("## REVIEW (build it, Eric reviews before push)")
    lines.append("")
    review_items = [r for r in ROADMAP if r["status"] == "active"
                    and r.get("team") in ("frontend", "backend")
                    and r not in auto_items]
    for item in review_items:
        team = item.get("team", "???").upper()
        lines.append(f"- [ ] [{team}] {item['name']}")
        if item.get("notes"):
            lines.append(f"      {item['notes']}")
    lines.append("")

    # Needs decision
    lines.append("## DECISION (don't start without talking to Eric)")
    lines.append("")
    decision_items = [r for r in ROADMAP if r["status"] in ("blocked", "parked")]
    for item in decision_items:
        lines.append(f"- [ ] {item['name']}")
        if item.get("blocked_by"):
            lines.append(f"      Blocked: {item['blocked_by']}")
        elif item.get("notes"):
            lines.append(f"      {item['notes']}")
    lines.append("")

    return "\n".join(lines)


# ─── HTML email renderer ─────────────────────────────────────────────────────
# Renders the briefing markdown into styled HTML for the morning email.
# Styles are inlined on every element — most email clients (Gmail in
# particular) strip <style> blocks. Targets only the markdown features the
# briefing actually emits (no general-purpose Markdown coverage).

# Status pill palette — picked from Eric's 2026-05-18 skate-trail photo
# (forest greens, BUMP-sign yellow, rust shorts, path gray). The first three
# also reappear as accent colors throughout the email so the whole thing
# feels of-a-piece.
_PILL_STYLES = {
    "SHIPPING": ("#588157", "#ffffff"),  # forest green — actually running daily
    "TODO":     ("#f0c014", "#1a1a1a"),  # caution yellow — waiting on human time
    "BLOCKED":  ("#b85c38", "#ffffff"),  # rust — waiting on external dep
    "PARKED":   ("#888888", "#ffffff"),  # path gray — explicitly deferred
    "DONE":     ("#3a5a40", "#ffffff"),  # deep forest — completed
}


def _md_inline(s: str) -> str:
    """Escape HTML and apply inline md: **bold**, *italic*, `code`, [PILL]."""
    import html as _h
    s = _h.escape(s)
    s = re.sub(
        r'`([^`]+)`',
        r'<code style="background:#f4f1de;padding:1px 6px;border-radius:3px;'
        r'font-family:\'SF Mono\',Menlo,Consolas,monospace;font-size:12px;'
        r'color:#3a5a40;">\1</code>',
        s,
    )
    s = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', s)
    s = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'<em>\1</em>', s)

    def _pill(m: 're.Match[str]') -> str:
        label = m.group(1)
        bg, fg = _PILL_STYLES[label]
        return (
            f'<span style="display:inline-block;background:{bg};color:{fg};'
            "font-size:10px;font-weight:700;text-transform:uppercase;"
            "letter-spacing:0.06em;padding:2px 7px;border-radius:3px;"
            'vertical-align:1px;margin-right:6px;">'
            f"{label}</span>"
        )

    s = re.sub(r'\[(SHIPPING|TODO|BLOCKED|PARKED|DONE)\]', _pill, s)
    return s


def briefing_to_html(md: str) -> str:
    """Convert the PM briefing markdown to a styled HTML email body."""
    import html as _h

    lines = md.split("\n")
    out: list[str] = []
    i = 0
    in_table = False
    in_pre = False
    in_eric_nag = False  # tracks the open yellow-banner <div> wrapping the Eric section
    list_stack: list[str] = []  # values: 'ul' or 'ol'

    def close_lists_to(target_depth: int):
        while len(list_stack) > target_depth:
            out.append(f"</{list_stack.pop()}>")

    def close_table():
        nonlocal in_table
        if in_table:
            out.append("</tbody></table>")
            in_table = False

    # Wrapping <body> + container. Photo-palette accents: forest-green
    # section headers + tinted body bg + extra line-height for readability.
    out.append(
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "</head>"
        '<body style="margin:0;padding:0;background:#f4f1de;">'
        '<div style="max-width:720px;margin:0 auto;padding:28px;'
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
        "Helvetica,Arial,sans-serif;color:#1a1a1a;background:#ffffff;"
        'line-height:1.65;">'
    )

    while i < len(lines):
        line = lines[i]

        # Fenced code block toggle
        if line.startswith("```"):
            close_lists_to(0)
            close_table()
            if in_pre:
                out.append("</pre>")
                in_pre = False
            else:
                out.append(
                    '<pre style="background:#f4f4f5;padding:14px;'
                    "border-radius:6px;overflow:auto;font-family:'SF Mono',"
                    "Menlo,Consolas,monospace;font-size:11.5px;line-height:1.45;"
                    'white-space:pre;color:#222;">'
                )
                in_pre = True
            i += 1
            continue
        if in_pre:
            out.append(_h.escape(line))
            i += 1
            continue

        # Table rows
        if line.startswith("|"):
            # Skip the |---|---| separator
            if re.match(r'^\|[\s\-\|:]+\|\s*$', line):
                i += 1
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not in_table:
                close_lists_to(0)
                out.append(
                    '<table style="border-collapse:collapse;width:100%;'
                    'margin:8px 0 16px 0;font-size:14px;"><thead><tr>'
                )
                for c in cells:
                    out.append(
                        '<th style="text-align:left;padding:10px 14px;'
                        "border-bottom:2px solid #588157;font-weight:700;"
                        "color:#3a5a40;font-size:11.5px;text-transform:uppercase;"
                        'letter-spacing:0.06em;background:#f4f1de;">'
                        f"{_md_inline(c)}</th>"
                    )
                out.append("</tr></thead><tbody>")
                in_table = True
            else:
                out.append("<tr>")
                for idx, c in enumerate(cells):
                    align = "right" if idx > 0 and re.match(
                        r'^[\d\.,%/\s]+$', c
                    ) else "left"
                    out.append(
                        f'<td style="padding:7px 12px;'
                        "border-bottom:1px solid #f0f0f0;"
                        f'text-align:{align};font-variant-numeric:tabular-nums;">'
                        f"{_md_inline(c)}</td>"
                    )
                out.append("</tr>")
            i += 1
            continue
        close_table()

        # Headers
        if line.startswith("# "):
            close_lists_to(0)
            out.append(
                '<h1 style="font-size:22px;font-weight:700;margin:0 0 4px 0;'
                f'color:#0a0a0a;">{_md_inline(line[2:])}</h1>'
            )
            i += 1
            continue
        if line.startswith("## "):
            close_lists_to(0)
            heading = line[3:]
            # Eric-nag section gets a loud yellow alert-box treatment so the
            # day counter is impossible to scroll past.
            if "ERIC: STILL OPEN" in heading:
                out.append(
                    '<div style="background:#fff8dc;border:2px solid #f0c014;'
                    "border-radius:6px;padding:14px 18px;margin:18px 0 24px 0;\">"
                    '<h2 style="font-size:14px;font-weight:700;'
                    "text-transform:uppercase;letter-spacing:0.08em;color:#0a0a0a;"
                    'margin:0 0 8px 0;padding:0;border:none;">'
                    f"{_md_inline(heading)}</h2>"
                )
                in_eric_nag = True
            else:
                if in_eric_nag:
                    out.append("</div>")
                    in_eric_nag = False
                out.append(
                    '<h2 style="font-size:14px;font-weight:700;text-transform:uppercase;'
                    "letter-spacing:0.09em;color:#3a5a40;margin:34px 0 14px 0;"
                    'padding-bottom:8px;border-bottom:2px solid #588157;">'
                    f"{_md_inline(heading)}</h2>"
                )
            i += 1
            continue
        if line.startswith("### "):
            close_lists_to(0)
            out.append(
                '<h3 style="font-size:13px;font-weight:600;color:#3a5a40;'
                f'margin:20px 0 8px 0;">{_md_inline(line[4:])}</h3>'
            )
            i += 1
            continue

        # Horizontal rule — h2 already has a bottom border so skip
        if line.strip() == "---":
            close_lists_to(0)
            i += 1
            continue

        # Bullet list (with optional indent for nesting)
        m = re.match(r'^(\s*)-\s+(.*)$', line)
        if m:
            indent_spaces = len(m.group(1))
            depth = indent_spaces // 2 + 1  # 0 spaces → depth 1, 2 spaces → 2
            content = m.group(2)
            # Open/close ul levels to reach `depth`
            while len(list_stack) < depth:
                out.append(
                    '<ul style="margin:6px 0 12px 0;padding-left:22px;'
                    f'font-size:14px;color:#1a1a1a;">'
                    if not list_stack
                    else '<ul style="margin:2px 0 4px 0;padding-left:20px;'
                    f'font-size:13px;color:#555;">'
                )
                list_stack.append("ul")
            while len(list_stack) > depth or (
                list_stack and list_stack[-1] != "ul"
            ):
                out.append(f"</{list_stack.pop()}>")
            out.append(f'<li style="margin:3px 0;">{_md_inline(content)}</li>')
            i += 1
            continue

        # Numbered list (RECOMMENDED NEXT). Items may have indented continuations.
        m = re.match(r'^(\d+)\.\s+(.*)$', line)
        if m:
            content = m.group(2)
            if not list_stack or list_stack[-1] != "ol":
                close_lists_to(0)
                out.append(
                    '<ol style="margin:8px 0 16px 0;padding-left:22px;'
                    'font-size:14px;">'
                )
                list_stack.append("ol")
            cont_parts: list[str] = []
            j = i + 1
            while j < len(lines) and re.match(r'^\s{3,}\S', lines[j]):
                cont_parts.append(lines[j].strip())
                j += 1
            cont_html = ""
            if cont_parts:
                cont_html = (
                    '<div style="color:#666;font-size:13px;margin-top:2px;">'
                    + _md_inline(" ".join(cont_parts))
                    + "</div>"
                )
            out.append(
                f'<li style="margin:6px 0;">{_md_inline(content)}{cont_html}</li>'
            )
            i = j
            continue

        # Blank line ends any open list group
        if line.strip() == "":
            close_lists_to(0)
            i += 1
            continue

        # Italic single-line note (e.g. "*Sorted by tier...*")
        if line.startswith("*") and line.rstrip().endswith("*") and \
                not line.startswith("**"):
            out.append(
                '<p style="color:#888;font-style:italic;font-size:13px;'
                f'margin:6px 0 10px 0;">{_md_inline(line.strip("*"))}</p>'
            )
            i += 1
            continue

        # Default paragraph
        close_lists_to(0)
        out.append(
            f'<p style="margin:8px 0;font-size:14px;">{_md_inline(line)}</p>'
        )
        i += 1

    close_lists_to(0)
    close_table()
    if in_pre:
        out.append("</pre>")

    out.append("</div></body></html>")
    return "".join(out)


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Guapa PM Daily Briefing")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print briefing without writing files")
    parser.add_argument("--days", type=int, default=1,
                        help="Days to look back (default: 1)")
    parser.add_argument("--email", action="store_true",
                        help="Also send via Homebase morning email")
    args = parser.parse_args()

    # When launched via pythonw.exe (no console — used by Task Scheduler),
    # sys.stdout is None, so any print() would crash with AttributeError.
    # Redirect to a rolling log file so scheduled runs leave a trail.
    if sys.stdout is None:
        PM_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        sys.stdout = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
        sys.stderr = sys.stdout
        print(f"\n=== Run started {datetime.now().isoformat()} ===")
    else:
        # Interactive runs: Windows cp1252 console can't encode emoji in
        # --dry-run output. File writes already pass encoding="utf-8".
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    # Generate briefing
    briefing = generate_briefing(days=args.days)
    task_queue = generate_task_queue()

    if args.dry_run:
        print(briefing)
        print("\n" + "=" * 60 + "\n")
        print(task_queue)
        return

    # Write files
    PM_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    report_file = PM_REPORTS_DIR / f"pm-{today}.md"

    report_file.write_text(briefing, encoding="utf-8")
    print(f"Briefing written: {report_file}")

    TASK_QUEUE_FILE.write_text(task_queue, encoding="utf-8")
    print(f"Task queue updated: {TASK_QUEUE_FILE}")

    # Send as its own separate email (sibling imports — same source as homebase's
    # morning summary, so recipient + creds live in one place).
    if args.email:
        try:
            from emailer import send_email
            from config import get_config

            cfg = get_config()
            to_addr = cfg["user"]["send_to_email"]
            subject = f"Guapa PM Briefing - {datetime.now().strftime('%A %Y-%m-%d')}"
            send_email(
                subject,
                {"text": briefing, "html": briefing_to_html(briefing)},
                to=to_addr,
            )
            print(f"Email sent: {to_addr}")
        except Exception as e:
            print(f"Warning: Could not send PM briefing email: {e}")


if __name__ == "__main__":
    main()
