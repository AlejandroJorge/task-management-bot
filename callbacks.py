"""
Inline keyboard callback routing.

callback_data format: namespace:action[:arg...]
  track:cat:<category>       — category selected (pending track flow)
  track:begin:<min|open>     — start session with optional planned duration
  track:plan:<min>           — set planned end on active session
  track:extend:<min>         — extend planned end on active session
  track:stop                 — stop active session
  log:cat:<category>         — category selected (pending log flow)
  confirm:yes / confirm:no   — destructive action confirmation
  task:done:<doc_id>         — mark task complete
"""

import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import tracking_state
import tz as _tz
from categories import load_categories
from formatting import esc_md1, fmt_duration
from tracking_tools import create_timeblock, list_timeblocks

logger = logging.getLogger(__name__)

# Pending state for multi-step command flows (in-memory, lost on restart — acceptable)
_pending_track: dict[int, dict] = {}  # chat_id → {activity}
_pending_log:   dict[int, dict] = {}  # chat_id → {activity, start, end}


# ── Keyboard builders ─────────────────────────────────────────────────────────

def build_category_keyboard(callback_prefix: str) -> InlineKeyboardMarkup:
    cats = load_categories()
    buttons = [
        InlineKeyboardButton(v["label"], callback_data=f"{callback_prefix}:{k}")
        for k, v in cats.items()
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


def build_duration_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("15 min",   callback_data="track:begin:15"),
            InlineKeyboardButton("30 min",   callback_data="track:begin:30"),
            InlineKeyboardButton("1 hora",   callback_data="track:begin:60"),
        ],
        [InlineKeyboardButton("Sin límite", callback_data="track:begin:open")],
    ])


def build_tracking_text(state: dict) -> str:
    activity = state.get("activity", "?")
    elapsed = state.get("elapsed_minutes", 0)
    try:
        started_dt = datetime.fromisoformat(state["started_at"]).astimezone(_tz.LIMA)
        desde = started_dt.strftime("%H:%M")
    except Exception:
        desde = "?"
    dur = fmt_duration(elapsed)
    text = f"⏱ *{esc_md1(activity)}* — desde las {desde} ({dur})"
    if state.get("planned_end"):
        try:
            end_dt = datetime.fromisoformat(state["planned_end"]).astimezone(_tz.LIMA)
            mins_rem = state.get("minutes_remaining", 0)
            if mins_rem > 0:
                text += f"\nTermina a las {end_dt.strftime('%H:%M')} ({mins_rem} min restantes)"
            else:
                text += "\n⚠️ Tiempo terminado — ¿extender o parar?"
        except Exception:
            pass
    return text


def build_tracking_keyboard(state: dict) -> InlineKeyboardMarkup:
    if state.get("planned_end"):
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("+15 min", callback_data="track:extend:15"),
            InlineKeyboardButton("+30 min", callback_data="track:extend:30"),
            InlineKeyboardButton("⏹ Parar", callback_data="track:stop"),
        ]])
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("15 min", callback_data="track:plan:15"),
            InlineKeyboardButton("30 min", callback_data="track:plan:30"),
            InlineKeyboardButton("1 hora", callback_data="track:plan:60"),
        ],
        [InlineKeyboardButton("⏹ Parar", callback_data="track:stop")],
    ])


def _libre_keyboard() -> InlineKeyboardMarkup | None:
    try:
        now = _tz.now()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        blocks = list_timeblocks(day_start.isoformat(), now.isoformat())
        seen: list[tuple[str, str]] = []
        seen_names: set[str] = set()
        for b in reversed(blocks):
            name = b["activity"]
            if name not in seen_names:
                seen_names.add(name)
                seen.append((name, b.get("category", "unclassified")))
            if len(seen) >= 3:
                break
    except Exception:
        seen = []
    if not seen:
        return None
    rows = []
    for name, cat in seen:
        cb = f"track:quickstart:{name}:{cat}"
        if len(cb.encode()) > 64:
            cb = f"track:quickstart:{name[:25]}:{cat}"
        rows.append([InlineKeyboardButton(name[:35], callback_data=cb)])
    return InlineKeyboardMarkup(rows)


# ── Status message helpers ────────────────────────────────────────────────────

async def send_tracking_status(bot, chat_id: int | str, notify: bool = True) -> None:
    """
    Send or update the persistent tracking status message.
    notify=True  → delete old + send new (push notification).
    notify=False → edit in place (silent).
    """
    state = tracking_state.get_state()
    msg_id = state.get("status_message_id")

    if state.get("active"):
        text = build_tracking_text(state)
        keyboard = build_tracking_keyboard(state)
    else:
        text = "¿Qué estás haciendo?"
        keyboard = _libre_keyboard()

    if notify:
        if msg_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception:
                pass
        msg = await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode="Markdown")
        tracking_state.set_status_message_id(msg.message_id)
    else:
        if msg_id:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id,
                    text=text, reply_markup=keyboard, parse_mode="Markdown",
                )
                return
            except Exception:
                pass
        msg = await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode="Markdown")
        tracking_state.set_status_message_id(msg.message_id)


# ── Main callback dispatcher ──────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    chat_id = update.effective_chat.id
    parts = data.split(":")
    ns = parts[0] if parts else ""

    if ns == "track":
        await _handle_track(query, chat_id, context, parts[1:])
    elif ns == "log":
        await _handle_log(query, chat_id, parts[1:])
    elif ns == "deltask":
        await _handle_deltask(query, parts[1:])
    elif ns == "delidea":
        await _handle_delidea(query, parts[1:])
    elif ns == "task" and len(parts) >= 3:
        await _handle_task(query, parts[1], parts[2])


# ── Track flow ────────────────────────────────────────────────────────────────

async def _handle_track(query, chat_id, context, args: list[str]) -> None:
    action = args[0] if args else ""

    if action == "cat":
        # Category chosen → show duration picker
        category = args[1] if len(args) > 1 else "unclassified"
        pending = _pending_track.get(chat_id)
        if not pending:
            await query.answer("Sesión expirada, usa /track de nuevo.", show_alert=True)
            return
        _pending_track[chat_id] = {**pending, "category": category}
        cat_label = load_categories().get(category, {}).get("label", category)
        activity = pending["activity"]
        text = f"⏱ *{esc_md1(activity)}* — {esc_md1(cat_label)}\n¿Cuánto tiempo planeas?"
        await query.edit_message_text(text, reply_markup=build_duration_keyboard(), parse_mode="Markdown")

    elif action == "begin":
        # Duration chosen (or open-ended) → start session
        pending = _pending_track.pop(chat_id, None)
        if not pending:
            await query.answer("Sesión expirada, usa /track de nuevo.", show_alert=True)
            return
        activity = pending["activity"]
        category = pending.get("category", "unclassified")
        try:
            tracking_state.start_tracking(activity, category=category)
        except ValueError as e:
            await query.answer(str(e), show_alert=True)
            return
        minutes_arg = args[1] if len(args) > 1 else "open"
        if minutes_arg != "open":
            try:
                tracking_state.set_planned_end(int(minutes_arg))
            except Exception:
                pass
        state = tracking_state.get_state()
        await query.edit_message_text(build_tracking_text(state), reply_markup=build_tracking_keyboard(state), parse_mode="Markdown")
        tracking_state.set_status_message_id(query.message.message_id)

    elif action == "quickstart":
        # One-tap restart of a recent activity (from libre widget)
        activity = args[1] if len(args) > 1 else ""
        category = args[2] if len(args) > 2 else "unclassified"
        if not activity:
            return
        try:
            tracking_state.start_tracking(activity, category=category)
        except ValueError as e:
            await query.answer(str(e), show_alert=True)
            return
        state = tracking_state.get_state()
        await query.edit_message_text(build_tracking_text(state), reply_markup=build_tracking_keyboard(state), parse_mode="Markdown")
        tracking_state.set_status_message_id(query.message.message_id)

    elif action == "stop":
        try:
            final = tracking_state.stop_tracking()
        except ValueError as e:
            await query.answer(str(e), show_alert=True)
            return
        _create_timeblock_safe(final)
        elapsed = _elapsed(final)
        activity = final.get("activity", "?")
        done_text = f"✅ *{esc_md1(activity)}* — {fmt_duration(elapsed)} registrados\n\n¿Qué estás haciendo?"
        keyboard = _libre_keyboard()
        try:
            await query.edit_message_text(done_text, reply_markup=keyboard, parse_mode="Markdown")
            tracking_state.set_status_message_id(query.message.message_id)
        except Exception:
            msg = await context.bot.send_message(chat_id=chat_id, text=done_text, reply_markup=keyboard, parse_mode="Markdown")
            tracking_state.set_status_message_id(msg.message_id)

    elif action == "plan" and args[1:]:
        try:
            tracking_state.set_planned_end(int(args[1]))
        except ValueError as e:
            await query.answer(str(e), show_alert=True)
            return
        state = tracking_state.get_state()
        await query.edit_message_text(build_tracking_text(state), reply_markup=build_tracking_keyboard(state), parse_mode="Markdown")

    elif action == "extend" and args[1:]:
        try:
            tracking_state.extend_planned(int(args[1]))
        except ValueError as e:
            await query.answer(str(e), show_alert=True)
            return
        state = tracking_state.get_state()
        await query.edit_message_text(build_tracking_text(state), reply_markup=build_tracking_keyboard(state), parse_mode="Markdown")


# ── Log flow ──────────────────────────────────────────────────────────────────

async def _handle_log(query, chat_id, args: list[str]) -> None:
    action = args[0] if args else ""

    if action == "cat":
        category = args[1] if len(args) > 1 else "unclassified"
        pending = _pending_log.pop(chat_id, None)
        if not pending:
            await query.answer("Sesión expirada, usa /log de nuevo.", show_alert=True)
            return
        try:
            create_timeblock(
                pending["activity"],
                pending["start"],
                pending["end"],
                category=category,
            )
        except Exception as e:
            await query.edit_message_text(f"Error al registrar: {e}")
            return
        elapsed = _elapsed({"started_at": pending["start"], "ended_at": pending["end"]})
        await query.edit_message_text(
            f"✅ *{esc_md1(pending['activity'])}* — {fmt_duration(elapsed)} registrados.",
            parse_mode="Markdown",
        )


# ── Delete flows ──────────────────────────────────────────────────────────────

async def _handle_deltask(query, args: list[str]) -> None:
    action = args[0] if args else ""
    if action == "no":
        await query.edit_message_text("Cancelado.")
        return
    if action == "yes" and len(args) > 1:
        from tasks_tools import delete_task
        try:
            delete_task(int(args[1]))
            await query.edit_message_text("✅ Tarea eliminada.")
        except Exception as e:
            await query.edit_message_text(f"Error: {e}")


async def _handle_delidea(query, args: list[str]) -> None:
    action = args[0] if args else ""
    if action == "no":
        await query.edit_message_text("Cancelado.")
        return
    if action == "yes" and len(args) > 1:
        from backlog_tools import delete_backlog_item
        try:
            delete_backlog_item(int(args[1]))
            await query.edit_message_text("✅ Idea eliminada.")
        except Exception as e:
            await query.edit_message_text(f"Error: {e}")


# ── Task flow ─────────────────────────────────────────────────────────────────

async def _handle_task(query, action: str, raw_id: str) -> None:
    if action == "done":
        from tasks_tools import update_task
        try:
            update_task(int(raw_id), done=True)
            await query.answer("✅ Tarea completada")
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception as e:
            await query.answer(str(e), show_alert=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_timeblock_safe(final: dict) -> None:
    try:
        create_timeblock(
            final["activity"],
            final["started_at"],
            final["ended_at"],
            category=final.get("category", "unclassified"),
        )
    except Exception:
        logger.exception("Failed to create timeblock on stop")


def _elapsed(final: dict) -> int:
    try:
        start = datetime.fromisoformat(final["started_at"])
        end = datetime.fromisoformat(final.get("ended_at", final.get("end", "")))
        return max(0, int((end - start).total_seconds() / 60))
    except Exception:
        return 0
