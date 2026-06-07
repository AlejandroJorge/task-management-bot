import logging
from collections import defaultdict

from telegram import Update
from telegram.ext import ContextTypes

import agent
import auth
from agent import ConfirmationRequest
from digest import build_digest

logger = logging.getLogger(__name__)

_histories: dict[int, list[dict]] = defaultdict(list)
_pending: dict[int, ConfirmationRequest] = {}

_YES = {"y", "yes", "si", "sí", "yep", "yeah", "sure", "ok", "confirm"}
_NO  = {"n", "no", "nope", "cancel", "nah"}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hola. Soy tu asistente personal.\n"
        "Puedo gestionar tu Google Calendar y tu lista de tareas.\n"
        "Escribe lo que necesitas."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*Comandos disponibles*\n\n"
        "/ls — resumen del dia: eventos y tareas\n"
        "/clear — borrar historial de conversacion\n"
        "/login — autenticar Google Calendar\n"
        "/authcode — completar login (pegar URL del navegador)\n"
        "/help — este mensaje\n\n"
        "O escribe directamente lo que necesitas.",
        parse_mode="Markdown",
    )


async def login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        url = auth.generate_auth_url()
    except KeyError as e:
        await update.message.reply_text(f"Falta variable de entorno: {e}")
        return
    await update.message.reply_text(
        f"1. Abre este enlace y aprueba el acceso:\n{url}\n\n"
        "2. El navegador mostrara un error de conexion — es normal.\n"
        "3. Copia la URL completa de la barra de direcciones y enviala como:\n"
        "/authcode <url>"
    )


async def authcode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw = " ".join(context.args or []).strip()
    if not raw:
        await update.message.reply_text("Uso: `/authcode <url del navegador>`", parse_mode="Markdown")
        return
    try:
        auth.exchange_code(raw)
        chat_id = update.effective_chat.id
        _histories[chat_id].clear()
        _pending.pop(chat_id, None)
        await update.message.reply_text("Autenticado. Google Calendar listo.")
    except RuntimeError as e:
        await update.message.reply_text(str(e))
    except Exception as e:
        logger.exception("Auth exchange failed")
        await update.message.reply_text(f"Error de autenticacion: {e}")


async def ls(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(build_digest(), parse_mode="MarkdownV2")


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    _histories[chat_id].clear()
    _pending.pop(chat_id, None)
    await update.message.reply_text("Historial borrado.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    if not text:
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    if chat_id in _pending:
        word = text.lower().split()[0]
        if word in _YES:
            confirmed = True
        elif word in _NO:
            confirmed = False
        else:
            await update.message.reply_text("Responde si o no.")
            return

        request = _pending.pop(chat_id)
        reply = await agent.resume_after_confirmation(confirmed, request, _histories[chat_id])
        await update.message.reply_text(reply, parse_mode="Markdown")
        return

    try:
        result = await agent.process(text, _histories[chat_id])
    except Exception as exc:
        logger.exception("Agent error")
        await update.message.reply_text(f"Error: {exc}")
        return

    if isinstance(result, ConfirmationRequest):
        _pending[chat_id] = result
        args_str = ", ".join(f"{k}={v}" for k, v in result.tool_args.items())
        await update.message.reply_text(
            f"Confirmas ejecutar `{result.tool_name}` con:\n{args_str}\n\nResponde *si* o *no*.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(result, parse_mode="Markdown")
