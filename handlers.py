import logging
from datetime import date, datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import auth
import tz as _tz
from backlog_tools import create_backlog_item, list_backlog, set_backlog_step
from calendar_tools import create_event, list_events
from digest import build_digest
from formatting import SEP, bold, esc, esc_md1, fmt_due, fmt_duration, italic
from tasks_tools import create_task, list_tasks, update_task
from tracking_tools import create_timeblock, delete_timeblock, list_timeblocks, update_timeblock

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hola. Soy tu asistente personal.\n"
        "Gestiono tu calendario, tareas y backlog.\n"
        "Usa /help para ver los comandos disponibles."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*Comandos disponibles*\n\n"
        "*Tareas*\n"
        "/tasks — listar tareas pendientes\n"
        "/task <título> | <primer paso> — crear tarea (paso opcional)\n"
        "/taskstep <n> <primer paso> — fijar el primer paso de una tarea\n"
        "/done <n> — marcar tarea como completada\n"
        "/deltask <n> — eliminar tarea\n\n"
        "*Backlog*\n"
        "/backlog — ver ideas a largo plazo\n"
        "/idea <título> | <desc> | <primer paso> — agregar idea (desc y paso opcionales)\n"
        "/step <n> <primer paso> — fijar el primer paso accionable de una idea\n"
        "/delidea <n> — eliminar idea del backlog\n\n"
        "*Calendario*\n"
        "/events — próximos eventos\n"
        "/event <título> | <inicio> | <fin> — crear evento (DD/MM HH:MM)\n"
        "/delevent <n> — eliminar evento\n\n"
        "*Tracking*\n"
        "Responde al mensaje de tracking — iniciar (o cambiar de) actividad al instante\n"
        "/track <actividad> — iniciar sesión eligiendo duración\n"
        "/log <actividad> <inicio HH:MM> <fin HH:MM> — registrar bloque pasado\n"
        "/blocks — listar bloques de hoy\n"
        "/delblock <n> — eliminar bloque\n"
        "/editblock <n> <inicio HH:MM> <fin HH:MM> — cambiar horario de un bloque\n\n"
        "*General*\n"
        "/status — resumen del día\n"
        "/login — autenticar Google Calendar\n"
        "/help — este mensaje",
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
        await update.message.reply_text("Autenticado. Google Calendar listo.")
    except RuntimeError as e:
        await update.message.reply_text(str(e))
    except Exception as e:
        logger.exception("Login failed")
        await update.message.reply_text(f"Error de autenticacion: {e}")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import tracking_state
    from callbacks import send_tracking_status
    await update.message.reply_text(build_digest(), parse_mode="MarkdownV2")
    # Keep the tracking box below the digest: delete + re-send it quietly
    if tracking_state.get_state().get("active"):
        await send_tracking_status(context.bot, update.effective_chat.id, notify=True, silent=True)


async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tasks = list_tasks(show_done=False)
    if not tasks:
        await update.message.reply_text("No hay tareas pendientes.")
        return
    lines = [f"✅ {bold(f'Tareas ({len(tasks)})')}", SEP, ""]
    for i, t in enumerate(tasks, 1):
        due_part = f" _{esc(fmt_due(t['due']))}_" if t.get("due") else ""
        lines.append(f"{i}\\. {bold(t['title'])}{due_part}")
        if t.get("notes"):
            lines.append(f"  {italic(t['notes'])}")
        if t.get("first_step"):
            lines.append(f"  ▸ {esc(t['first_step'])}")
    lines += ["", italic("Usa /done \\<n\\>, /deltask \\<n\\> o /taskstep \\<n\\> \\<primer paso\\>")]
    await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")


async def task_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text("Uso: /task <título>  (o /task <título> | <primer paso>)")
        return
    title, step = (text.split(" | ", 1) + [""])[:2]
    create_task(title.strip(), first_step=step.strip())
    reply = f"✅ Tarea creada: {title.strip()}"
    if step.strip():
        reply += f"\n▸ Primer paso: {step.strip()}"
    await update.message.reply_text(reply)


async def taskstep_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Uso: /taskstep <n> <primer paso>  (número según /tasks)")
        return
    task = await _pick_numbered(update, args[0], list_tasks(show_done=False), "/tasks")
    if task is None:
        return
    step = " ".join(args[1:])
    update_task(task["doc_id"], first_step=step)
    await update.message.reply_text(f"▸ Primer paso para «{task['title']}»: {step}")


async def _pick_numbered(update: Update, arg: str, items: list[dict], list_cmd: str) -> dict | None:
    """Resolve a 1-based position (as shown by list_cmd) to an item, replying on error."""
    try:
        n = int(arg)
    except ValueError:
        await update.message.reply_text(f"El número debe ser un entero (ver {list_cmd}).")
        return None
    if not 1 <= n <= len(items):
        await update.message.reply_text(f"No existe el número {n}. Hay {len(items)} (ver {list_cmd}).")
        return None
    return items[n - 1]


async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Uso: /done <n>  (número según /tasks)")
        return
    task = await _pick_numbered(update, context.args[0], list_tasks(show_done=False), "/tasks")
    if task is None:
        return
    try:
        update_task(task["doc_id"], done=True)
        await update.message.reply_text(f"✅ Tarea completada: {task['title']}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def _confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          namespace: str, noun: str, items: list[dict], list_cmd: str) -> None:
    """Shared /deltask and /delidea flow: resolve position, ask for confirmation.
    The callback carries the doc_id so later list changes can't shift the target."""
    if not context.args:
        await update.message.reply_text(f"Uso: /{namespace} <n>  (número según {list_cmd})")
        return
    item = await _pick_numbered(update, context.args[0], items, list_cmd)
    if item is None:
        return
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Eliminar", callback_data=f"{namespace}:yes:{item['doc_id']}"),
        InlineKeyboardButton("❌ Cancelar", callback_data=f"{namespace}:no"),
    ]])
    await update.message.reply_text(
        f"🗑 Eliminar {noun} *{esc_md1(item['title'])}*?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def deltask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _confirm_delete(update, context, "deltask", "tarea", list_tasks(show_done=False), "/tasks")


async def events_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        evs = list_events(max_results=10)
    except Exception as e:
        await update.message.reply_text(f"Error al obtener eventos: {e}")
        return
    if not evs:
        await update.message.reply_text("No hay próximos eventos.")
        return
    lines = [f"📅 {bold(f'Próximos eventos ({len(evs)})')}", SEP, ""]
    for i, ev in enumerate(evs, 1):
        summary = ev.get("summary", "(sin título)")
        start = ev.get("start", {})
        start_str = start.get("dateTime") or start.get("date", "")
        try:
            if "T" in start_str:
                dt = datetime.fromisoformat(start_str).astimezone(_tz.LIMA)
                when = dt.strftime("%d/%m %H:%M")
            else:
                d = date.fromisoformat(start_str)
                when = d.strftime("%d/%m")
        except Exception:
            when = start_str
        lines.append(f"{i}\\. {bold(summary)} — {esc(when)}")
    lines += ["", italic("Usa /event para crear o /delevent \\<n\\> para eliminar")]
    await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")


def _parse_event_datetime(s: str, base_date: date | None = None) -> datetime:
    """Parse 'DD/MM HH:MM' or 'HH:MM' (relative to base_date/today) as a Lima
    datetime. Dates without a year that already passed roll to next year.
    Raises ValueError with a user-facing message."""
    s = s.strip()
    today = _tz.now().date()
    try:
        if " " in s:
            date_part, time_part = s.split()
            day_s, month_s = date_part.split("/")
            d = date(today.year, int(month_s), int(day_s))
            if d < today:
                d = d.replace(year=today.year + 1)
        else:
            time_part = s
            d = base_date or today
        t = datetime.strptime(time_part, "%H:%M").time()
    except (ValueError, TypeError):
        raise ValueError("Formato inválido. Usa DD/MM HH:MM (u HH:MM para hoy), ej: 12/07 15:00")
    return datetime.combine(d, t, tzinfo=_tz.LIMA)


async def event_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args) if context.args else ""
    parts = [p.strip() for p in text.split(" | ")]
    if len(parts) != 3 or not all(parts):
        await update.message.reply_text(
            "Uso: /event <título> | <inicio> | <fin>\n"
            "Fechas: DD/MM HH:MM, o solo HH:MM para hoy. El fin puede ser solo HH:MM (mismo día).\n"
            "Ej: /event Dentista | 12/07 15:00 | 16:00"
        )
        return
    title, start_s, end_s = parts
    try:
        start_dt = _parse_event_datetime(start_s)
        end_dt = _parse_event_datetime(end_s, base_date=start_dt.date())
        if end_dt <= start_dt:
            raise ValueError("La hora de fin debe ser posterior a la de inicio.")
    except ValueError as e:
        await update.message.reply_text(str(e))
        return
    try:
        create_event(title, start_dt.isoformat(), end_dt.isoformat())
    except Exception as e:
        await update.message.reply_text(f"Error al crear el evento: {e}")
        return
    await update.message.reply_text(
        f"📅 Evento creado: {title}\n"
        f"{start_dt.strftime('%d/%m %H:%M')}–{end_dt.strftime('%H:%M' if end_dt.date() == start_dt.date() else '%d/%m %H:%M')}"
    )


async def delevent_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Uso: /delevent <n>  (número según /events)")
        return
    try:
        evs = list_events(max_results=10)
    except Exception as e:
        await update.message.reply_text(f"Error al obtener eventos: {e}")
        return
    ev = await _pick_numbered(update, context.args[0], evs, "/events")
    if ev is None:
        return
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Eliminar", callback_data=f"delevent:yes:{ev['id']}"),
        InlineKeyboardButton("❌ Cancelar", callback_data="delevent:no"),
    ]])
    await update.message.reply_text(
        f"🗑 Eliminar evento *{esc_md1(ev.get('summary', '(sin título)'))}*?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def backlog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items = list_backlog()
    if not items:
        await update.message.reply_text("No hay ideas en el backlog.")
        return
    lines = [f"💡 {bold(f'Backlog ({len(items)})')}", SEP, ""]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}\\. {bold(item['title'])}")
        if item.get("description"):
            lines.append(f"  {italic(item['description'])}")
        if item.get("next_step"):
            lines.append(f"  ▸ {esc(item['next_step'])}")
        else:
            lines.append(f"  ⚠ {italic('sin primer paso')}")
    lines += ["", italic("Usa /step \\<n\\> \\<primer paso\\> o /delidea \\<n\\>")]
    await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")


async def idea_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text(
            "Uso: /idea <título>  (o /idea <título> | <descripción> | <primer paso>)"
        )
        return
    title, desc, step = (text.split(" | ", 2) + ["", ""])[:3]
    create_backlog_item(title.strip(), description=desc.strip(), next_step=step.strip())
    reply = f"💡 Idea guardada: {title.strip()}"
    if not step.strip():
        reply += "\nSin primer paso aún — dale uno con /step cuando lo tengas."
    await update.message.reply_text(reply)


async def step_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Uso: /step <n> <primer paso>  (número según /backlog)")
        return
    item = await _pick_numbered(update, args[0], list_backlog(), "/backlog")
    if item is None:
        return
    step = " ".join(args[1:])
    set_backlog_step(item["doc_id"], step)
    await update.message.reply_text(f"▸ Primer paso para «{item['title']}»: {step}")


async def delidea_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _confirm_delete(update, context, "delidea", "idea", list_backlog(), "/backlog")


async def track_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from callbacks import _pending_track, build_duration_keyboard
    activity = " ".join(context.args) if context.args else ""
    if not activity:
        await update.message.reply_text("Uso: /track <actividad>")
        return
    _pending_track[update.effective_chat.id] = {"activity": activity}
    await update.message.reply_text(
        f"⏱ *{esc_md1(activity)}*\n¿Cuánto tiempo planeas?",
        reply_markup=build_duration_keyboard(),
        parse_mode="Markdown",
    )


def _parse_today_range(start_str: str, end_str: str) -> tuple[str, str]:
    """Parse two HH:MM strings as today's Lima times. Returns ISO strings.
    Raises ValueError with a user-facing message."""
    today = _tz.now().date()
    try:
        start_dt = datetime.strptime(start_str, "%H:%M").replace(
            year=today.year, month=today.month, day=today.day, tzinfo=_tz.LIMA
        )
        end_dt = datetime.strptime(end_str, "%H:%M").replace(
            year=today.year, month=today.month, day=today.day, tzinfo=_tz.LIMA
        )
    except ValueError:
        raise ValueError("Formato de hora inválido. Usa HH:MM, ej: 10:00 11:30")
    if end_dt <= start_dt:
        raise ValueError("La hora de fin debe ser posterior a la de inicio.")
    return start_dt.isoformat(), end_dt.isoformat()


async def log_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text("Uso: /log <actividad> <inicio HH:MM> <fin HH:MM>")
        return
    activity = " ".join(args[:-2])
    try:
        start_iso, end_iso = _parse_today_range(args[-2], args[-1])
        create_timeblock(activity, start_iso, end_iso)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return
    except Exception as e:
        await update.message.reply_text(f"Error al registrar: {e}")
        return
    mins = round((datetime.fromisoformat(end_iso) - datetime.fromisoformat(start_iso)).total_seconds() / 60)
    await update.message.reply_text(
        f"✅ *{esc_md1(activity)}* — {fmt_duration(mins)} registrados.",
        parse_mode="Markdown",
    )


def _todays_blocks() -> list[dict]:
    """Today's timeblocks in chronological order; index+1 is the user-facing number."""
    now = _tz.now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return list_timeblocks(day_start.isoformat(), now.isoformat())


def _fmt_block(b: dict) -> str:
    s = datetime.fromisoformat(b["start"]).astimezone(_tz.LIMA)
    e = datetime.fromisoformat(b["end"]).astimezone(_tz.LIMA)
    return f"{s.strftime('%H:%M')}–{e.strftime('%H:%M')} {b['activity']}"


async def blocks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        blocks = _todays_blocks()
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return
    if not blocks:
        await update.message.reply_text("No hay bloques registrados hoy.")
        return
    lines = [f"⏱ {bold(f'Bloques de hoy ({len(blocks)})')}", SEP, ""]
    for i, b in enumerate(blocks, 1):
        s = datetime.fromisoformat(b["start"]).astimezone(_tz.LIMA)
        e = datetime.fromisoformat(b["end"]).astimezone(_tz.LIMA)
        mins = round((e - s).total_seconds() / 60)
        lines.append(
            f"{i}\\. {esc(s.strftime('%H:%M'))}–{esc(e.strftime('%H:%M'))} "
            f"{bold(b['activity'])} _{esc(fmt_duration(mins))}_"
        )
    lines += ["", italic("Usa /delblock \\<n\\> o /editblock \\<n\\> \\<inicio\\> \\<fin\\>")]
    await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")


async def _pick_block(update: Update, arg: str) -> dict | None:
    """Resolve a /blocks number to a block, replying with the error if invalid."""
    try:
        blocks = _todays_blocks()
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return None
    return await _pick_numbered(update, arg, blocks, "/blocks")


async def delblock_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Uso: /delblock <n>  (número según /blocks)")
        return
    block = await _pick_block(update, context.args[0])
    if block is None:
        return
    try:
        delete_timeblock(block["event_id"])
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return
    await update.message.reply_text(f"🗑 Bloque eliminado: {_fmt_block(block)}")


async def editblock_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) != 3:
        await update.message.reply_text("Uso: /editblock <n> <inicio HH:MM> <fin HH:MM>")
        return
    block = await _pick_block(update, args[0])
    if block is None:
        return
    try:
        start_iso, end_iso = _parse_today_range(args[1], args[2])
        update_timeblock(block["event_id"], start=start_iso, end=end_iso)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return
    await update.message.reply_text(
        f"✏️ Bloque actualizado: {args[1]}–{args[2]} {block['activity']} (antes {_fmt_block(block)})"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Replying to the tracking status message with plain text starts that activity
    immediately (open-ended). If a session is already active, log it first and
    switch. Any other free text just gets a pointer to /help."""
    import tracking_state
    from callbacks import _create_timeblock_safe, _elapsed, send_tracking_status

    activity = (update.message.text or "").strip()
    if not activity:
        return
    chat_id = update.effective_chat.id

    reply_to = update.message.reply_to_message
    status_id = tracking_state.get_state().get("status_message_id")
    if reply_to is None or reply_to.message_id != status_id:
        await update.message.reply_text(
            "No entiendo ese mensaje. Responde al mensaje de tracking para "
            "iniciar o cambiar de actividad, o usa /help."
        )
        return

    state = tracking_state.get_state()
    if state.get("active"):
        if activity == state.get("activity"):
            await send_tracking_status(context.bot, chat_id, notify=True)
            return
        final = tracking_state.stop_tracking()
        _create_timeblock_safe(final)
        await update.message.reply_text(
            f"✅ {final.get('activity', '?')} — {fmt_duration(_elapsed(final))} registrados."
        )
    tracking_state.start_tracking(activity)
    await send_tracking_status(context.bot, chat_id, notify=True)
