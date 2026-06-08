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
        logger.exception("Failed to save tracking state")


def get_state() -> dict:
    state = dict(_state)
    if state.get("status") == "ACTIVO" and state.get("started_at"):
        started = datetime.fromisoformat(state["started_at"])
        state["elapsed_minutes"] = int((_tz.now() - started).total_seconds() / 60)
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
        started = datetime.fromisoformat(_state["started_at"])
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
    now = _tz.now()
    try:
        _patch_end(_state["event_id"], now.isoformat())
        logger.info("Tracking synced: %s end → %s", _state.get("activity"), now.strftime("%H:%M"))
    except Exception:
        logger.exception("Calendar sync failed for event_id=%s, recreating", _state.get("event_id"))
        _recreate_event()


def start_tracking(activity: str) -> dict:
    global _state
    if _state.get("status") == "ACTIVO":
        raise ValueError(
            f"Ya estás trackeando '{_state['activity']}'. Deténlo primero con stop_tracking."
        )
    now = _tz.now()
    event = _service().events().insert(
        calendarId=_get_calendar_id(_TRACKING),
        body={
            "summary": activity,
            "start": {"dateTime": now.isoformat()},
            "end": {"dateTime": (now + timedelta(minutes=1)).isoformat()},
        },
    ).execute()
    _state = {
        "status": "ACTIVO",
        "activity": activity,
        "started_at": now.isoformat(),
        "event_id": event["id"],
    }
    save_state()
    logger.info("Tracking started: %s [event_id=%s]", activity, event["id"])
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
