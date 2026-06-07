import logging
from collections import defaultdict

from telegram import Update
from telegram.ext import ContextTypes

import agent
import auth
from agent import ConfirmationRequest
from digest import build_digest

logger = logging.getLogger(__name__)

# Per-chat state (lives for the process lifetime)
_histories: dict[int, list[dict]] = defaultdict(list)
_pending: dict[int, ConfirmationRequest] = {}

_YES = {"y", "yes", "si", "sí", "yep", "yeah", "sure", "ok", "confirm"}
_NO  = {"n", "no", "nope", "cancel", "nah"}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hi! I'm your personal assistant. Tell me what you need — "
        "I can manage your Google Calendar and task list."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "/start    — greet\n"
        "/help     — this message\n"
        "/ls       — today's events + pending tasks\n"
        "/clear    — reset conversation history\n"
        "/login    — re-authenticate Google Calendar\n"
        "/authcode — finish login (paste URL from browser)\n\n"
        "Just write naturally — I'll figure out what to do."
    )


async def login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        url = auth.generate_auth_url()
    except KeyError as e:
        await update.message.reply_text(f"Missing env var: {e}. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.")
        return
    await update.message.reply_text(
        f"1. Open this link and approve access:\n{url}\n\n"
        "2. Your browser will show a connection error — that's expected.\n"
        "3. Copy the full URL from the address bar and send it here as:\n"
        "/authcode <url>"
    )


async def authcode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw = " ".join(context.args or []).strip()
    if not raw:
        await update.message.reply_text("Usage: /authcode <url from browser address bar>")
        return
    try:
        auth.exchange_code(raw)
        # Clear history so the LLM doesn't see previous failed calendar calls
        chat_id = update.effective_chat.id
        _histories[chat_id].clear()
        _pending.pop(chat_id, None)
        await update.message.reply_text("✅ Authenticated! Google Calendar is ready.")
    except RuntimeError as e:
        await update.message.reply_text(str(e))
    except Exception as e:
        logger.exception("Auth exchange failed")
        await update.message.reply_text(f"Auth failed: {e}")


async def ls(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(build_digest(), parse_mode="Markdown")


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    _histories[chat_id].clear()
    _pending.pop(chat_id, None)
    await update.message.reply_text("History cleared.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    if not text:
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    # ── confirmation flow ─────────────────────────────────────────────────────
    if chat_id in _pending:
        word = text.lower().split()[0]
        if word in _YES:
            confirmed = True
        elif word in _NO:
            confirmed = False
        else:
            await update.message.reply_text("Please reply yes or no.")
            return

        request = _pending.pop(chat_id)
        reply = await agent.resume_after_confirmation(
            confirmed, request, _histories[chat_id]
        )
        await update.message.reply_text(reply)
        return

    # ── normal message → agent ────────────────────────────────────────────────
    try:
        result = await agent.process(text, _histories[chat_id])
    except Exception as exc:
        logger.exception("Agent error")
        await update.message.reply_text(f"Something went wrong: {exc}")
        return

    if isinstance(result, ConfirmationRequest):
        _pending[chat_id] = result
        args_str = ", ".join(f"{k}={v}" for k, v in result.tool_args.items())
        await update.message.reply_text(
            f"Are you sure you want to run {result.tool_name}({args_str})?\n\nReply yes or no."
        )
    else:
        await update.message.reply_text(result)
