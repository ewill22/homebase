# Claude Code — Homebase

Rules and context for working in this repo.

## Critical Rules

- **Never name a file `calendar.py`** — conflicts with Python stdlib, breaks everything silently
- **Never touch the `guapa` database tables** (`parcels`, `sr1a_sales`, `tax_list`) — that's business data
- **DB connection is `get_connection()`** (not `get_conn()`) from `db.py` — connects to the **homebase** database. Queries against guapa tables (e.g. `strain_stock`) must be **fully qualified** as `guapa.<table>` or they'll hit a non-existent `homebase.<table>`. Broke strain sync silently for 6 days on 4/18.
- **Don't stack stdout redirects** — if a `.bat` wrapper does `>> logs/foo.log 2>&1`, the Python script inside must NOT also `open(same_log, "a")`. Windows won't allow a second handle; errors surface as `PermissionError` and the real cause gets buried.
- **Don't swallow exceptions with `try/except: pass`** in nightly jobs — at minimum `print(traceback)` so the bat-wrapped log captures it. Silent failure is worse than loud failure.
- **In `commands.py` use `_get_config()` (the module-level alias), not bare `get_config()`** — the latter is only imported locally inside `cmd_home_summary`. Two handlers (`brief <team>` and `going to <dispensary>`) silently `NameError`'d and marked emails as Seen with no reply, because `pythonw.exe` swallows stderr. Caught 5/02 when "going to medleaf" produced no email despite the task running successfully.
- **When Eric reports Hard Rock Bet end-of-night numbers, insert into `homebase.hrb_daily_pnl`.** Trigger phrases: "today we started -X, ended +Y," "we're at +$Z tonight," etc. Table columns: `date`, `start_balance`, `end_balance`, `net` (generated), `note`. Upsert by date so a corrected number replaces the row. Exists because the sportsbook has no API and Eric rejected scraping settlement emails as "not worth it" — manual end-of-day entry is the tradeoff. Tied to the odds_alerter project (Eric tracks whether the alerter moves the number).
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
- `strain_sync.py` — collector: scrapes 12 NJ dispensaries (DispenseApp/Dutchie/Sweed), writes to `guapa.strain_stock`. Three platform shapes:
  - **DispenseApp** (Med Leaf, City Leaves, Conservatory, Green Wellness) — JSON API with full lab panel: cannabinoids + terpenes + potency + strain type
  - **Dutchie** (Brute's Roots, The Botanist, Public Absecon, AC LEEF, MPX NJ, Juniper Lane, Atlantic Flower) — GraphQL API. Requires `curl_cffi` with `impersonate="chrome120"` to clear Cloudflare; standard `urllib` returns 403. Returns THC/THCA/CBD/CBDA/CBG/CBN via `cannabinoidsV2` (extracted by `_du_extract_cannabinoids`) but **no terpene data** (see note below).
  - **Sweed/HTML** (Cannabist Mays Landing) — server-rendered page; products parsed out of an embedded JSON blob
  - Vapes/cartridges/disposables filtered at both category and product-name level. `new_batch=1` flag set when `package_id` differs from previous logged row for the same dispensary+strain.
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
  - Side-effect: writes a freeze-pane HTML to `iCloudDrive/homebase/secret_meetings_compare.html` (also `logs/`). **Always shows both Conservatory AND Med Leaf** stacked — every trigger re-scrapes BOTH stores so all sections show live data. Each section has its own sticky reference column, drastic-cell highlighting, and a "Total terpenes" row showing absolute loudness (% of bud weight). Open on phone via Files → iCloud Drive → homebase.
  - **Per-terpene values are normalized to share-of-total-terps**, not absolute % of bud weight. So "27%" means 27% of the strain's total terpene budget is limonene. This decouples profile shape from loudness — a strain with 2× SM's total terps but the same shape ranks as very similar (good for "find me something like SM but louder"). Distance and clone detection both operate in this relative space (clone tolerance: 4 percentage points per terp).
  - **Chemovar classification** per Lewis (2018)-style framework: every strain gets a `Type / Cluster / Subtype` label (e.g. "Type I / C / lim/caryo balanced"). Type from THC:CBD ratio, Cluster from terpene profile shape (A=myrcene/pinene "indica", B=terpinolene "sativa", C=limonene/caryo "modern hybrid"), Subtype from dominant terpene. Computed by `classify_chemovar()` in `dispensary_planner.py`.
  - **Terpinolene weighting**: distance metric weights terpinolene 3x. Reason: SM has 5% of total terps as terpinolene (a distinctive whisper for a Cluster C strain — most modern hybrids have 0). Without weighting, the relative-profile distance treats no-terpinolene strains as twins. The 3x weight is calibrated against the inventory: only 14% of flower has terpinolene >= 0.04%, so penalizing absence ranks the rare matches higher.
  - **"Terp whisper" row** shows ✓ for candidates with terpinolene at SM's level (>= 3% of total OR >= 0.04% absolute).
  - **"Loud-terpinolene cousins" section** under each store's main table — limonene-rich strains with much louder terpinolene than SM. Different feel (more cerebral / old-school sativa) but related family. Worth knowing about for variety, not for matching SM.
  - Manual refresh without re-scraping: `python _compare_with_highlight.py` rebuilds the HTML from the latest snapshots in DB.
  - DispenseApp stores only — Dutchie has no terpene data (see note above), so Botanist/MPX/AC LEEF aren't supported. Same wall applies to Red Oak Absecon (also Dutchie). Eric explicitly chose not to build a degraded Dutchie variant.
  - Reference profile is hardcoded in `_SECRET_MEETINGS_REF` — averaged from Secret Meetings rows with terp data on 5/02. Update if Crops genetics drift, or build dynamic reference selection from the email command (`going to conservatory like high society`).
  - Clone tolerance default 0.05: tighter rejects even genuine SM (lab-to-lab variation), looser flags strains with real myrcene/linalool divergence. Calibrated 5/02.
  - **Strain-name parser handles 4 conventions**: Conservatory `BRAND|STRAIN|SIZE`, Med Leaf `STRAIN|SIZE|CATEGORY`, sub-branded `SUB|STRAIN|SIZE` (e.g. Harvest Moon's MADE line), and 4-segment `BRAND|SUB|STRAIN|SIZE` (Magic Garden Botanicals). `_strain_label_from_product` filters out brand + size + category tokens and returns the longest survivor. If a new store has a 5th format, extend `_NON_STRAIN_TOKENS` / `_SIZE_TOKEN_RE`.
  - **Acknowledged limitations** (worth fixing if they bite):
    - Subtype label is a threshold cliff at 5pp gap between top two terps. A 5.1pp gap and a 4.9pp gap land on different labels ("led" vs "balanced") despite being identical in feel. Showing the actual gap inline (e.g. "lim-led (gap 8pp)") would smooth this.
    - `dispensary_menu` snapshots accumulate forever (~750 rows per trigger now that both stores refresh). No retention policy. Revisit if it gets unwieldy — Eric chose to defer the audit/prune work.
    - Per-trip `going to` only re-scrapes Conservatory + Med Leaf hardcoded in the side-effect loop. If a new DispenseApp store is added, update that loop too.

## Email Layout Order

greeting → date → day of life → steps → weather → calendar → devils → listening → strain → monthly recap

## Ideas Parked for Later
- **Email-to-Claude planning**: User emails "idea: [description]" → `commands.py` calls Anthropic API → Claude writes a plan → emailed back + saved to ideas table. Needs an Anthropic API key (console.anthropic.com).
- **MAL SQL bucket**: Add a classification in `sql_qualification_status` for converted MAL leads, so their conversion rate is tracked separately from regular PQL SQLs. Work file: `work/leads_simple.sql` (dbt/Snowflake model).
- **Guapa music data → Homebase**: Guapa Inc is building a music data product (artist similarity, discovery, Last.fm/MusicBrainz). Homebase will eventually consume it for a "recommended new releases" section. Homebase = consumer, Guapa = data provider — like YouTube to Google. Wait until Guapa's product is ready before building the Homebase side.
- **Strain rating system**: A `strain_stock_ratings` table to correlate Eric's personal experience with terpene profiles over time. Parked — needs the trip planner to mature first.
- **Cross-dispensary price comparison and batch quality tracking**: long-term direction for the strain tracker, building on accumulated `strain_stock` and `dispensary_menu` history.
- **Dynamic reference profile** for the trip planner: take a strain name from the email command (`going to conservatory like high society`) and build the reference on the fly instead of using the hardcoded SM profile.

## Accounts

- Homebase sends/receives as: `eewilliamsremote@gmail.com`
- Personal (send summaries to): `ewill22@gmail.com`
- ewill22 Google Calendar is shared read-only — homebase cannot edit it
