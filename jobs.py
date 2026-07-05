import logging
import os
from datetime import datetime, timedelta, timezone

import tz as _tz

from telegram.ext import ContextTypes

import auth
from calendar_tools import list_events
from digest import build_digest
from tasks_tools import list_tasks as _list_tasks

logger = logging.getLogger(__name__)

_last_auth_reminder: datetime | None = None

_NOTIFY_BEFORE = [120, 90, 60, 50, 40, 30, 20, 10, 5]
_notified: dict[str, set[int]] = {}
_starts:   dict[str, datetime] = {}


async def auth_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    global _last_auth_reminder
    if auth.get_refresh_token():
        _last_auth_reminder = None
        return
    now = _tz.now()
    if _last_auth_reminder is None or now - _last_auth_reminder >= timedelta(minutes=20):
        await context.bot.send_message(
            chat_id=context.job.data,
            text="🔑 Google Calendar no está autenticado. Usa /login para conectarlo.",
        )
        _last_auth_reminder = now


async def digest_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(chat_id=context.job.data, text=build_digest(), parse_mode="MarkdownV2")


async def tracking_nudge_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fires every TRACKING_NUDGE_MINUTES. Re-sends '¿Qué estás haciendo?' (with
    notification) only when idle; active sessions are refreshed silently by
    tracking_minutely_job."""
    import tracking_state
    from callbacks import send_tracking_status
    if tracking_state.get_state().get("active"):
        return
    await send_tracking_status(context.bot, context.job.data, notify=True)


async def tracking_minutely_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fires every minute while a session is active: silently edits the status
    message so elapsed/remaining stay current. Only notifies (delete + resend)
    at the 5-min warning and at time-up."""
    import tracking_state
    from callbacks import send_tracking_status

    state = tracking_state.get_state()
    if not state.get("active"):
        return

    notify = False
    if state.get("planned_end"):
        mins_rem = state.get("minutes_remaining", 999)
        if not state.get("plan_warned") and 0 < mins_rem <= 5:
            tracking_state.mark_plan_warned()
            notify = True
        elif not state.get("plan_ended") and mins_rem <= 0:
            tracking_state.mark_plan_ended()
            notify = True

    await send_tracking_status(context.bot, context.job.data, notify=notify)


async def event_notifier(context: ContextTypes.DEFAULT_TYPE) -> None:
    from formatting import esc_md1
    if not auth.get_refresh_token():
        return

    now = datetime.now(timezone.utc)

    stale = [eid for eid, start in _starts.items() if start < now - timedelta(minutes=10)]
    for eid in stale:
        _notified.pop(eid, None)
        _starts.pop(eid, None)

    try:
        time_min = now.isoformat()
        time_max = (now + timedelta(hours=2, minutes=5)).isoformat()
        events = list_events(max_results=20, time_min=time_min, time_max=time_max)
    except Exception:
        return

    async def _maybe_notify(key: str, title: str, due_dt: datetime, suffix: str = "") -> None:
        _starts[key] = due_dt
        if key not in _notified:
            _notified[key] = set()
        minutes_until = (due_dt - now).total_seconds() / 60
        for interval in _NOTIFY_BEFORE:
            if interval in _notified[key]:
                continue
            if abs(minutes_until - interval) <= 0.6:
                if interval >= 60:
                    h, m = divmod(interval, 60)
                    label = f"{h}h {m}min" if m else f"{h}h"
                else:
                    label = f"{interval} min"
                emoji = "⏰" if suffix else "🔔"
                text = f"{emoji} *{esc_md1(title)}*{suffix} — en {label}"
                try:
                    await context.bot.send_message(
                        chat_id=context.job.data, text=text, parse_mode="Markdown"
                    )
                except Exception:
                    await context.bot.send_message(
                        chat_id=context.job.data, text=f"{title}{suffix} en {label}"
                    )
                _notified[key].add(interval)

    for event in events:
        event_id = event.get("id", "")
        start_raw = event.get("start", {}).get("dateTime")
        if not start_raw:
            continue
        start_dt = datetime.fromisoformat(start_raw)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        await _maybe_notify(f"evt_{event_id}", event.get("summary", "(sin título)"), start_dt)

    try:
        tasks = _list_tasks(show_done=False)
    except Exception:
        tasks = []
    for task in tasks:
        due_str = task.get("due", "")
        if not due_str or "T" not in due_str:
            continue
        due_dt = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
        if due_dt.tzinfo is None:
            due_dt = due_dt.replace(tzinfo=timezone.utc)
        await _maybe_notify(f"task_{task['doc_id']}", task["title"], due_dt, " (tarea)")
