import json
import logging
from collections import defaultdict
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import agent
import auth
import tz as _tz
from agent import ConfirmationRequest
from backlog_tools import list_backlog
from callbacks import _pending_log, _pending_track, build_category_keyboard
from digest import build_digest
from formatting import SEP, bold, esc, esc_md1, italic
from calendar_tools import get_event
from tracking_tools import get_timeblock
from tasks_tools import list_tasks
from tools_registry import REQUIRE_CONFIRMATION

logger = logging.getLogger(__name__)


async def _reply(message, text: str, parse_mode: str = "Markdown", reply_markup=None) -> None:
    logger.info("Sending reply: %s", text.splitlines()[0][:120] if text else "(empty)")
    try:
        await message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception:
        logger.warning("Markdown parse failed, retrying as plain text")
        await message.reply_text(text, reply_markup=reply_markup)


def _describe_call(name: str, args: dict) -> str:
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


async def track_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    activity = " ".join(context.args) if context.args else ""
    if not activity:
        await update.message.reply_text("Uso: /track <actividad>")
        return
    chat_id = update.effective_chat.id
    _pending_track[chat_id] = {"activity": activity}
    await update.message.reply_text(
        f"🏷 Categoría para *{esc_md1(activity)}*:",
        reply_markup=build_category_keyboard("track:cat"),
        parse_mode="Markdown",
    )


async def log_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Usage: /log <actividad> <HH:MM> <HH:MM>"""
    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text("Uso: /log <actividad> <inicio HH:MM> <fin HH:MM>")
        return
    start_str, end_str = args[-2], args[-1]
    activity = " ".join(args[:-2])
    try:
        today = _tz.now().date()
        tz = _tz.LIMA
        start_dt = datetime.strptime(start_str, "%H:%M").replace(
            year=today.year, month=today.month, day=today.day, tzinfo=tz
        )
        end_dt = datetime.strptime(end_str, "%H:%M").replace(
            year=today.year, month=today.month, day=today.day, tzinfo=tz
        )
    except ValueError:
        await update.message.reply_text("Formato de hora inválido. Usa HH:MM, ej: /log Proyecto 10:00 11:30")
        return
    if end_dt <= start_dt:
        await update.message.reply_text("La hora de fin debe ser posterior a la de inicio.")
        return
    chat_id = update.effective_chat.id
    _pending_log[chat_id] = {
        "activity": activity,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
    }
    await update.message.reply_text(
        f"🏷 Categoría para *{esc_md1(activity)}*:",
        reply_markup=build_category_keyboard("log:cat"),
        parse_mode="Markdown",
    )


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
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirmar", callback_data="confirm:yes"),
            InlineKeyboardButton("❌ Cancelar", callback_data="confirm:no"),
        ]])
        await _reply(update.message, "\n".join(lines), parse_mode="MarkdownV2", reply_markup=keyboard)
        return

    await _reply(update.message, result)

    if len(_histories[chat_id]) > 40:
        await context.bot.send_message(
            chat_id=chat_id,
            text="_(Historial largo — considera /clear si empiezas un tema nuevo)_",
            parse_mode="Markdown",
        )
