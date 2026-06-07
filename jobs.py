import logging
from datetime import datetime, timedelta, timezone

from telegram.ext import ContextTypes

import auth
from calendar_tools import list_events
from digest import build_digest
from formatting import bold, esc, fmt_due, italic
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
    now = datetime.now()
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
                text = f"{emoji} *{title}*{suffix} — en {label}"
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


async def daily_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs once per day at a scheduled time."""
    chat_id = context.job.data
    if not chat_id:
        return
    today = datetime.now().strftime("%A, %d de %B")
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Buenos dias. Hoy es {today}.",
    )
