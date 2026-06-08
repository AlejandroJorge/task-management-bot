import logging
import os
from datetime import datetime, timedelta, timezone

import tz as _tz

from telegram.ext import ContextTypes

import auth
from calendar_tools import list_events
from digest import build_digest
from formatting import bold, esc, esc_md1, fmt_due, italic
from tasks_tools import list_tasks as _list_tasks

logger = logging.getLogger(__name__)

_last_auth_reminder: datetime | None = None

# Event notifier state
_NOTIFY_BEFORE = [120, 90, 60, 50, 40, 30, 20, 10, 5]  # minutes before event
_notified: dict[str, set[int]] = {}   # event_id → intervals already sent
_starts:   dict[str, datetime] = {}   # event_id → start datetime (for cleanup)


async def auth_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs every 10 min. Sends a /login reminder every 20 min while unauthenticated."""
    global _last_auth_reminder
    if auth.get_refresh_token():
        _last_auth_reminder = None  # reset so next de-auth triggers immediately
        return
    now = _tz.now()
    if _last_auth_reminder is None or now - _last_auth_reminder >= timedelta(minutes=20):
        await context.bot.send_message(
            chat_id=context.job.data,
            text="🔑 Google Calendar no está autenticado. Usa /login para conectarlo.",
        )
        _last_auth_reminder = now


async def digest_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends the daily digest (events + tasks) at scheduled times."""
    text = build_digest()
    await context.bot.send_message(
        chat_id=context.job.data, text=text, parse_mode="MarkdownV2"
    )



async def tracking_sync_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs every 5 minutes. Syncs active tracking session end time to Google Calendar."""
    from tracking_state import sync_to_calendar
    sync_to_calendar()


# ── tracking_active_job state ─────────────────────────────────────────────────
_active_last_event_id: str | None = None
_active_last_nudge: datetime | None = None
_active_plan_warned: bool = False
_active_plan_ended_asked: bool = False


async def tracking_active_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs every minute. Handles indefinido check-ins and planificado end notifications."""
    global _active_last_event_id, _active_last_nudge, _active_plan_warned, _active_plan_ended_asked
    from tracking_state import get_state

    state = get_state()
    if state.get("status") != "ACTIVO":
        _active_last_event_id = None
        return

    # Reset state when a new session starts
    current_event_id = state.get("event_id")
    if current_event_id != _active_last_event_id:
        _active_last_nudge = None
        _active_plan_warned = False
        _active_plan_ended_asked = False
        _active_last_event_id = current_event_id

    now = _tz.now()
    activity = state.get("activity", "esto")
    mode = state.get("mode", "indefinido")

    if mode == "indefinido":
        nudge_mins = int(os.getenv("TRACKING_ACTIVE_NUDGE_MINUTES", "20"))
        if _active_last_nudge is None or (now - _active_last_nudge).total_seconds() / 60 >= nudge_mins:
            await context.bot.send_message(
                chat_id=context.job.data,
                text=f"¿Sigues haciendo *{esc_md1(activity)}*?",
                parse_mode="Markdown",
            )
            _active_last_nudge = now

    elif mode == "planificado":
        minutes_remaining = state.get("minutes_remaining", 0)

        if not _active_plan_warned and 0 < minutes_remaining <= 5:
            try:
                started = datetime.fromisoformat(state["started_at"])
                planned_end = datetime.fromisoformat(state["planned_end"])
                total_planned = (planned_end - started).total_seconds() / 60
            except Exception:
                total_planned = 999
            if total_planned > 5:
                await context.bot.send_message(
                    chat_id=context.job.data,
                    text=f"Quedan 5 min de *{esc_md1(activity)}*. ¿Quieres extender el tiempo?",
                    parse_mode="Markdown",
                )
                _active_plan_warned = True

        if not _active_plan_ended_asked and minutes_remaining <= 0:
            await context.bot.send_message(
                chat_id=context.job.data,
                text=f"Se acabó el tiempo de *{esc_md1(activity)}*. ¿Terminaste o quieres extender?",
                parse_mode="Markdown",
            )
            _active_plan_ended_asked = True


async def tracking_nudge_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a reminder when nothing is being tracked."""
    from tracking_state import get_state
    if get_state().get("status") != "LIBRE":
        return
    await context.bot.send_message(chat_id=context.job.data, text="¿Qué estás haciendo?")


async def event_notifier(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs every minute. Sends reminders at defined intervals before events."""
    if not auth.get_refresh_token():
        return

    now = datetime.now(timezone.utc)

    # Cleanup: drop events that started more than 10 min ago
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
            if abs(minutes_until - interval) <= 0.6:  # ±36 s tolerance
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

    # ── Eventos ───────────────────────────────────────────────────────────────
    for event in events:
        event_id = event.get("id", "")
        start_raw = event.get("start", {}).get("dateTime")
        if not start_raw:
            continue  # all-day event
        start_dt = datetime.fromisoformat(start_raw)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        await _maybe_notify(f"evt_{event_id}", event.get("summary", "(sin título)"), start_dt)

    # ── Tareas con hora de vencimiento ────────────────────────────────────────
    try:
        tasks = _list_tasks(show_done=False)
    except Exception:
        tasks = []
    for task in tasks:
        due_str = task.get("due", "")
        if not due_str or "T" not in due_str:
            continue  # date-only or no due — no time to count down to
        due_dt = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
        if due_dt.tzinfo is None:
            due_dt = due_dt.replace(tzinfo=timezone.utc)
        await _maybe_notify(f"task_{task['doc_id']}", task["title"], due_dt, " (tarea)")


