#!/usr/bin/env python3
"""
Apple Health — Live Step Counter (macOS)
iPhone Shortcut writes steps to iCloud Drive → Python reads the file.

Requirements:
  • iPhone with Shortcuts app
  • iCloud Drive enabled on both iPhone and Mac
  • One-time Shortcut setup — run:  python3 health_steps.py --setup

Cache is stored at ~/.health_steps_cache.json so history builds up over time.
You can also bulk-import from an Apple Health XML export to backfill history.

Usage:
    python3 health_steps.py                              # today's steps
    python3 health_steps.py --days 30                   # last 30 days
    python3 health_steps.py --year 2025                 # weekly view for a year
    python3 health_steps.py --summary                   # all-time monthly totals
    python3 health_steps.py --sync                      # pull from iCloud file + cache
    python3 health_steps.py --setup                     # print Shortcut setup guide
    python3 health_steps.py --import-xml ~/Downloads/apple_health_export/export.xml
"""

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime, timedelta

CACHE_PATH    = os.path.expanduser("~/.health_steps_cache.json")

import platform
if platform.system() == "Windows":
    ICLOUD_DIR = os.path.expanduser("~/iCloudDrive")
else:
    ICLOUD_DIR = os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs")

ICLOUD_FILE   = os.path.join(ICLOUD_DIR, "steps_today.txt")
GOAL         = 10_000
BAR_MAX      = 22


# ══════════════════════════════════════════════════════════════════════════════
# Cache  (plain JSON  {YYYY-MM-DD: int})
# ══════════════════════════════════════════════════════════════════════════════

def load_cache():
    if os.path.isfile(CACHE_PATH):
        with open(CACHE_PATH) as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# iCloud Drive bridge
# ══════════════════════════════════════════════════════════════════════════════

def read_icloud_steps():
    """
    Read steps_today.txt from iCloud Drive (or latest steps_today-N.txt if present).
    File written by iPhone Shortcut as JSON: {"date":"YYYY-MM-DD","steps":1234}
    Returns (date_str, steps) or (None, None).
    """
    import glob
    # Find all steps_today*.txt files, pick the most recently modified valid one
    candidates = sorted(
        glob.glob(os.path.join(ICLOUD_DIR, "steps_today*.txt")),
        key=os.path.getmtime,
        reverse=True,
    )
    for path in candidates:
        try:
            with open(path) as f:
                data = json.load(f)
            date_str = data["date"]
            steps = int(float(str(data["steps"]).replace(",", "")))
            # Basic sanity: date must be parseable and steps must be plausible
            datetime.strptime(date_str, "%Y-%m-%d")
            if 0 <= steps < 100_000:
                return date_str, steps
        except Exception:
            continue
    return None, None


def sync_today(cache):
    """Read iCloud file, update cache. Returns step count or None."""
    file_date, steps = read_icloud_steps()
    today = str(date.today())
    if steps is not None and file_date == today:
        cache[today] = steps
        save_cache(cache)
        return steps
    elif steps is not None and file_date:
        # File exists but is from a previous day — cache it anyway
        cache[file_date] = steps
        save_cache(cache)
    return cache.get(today)


# ══════════════════════════════════════════════════════════════════════════════
# XML import (bulk backfill from Apple Health export)
# ══════════════════════════════════════════════════════════════════════════════

STEP_TYPE = "HKQuantityTypeIdentifierStepCount"
DATE_FMTS = ["%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S"]


def _parse_dt(s):
    for fmt in DATE_FMTS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def import_xml(xml_path, cache):
    xml_path = os.path.expanduser(xml_path)
    if not os.path.isfile(xml_path):
        sys.exit(f"File not found: {xml_path}")
    print(f"Importing from {xml_path} ...")
    tree = ET.parse(xml_path)
    daily = defaultdict(int)
    for rec in tree.getroot().iter("Record"):
        if rec.get("type") != STEP_TYPE:
            continue
        dt = _parse_dt(rec.get("startDate") or rec.get("creationDate", ""))
        if dt is None:
            continue
        try:
            daily[str(dt.date())] += int(float(rec.get("value", "0")))
        except ValueError:
            pass
    before = len(cache)
    cache.update(daily)
    save_cache(cache)
    added = len(cache) - before
    updated = len(daily) - added
    print(f"Imported {len(daily):,} days — {added} new, {updated} updated in cache.\n")


# ══════════════════════════════════════════════════════════════════════════════
# Display helpers
# ══════════════════════════════════════════════════════════════════════════════

def bar(steps, peak):
    filled = int(BAR_MAX * min(steps, peak) / peak) if peak > 0 else 0
    b = "█" * filled + "░" * (BAR_MAX - filled)
    return f"[{b}]"


def goal_mark(steps):
    return "✓" if steps >= GOAL else " "


def week_monday(d):
    return d - timedelta(days=d.weekday())


# ══════════════════════════════════════════════════════════════════════════════
# Views
# ══════════════════════════════════════════════════════════════════════════════

def view_days(cache, n_days):
    today  = date.today()
    days   = [today - timedelta(days=i) for i in range(n_days - 1, -1, -1)]
    rows   = [(d, cache.get(str(d), 0)) for d in days]
    peak   = max((s for _, s in rows), default=1) or 1
    total  = sum(s for _, s in rows)
    avg    = total // n_days
    hits   = sum(1 for _, s in rows if s >= GOAL)

    print()
    print("=" * 62)
    print(f"  Steps — last {n_days} days")
    print(f"  Daily goal: {GOAL:,}   Avg: {avg:,}/day   Total: {total:,}")
    print("=" * 62)
    for d, steps in rows:
        label  = d.strftime("%a %b %d")
        marker = " ← today" if d == today else ""
        print(f"  {label}  {bar(steps, peak)} {goal_mark(steps)}  {steps:>7,}{marker}")
    print(f"\n  Goal reached: {hits}/{n_days} days")
    print()


def view_year(cache, year):
    weeks = defaultdict(int)
    for ds, steps in cache.items():
        d = date.fromisoformat(ds)
        if d.year == year:
            weeks[week_monday(d)] += steps
    if not weeks:
        print(f"No data for {year}.")
        return
    sorted_weeks = sorted(weeks.items())
    peak  = max(s for _, s in sorted_weeks) or 1
    total = sum(s for _, s in sorted_weeks)
    avg   = total // len(sorted_weeks)

    print()
    print("=" * 62)
    print(f"  Steps — {year}  (weekly totals)")
    print(f"  Avg: {avg:,}/week   Total: {total:,}")
    print("=" * 62)
    for monday, steps in sorted_weeks:
        label = monday.strftime("Wk %W  %b %d")
        print(f"  {label}  {bar(steps, peak)}  {steps:>9,}")
    print()


def view_summary(cache):
    months = defaultdict(int)
    for ds, steps in cache.items():
        d = date.fromisoformat(ds)
        months[(d.year, d.month)] += steps
    if not months:
        print("Cache is empty. Run without flags to pull today's steps.")
        return
    sorted_months = sorted(months.items())
    peak  = max(s for _, s in sorted_months) or 1
    total = sum(s for _, s in sorted_months)

    print()
    print("=" * 62)
    print(f"  Steps — All-time monthly summary")
    print(f"  Total: {total:,} steps  |  {len(cache):,} tracked days")
    print("=" * 62)
    for (yr, mo), steps in sorted_months:
        label = date(yr, mo, 1).strftime("%b %Y")
        print(f"  {label}    {bar(steps, peak)}  {steps:>10,}")
    print()


def view_today(cache, steps):
    today = date.today()
    pct   = int(100 * steps / GOAL)
    peak  = max(steps, GOAL)
    remaining = max(0, GOAL - steps)

    print()
    print("=" * 62)
    print(f"  Steps — {today.strftime('%A, %B %d %Y')}")
    print("=" * 62)
    print(f"\n  {steps:,} steps   ({pct}% of {GOAL:,} goal)")
    print(f"  {bar(steps, peak)} {goal_mark(steps)}")
    if remaining:
        print(f"\n  {remaining:,} steps to go")
    else:
        print(f"\n  Goal reached!")

    # Also show last 7 days for context
    days   = [today - timedelta(days=i) for i in range(6, 0, -1)]
    recent = [(d, cache.get(str(d), 0)) for d in days]
    recent_nonzero = [s for _, s in recent if s > 0]
    if recent_nonzero:
        avg = sum(recent_nonzero) // len(recent_nonzero)
        print(f"\n  6-day avg (excl. today): {avg:,}")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# Setup guide
# ══════════════════════════════════════════════════════════════════════════════

SETUP_GUIDE = """
╔══════════════════════════════════════════════════════════════╗
║   One-time iPhone Shortcut Setup — ~3 minutes                ║
╠══════════════════════════════════════════════════════════════╣

How it works:
  iPhone Shortcut reads your steps → saves to iCloud Drive
  → this script reads that file on your Mac.

Requirements:
  • iPhone with Shortcuts app
  • iCloud Drive turned on (Settings → [your name] → iCloud → iCloud Drive)

── PART 1: Build the Shortcut on iPhone ───────────────────────

  1. Open the Shortcuts app on iPhone

  2. Tap  +  (top right) to create a new shortcut

  3. Tap the name at the top, rename it:  Steps Today

  4. Search and add:  "Find Health Samples"
       Sample Type  →  Steps
       Date         →  Is Today

  5. Search and add:  "Get Numbers from Input"
       (auto-connects to previous step)

  6. Search and add:  "Calculate Statistics"
       Function  →  Sum

  7. Search and add:  "Text"
       Type exactly (tap to insert variables):
         {"date":"[Current Date]","steps":[Statistics Result]}
       • Tap "Current Date" → Date Format → Custom → type:  yyyy-MM-dd
       • Tap "Statistics Result" to insert it

  8. Search and add:  "Save File"
       → Save to: iCloud Drive
       → File Name: steps_today.txt
       → Toggle OFF "Ask Where to Save"

  9. Tap  X  (top left) to save

── PART 2: Automate it to run hourly ──────────────────────────

  1. In Shortcuts, tap  Automation  tab (bottom)
  2. Tap  +  → Personal Automation
  3. Choose  Time of Day
  4. Set time, repeat:  Hourly
  5. Tap  Next  → search and add  Run Shortcut  → pick  Steps Today
  6. Tap  Done  — toggle OFF "Ask Before Running"

── PART 3: Test it ────────────────────────────────────────────

  Run the shortcut once manually on iPhone (tap ▶ play button).
  Then on your Mac:

    cat ~/Library/Mobile\\ Documents/com~apple~CloudDocs/steps_today.txt
    python3 health_steps.py

╚══════════════════════════════════════════════════════════════╝
"""


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Apple Health step counter (macOS live)")
    parser.add_argument("--days",       metavar="N", type=int, default=None,
                        help="Show last N days from cache")
    parser.add_argument("--year",       metavar="YYYY", type=int,
                        help="Weekly totals for a year")
    parser.add_argument("--summary",    action="store_true",
                        help="All-time monthly summary from cache")
    parser.add_argument("--sync",       action="store_true",
                        help="Refresh today's steps in cache and exit")
    parser.add_argument("--setup",      action="store_true",
                        help="Print Shortcut setup instructions")
    parser.add_argument("--import-xml", metavar="PATH", dest="import_xml",
                        help="Bulk-import history from Apple Health XML export")
    args = parser.parse_args()

    if args.setup:
        print(SETUP_GUIDE)
        return

    cache = load_cache()

    if args.import_xml:
        import_xml(args.import_xml, cache)
        return

    if args.summary:
        view_summary(cache)
        return

    if args.year:
        view_year(cache, args.year)
        return

    if args.days:
        # Refresh today first, then show range
        steps = sync_today(cache)
        if steps is None:
            print(f"Warning: could not query live steps. Showing cached data.")
            print(f"(Is the '{SHORTCUT_NAME}' Shortcut installed? Run --setup for help.)\n")
        view_days(cache, args.days)
        return

    if args.sync:
        steps = sync_today(cache)
        today = str(date.today())
        if steps is not None:
            print(f"[{today}]  {steps:,} steps  — cached.")
        else:
            print(f"Failed to query steps. Run --setup to check your Shortcut.")
        return

    # Default: read iCloud file + show today
    steps = sync_today(cache)

    if steps is None:
        print("No step data found yet.")
        print(f"iCloud file expected at:")
        print(f"  {ICLOUD_FILE}")
        print()
        print("Run the 'Steps Today' shortcut on your iPhone once, then try again.")
        print("For setup instructions:  python3 health_steps.py --setup")
        sys.exit(1)

    view_today(cache, steps)


if __name__ == "__main__":
    main()
