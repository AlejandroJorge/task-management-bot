import logging
import os
import sys
from datetime import datetime, time
import tz as _tz

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

import auth
import tracking_state
from callbacks import handle_callback
from handlers import (
    backlog, blocks_command, delblock_command, delidea_command, deltask_command,
    done_command, editblock_command, events_command, handle_message, help_command,
    idea_command, log_command, login, start, status, step_command, task_command,
    tasks_command, track_command,
)
from jobs import auth_check, daily_summary_job, event_notifier, tracking_minutely_job, tracking_nudge_job

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main() -> None:
    _required = ["BOT_TOKEN", "ALLOWED_USER_ID", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "DEEPSEEK_API_KEY"]
    if missing := [v for v in _required if not os.getenv(v)]:
        sys.exit(f"Missing required env vars: {', '.join(missing)}")

    token = os.environ["BOT_TOKEN"]
    allowed_user_id = int(os.environ["ALLOWED_USER_ID"])
    chat_id = str(allowed_user_id)

    me = filters.User(user_id=allowed_user_id)

    app = Application.builder().token(token).build()

    # ── command handlers ──────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",    start,           filters=me))
    app.add_handler(CommandHandler("help",     help_command,    filters=me))
    app.add_handler(CommandHandler("login",    login,           filters=me))
    app.add_handler(CommandHandler("status",   status,          filters=me))
    app.add_handler(CommandHandler("tasks",    tasks_command,   filters=me))
    app.add_handler(CommandHandler("task",     task_command,    filters=me))
    app.add_handler(CommandHandler("done",     done_command,    filters=me))
    app.add_handler(CommandHandler("deltask",  deltask_command, filters=me))
    app.add_handler(CommandHandler("events",   events_command,  filters=me))
    app.add_handler(CommandHandler("backlog",  backlog,         filters=me))
    app.add_handler(CommandHandler("idea",     idea_command,    filters=me))
    app.add_handler(CommandHandler("step",     step_command,    filters=me))
    app.add_handler(CommandHandler("delidea",  delidea_command, filters=me))
    app.add_handler(CommandHandler("track",    track_command,   filters=me))
    app.add_handler(CommandHandler("log",      log_command,     filters=me))
    app.add_handler(CommandHandler("blocks",   blocks_command,  filters=me))
    app.add_handler(CommandHandler("delblock", delblock_command, filters=me))
    app.add_handler(CommandHandler("editblock", editblock_command, filters=me))

    # ── inline button callbacks ───────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(handle_callback))

    # ── free-text messages ────────────────────────────────────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & me, handle_message))

    # ── proactive jobs ────────────────────────────────────────────────────────
    jq = app.job_queue

    jq.run_repeating(auth_check, interval=600, first=15, data=chat_id, name="auth_check")
    jq.run_repeating(event_notifier, interval=60, first=10, data=chat_id, name="event_notifier")

    # Idle nudge: delete + resend "¿Qué estás haciendo?" on interval (push notification)
    nudge_mins = int(os.getenv("TRACKING_NUDGE_MINUTES", "15"))
    jq.run_repeating(tracking_nudge_job, interval=nudge_mins * 60, first=nudge_mins * 60, data=chat_id, name="tracking_nudge")

    # Active session: silent minutely refresh; notifies only at 5-min warning and time-up
    jq.run_repeating(tracking_minutely_job, interval=60, first=60, data=chat_id, name="tracking_minutely")

    # Daily 8pm summary of the last 24h of tracking. tzinfo is mandatory here:
    # the job queue scheduler defaults to UTC, so a naive time runs 5h early.
    summary_hour = int(os.getenv("DAILY_SUMMARY_HOUR", "20"))
    jq.run_daily(daily_summary_job, time=time(summary_hour, 0, tzinfo=_tz.LIMA), data=chat_id, name="daily_summary")

    async def on_startup(app):
        await auth.start_callback_server()
        auth.load_saved_token()
        restart_msg = "He sido reiniciado."
        state = tracking_state.load_state()
        if state.get("active"):
            try:
                started = datetime.fromisoformat(state["started_at"]).astimezone(_tz.LIMA)
                restart_msg += (
                    f" Sesión en curso restaurada: {state['activity']}"
                    f" (desde las {started.strftime('%H:%M')})."
                )
            except Exception:
                logger.warning("Corrupt tracking state on startup, resetting to inactive")
                tracking_state.reset()
        await app.bot.send_message(chat_id=chat_id, text=restart_msg)

    async def on_shutdown(app):
        await auth.stop_callback_server()

    app.post_init = on_startup
    app.post_shutdown = on_shutdown

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
