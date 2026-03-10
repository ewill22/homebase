# Homebase

A personal command center for household data, automation, and communication.
Built with Python + MySQL + Gmail.

---

## Infrastructure

### Database
- MySQL running locally at `127.0.0.1:3306`
- Database: `homebase` (separate from business data)
- Connection helper: `db.py` — any script imports `get_connection()` and its ready

### Email
- Outbound (sending): `emailer.py` — `send_email(subject, body, to=None)`
- Inbound (reading/managing): `gmail.py` — IMAP access to `eewilliamsremote@gmail.com`
- Commands can be sent from `ewill22@gmail.com` or `eewilliamsremote@gmail.com`

---

## What's Running

### Weather (`weather.py`)
Pulls current conditions for Northfield, NJ from Open-Meteo (free, no API key).
Stores readings in the `weather` table over time.

| Column | Description |
|---|---|
| recorded_at | Timestamp of reading |
| temp_f | Temperature in °F |
| humidity_pct | Relative humidity % |
| wind_mph | Wind speed in mph |

### Email Command Listener (`commands.py`)
Runs every 5 minutes via Windows Task Scheduler.
Checks inbox for unread emails from trusted senders and responds automatically.

**Trusted senders:** `ewill22@gmail.com`, `eewilliamsremote@gmail.com`

#### Available Commands (email subject)
| Subject | Response |
|---|---|
| "how are things at home" | Home summary with current weather |
| "hows it going at home" | Same as above |
| "whats up at home" | Same as above |

---

## What's Possible Next

### More summary data
Anything tracked in MySQL can be added to the home summary email:
- Bills due / upcoming expenses
- Tasks or reminders
- Notes you've logged

### More email commands
Adding a new command is two lines of code — a trigger phrase and a function.
Examples of what could be added:
- "add task [something]" → writes to a tasks table
- "remind me to [x] at [time]" → sets a reminder
- "log expense [amount] [category]" → tracks spending

### Scheduled reports
Instead of asking, homebase emails you automatically on a schedule:
- Morning briefing with weather
- Weekly summaries of anything tracked

### Gmail management
- Bulk delete/archive by sender or subject
- Auto-clean newsletters, promotions, alerts

---

## File Structure

```
homebase/
├── .env              # Credentials (never commit this)
├── db.py             # MySQL connection helper
├── emailer.py        # Send emails via Gmail SMTP
├── gmail.py          # Read/manage emails via IMAP
├── weather.py        # Fetch and store weather data
├── commands.py       # Email command listener
└── README.md         # This file
```
