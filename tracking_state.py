import json
import logging
import os
from datetime import datetime, timedelta

import tz as _tz
from calendar_tools import _TRACKING, _get_calendar_id, _service

logger = logging.getLogger(__name__)

_STATE_PATH = os.getenv("TRACKING_STATE_PATH", "data/tracking_state.json")
_state: dict = {"status": "LIBRE"}


def load_state() -> dict:
    global _state
    try:
        with open(_STATE_PATH) as f:
            _state = json.load(f)
        logger.info("Tracking state loaded: %s", _state.get("status"))
    except FileNotFoundError:
        _state = {"status": "LIBRE"}
    except Exception:
        logger.exception("Failed to load tracking state, defaulting to LIBRE")
        _state = {"status": "LIBRE"}
    return dict(_state)


def save_state() -> None:
    try:
        parent = os.path.dirname(_STATE_PATH)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(_STATE_PATH, "w") as f:
            json.dump(_state, f)
    except Exception:
        logger.warning(
            "TRACKING STATE NOT PERSISTED — in-memory state diverges from disk. "
            "A restart will load stale state.",
            exc_info=True,
        )


def get_state() -> dict:
    state = dict(_state)
    if state.get("status") == "ACTIVO" and state.get("started_at"):
        try:
            started = datetime.fromisoformat(state["started_at"])
            elapsed = max(0, int((_tz.now() - started).total_seconds() / 60))
            state["elapsed_minutes"] = elapsed
        except Exception:
            state["elapsed_minutes"] = 0
    return state


def _patch_end(event_id: str, end_iso: str) -> None:
    _service().events().patch(
        calendarId=_get_calendar_id(_TRACKING),
        eventId=event_id,
        body={"end": {"dateTime": end_iso}},
    ).execute()


def _recreate_event() -> None:
    global _state
    try:
        now = _tz.now()
        started_raw = _state.get("started_at")
        if not started_raw:
            logger.warning("Cannot recreate tracking event: started_at missing from state")
            return
        started = datetime.fromisoformat(started_raw)
        event = _service().events().insert(
            calendarId=_get_calendar_id(_TRACKING),
            body={
                "summary": _state["activity"],
                "start": {"dateTime": started.isoformat()},
                "end": {"dateTime": now.isoformat()},
            },
        ).execute()
        _state["event_id"] = event["id"]
        save_state()
        logger.info("Tracking event recreated: %s", event["id"])
    except Exception:
        logger.exception("Failed to recreate tracking event")


def sync_to_calendar() -> None:
    if _state.get("status") != "ACTIVO":
        return
    event_id = _state.get("event_id")
    if not event_id:
        logger.warning("sync_to_calendar: no event_id in state, skipping")
        return
    now = _tz.now()
    try:
        _patch_end(event_id, now.isoformat())
        logger.info("Tracking synced: %s end → %s", _state.get("activity"), now.strftime("%H:%M"))
    except Exception:
        logger.exception("Calendar sync failed for event_id=%s, recreating", event_id)
        _recreate_event()


def start_tracking(activity: str, started_at: str | None = None) -> dict:
    global _state
    if _state.get("status") == "ACTIVO":
        raise ValueError(
            f"Ya estás trackeando '{_state['activity']}'. Deténlo primero con stop_tracking."
        )
    now = _tz.now()

    if started_at:
        try:
            event_start = datetime.fromisoformat(started_at)
        except ValueError:
            raise ValueError("started_at debe ser ISO 8601 con zona horaria, ej. 2026-06-07T22:17:00-05:00")
        if event_start.tzinfo is None:
            raise ValueError("started_at debe incluir zona horaria (ej. -05:00)")
        if event_start >= now:
            raise ValueError("started_at debe ser un momento en el pasado")
        items = _service().events().list(
            calendarId=_get_calendar_id(_TRACKING),
            timeMin=event_start.isoformat(),
            timeMax=now.isoformat(),
            singleEvents=True,
        ).execute().get("items", [])
        if items:
            names = ", ".join(e.get("summary", "?") for e in items)
            raise ValueError(f"Hay bloques registrados en ese intervalo ({names})")
    else:
        event_start = now

    event = _service().events().insert(
        calendarId=_get_calendar_id(_TRACKING),
        body={
            "summary": activity,
            "start": {"dateTime": event_start.isoformat()},
            "end": {"dateTime": (now + timedelta(minutes=1)).isoformat()},
        },
    ).execute()
    _state = {
        "status": "ACTIVO",
        "activity": activity,
        "started_at": event_start.isoformat(),
        "event_id": event["id"],
    }
    save_state()
    logger.info("Tracking started: %s [event_id=%s, started_at=%s]", activity, event["id"], event_start.isoformat())
    return get_state()


def resume_as_live(event_id: str) -> dict:
    global _state
    if _state.get("status") == "ACTIVO":
        raise ValueError(
            f"Ya estás trackeando '{_state['activity']}'. Deténlo primero con stop_tracking."
        )
    svc = _service()
    cal_id = _get_calendar_id(_TRACKING)
    event = svc.events().get(calendarId=cal_id, eventId=event_id).execute()
    activity = event.get("summary", "Actividad")
    if "dateTime" not in event.get("start", {}):
        raise ValueError("Este bloque es de día completo y no tiene hora de inicio precisa.")
    original_end = event.get("end", {}).get("dateTime")
    if not original_end:
        raise ValueError("El bloque no tiene hora de fin registrada.")
    now = _tz.now()

    items = svc.events().list(
        calendarId=cal_id,
        timeMin=original_end,
        timeMax=now.isoformat(),
        singleEvents=True,
    ).execute().get("items", [])
    conflicts = [e for e in items if e.get("id") != event_id]
    if conflicts:
        names = ", ".join(e.get("summary", "?") for e in conflicts)
        raise ValueError(
            f"No se puede extender: hay bloques registrados entre el fin del bloque y ahora ({names})."
        )

    _patch_end(event_id, now.isoformat())
    _state = {
        "status": "ACTIVO",
        "activity": activity,
        "started_at": event["start"]["dateTime"],
        "event_id": event_id,
    }
    save_state()
    logger.info("Tracking resumed from existing block: %s [event_id=%s]", activity, event_id)
    return get_state()


def stop_tracking() -> dict:
    global _state
    if _state.get("status") != "ACTIVO":
        raise ValueError("No hay ninguna sesión de tracking activa.")
    now = _tz.now()
    try:
        _patch_end(_state["event_id"], now.isoformat())
    except Exception:
        logger.exception("Failed to update event on stop, event_id=%s", _state.get("event_id"))
    result = {**_state, "ended_at": now.isoformat()}
    _state = {"status": "LIBRE"}
    save_state()
    logger.info("Tracking stopped: %s", result.get("activity"))
    return result
