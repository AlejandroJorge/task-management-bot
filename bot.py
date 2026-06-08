import logging
import os
import sys
from datetime import datetime, time
import tz as _tz

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

import auth
import tracking_state
from handlers import backlog, clear, handle_message, help_command, login, start, status
from jobs import auth_check, digest_job, event_notifier, tracking_sync_job

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main() -> None:
    token = os.environ["BOT_TOKEN"]
    allowed_user_id = int(os.environ["ALLOWED_USER_ID"])
    chat_id = str(allowed_user_id)

    me = filters.User(user_id=allowed_user_id)

    app = Application.builder().token(token).build()

    # ── command handlers (owner only) ─────────────────────────────────────────
    app.add_handler(CommandHandler("start",    start,        filters=me))
    app.add_handler(CommandHandler("help",     help_command, filters=me))
    app.add_handler(CommandHandler("clear",    clear,        filters=me))
    app.add_handler(CommandHandler("login",    login,        filters=me))
    app.add_handler(CommandHandler("status",   status,       filters=me))
    app.add_handler(CommandHandler("backlog",  backlog,      filters=me))

    # ── message handlers (owner only) ─────────────────────────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & me, handle_message))

    # ── proactive jobs ────────────────────────────────────────────────────────
    jq = app.job_queue

    # Auth watchdog: poll every 10 min, remind every 20 min if unauthenticated
    jq.run_repeating(auth_check, interval=600, first=15, data=chat_id, name="auth_check")

    # Event notifier: checks every minute, fires at 120/90/60/50/40/30/20/10/5 min before
    jq.run_repeating(event_notifier, interval=60, first=10, data=chat_id, name="event_notifier")

    # Tracking: sync active session end time to Calendar every 5 min
    jq.run_repeating(tracking_sync_job, interval=300, first=60, name="tracking_sync")

    # Morning digest
    morning_hour = int(os.getenv("MORNING_DIGEST_HOUR", "6"))
    jq.run_daily(digest_job, time=time(morning_hour, 0), data=chat_id, name="morning_digest")

    # Evening digest
    evening_hour = int(os.getenv("EVENING_DIGEST_HOUR", "20"))
    jq.run_daily(digest_job, time=time(evening_hour, 0), data=chat_id, name="evening_digest")

    async def on_startup(app):
        await auth.start_callback_server()
        if auth.load_saved_token():
            logger.info("Refresh token restored from DB.")
        state = tracking_state.load_state()
        if state.get("status") == "ACTIVO":
            logger.info("Tracking session restored: %s", state.get("activity"))
            try:
                started = datetime.fromisoformat(state["started_at"]).astimezone(_tz.LIMA)
                restart_msg = (
                    f"He sido reiniciado. "
                    f"Sesión en curso restaurada: {state['activity']} "
                    f"(desde las {started.strftime('%H:%M')})."
                )
            except Exception:
                logger.warning("Corrupt tracking state on startup (missing/invalid started_at), resetting to LIBRE")
                tracking_state._state = {"status": "LIBRE"}
                tracking_state.save_state()
                restart_msg = "He sido reiniciado."
        else:
            restart_msg = "He sido reiniciado."
        await app.bot.send_message(chat_id=chat_id, text=restart_msg)

    async def on_shutdown(app):
        await auth.stop_callback_server()

    app.post_init = on_startup
    app.post_shutdown = on_shutdown

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
