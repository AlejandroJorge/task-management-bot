"""
Inline keyboard callback routing.

callback_data format: namespace:action[:arg...]
  track:begin:<min|open>     — start session with optional planned duration
  track:plan:<min>           — set planned end on active session
  track:extend:<min>         — extend planned end on active session
  track:stop                 — stop active session
  track:unplan               — make active session open-ended again
  track:backdate             — show "started earlier" picker on active session
  track:setstart:<min>       — move session start to <min> minutes ago
  track:refresh              — re-render the status message
  deltask:yes:<doc_id> / deltask:no — task deletion confirmation
  delidea:yes:<doc_id> / delidea:no — backlog deletion confirmation
"""

import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import tracking_state
import tz as _tz
from formatting import esc_md1, fmt_duration
from tracking_tools import create_timeblock

logger = logging.getLogger(__name__)

# Pending state for multi-step command flows (in-memory, lost on restart — acceptable)
_pending_track: dict[int, dict] = {}  # chat_id → {activity}


# ── Keyboard builders ─────────────────────────────────────────────────────────

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
        rows = [
            [
                InlineKeyboardButton("+15 min", callback_data="track:extend:15"),
                InlineKeyboardButton("+30 min", callback_data="track:extend:30"),
            ],
            [
                InlineKeyboardButton("♾ Sin límite", callback_data="track:unplan"),
                InlineKeyboardButton("⏹ Parar", callback_data="track:stop"),
            ],
        ]
    else:
        rows = [
            [
                InlineKeyboardButton("15 min", callback_data="track:plan:15"),
                InlineKeyboardButton("30 min", callback_data="track:plan:30"),
                InlineKeyboardButton("1 hora", callback_data="track:plan:60"),
            ],
            [InlineKeyboardButton("⏹ Parar", callback_data="track:stop")],
        ]
    rows.append([InlineKeyboardButton("⏪ Empezó antes", callback_data="track:backdate")])
    return InlineKeyboardMarkup(rows)


def build_backdate_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("hace 5 min",  callback_data="track:setstart:5"),
            InlineKeyboardButton("hace 10 min", callback_data="track:setstart:10"),
            InlineKeyboardButton("hace 15 min", callback_data="track:setstart:15"),
        ],
        [
            InlineKeyboardButton("hace 30 min", callback_data="track:setstart:30"),
            InlineKeyboardButton("hace 1 hora", callback_data="track:setstart:60"),
            InlineKeyboardButton("↩ Volver",    callback_data="track:refresh"),
        ],
    ])


# ── Status message helpers ────────────────────────────────────────────────────

async def send_tracking_status(bot, chat_id: int | str, notify: bool = True, silent: bool = False) -> None:
    """
    Send or update the persistent tracking status message.
    notify=True  → delete old + send new (push notification).
    notify=False → edit in place (silent).
    silent=True  → when re-sending, do it without a notification
                   (moves the message to the bottom quietly).
    """
    state = tracking_state.get_state()
    msg_id = state.get("status_message_id")

    if state.get("active"):
        text = build_tracking_text(state)
        keyboard = build_tracking_keyboard(state)
    else:
        text = "¿Qué estás haciendo?"
        keyboard = None

    if msg_id:
        try:
            if notify:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            else:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id,
                    text=text, reply_markup=keyboard, parse_mode="Markdown",
                )
                return
        except Exception as e:
            # Unchanged text is fine — don't fall through to a (notifying) resend
            if "not modified" in str(e).lower():
                return
    msg = await bot.send_message(
        chat_id=chat_id, text=text, reply_markup=keyboard,
        parse_mode="Markdown", disable_notification=silent,
    )
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
    elif ns == "deltask":
        from tasks_tools import delete_task
        await _handle_delete(query, parts[1:], delete_task, "Tarea eliminada")
    elif ns == "delidea":
        from backlog_tools import delete_backlog_item
        await _handle_delete(query, parts[1:], delete_backlog_item, "Idea eliminada")


# ── Track flow ────────────────────────────────────────────────────────────────

async def _show_active_session(query) -> None:
    """Render the active session on the tapped message and make it the status message."""
    state = tracking_state.get_state()
    await query.edit_message_text(build_tracking_text(state), reply_markup=build_tracking_keyboard(state), parse_mode="Markdown")
    tracking_state.set_status_message_id(query.message.message_id)


async def _handle_track(query, chat_id, context, args: list[str]) -> None:
    action = args[0] if args else ""

    if action == "begin":
        # Duration chosen (or open-ended) → start session
        pending = _pending_track.pop(chat_id, None)
        if not pending:
            await query.answer("Sesión expirada, usa /track de nuevo.", show_alert=True)
            return
        try:
            tracking_state.start_tracking(pending["activity"])
        except ValueError as e:
            await query.answer(str(e), show_alert=True)
            return
        minutes_arg = args[1] if len(args) > 1 else "open"
        if minutes_arg != "open":
            try:
                tracking_state.set_planned_end(int(minutes_arg))
            except Exception:
                pass
        await _show_active_session(query)

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
        try:
            await query.edit_message_text(done_text, parse_mode="Markdown")
            tracking_state.set_status_message_id(query.message.message_id)
        except Exception:
            msg = await context.bot.send_message(chat_id=chat_id, text=done_text, parse_mode="Markdown")
            tracking_state.set_status_message_id(msg.message_id)

    elif action == "unplan":
        try:
            tracking_state.clear_planned_end()
        except ValueError as e:
            await query.answer(str(e), show_alert=True)
            return
        await _show_active_session(query)

    elif action == "backdate":
        await query.edit_message_reply_markup(reply_markup=build_backdate_keyboard())

    elif action == "setstart" and args[1:]:
        try:
            old_start, new_start = tracking_state.backdate_start(int(args[1]))
        except ValueError as e:
            await query.answer(str(e), show_alert=True)
            return
        note = _resolve_overlaps(new_start, old_start)
        if note:
            await query.answer(f"Bloques ajustados: {note}", show_alert=False)
        await _show_active_session(query)

    elif action == "refresh":
        await _show_active_session(query)

    elif action in ("plan", "extend") and args[1:]:
        # Both set planned_end to now + minutes; only the button label differs.
        try:
            tracking_state.set_planned_end(int(args[1]))
        except ValueError as e:
            await query.answer(str(e), show_alert=True)
            return
        await _show_active_session(query)


# ── Delete flows ──────────────────────────────────────────────────────────────

async def _handle_delete(query, args: list[str], delete_fn, ok_text: str) -> None:
    action = args[0] if args else ""
    if action == "no":
        await query.edit_message_text("Cancelado.")
        return
    if action == "yes" and len(args) > 1:
        try:
            delete_fn(int(args[1]))
            await query.edit_message_text(f"✅ {ok_text}.")
        except Exception as e:
            await query.edit_message_text(f"Error: {e}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_overlaps(new_start: str, old_start: str) -> str | None:
    """After backdating a session, trim or remove logged timeblocks that the
    session now covers ('forgot to stop X before starting Y'). Returns a short
    summary of what was adjusted, or None."""
    from tracking_tools import delete_timeblock, list_timeblocks, update_timeblock
    ns = datetime.fromisoformat(new_start)
    if ns >= datetime.fromisoformat(old_start):
        return None  # start moved forward — session shrank, nothing to resolve
    try:
        notes = []
        for b in list_timeblocks(new_start, old_start):
            if datetime.fromisoformat(b["end"]) <= ns:
                continue
            if datetime.fromisoformat(b["start"]) < ns:
                update_timeblock(b["event_id"], end=new_start)
                notes.append(f"{b['activity']} recortado")
            else:
                delete_timeblock(b["event_id"])
                notes.append(f"{b['activity']} eliminado")
        return ", ".join(notes) or None
    except Exception:
        logger.exception("Failed to resolve overlaps after backdate")
        return None


def _create_timeblock_safe(final: dict) -> None:
    try:
        create_timeblock(final["activity"], final["started_at"], final["ended_at"])
    except Exception:
        logger.exception("Failed to create timeblock on stop")


def _elapsed(final: dict) -> int:
    try:
        start = datetime.fromisoformat(final["started_at"])
        end = datetime.fromisoformat(final.get("ended_at", final.get("end", "")))
        return max(0, round((end - start).total_seconds() / 60))
    except Exception:
        return 0
