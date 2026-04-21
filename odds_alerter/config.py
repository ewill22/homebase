"""Tunables for the odds flip alerter. Adjust here, not inline."""

SPORT       = "icehockey_nhl"
BOOKMAKER   = "draftkings"
REGION      = "us"
MARKET      = "h2h"
ODDS_FORMAT = "american"

# Line filtering
MIN_OPENING_FAVORITE = -120   # skip pick-ems (fav shorter than -120 means |ml| >= 120)

# Polling cadence — scheduler fires every 15 min (was 10 on day 1; dropped to save budget)
POLL_INTERVAL_MIN    = 15     # min wait between /odds calls for the same game
PRE_GAME_WINDOW_MIN  = 120    # start considering games this many min before puck drop

# Period handling
SKIP_THIRD_PERIOD    = True
THIRD_PERIOD_ELAPSED_MIN   = 85   # rough floor for "likely in 3rd" if NHL API period is missing

# /scores endpoint was retired 2026-04-21 — score + period now come from NHL
# play-by-play (free, real-time). fetch_scores.py kept for reference but unused.

# CF% (Corsi) thresholds for shot-share alerts (NHL API, free)
CF_LOW_THRESHOLD       = 45   # favorite under this % → getting outplayed, alert
CF_HIGH_THRESHOLD      = 55   # favorite over this % → dominating, alert (flip is fake)
CF_MIN_SAMPLE_ATTEMPTS = 15   # don't alert until enough shot attempts to be meaningful

# Dedup
ALERT_ONCE_PER_GAME  = True

# Budget
MONTHLY_API_BUDGET   = 500     # free tier ceiling — hard stop
BUDGET_WARN_AT       = 450

API_BASE = "https://api.the-odds-api.com/v4"
