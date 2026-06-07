import logging
from datetime import datetime

from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def periodic_checkin(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs on a fixed interval. context.job.data holds the target chat_id."""
    chat_id = context.job.data
    if not chat_id:
        logger.warning("periodic_checkin: no chat_id set")
        return
    now = datetime.now().strftime("%H:%M")
    await context.bot.send_message(chat_id=chat_id, text=f"[{now}] Just checking in!")


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
