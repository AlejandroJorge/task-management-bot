import json
import logging
import os
from datetime import datetime, timedelta

import tz as _tz

logger = logging.getLogger(__name__)

_STATE_PATH = os.getenv("TRACKING_STATE_PATH", "data/tracking_state.json")
_state: dict = {"active": False, "status_message_id": None}


def load_state() -> dict:
    global _state
    try:
        with open(_STATE_PATH) as f:
            _state = json.load(f)
        logger.info("Tracking state loaded: active=%s", _state.get("active"))
    except FileNotFoundError:
        _state = {"active": False, "status_message_id": None}
    except Exception:
        logger.exception("Failed to load tracking state, defaulting to inactive")
        _state = {"active": False, "status_message_id": None}
    return dict(_state)


def save_state() -> None:
    try:
        parent = os.path.dirname(_STATE_PATH)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(_STATE_PATH, "w") as f:
            json.dump(_state, f)
    except Exception:
        logger.warning("TRACKING STATE NOT PERSISTED", exc_info=True)


def reset() -> None:
    global _state
    _state = {"active": False, "status_message_id": None}
    save_state()


def get_state() -> dict:
    state = dict(_state)
    if state.get("active") and state.get("started_at"):
        now = _tz.now()
        try:
            started = datetime.fromisoformat(state["started_at"])
            state["elapsed_minutes"] = max(0, round((now - started).total_seconds() / 60))
        except Exception:
            state["elapsed_minutes"] = 0
        if state.get("planned_end"):
            try:
                planned_end = datetime.fromisoformat(state["planned_end"])
                state["minutes_remaining"] = round((planned_end - now).total_seconds() / 60)
            except Exception:
                pass
    return state


def start_tracking(activity: str, started_at: str | None = None) -> dict:
    global _state
    if _state.get("active"):
        raise ValueError(f"Ya estás trackeando '{_state['activity']}'. Detén la sesión primero.")
    now = _tz.now()
    if started_at:
        try:
            event_start = datetime.fromisoformat(started_at)
        except ValueError:
            raise ValueError("started_at debe ser ISO 8601 con zona horaria")
        if event_start.tzinfo is None:
            raise ValueError("started_at debe incluir zona horaria")
        if event_start >= now:
            raise ValueError("started_at debe ser en el pasado")
    else:
        event_start = now
    _state = {
        "active": True,
        "activity": activity,
        "started_at": event_start.isoformat(),
        "planned_end": None,
        "plan_warned": False,
        "plan_ended": False,
        "status_message_id": _state.get("status_message_id"),
    }
    save_state()
    logger.info("Tracking started: %s", activity)
    return get_state()


def stop_tracking() -> dict:
    global _state
    if not _state.get("active"):
        raise ValueError("No hay ninguna sesión de tracking activa.")
    now = _tz.now()
    final = {**_state, "ended_at": now.isoformat()}
    _state = {"active": False, "status_message_id": _state.get("status_message_id")}
    save_state()
    logger.info("Tracking stopped: %s", final.get("activity"))
    return final


def set_planned_end(minutes: int) -> None:
    global _state
    if not _state.get("active"):
        raise ValueError("No hay sesión activa.")
    planned_end = _tz.now() + timedelta(minutes=minutes)
    _state["planned_end"] = planned_end.isoformat()
    _state["plan_warned"] = False
    _state["plan_ended"] = False
    save_state()
    logger.info("Planned end set: %d min → %s", minutes, planned_end.strftime("%H:%M"))


def clear_planned_end() -> None:
    global _state
    if not _state.get("active"):
        raise ValueError("No hay sesión activa.")
    _state["planned_end"] = None
    _state["plan_warned"] = False
    _state["plan_ended"] = False
    save_state()
    logger.info("Planned end cleared — session is now open-ended")


def backdate_start(minutes: int) -> tuple[str, str]:
    """Set started_at to now - minutes. Returns (old_start, new_start) as ISO strings."""
    global _state
    if not _state.get("active"):
        raise ValueError("No hay sesión activa.")
    old_start = _state["started_at"]
    new_start = (_tz.now() - timedelta(minutes=minutes)).isoformat()
    _state["started_at"] = new_start
    save_state()
    logger.info("Start backdated %d min: %s → %s", minutes, old_start, new_start)
    return old_start, new_start


def set_status_message_id(mid: int | None) -> None:
    global _state
    _state["status_message_id"] = mid
    save_state()


def mark_plan_warned() -> None:
    global _state
    _state["plan_warned"] = True
    save_state()


def mark_plan_ended() -> None:
    global _state
    _state["plan_ended"] = True
    save_state()
