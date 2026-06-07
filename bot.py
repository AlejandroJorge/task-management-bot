import logging
import os
from datetime import time

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.ext.filters import User

from handlers import authcode, clear, handle_message, help_command, login, start
from jobs import daily_summary, task_reminder

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    token = os.environ["BOT_TOKEN"]
    allowed_user_id = int(os.environ["ALLOWED_USER_ID"])
    chat_id = str(allowed_user_id)

    me = User(user_id=allowed_user_id)

    app = Application.builder().token(token).build()

    # ── command handlers (owner only) ─────────────────────────────────────────
    app.add_handler(CommandHandler("start", start, filters=me))
    app.add_handler(CommandHandler("help", help_command, filters=me))
    app.add_handler(CommandHandler("clear", clear, filters=me))
    app.add_handler(CommandHandler("login", login, filters=me))
    app.add_handler(CommandHandler("authcode", authcode, filters=me))

    # ── message handlers (owner only) ─────────────────────────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & me, handle_message))

    # ── proactive jobs ────────────────────────────────────────────────────────
    interval_hours = float(os.getenv("REMINDER_INTERVAL_HOURS", "6"))
    jq = app.job_queue

    jq.run_repeating(
        task_reminder,
        interval=interval_hours * 3600,
        first=10,
        data=chat_id,
        name="task_reminder",
    )

    jq.run_daily(
        daily_summary,
        time=time(8, 0),
        data=chat_id,
        name="daily_summary",
    )

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
