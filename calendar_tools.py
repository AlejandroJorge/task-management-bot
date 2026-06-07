import os
from datetime import datetime, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

import auth

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")


def _service():
    token = auth.get_refresh_token()
    if not token:
        raise RuntimeError("Google Calendar is not authenticated. Send /login to set it up.")
    creds = Credentials(
        token=None,
        refresh_token=token,
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return build("calendar", "v3", credentials=creds)


def create_event(
    summary: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    timezone: str = "UTC",
) -> dict:
    """
    Create an event. start/end are ISO 8601 strings with offset,
    e.g. "2026-06-07T14:00:00-05:00". Returns the created event dict.
    """
    body = {
        "summary": summary,
        "description": description,
        "location": location,
        "start": {"dateTime": start, "timeZone": timezone},
        "end": {"dateTime": end, "timeZone": timezone},
    }
    return _service().events().insert(calendarId=CALENDAR_ID, body=body).execute()


def list_events(max_results: int = 10, time_min: str | None = None) -> list[dict]:
    """
    Return upcoming events ordered by start time.
    time_min defaults to now (UTC). Returns a list of event dicts.
    """
    if time_min is None:
        time_min = datetime.now(tz=timezone.utc).isoformat()
    result = (
        _service()
        .events()
        .list(
            calendarId=CALENDAR_ID,
            timeMin=time_min,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return result.get("items", [])


def update_event(event_id: str, **fields) -> dict:
    """
    Patch an existing event by ID. Accepted keyword args:
      summary, description, location   → plain strings
      start, end                        → ISO 8601 datetime strings
    Returns the updated event dict.
    """
    body: dict = {}
    for key in ("summary", "description", "location"):
        if key in fields:
            body[key] = fields[key]
    for key in ("start", "end"):
        if key in fields:
            body[key] = {"dateTime": fields[key]}
    return (
        _service()
        .events()
        .patch(calendarId=CALENDAR_ID, eventId=event_id, body=body)
        .execute()
    )


def delete_event(event_id: str) -> None:
    """Permanently delete an event by its ID."""
    _service().events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
