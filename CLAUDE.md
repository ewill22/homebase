# Claude Code — Homebase

Rules and context for working in this repo.

## Critical Rules

- **Never name a file `calendar.py`** — conflicts with Python stdlib, breaks everything silently
- **Never touch the `guapa` database tables** (`parcels`, `sr1a_sales`, `tax_list`) — that's business data
- **DB connection is `get_connection()`** (not `get_conn()`) from `db.py`
- **All user-facing HTML text through `safe()`** — normalizes Unicode + html.escape() + xmlcharrefreplace
- **Email subject lines must be ASCII only** — em dashes, curly quotes etc. break Gmail threading
- **Degree symbols in HTML must be `&deg;`** — bare ° breaks Gmail rendering mid-email
- **Task Scheduler uses full python path**: `C:\Users\eewil\AppData\Local\Programs\Python\Python314\python.exe` — `python` alone won't work since PATH isn't inherited

## Architecture

```
iPhone Shortcut (11:59 PM) → iCloudDrive/steps_today.txt
                                        ↓
Guapa Strains Sync (6:30 AM)     Steps Sync (6:50 AM) → ~/.health_steps_cache.json
        ↓                                  ↓
   guapa.strain_stock            Morning Summary (7:00 AM) → ewill22@gmail.com
        ↓                                  ↑
Spotify Tracker (every 5 min) → spotify_plays
```

## Scheduled Tasks

| Task | Schedule | Status |
|------|----------|--------|
| Guapa Strains Sync | Daily 6:30 AM | Active |
| Homebase Steps Sync | Daily 6:50 AM | Active |
| Homebase Morning Summary | Daily 7:00 AM | Active |
| Homebase Spotify Tracker | Every 5 min | Active |
| Homebase Commands | Every 5 min | **Disabled** |

## Key Files

- `commands.py` — builds the home summary HTML; also the email command listener (disabled)
- `send_summary.py` — morning email entry point, logs to `homebase_log`
- `spotify.py` — all play queries filter `HOUR(played_at) BETWEEN 5 AND 22`
- `steps.py` — reads `~/.health_steps_cache.json`; monthly goal is 7,500 steps/day avg
- `health_steps.py` — full step CLI; use `--import-xml` to backfill from Apple Health export

## Email Layout Order

greeting → date → day of life → steps → weather → calendar → devils → listening → strain → monthly recap

## Accounts

- Homebase sends/receives as: `eewilliamsremote@gmail.com`
- Personal (send summaries to): `ewill22@gmail.com`
- ewill22 Google Calendar is shared read-only — homebase cannot edit it
