import logging
import os
from datetime import time

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.ext.filters import User

from handlers import clear, handle_message, help_command, start
from jobs import daily_summary, periodic_checkin

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    token = os.environ["BOT_TOKEN"]
    chat_id = os.getenv("PROACTIVE_CHAT_ID")

    allowed_user_id = int(os.environ["ALLOWED_USER_ID"])
    me = User(user_id=allowed_user_id)

    app = Application.builder().token(token).build()

    # ── command handlers (owner only) ─────────────────────────────────────────
    app.add_handler(CommandHandler("start", start, filters=me))
    app.add_handler(CommandHandler("help", help_command, filters=me))
    app.add_handler(CommandHandler("clear", clear, filters=me))

    # ── message handlers (owner only) ─────────────────────────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & me, handle_message))

    # ── proactive jobs (only if a default chat is configured) ─────────────────
    if chat_id:
        jq = app.job_queue

        # Send a message every hour
        jq.run_repeating(
            periodic_checkin,
            interval=3600,
            first=10,
            data=chat_id,
            name="hourly_checkin",
        )

        # Send a daily greeting at 08:00 local time
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
