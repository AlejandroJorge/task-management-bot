import logging
import os
from datetime import datetime, timezone

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

import auth

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]

_EVENTOS  = "Eventos"
_TRACKING = "Tracking"  # reserved for future tracking tools

_calendar_ids: dict[str, str] = {}


def _get_calendar_id(name: str) -> str:
    if name in _calendar_ids:
        return _calendar_ids[name]
    svc = _service()
    items = svc.calendarList().list().execute().get("items", [])
    for cal in items:
        if cal.get("summary") == name:
            _calendar_ids[name] = cal["id"]
            logger.info("Resolved calendar '%s' → %s", name, cal["id"])
            return cal["id"]
    logger.info("Calendar '%s' not found — creating it.", name)
    created = svc.calendars().insert(body={"summary": name}).execute()
    cal_id = created["id"]
    _calendar_ids[name] = cal_id
    logger.info("Created calendar '%s' → %s", name, cal_id)
    return cal_id


def _service():
    token = auth.get_refresh_token()
    if not token:
        raise RuntimeError("Google Calendar no autenticado. Usa /login para conectarlo.")
    creds = Credentials(
        token=None,
        refresh_token=token,
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    try:
        creds.refresh(Request())
    except RefreshError:
        logger.error("Google credentials refresh failed — token revoked or expired.")
        auth.clear_token()
        raise RuntimeError(
            "Las credenciales de Google expiraron o fueron revocadas. "
            "Usa /login para autenticarte de nuevo."
        )
    return build("calendar", "v3", credentials=creds)


def create_event(
    summary: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    tz: str = "America/Lima",
) -> dict:
    body = {
        "summary": summary,
        "description": description,
        "location": location,
        "start": {"dateTime": start, "timeZone": tz},
        "end": {"dateTime": end, "timeZone": tz},
    }
    return _service().events().insert(calendarId=_get_calendar_id(_EVENTOS), body=body).execute()


def list_events(
    max_results: int = 10,
    time_min: str | None = None,
    time_max: str | None = None,
) -> list[dict]:
    if time_min is None:
        time_min = datetime.now(tz=timezone.utc).isoformat()
    kwargs: dict = dict(
        calendarId=_get_calendar_id(_EVENTOS),
        timeMin=time_min,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    )
    if time_max:
        kwargs["timeMax"] = time_max
    result = (
        _service()
        .events()
        .list(
            **kwargs,
        )
        .execute()
    )
    return result.get("items", [])


def update_event(event_id: str, **fields) -> dict:
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
        .patch(calendarId=_get_calendar_id(_EVENTOS), eventId=event_id, body=body)
        .execute()
    )


def delete_event(event_id: str) -> None:
    _service().events().delete(calendarId=_get_calendar_id(_EVENTOS), eventId=event_id).execute()
