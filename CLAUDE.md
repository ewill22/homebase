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
- **All tasks run hidden** — no console popups. Use `pythonw.exe` for direct Python tasks, or `wscript.exe` + `run-hidden.vbs` (in this repo root) for bat file tasks. Never use `python.exe` directly in Task Scheduler.

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

| Task | Schedule | Executor | Status |
|------|----------|----------|--------|
| Guapa Strains Sync | Daily 6:30 AM | `wscript.exe` + `strain_sync.bat` | Active |
| Homebase iCloud Nudge | Daily 6:45 AM | `powershell.exe -WindowStyle Hidden` | Active |
| Homebase Steps Sync | Daily 6:50 AM | `wscript.exe` + `steps_sync.bat` | Active |
| Homebase Morning Summary | Daily 7:00 AM | `pythonw.exe send_summary.py` | Active |
| Homebase Spotify Tracker | Every 5 min | `pythonw.exe spotify_tracker.py` | Active |
| Homebase Commands | Every 5 min | `pythonw.exe commands.py` | Active |
| Guapa Apply Editorial Suggestions | Every 5 min | `pythonw.exe apply-suggestions.py` | Active |

**Popup suppression:** Eric's PC uses PIN login (no Windows password), so "Run whether user is logged on or not" doesn't work. Instead:
- Python-only tasks use `pythonw.exe` (windowless Python, drops stdout — OK if script logs to file/DB)
- Tasks needing stdout redirect use bat file + `run-hidden.vbs` (in this repo root)
- PowerShell tasks use `-WindowStyle Hidden`
- Use `Set-ScheduledTask` (not `schtasks /Change`) to update tasks — avoids password prompt

## Key Files

- `commands.py` — builds the home summary HTML; also the email command listener
- `send_summary.py` — morning email entry point, logs to `send_summary.log` + `homebase_log`
- `strain_checker.py` — thin reader over `guapa.strain_stock` (used by morning email)
- `strain_sync.py` — collector: scrapes 12 NJ dispensaries (DispenseApp/Dutchie/Sweed), writes to `guapa.strain_stock`
- `strain_sync_run.py` — entry point for the 6:30 AM scheduled task (calls `sync_crops_catalog()`)
- `guapa_music.py` — parses guapa-data's DQ summary (coverage stats, editorial content, per-artist enrichment)
- `spotify.py` — all play queries filter `HOUR(played_at) BETWEEN 5 AND 22`
- `steps.py` — reads `~/.health_steps_cache.json`; monthly goal is 7,500 steps/day avg
- `health_steps.py` — full step CLI; use `--import-xml` to backfill from Apple Health export

## Email Layout Order

greeting → date → day of life → steps → weather → calendar → devils → listening → strain → monthly recap

## Accounts

- Homebase sends/receives as: `eewilliamsremote@gmail.com`
- Personal (send summaries to): `ewill22@gmail.com`
- ewill22 Google Calendar is shared read-only — homebase cannot edit it
