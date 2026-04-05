# Homebase

A personal command center — weather, steps, calendar, music, and dispensary stock delivered daily by email.

Built with Python + MySQL + Gmail. Part of the Guapa Inc ecosystem: homebase is a consumer of data products built in `guapa-data/`.

---

## Architecture Overview

```
guapa-data/strains/     ← collects dispensary stock data → guapa.strain_stock
guapa-data/music/       ← music pipeline (planned)       → guapa DB
homebase/               ← reads all of the above, sends email
```

Homebase never scrapes or collects raw data directly (except weather, Spotify plays, and steps). It assembles data from its own DB and from guapa, formats it, and delivers it.

---

## Infrastructure

### Database
- MySQL at `127.0.0.1:3306`, database: `homebase`
- User: `guapa_will` — also has access to the `guapa` database (cross-DB reads)
- Credentials in `.env` (never commit)
- Connection helper: `db.py` — `get_connection()` used everywhere

### Email
- Outbound: `emailer.py` — `send_email(subject, body, to=None, attachments=None)`
  - body can be plain string or `{"text": ..., "html": ...}` dict
  - Gmail SMTP, SSL port 465, UTF-8
- Inbound: `gmail.py` — IMAP read/manage/delete against `eewilliamsremote@gmail.com`
- Homebase address: `eewilliamsremote@gmail.com`
- Personal address: `ewill22@gmail.com`

### Config
- `config.py` — `get_config(user_id=1)` loads per-user settings from DB, cached per process
- Returns: `user` dict, `cities` list, `calendars` list, `personal_cal_ids`, `trusted_senders`
- All scripts pull timezone, email addresses, city list, and calendar IDs from here — nothing hardcoded

### Logging
- `logger.py` — `log_event(event_type, status, message, detail, user_id)` writes to `homebase_log` table
- Never crashes the caller — all DB errors silently swallowed
- Used by: `send_summary.py` (summary_sent), `spotify_tracker.py` (spotify_sync), errors

---

## Scheduled Tasks (Windows Task Scheduler)

| Task | Schedule | Script | Status |
|---|---|---|---|
| Homebase iCloud Nudge | Daily 6:45 AM | PowerShell iCloud sync | Active |
| Homebase Steps Sync | Daily 6:50 AM | `steps_sync.bat` → `health_steps.py --sync` | Active |
| Homebase Morning Summary | Daily 7:00 AM | `send_summary.py` | Active |
| Homebase Spotify Tracker | Every 5 min | `spotify_tracker.py` | Active |
| Homebase Commands | Every 5 min | `commands.py` | Active |
| Guapa Apply Editorial Suggestions | Every 5 min | `guapa-site/scripts/apply-suggestions.py` | Active |

All tasks run hidden (no console window popups):
- Python-only tasks use `pythonw.exe` (windowless Python interpreter)
- Tasks needing stdout logging use bat wrappers + `run-hidden.vbs` (in guapa-data repo)
- PowerShell tasks use `-WindowStyle Hidden`

---

## Morning Email (`send_summary.py`)

Sends a daily HTML email to `ewill22@gmail.com` at 7:00 AM.
Subject format: `homebase | Mon Mar 15, 07:00 AM`

Sections (in order):

### Greeting
Random small talk or fortune cookie (40% chance), time-of-day aware.

### Steps
Yesterday's step count vs an adjusted daily target.
- Target recalculates daily to hit a **7,500 steps/day monthly average** based on MTD actuals
- Progress bar: green if yesterday hit the target, blue if under
- Data sourced from `~/.health_steps_cache.json` (written by `health_steps.py --sync`)
- Section hidden if no data available

### Weather
Three cities side by side — Northfield NJ, Fort Lauderdale FL, Amsterdam NL.
Amsterdam shows °C with °F below. Humidity + wind stacked under each temp.
Data fetched live from Open-Meteo (free, no key) and stored in `homebase.weather`.

### Calendar
Pulled from Google Calendar via OAuth2. Reads:
- `eewilliamsremote@gmail.com` (primary)
- `ewill22@gmail.com` (shared read-only, "See all event details")
- NJ Devils games calendar

Dynamic header based on day of week:
- Mon–Wed: "What's up next this week" + "Weekend"
- Thu–Fri: "What's up next this week" (events capped at that Friday) + "What's going on this weekend"
- Sat: "What's going on this weekend"
- Sun: "Next week"

Weekend = Sat + Sun + any weekday with a day-off/holiday/vacation/PTO all-day event.
All-day events hidden unless "birthday" or "bday" in the name.
Events show Google Calendar color as a square dot.

### Devils Game
Shown if there's a Devils game today ("Devils — Tonight") or tomorrow ("Devils — Tomorrow"). Hidden entirely otherwise.

### Spotify Listening
Stacked bar chart — last 7 days of listening, grouped by top 10 artists.
Guapa dark panel (`#111111`), legend with artist name (clickable Spotify link) and play count.
Play counts filter to **5 AM – 11 PM only** (excludes late night/early morning noise).
Bar colors defined in `ARTIST_COLORS` in `spotify.py` (10 colors).

### Strain Stock
Dispensaries currently carrying Crops "Secret Meetings" near Atlantic City.
Reads from `guapa.strain_stock` — a data product maintained by `guapa-data/strains/`.
Shows dispensary, product, price, nav link (Google Maps), and "new batch" badge if package ID changed.

### Monthly Recap
Shown on the 1st of each month only.
Top artists + tracks for the prior month, YTD play counts, horizontal bar charts.

---

## Step Tracking (`health_steps.py` + `steps.py`)

iPhone Shortcut writes daily step count to iCloud Drive at 11:59 PM:
```
iPhone Shortcut (11:59 PM) → iCloudDrive/steps_today.txt → Steps Sync task (6:50 AM) → cache → Morning Email (7:00 AM)
```

- `steps_today.txt` format: `{"date":"YYYY-MM-DD","steps":1234}`
- Cache stored at `~/.health_steps_cache.json`
- `health_steps.py` — full CLI: `--sync`, `--import-xml`, `--days N`, `--summary`, `--setup`
- `steps.py` — thin reader for the email: `get_steps_yesterday()`, `get_daily_target()`
- Backfill from Apple Health export: `python health_steps.py --import-xml path/to/export.xml`

---

## Email Commands (`commands.py`)

**Currently disabled** — the Task Scheduler job is turned off. Can be re-enabled via Task Scheduler if needed.

When active: runs every 5 minutes, checks inbox for unread emails from trusted senders, acts on the subject line (falls back to body), deletes the email after processing.

| Trigger phrase | Response |
|---|---|
| "how are things at home" | Full home summary email |
| "hows it going at home" | Full home summary email |
| "whats up at home" | Full home summary email |

---

## Spotify Tracking (`spotify_tracker.py`)

Polls Spotify every 5 minutes for recently played tracks.
Upserts into `homebase.spotify_plays` — unique on `(played_at, track_id)`.
`played_at` stored as ET naive datetime.

All play count queries filter to **hours 5–22** (`HOUR(played_at) BETWEEN 5 AND 22`) to exclude late night/early morning plays from stats.

Auth via `spotify_auth.py` — SpotifyOAuth with scopes:
- `user-read-recently-played`
- `user-top-read`

Query helpers in `spotify.py`:
- `get_weekly_listens()` — 7-day play counts by artist (top 10)
- `get_monthly_recap()` — top artists/tracks + YTD counts for the prior month
- `get_new_releases()` / `get_top_artist_new_releases()` — parked, will be replaced by guapa-data music product

---

## Weather (`weather.py`)

- `fetch_and_store(user_id=1)` — fetches current conditions for all configured cities, writes to `homebase.weather`
- `fetch_all(user_id=1)` — returns latest reading per city as list of dicts
- Cities loaded from `user_cities` table via config
- Open-Meteo API, no key required

---

## Google Calendar (`gcal.py`)

- `get_upcoming_events(user_id=1)` — returns events for the next ~2 weeks across all personal calendars
- `get_devils_games()` — reads NJ Devils calendar (`DEVILS_CAL_ID` hardcoded in gcal.py)
- `create_event()` — creates an event on the primary calendar
- Auth via `gcal_auth.py` — OAuth2, credentials in `credentials.json` + `token.json`
- **Never name a file `calendar.py`** — conflicts with Python stdlib

---

## Strain Stock (`strain_checker.py`)

Thin reader only. All data collection happens in `guapa-data/strains/`.

- `get_strain_stock(strain="secret meetings")` — queries `guapa.strain_stock` for the latest snapshot
- Returns: `dispensary, name, brand, category, price, url, listed_at, package_id, strain_type, crops_grower, new_batch`

---

## File Structure

```
homebase/
├── .env                  # DB + email credentials (never commit)
├── db.py                 # MySQL connection helper
├── config.py             # Per-user config loader (cities, calendars, email, timezone)
├── logger.py             # Structured event logging → homebase_log table
├── emailer.py            # Send email via Gmail SMTP
├── gmail.py              # Read/manage email via IMAP
├── weather.py            # Fetch + store weather, multi-city
├── gcal_auth.py          # Google Calendar OAuth2
├── gcal.py               # Google Calendar read/create
├── spotify_auth.py       # Spotify OAuth2
├── spotify_tracker.py    # Poll + store recently played tracks (every 5 min)
├── spotify.py            # Query helpers for weekly/monthly listening data
├── strain_checker.py     # Thin reader → guapa.strain_stock
├── guapa_music.py        # Parse guapa-data DQ summary (coverage, editorial, enrichment)
├── health_steps.py       # Apple Health step CLI (sync, import-xml, history views)
├── steps.py              # Thin reader for morning email (yesterday + daily target)
├── steps_sync.bat        # Task Scheduler wrapper for health_steps.py --sync
├── commands.py           # Email command listener + home summary builder
├── send_summary.py       # Morning email entry point (daily 7 AM)
└── work/                 # Business/analytics files (leads_simple.sql etc.)
```

---

## Database Tables

| Table | Description |
|---|---|
| `users` | Per-user config (timezone, email, trusted senders, logo URL) |
| `user_cities` | Cities to show weather for, with display order |
| `user_calendars` | Google Calendar IDs to include |
| `weather` | Historical weather readings per city |
| `spotify_plays` | Every Spotify track play, with played_at in ET |
| `homebase_log` | Structured event log (summary sends, sync runs, errors) |

Strain stock data lives in `guapa.strain_stock` — see `guapa-data/strains/` for full schema.
