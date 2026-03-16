# Homebase

A personal command center — weather, calendar, music, and dispensary stock delivered daily by email, with an on-demand command interface via Gmail.

Built with Python + MySQL + Gmail. Part of the Guapa Inc ecosystem: homebase is a consumer of data products built in `guapa-data/`.

---

## Architecture Overview

```
guapa-data/strains/     ← collects dispensary stock data → guapa.strain_stock
guapa-data/music/       ← music pipeline (planned)       → guapa DB
homebase/               ← reads all of the above, sends email, listens for commands
```

Homebase never scrapes or collects raw data directly (except weather and Spotify plays). It assembles data from its own DB and from guapa, formats it, and delivers it.

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

| Task | Schedule | Script |
|---|---|---|
| Homebase Summary | Daily 7:00 AM | `send_summary.py` |
| Homebase Commands | Every 5 min | `commands.py` |
| Homebase Spotify Tracker | Every 5 min | `spotify_tracker.py` |
| Guapa Strains Sync | Daily 6:30 AM | `guapa-data/strains/sync.py` |

---

## Morning Email (`send_summary.py`)

Sends a daily HTML email to `ewill22@gmail.com` at 7:00 AM.
Subject format: `homebase | Mon Mar 15, 07:00 AM`

Sections (in order):

### Greeting
Random small talk or fortune cookie (40% chance), time-of-day aware.

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
- Thu–Fri: "What's up next this week" + "What's going on this weekend"
- Sat: "What's going on this weekend"
- Sun: "Next week"

Weekend = Sat + Sun + any weekday with a day-off/holiday/vacation/PTO all-day event.
All-day events hidden unless "birthday" or "bday" in the name.
Events show Google Calendar color as a square dot.

### Devils Game
Shown if there's a Devils game today ("Devils — Tonight") or tomorrow ("Devils — Tomorrow"). Hidden entirely otherwise.

### Spotify Listening
Stacked bar chart — last 7 days of listening, grouped by artist.
Guapa dark panel (`#111111`), legend with artist name (clickable Spotify link) and play count.
Bar colors: yellow, pink, blue, green, amber (`ARTIST_COLORS` in `spotify.py`).

### Strain Stock
Dispensaries currently carrying Crops "Secret Meetings" near Atlantic City.
Reads from `guapa.strain_stock` — a data product maintained by `guapa-data/strains/`.
Shows dispensary, product, price, nav link (Google Maps), and "new batch" badge if package ID changed.

### Monthly Recap
Shown on the 1st of each month only.
Top artists + tracks for the prior month, YTD play counts, horizontal bar charts.

---

## Email Commands (`commands.py`)

Runs every 5 minutes via Task Scheduler. Checks inbox for unread emails from trusted senders, acts on the subject line (falls back to body), deletes the email after processing.

**Trusted senders:** configured in DB (`users.trusted_senders`), defaults to `ewill22@gmail.com` and `eewilliamsremote@gmail.com`.

Subject decoding handles smart quotes from phone autocorrect (unicodedata NFKD normalization).

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

Auth via `spotify_auth.py` — SpotifyOAuth with scopes:
- `user-read-recently-played`
- `user-top-read`

Query helpers in `spotify.py`:
- `get_weekly_listens()` — 7-day play counts by artist
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

For scraper details, dispensary list, API notes, and full schema — see `guapa-data/strains/`.

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
