import logging
from datetime import datetime

import tz as _tz
from calendar_tools import _TRACKING, _get_calendar_id, _service
from categories import color_id_for

logger = logging.getLogger(__name__)


def _assert_past(dt_str: str, label: str) -> datetime:
    dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is None:
        raise ValueError(f"{label} debe incluir zona horaria (ej. -05:00)")
    from datetime import timedelta
    if dt > _tz.now() + timedelta(seconds=5):
        raise ValueError(f"{label} debe ser en el pasado")
    return dt


def _check_collision(start: str, end: str, exclude_id: str | None = None) -> None:
    items = (
        _service()
        .events()
        .list(
            calendarId=_get_calendar_id(_TRACKING),
            timeMin=start,
            timeMax=end,
            singleEvents=True,
        )
        .execute()
        .get("items", [])
    )
    conflicts = [e for e in items if e.get("id") != exclude_id]
    if conflicts:
        names = ", ".join(e.get("summary", "?") for e in conflicts)
        raise ValueError(f"Conflicto con bloque existente: {names}")


def get_timeblock(event_id: str) -> dict:
    return _service().events().get(calendarId=_get_calendar_id(_TRACKING), eventId=event_id).execute()


def create_timeblock(activity: str, start: str, end: str, notes: str = "", category: str = "unclassified") -> dict:
    dt_start = _assert_past(start, "Inicio")
    dt_end = _assert_past(end, "Fin")
    if dt_start >= dt_end:
        raise ValueError("El inicio debe ser antes que el fin")
    _check_collision(start, end)
    body = {
        "summary": activity,
        "description": notes,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
        "colorId": color_id_for(category) or "3",
        "extendedProperties": {"private": {"category": category}},
    }
    result = _service().events().insert(calendarId=_get_calendar_id(_TRACKING), body=body).execute()
    logger.info("Timeblock created: %s [%s – %s] category=%s", activity, start, end, category)
    return {**result, "category": category}


def list_timeblocks(time_min: str, time_max: str) -> list[dict]:
    items = (
        _service()
        .events()
        .list(
            calendarId=_get_calendar_id(_TRACKING),
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
        .get("items", [])
    )
    return [
        {
            "event_id": e["id"],
            "activity": e.get("summary", ""),
            "start": e["start"].get("dateTime", ""),
            "end": e["end"].get("dateTime", ""),
            "notes": e.get("description", ""),
            "category": e.get("extendedProperties", {}).get("private", {}).get("category", "unclassified"),
        }
        for e in items
    ]


def update_timeblock(event_id: str, **fields) -> dict:
    svc = _service()
    cal_id = _get_calendar_id(_TRACKING)
    current = svc.events().get(calendarId=cal_id, eventId=event_id).execute()

    body: dict = {}
    if "activity" in fields:
        body["summary"] = fields["activity"]
    if "notes" in fields:
        body["description"] = fields["notes"]
    if "category" in fields:
        body["colorId"] = color_id_for(fields["category"]) or "3"
        body["extendedProperties"] = {"private": {"category": fields["category"]}}

    current_start = current["start"]["dateTime"]
    current_end = current["end"]["dateTime"]

    if "start" in fields:
        _assert_past(fields["start"], "Inicio")
        body["start"] = {"dateTime": fields["start"]}
    if "end" in fields:
        _assert_past(fields["end"], "Fin")
        body["end"] = {"dateTime": fields["end"]}

    new_start = fields.get("start", current_start)
    new_end = fields.get("end", current_end)
    _check_collision(new_start, new_end, exclude_id=event_id)

    return svc.events().patch(calendarId=cal_id, eventId=event_id, body=body).execute()


def delete_timeblock(event_id: str) -> None:
    _service().events().delete(calendarId=_get_calendar_id(_TRACKING), eventId=event_id).execute()
    logger.info("Timeblock deleted: %s", event_id)
