import logging
from datetime import datetime, timedelta, timezone

from telegram.ext import ContextTypes

import auth
from calendar_tools import list_events
from digest import build_digest
from formatting import bold, esc, fmt_due, italic
from tasks_tools import list_tasks

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
            text="Google Calendar no esta autenticado. Usa /login para conectarlo.",
        )
        _last_auth_reminder = now


async def digest_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends the daily digest (events + tasks) at scheduled times."""
    text = build_digest()
    await context.bot.send_message(
        chat_id=context.job.data, text=text, parse_mode="MarkdownV2"
    )


async def task_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends pending tasks to the owner on a repeating interval."""
    tasks = list_tasks(show_done=False)
    if not tasks:
        text = esc("Sin tareas pendientes.")
    else:
        hora = esc(datetime.now().strftime("%H:%M"))
        lines = [f"{bold('Tareas pendientes')} — {hora}", ""]
        for t in tasks:
            due = f"  — vence {esc(fmt_due(t['due']))}" if t.get("due") else ""
            lines.append(f"• {esc(t['title'])}{due}")
            if t.get("notes"):
                lines.append(f"  {italic(t['notes'])}")
        text = "\n".join(lines)
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

    for event in events:
        event_id = event.get("id", "")
        start_raw = event.get("start", {}).get("dateTime")
        if not start_raw:
            continue  # all-day event

        start_dt = datetime.fromisoformat(start_raw)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)

        _starts[event_id] = start_dt
        if event_id not in _notified:
            _notified[event_id] = set()

        minutes_until = (start_dt - now).total_seconds() / 60

        for interval in _NOTIFY_BEFORE:
            if interval in _notified[event_id]:
                continue
            if abs(minutes_until - interval) <= 0.6:  # ±36 s tolerance
                summary = event.get("summary", "(sin título)")
                if interval >= 60:
                    h, m = divmod(interval, 60)
                    label = f"{h}h {m}min" if m else f"{h}h"
                else:
                    label = f"{interval} min"
                try:
                    await context.bot.send_message(
                        chat_id=context.job.data,
                        text=f"*{summary}* en {label}",
                        parse_mode="Markdown",
                    )
                except Exception:
                    await context.bot.send_message(
                        chat_id=context.job.data,
                        text=f"{summary} en {label}",
                    )
                _notified[event_id].add(interval)


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
