import logging
from datetime import datetime, timedelta

from telegram.ext import ContextTypes

import auth
from digest import build_digest
from tasks_tools import list_tasks

logger = logging.getLogger(__name__)

_last_auth_reminder: datetime | None = None


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
        chat_id=context.job.data, text=text, parse_mode="Markdown"
    )


async def task_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends pending tasks to the owner on a repeating interval."""
    tasks = list_tasks(show_done=False)
    if not tasks:
        text = "Sin tareas pendientes."
    else:
        lines = [f"*Tareas pendientes* — {datetime.now().strftime('%H:%M')}\n"]
        for t in tasks:
            due = f"  — vence {t['due']}" if t.get("due") else ""
            lines.append(f"- [{t['doc_id']}] {t['title']}{due}")
            if t.get("notes"):
                lines.append(f"  _{t['notes']}_")
        text = "\n".join(lines)
    await context.bot.send_message(
        chat_id=context.job.data, text=text, parse_mode="Markdown"
    )


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
