# Odds Flip Alerter

NHL playoff flip detector. Texts Eric via the Google Fi SMS gateway when a pregame favorite's live moneyline crosses to positive (the favorite just got scored on first), and enriches every alert with the favorite's Corsi shot share so he can tell a real collapse from a fluky bounce.

Built for the 2026 NHL playoffs (Apr–Jun 2026). Reassess in the off-season.

---

## The bet this is watching for

Pregame favorite opens at, say, PIT -142. They give up the first goal in the 1st or 2nd period, and the live line swings to PIT +108. That's the **flip** — a short window where the market overreacts to the first goal and you can buy the favorite back at plus money. This tool's job is to text me the instant that happens so I don't have to stare at DraftKings all night.

CF% (shot share) gets bolted on so I can separate "they're outplaying but unlucky" (buy) from "they're getting caved in" (pass). Added after day 1 when Pittsburgh got torched in every phase and the flip was still showing +108.

---

## How it runs

Windows Task Scheduler fires every 15 minutes:

```
pythonw.exe -m odds_alerter.main
```

The orchestrator `main.py` does, in order:

1. **Quiet hours** — no-op between 11 PM and 2 PM ET
2. **Free `/events`** — lists today's NHL games
3. **Budget guard** — halt if monthly credit count ≥ `MONTHLY_API_BUDGET` (500)
4. **Classify** each event: need opener capture, live, or skip
5. **Maybe `/scores`** — only if at least one game is past `SCORES_ELAPSED_TRIGGER_MIN` (75 min) AND we haven't called /scores in `SCORES_MIN_INTERVAL_MIN` (30 min)
6. **Per-game polling decision** — `/odds` is sport-wide so one call covers all games; 3rd-period games skipped (`SKIP_THIRD_PERIOD`)
7. **`/odds`** — fetches moneyline for the whole slate (1 credit)
8. **Opener capture** — first time we see a game inside the 2h pregame window, store the opening line
9. **NHL CF%** — for every live game, fetch Corsi from the free `api-web.nhle.com/v1/gamecenter/{id}/play-by-play` endpoint
10. **Flip + threshold detection** — `detect_flips.py` checks if opener was favorite and current is plus; `main.py` checks CF% crosses 45/55 boundaries
11. **Flip alerts** — once per game, enriched with CF% read
12. **CF% threshold alerts** — fires on direction change (below 45 or above 55), deduped by `last_cf_alert_dir`
13. **Watch-command pulses** — for any active `odds_watch` row, sends a per-cycle status text

---

## Module layout

```
odds_alerter/
├── __init__.py
├── config.py            # All tunables — change here, not inline
├── state.py             # MySQL accessors (homebase DB)
├── fetch_events.py      # FREE /events endpoint
├── fetch_odds.py        # PAID /odds (1 credit, sport-wide)
├── fetch_scores.py      # PAID /scores (1 credit, sport-wide) — spec was wrong about this being free
├── nhl_api.py           # FREE NHL public API — schedule lookup + Corsi from play-by-play
├── detect_flips.py      # Pure functions — identify_favorite, is_flip, favorite_line
├── notify.py            # Message composers + Google Fi SMS gateway sender
├── main.py              # Orchestrator — run via pythonw.exe -m odds_alerter.main
└── README.md            # This file
```

---

## Budget math

The Odds API free tier: **500 credits/month**.

| Endpoint | Cost | When called |
|---|---|---|
| `/events` | free | every cycle that isn't in quiet hours |
| `/odds` | 1 credit, sport-wide | every 15 min during an active slate |
| `/scores` | 1 credit, sport-wide | rate-limited: only when a game is past 75 min elapsed AND ≥30 min since last /scores |

At 15-min cadence with a ~3–4 hour slate, that's roughly `(3.5 * 60 / 15) = 14` cycles per day × 1 /odds credit + ~4 /scores credits ≈ 18–20 credits/day. Over a 2-month playoff window that's well under 500/mo.

**NHL public API** (`api-web.nhle.com/v1`) is free, no key, and the CF% fetch runs every cycle per live game without touching the quota.

---

## State (MySQL in the `homebase` DB)

- **`odds_games`** — per-event row. Columns for opener (ml_home/away, favorite), current odds, score + period, NHL game id, `last_cf_*` snapshot, `last_cf_alert_dir` (ENUM for dedup), `alerted` flag, `status`, `final`.
- **`odds_api_usage`** — one row per `YYYY-MM` with `paid_calls` counter, `last_endpoint`, `last_call_at`.
- **`odds_flip_history`** — append-only log of every flip alert (event, favorite, opening/current ml, score, period, message sent, sms_ok flag).
- **`odds_watch`** — active `watch TEAM` subscriptions. One row per subscription, `active` flag flips to FALSE when the game goes final.

---

## Alert types

### 1. Flip alert (once per game)
```
you watching this? favorite just got scored on, PIT opened -142, now +108 live. Down 1-0 2nd. PIT 38% shot share - getting outplayed
```

### 2. CF% threshold crossing (deduped by direction)
```
PIT is being outplayed - 38% shot share, 2nd, tied 1-1
PIT is dominating - 62% shot share, 2nd, down 1-0
```
Fires when the favorite's CF% crosses below 45 or above 55 with ≥15 shot attempts on the board. Direction is persisted in `last_cf_alert_dir`; resets to NULL when CF% settles back into the 45–55 band so the next swing can re-fire.

### 3. Watch command pulse (on demand, every cycle while active)
Email subject `watch PIT` → inserts row into `odds_watch` → every cycle sends:
```
PIT 1 PHI 1 | 2nd | 38% shots
```
Auto-deactivates when `odds_games.final = TRUE`.

---

## Delivery

`notify.py::send_flip_alert(phone_number, message)`:
1. Primary: SMS via `<phone>@msg.fi.google.com` (Google Fi gateway)
2. Backup: email to `ewill22@gmail.com` with subject `odds alert`

Both attempts are wrapped in try/except so a single failure doesn't block the other.

**ASCII-only bodies.** Em-dashes replaced with `-`, middots with `|`. The Google Fi gateway has been flaky with non-ASCII characters and subject-line Unicode.

---

## Phone number + API key

Both live in `homebase/.env`:
```
ODDS_API_KEY=...
ALERT_SMS_TO=9083190212
```

---

## Day 1 notes (2026-04-19)

- Went live at ~4 PM. Net result: **-$0.50 open, +$0.19 close, +$0.69 day**.
- Burned 34 credits in ~3.5 hours — hotter than projected. Causes:
  - 10-min poll instead of spec's 20 (now 15)
  - `/scores` fired every cycle past a 60-min elapsed gate (now 75 min + 30-min min interval)
  - Slate longer than my 5-hour estimate
- Spec was wrong about `/scores` being free. It's 1 credit. Any future optimization should treat it as paid.

## Day 2 notes (2026-04-20)

- Added NHL CF% via `nhl_api.py` (free — no quota impact)
- Flip alerts now include favorite CF% and a read ("getting outplayed" / "dominating" / "game is even")
- New threshold-crossing alert type (45/55 bounds, 15-attempt minimum, dedup by `last_cf_alert_dir`)
- New on-demand `watch <TAG>` email command via `commands.py`
