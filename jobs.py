import logging
from datetime import datetime

from telegram.ext import ContextTypes

from tasks_tools import list_tasks

logger = logging.getLogger(__name__)


async def task_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends pending tasks to the owner on a repeating interval."""
    chat_id = context.job.data
    tasks = list_tasks(show_done=False)

    if not tasks:
        text = "✅ No pending tasks right now."
    else:
        lines = [f"📋 *Pending tasks* ({datetime.now().strftime('%H:%M')})\n"]
        for t in tasks:
            due = f"  — due {t['due']}" if t.get("due") else ""
            lines.append(f"• [{t.doc_id}] {t['title']}{due}")
            if t.get("notes"):
                lines.append(f"    _{t['notes']}_")
        text = "\n".join(lines)

    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")


async def daily_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs once per day at a scheduled time."""
    chat_id = context.job.data
    if not chat_id:
        return
    today = datetime.now().strftime("%A, %B %d")
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Good morning! Today is {today}. Have a great day.",
    )
