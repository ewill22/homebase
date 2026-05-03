# Claude Code — Homebase

Rules and context for working in this repo.

## Critical Rules

- **Never name a file `calendar.py`** — conflicts with Python stdlib, breaks everything silently
- **Never touch the `guapa` database tables** (`parcels`, `sr1a_sales`, `tax_list`) — that's business data
- **DB connection is `get_connection()`** (not `get_conn()`) from `db.py` — connects to the **homebase** database. Queries against guapa tables (e.g. `strain_stock`) must be **fully qualified** as `guapa.<table>` or they'll hit a non-existent `homebase.<table>`. Broke strain sync silently for 6 days on 4/18.
- **Don't stack stdout redirects** — if a `.bat` wrapper does `>> logs/foo.log 2>&1`, the Python script inside must NOT also `open(same_log, "a")`. Windows won't allow a second handle; errors surface as `PermissionError` and the real cause gets buried.
- **Don't swallow exceptions with `try/except: pass`** in nightly jobs — at minimum `print(traceback)` so the bat-wrapped log captures it. Silent failure is worse than loud failure.
- **In `commands.py` use `_get_config()` (the module-level alias), not bare `get_config()`** — the latter is only imported locally inside `cmd_home_summary`. Two handlers (`brief <team>` and `going to <dispensary>`) silently `NameError`'d and marked emails as Seen with no reply, because `pythonw.exe` swallows stderr. Caught 5/02 when "going to medleaf" produced no email despite the task running successfully.
- **After creating or altering any homebase MySQL table, run `bash scripts/dump_schema.sh`** to refresh `schema.sql`. The repo carries a frozen snapshot of every table so the DB can be rebuilt from scratch on a new machine. The dump script reads `.env`, strips `AUTO_INCREMENT=N` (churns every dump), and writes `schema.sql` with a stable header. Forgetting this means future-you tries to clone homebase onto a new PC and gets `Table 'homebase.<X>' doesn't exist` everywhere.
- **Always pass `encoding="utf-8"` to `open()`** — Python on Windows defaults to cp1252 and silently breaks the moment a file gains a curly quote, em dash, or any high-bit byte. Broke guapa_music summary parsing on 5/01 when 103 new editorial descriptions introduced non-ASCII; the bare `except: return None` hid it and dropped the music section from the morning email.
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
| Homebase Odds Alerter | Every 15 min | `pythonw.exe -m odds_alerter.main` | Active |

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
- **Terpene coverage is structurally limited — don't re-investigate.** DispenseApp stores (Conservatory, Med Leaf, City Leaves, Green Wellness) populate terpenes via their API. Dutchie stores (MPX, Botanist, AC LEEF, Brute's, Public Absecon, Juniper, Atlantic Flower) do not: the schema's `terpenes` field returns null and `terpenesV2` doesn't exist on the `Products` type. COA URLs (`canonicalLabResultUrl`) are null on 100% of Dutchie products too — the dispensaries simply don't publish terps upstream. AC LEEF additionally publishes no cannabinoid data. Probed 5/02 (introspection blocked at Cloudflare, POSTs blocked, GET non-persisted queries work but the data isn't there). Cannabinoid coverage on Dutchie (THC/THCA/CBD/CBDA/CBG/CBN) IS extracted via `_du_extract_cannabinoids` from `cannabinoidsV2`.
- `guapa_music.py` — parses guapa-data's DQ summary (coverage stats, editorial content, per-artist enrichment)
- `spotify.py` — all play queries filter `HOUR(played_at) BETWEEN 5 AND 22`
- `steps.py` — reads `~/.health_steps_cache.json`; monthly goal is 7,500 steps/day avg
- `health_steps.py` — full step CLI; use `--import-xml` to backfill from Apple Health export
- `odds_alerter/` — NHL playoff flip detector; texts via Google Fi SMS gateway when a pregame favorite's live moneyline crosses to positive. Enriches alerts with NHL CF% (Corsi shot share) via free `api-web.nhle.com`. Supports `watch <TAG>` email command for per-cycle score/CF% pulses. State in `odds_games`, `odds_api_usage`, `odds_flip_history`, `odds_watch`. 500-credit/mo budget on The Odds API — see `odds_alerter/README.md`.
- `dispensary_planner.py` — pre-trip dispensary report. Email triggers `going to <dispensary>` / `heading to <dispensary>` (conservatory, med leaf, city leaves, green wellness). On request:
  - Snapshots full flower/pre-roll menu via DispenseApp into `homebase.dispensary_menu` (one snapshot_id per call, kept forever)
  - Emails back: top sales (>=25% off, sorted by % off) + top 10 flower SKUs by terpene similarity to Secret Meetings (default reference; pre-rolls excluded from similarity)
  - Side-effect: writes a freeze-pane HTML side-by-side comparison to `iCloudDrive/homebase/secret_meetings_compare.html` (also `logs/`) — sticky reference column, drastic-cell highlighting, green column for genuine clones (every measured terp within 0.05 of reference). Open on phone via Files → iCloud Drive → homebase.
  - Manual refresh without re-scraping: `python _compare_with_highlight.py [conservatory|medleaf|...]` rebuilds the HTML from the latest snapshot in DB.
  - DispenseApp stores only — Dutchie has no terpene data (see note above), so Botanist/MPX/AC LEEF aren't supported.
  - Reference profile is hardcoded in `_SECRET_MEETINGS_REF` — averaged from Secret Meetings rows with terp data on 5/02. Update if Crops genetics drift.
  - Clone tolerance default 0.05: tighter rejects even genuine SM (lab-to-lab variation), looser flags strains with real myrcene/linalool divergence. Calibrated 5/02.

## Email Layout Order

greeting → date → day of life → steps → weather → calendar → devils → listening → strain → monthly recap

## Accounts

- Homebase sends/receives as: `eewilliamsremote@gmail.com`
- Personal (send summaries to): `ewill22@gmail.com`
- ewill22 Google Calendar is shared read-only — homebase cannot edit it
