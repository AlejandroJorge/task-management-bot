import json
import logging
from collections import defaultdict

from telegram import Update
from telegram.ext import ContextTypes

import agent
import auth
from agent import ConfirmationRequest
from backlog_tools import list_backlog
from digest import build_digest
from formatting import SEP, bold, esc, italic
from calendar_tools import get_event
from tracking_tools import get_timeblock
from tasks_tools import list_tasks
from tools_registry import REQUIRE_CONFIRMATION

logger = logging.getLogger(__name__)


async def _reply(message, text: str, parse_mode: str = "Markdown") -> None:
    """Send a reply, falling back to plain text if Markdown parsing fails."""
    logger.info("Sending reply: %s", text.splitlines()[0][:120] if text else "(empty)")
    try:
        await message.reply_text(text, parse_mode=parse_mode)
    except Exception:
        logger.warning("Markdown parse failed, retrying as plain text")
        await message.reply_text(text)


def _describe_call(name: str, args: dict) -> str:
    """Return a human-readable label for a destructive tool call."""
    if name == "delete_task":
        doc_id = args.get("doc_id")
        task = next((t for t in list_tasks(show_done=True) if t["doc_id"] == doc_id), None)
        return task["title"] if task else f"tarea #{doc_id}"
    if name == "delete_backlog_item":
        doc_id = args.get("doc_id")
        item = next((i for i in list_backlog() if i["doc_id"] == doc_id), None)
        return item["title"] if item else f"backlog #{doc_id}"
    if name == "delete_event":
        event_id = args.get("event_id", "")
        try:
            event = get_event(event_id)
            return event.get("summary") or "(evento sin título)"
        except Exception:
            return "(evento no disponible)"
    if name == "delete_timeblock":
        event_id = args.get("event_id", "")
        try:
            from datetime import datetime
            import tz as _tz
            event = get_timeblock(event_id)
            activity = event.get("summary", "?")
            start_raw = event["start"].get("dateTime", "")
            end_raw = event["end"].get("dateTime", "")
            start_t = datetime.fromisoformat(start_raw).astimezone(_tz.LIMA).strftime("%H:%M")
            end_t = datetime.fromisoformat(end_raw).astimezone(_tz.LIMA).strftime("%H:%M")
            return f"{activity} ({start_t}–{end_t})"
        except Exception:
            return "(bloque de tiempo no disponible)"
    return name


_histories: dict[int, list[dict]] = defaultdict(list)
_pending: dict[int, ConfirmationRequest] = {}

_YES = {"y", "yes", "si", "sí", "yep", "yeah", "sure", "ok", "confirm", "confirmar", "afirmar", "dale", "va"}
_NO  = {"n", "no", "nope", "cancel", "nah", "cancelar", "rechazar"}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hola. Soy tu asistente personal.\n"
        "Puedo gestionar tu Google Calendar y tu lista de tareas.\n"
        "Escribe lo que necesitas."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*Comandos disponibles*\n\n"
        "/status — resumen del dia: eventos, tracking y tareas\n"
        "/backlog — ver ideas a largo plazo\n"
        "/clear — borrar historial de conversacion\n"
        "/login — autenticar Google Calendar\n"
        "/help — este mensaje\n\n"
        "O escribe directamente lo que necesitas.",
        parse_mode="Markdown",
    )


async def login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        url = auth.generate_auth_url()
    except RuntimeError as e:
        await update.message.reply_text(str(e))
        return
    except KeyError as e:
        await update.message.reply_text(f"Falta variable de entorno: {e}")
        return
    await update.message.reply_text(
        f"Abre este enlace y aprueba el acceso:\n{url}\n\n"
        "Cuando completes el proceso, te confirmo aqui."
    )
    try:
        await auth.await_login_result()
        chat_id = update.effective_chat.id
        _histories[chat_id].clear()
        _pending.pop(chat_id, None)
        await update.message.reply_text("Autenticado. Google Calendar listo.")
    except RuntimeError as e:
        await update.message.reply_text(str(e))
    except Exception as e:
        logger.exception("Login failed")
        await update.message.reply_text(f"Error de autenticacion: {e}")



async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(build_digest(), parse_mode="MarkdownV2")


async def backlog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items = list_backlog()
    if not items:
        await update.message.reply_text("No hay ideas en el backlog.")
        return
    lines = [f"💡 {bold(f'Backlog ({len(items)})')}", SEP, ""]
    for item in items:
        lines.append(f"• {bold(item['title'])}")
        if item.get("description"):
            lines.append(f"  {italic(item['description'])}")
    await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")


def clear_history(chat_id: int) -> None:
    _histories[chat_id].clear()
    _pending.pop(chat_id, None)


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    clear_history(chat_id)
    await update.message.reply_text("Historial borrado.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    if not text:
        return

    logger.info("Message from %s: %s", chat_id, text[:80])
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
        await _reply(update.message, reply)
        return

    try:
        result = await agent.process(text, _histories[chat_id])
    except Exception as exc:
        logger.exception("Agent error for message: %s", text[:80])
        await update.message.reply_text(f"Error: {exc}")
        return

    if isinstance(result, ConfirmationRequest):
        _pending[chat_id] = result
        destructive = [c for c in result.pending_calls if c["name"] in REQUIRE_CONFIRMATION]
        lines = [f"🗑 {bold('Confirmar eliminación')}", SEP, ""]
        for call in destructive:
            args = json.loads(call["args_json"])
            lines.append(f"• {esc(_describe_call(call['name'], args))}")
        lines += ["", esc("Responde si o no.")]
        await _reply(update.message, "\n".join(lines), parse_mode="MarkdownV2")
    else:
        if len(_histories[chat_id]) > 40:
            result += "\n\n_(Historial largo — considera /clear si empiezas un tema nuevo)_"
        await _reply(update.message, result)
