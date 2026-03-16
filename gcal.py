from gcal_auth import get_calendar_creds
from googleapiclient.discovery import build
from datetime import datetime, timezone, timedelta

DEVILS_CAL_ID = "nhl_-m-0hm2b_%4eew+%4aersey+%44evils#sports@group.v.calendar.google.com"


def get_service():
    return build("calendar", "v3", credentials=get_calendar_creds())

def get_upcoming_events(days=7, max_results=10, user_id=1):
    """Return upcoming events within the next N days across all personal calendars."""
    from config import get_config
    calendar_ids = get_config(user_id)["personal_cal_ids"]

    service = get_service()
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)

    all_events = []
    for cal_id in calendar_ids:
        result = service.events().list(
            calendarId=cal_id,
            timeMin=now.isoformat(),
            timeMax=end.isoformat(),
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        all_events += result.get("items", [])

    all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date")))
    return all_events

def get_devils_games(days=14):
    """Return upcoming Devils games within the next N days."""
    service = get_service()
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)

    result = service.events().list(
        calendarId=DEVILS_CAL_ID,
        timeMin=now.isoformat(),
        timeMax=end.isoformat(),
        maxResults=5,
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    return result.get("items", [])

def create_event(summary, start_dt, end_dt, description=None):
    """Create a calendar event on the primary calendar."""
    service = get_service()
    event = {
        "summary": summary,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "America/New_York"},
        "end":   {"dateTime": end_dt.isoformat(),   "timeZone": "America/New_York"},
    }
    if description:
        event["description"] = description

    return service.events().insert(calendarId="primary", body=event).execute()
