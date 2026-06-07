import logging
import os
from datetime import time

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.ext.filters import User

from handlers import authcode, clear, handle_message, help_command, login, ls, start
from jobs import auth_check, digest_job, task_reminder

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
    app.add_handler(CommandHandler("start",    start,        filters=me))
    app.add_handler(CommandHandler("help",     help_command, filters=me))
    app.add_handler(CommandHandler("clear",    clear,        filters=me))
    app.add_handler(CommandHandler("login",    login,        filters=me))
    app.add_handler(CommandHandler("authcode", authcode,     filters=me))
    app.add_handler(CommandHandler("ls",       ls,           filters=me))

    # ── message handlers (owner only) ─────────────────────────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & me, handle_message))

    # ── proactive jobs ────────────────────────────────────────────────────────
    jq = app.job_queue

    # Auth watchdog: poll every 10 min, remind every 20 min if unauthenticated
    jq.run_repeating(auth_check, interval=600, first=15, data=chat_id, name="auth_check")

    # Task reminder on a fixed interval
    interval_hours = float(os.getenv("REMINDER_INTERVAL_HOURS", "6"))
    jq.run_repeating(
        task_reminder,
        interval=interval_hours * 3600,
        first=20,
        data=chat_id,
        name="task_reminder",
    )

    # Morning digest
    morning_hour = int(os.getenv("MORNING_DIGEST_HOUR", "6"))
    jq.run_daily(digest_job, time=time(morning_hour, 0), data=chat_id, name="morning_digest")

    # Evening digest
    evening_hour = int(os.getenv("EVENING_DIGEST_HOUR", "20"))
    jq.run_daily(digest_job, time=time(evening_hour, 0), data=chat_id, name="evening_digest")

    async def on_startup(app):
        await app.bot.send_message(chat_id=chat_id, text="He sido reiniciado.")

    app.post_init = on_startup

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
