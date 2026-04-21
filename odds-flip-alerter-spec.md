# Odds Flip Alerter — Build Spec

## Goal

Build a scheduled job that emails me when an **NHL pre-game favorite's live moneyline flips to a plus number** during the game. This typically happens when a favored team gives up the first goal (e.g., Penguins open -142, get scored on first, live ML drifts to +108). That's the bet window I want to catch.

**Pattern in one sentence:** team opens at negative odds → at any point during the live game, same team is now at positive odds → send email.

**Scope:** NHL only. Free tier of The Odds API (500 req/month). Staying under that budget is a hard requirement, not a nice-to-have.

---

## Core Trigger Logic

For each game on the slate:

1. **Opening snapshot (pre-game):** On the first time we see a game, capture `opening_ml_home` and `opening_ml_away` from the consensus/first bookmaker. Persist these. Never overwrite.
2. **Identify the opening favorite:** whichever side has the negative number. If the line is a pick-em (both around +100/-105), skip — no favorite to flip.
3. **Live polling:** Once `commence_time` has passed and the game isn't final, pull live odds every N minutes.
4. **Flip detection:** If `opening_favorite`'s live ML is now positive → **fire alert** → mark this game as "alerted" so we don't spam repeats.
5. **Cooldown/dedup:** One alert per game per flip event. If odds flip back and then re-flip, that's a judgment call — default to one-per-game only, make it configurable.

**Edge cases to handle:**
- Pick-em games (skip)
- Postponed games (skip, don't consume API calls)
- Games where we missed the opening pull (skip — can't detect a flip without a baseline)
- Bookmaker outage / missing markets (retry next cycle, don't error out)
- Multiple bookmakers: use DraftKings as the primary, FanDuel as fallback (configurable)

---

## Data Source

**The Odds API** (https://the-odds-api.com) — **free tier, 500 requests/month.** Staying within this requires aggressive gating.

**Sport:** `icehockey_nhl` only. No other sports.

**Two endpoints we use:**

1. **`GET /v4/sports/{sport}/events`** — **FREE, does not count against quota.** Returns event IDs, teams, and commence times. No odds. Use this as a cheap "what's live / starting soon?" check on every cron run.
2. **`GET /v4/sports/{sport}/odds`** — **1 credit per call.** Only call this when we actually need odds (capturing opener or polling a live game).

**Market param:** `h2h` (moneyline) only.
**Regions:** `us`. **Bookmakers:** `draftkings` (primary). A single bookmaker keeps the call cost exactly 1 credit.

### Cost Math (NHL playoffs — right now through ~June 20)

Assumptions for round 1 / round 2:
- ~20 game days per month (playoffs aren't every day)
- ~3 games per game day on average
- Live window per game: ~2.5 hours
- Staggered starts mean total live hours per game day: ~5 hours

Budget per game day:
- 1 opener capture per game × 3 games = 3 credits
- Live polling every 20 min during 5-hour window = 15 credits
- **Total: ~18 credits/game day × 20 game days = 360 credits/month** ✓

That leaves ~140 credits/month of buffer for retries, multi-game overlap nights, and Round 3/Finals schedule compression.

### Hard rules to stay under 500

- Use `/events` (free) to decide if the paid `/odds` call is worth making
- Only poll live games — stop polling once a game is final
- Only poll games where we captured an opener (no opener = can't detect flip)
- **Don't poll in the 3rd period.** A flip in the 3rd when the favorite is down 4-1 is a blowout, not a bet. Saves ~1/3 of in-play calls and they're the least actionable ones anyway.
- Skip postponed games
- When the NHL season ends (mid-June through October), the workflow should auto-idle — no games means no calls

### When the season is over

Playoffs end mid-June. From mid-June through early October, there are zero NHL games and the job should make zero paid API calls. The free `/events` check will return an empty list and we exit early. Don't disable the cron — let it run, it'll just no-op until October.

---

## Architecture

```
┌─────────────────────┐
│  GitHub Actions     │  cron: every 10 min
│  (scheduled job)    │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐      ┌──────────────────┐
│  fetch_odds.py      │─────▶│  The Odds API    │
│  - pull slate       │      └──────────────────┘
│  - diff vs state    │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  state.json (or     │   committed back to repo
│  SQLite in repo)    │   so state persists across runs
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐      ┌──────────────────┐
│  alerter.py         │─────▶│  Resend API      │
│  - detect flips     │      │  (or SMTP)       │
│  - send email       │      └──────────────────┘
└─────────────────────┘
```

**Why GitHub Actions over the Windows desktop:** the music pipeline can afford to miss a day if the PC is off. This can't — a flip happens in a 30-min window and is gone. GitHub Actions cron is free, runs on hosted infra, and minimum granularity of 5 min is fine for this use case.

**State persistence:** Simplest approach = commit a `state.json` back to the repo at the end of each run. Slightly ugly but zero infra. Alternative: a free Supabase/Turso/Neon instance. Start with the JSON, migrate if it gets noisy.

---

## Repo Structure

```
odds-flip-alerter/
├── .github/
│   └── workflows/
│       └── poll-odds.yml          # cron every 10 min
├── src/
│   ├── fetch_events.py            # FREE /events endpoint — gate before paid calls
│   ├── fetch_odds.py              # PAID /odds endpoint — tracked against budget
│   ├── detect_flips.py            # core logic
│   ├── notify.py                  # email sender
│   ├── state.py                   # read/write state.json
│   └── main.py                    # orchestrator
├── tests/
│   ├── fixtures/
│   │   ├── pregame_response.json
│   │   ├── in_play_flip.json
│   │   └── in_play_no_flip.json
│   ├── test_detect_flips.py
│   └── test_state.py
├── state.json                     # committed, updated by workflow
├── config.yaml                    # sports, books, thresholds
├── requirements.txt
└── README.md
```

---

## Implementation Tasks

### Phase 1 — Core pipeline (ship this first, test end-to-end)

1. **Scaffold repo** with `requirements.txt` (`requests`, `pyyaml`, `python-dotenv`). Python 3.11+.
2. **`config.yaml`** (see Config section below for full example).
3. **`fetch_events.py`**: `get_events() -> list[Event]`. Calls the FREE `/events` endpoint. Returns event IDs, teams, commence times. **Never costs a credit.** Call this on every cron run.
4. **`fetch_odds.py`**: `get_odds() -> list[GameOdds]`. Calls the paid `/odds` endpoint. **Increments the API call counter in state.** Returns a typed dataclass, not raw JSON. Handle 429s with backoff.
5. **`state.py`**: `load_state() / save_state()`. Schema:
   ```json
   {
     "api_calls_this_month": 37,
     "month_key": "2026-04",
     "games": {
       "<event_id>": {
         "home": "Pittsburgh Penguins",
         "away": "Philadelphia Flyers",
         "commence_time": "2026-04-18T00:00:00Z",
         "opening_ml_home": -142,
         "opening_ml_away": 118,
         "opening_favorite": "home",
         "opening_captured_at": "...",
         "period": 2,
         "status": "in_play",
         "alerted": false,
         "alerted_at": null,
         "final": false
       }
     }
   }
   ```
   Reset `api_calls_this_month` and `month_key` on the 1st of each month.
6. **`detect_flips.py`**: pure function. Inputs: current odds + stored state. Outputs: list of flip events + updated state. No I/O here — easy to unit test.
7. **`notify.py`**: Resend API (https://resend.com) — 3,000 free emails/month, one-line setup, deliverable. Fallback: Gmail SMTP via app password.
8. **`main.py`**: orchestrator with this decision tree:
   ```
   load_state()
   if new month: reset counter
   events = fetch_events()                          # free
   relevant = filter(events, live or starting <30min)
   if not relevant: exit 0                          # no-op, saves credits
   for each game in relevant:
       if in 3rd period and skip_third_period: skip
       if no opener yet and game not started: capture opener (1 credit)
       if game is live and has opener: poll odds (1 credit)
   run detect_flips on results
   send emails for any flips
   save_state()
   ```
9. **GitHub Actions workflow**: cron `*/15 * * * *` (every 15 min — `/events` is free so this is cheap). Commits `state.json` back via `stefanzweifel/git-auto-commit-action`. Secrets: `ODDS_API_KEY`, `RESEND_API_KEY`, `ALERT_EMAIL`.

### Phase 2 — Polish

10. **Budget guard:** `main.py` aborts before any paid call if `api_calls_this_month >= 500`. Log a warning so I see it in the Actions run log.
11. **Email formatting:** HTML email with team logos (ESPN CDN has them), opening line, current line, link to DraftKings for the game.
12. **Flip history log:** append every flip event to `history.json` so we can review hit rate later — was the live bet actually +EV?

### Phase 3 — Stretch

13. **Confidence filtering:** only alert if the opener was -140 or shorter (bigger mismatch = juicier live line when they fall behind).
14. **Score context:** cross-reference the `/scores` endpoint (also free — doesn't count against quota per The Odds API docs, but confirm before relying on it) so the email includes "PIT down 2-0 in the 2nd" — tells me *why* the line flipped and whether it's still a live-bet opportunity.
15. **Telegram/SMS alternative** for faster notifications than email (email latency can be 30-60s).

---

## Config & Secrets

Environment variables (set as GitHub Actions secrets):

```
ODDS_API_KEY=...              # the-odds-api.com
RESEND_API_KEY=...            # resend.com (or SMTP creds)
ALERT_EMAIL=<my-email>
```

`config.yaml`:

```yaml
sport: icehockey_nhl          # NHL only
bookmaker: draftkings         # single book, keeps API cost at 1 credit/call
region: us
min_opening_favorite: -120    # don't track pick-ems
alert_once_per_game: true
poll_window_hours_before: 0.5 # start polling 30 min before puck drop
live_poll_interval_minutes: 20
skip_third_period: true       # flips in 3rd are usually blowouts, not actionable
monthly_api_budget: 500       # free tier ceiling — HARD STOP when hit
```

---

## Testing

- **Unit tests** for `detect_flips.py` using fixture JSON files. Cover: opener capture, flip detected, no-flip, already-alerted, pick-em skip, 3rd-period skip, missing bookmaker, budget-exceeded.
- **Dry-run mode**: `--dry-run` flag on `main.py` that prints what would be emailed without sending or committing state. Useful for first week of operation.
- **Replay mode**: feed historical odds into the pipeline to verify it would've caught known flips (e.g., an NHL playoff game where a -140 favorite gave up the first goal and drifted to +money).

---

## Acceptance Criteria

- [ ] Job runs every 15 minutes on GitHub Actions without failure
- [ ] Opening moneylines are captured once per game and never overwritten
- [ ] When a pre-game favorite's live ML flips to positive, I get an email within 20 minutes
- [ ] No duplicate alerts for the same game
- [ ] State persists across runs via committed `state.json`
- [ ] **API usage stays under 500 req/month** (free tier ceiling) — tracked in state, hard-stopped when hit
- [ ] No paid `/odds` calls are made when no NHL games are live or starting soon
- [ ] All logic in `detect_flips.py` is unit-tested

---

## Open Questions for Me (Eric)

1. Email or SMS/Telegram? Email latency could mean missing the bet window.
2. Should the alert include a bet recommendation (e.g., "bet $X at current +108") or just the data?
3. Track flip history to analyze hit rate over a season? (Easy add — one extra JSON file.)
