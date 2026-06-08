"""
Agentic loop: natural language message → LLM → tool calls → final reply.

Flow:
  1. User message appended to history.
  2. LLM called with full history + tool schemas.
  3. If LLM returns tool_calls:
       a. Safe tools execute immediately.
       b. On the first destructive tool, ALL remaining calls (safe + destructive)
          get placeholder responses so history stays valid, and a single
          ConfirmationRequest is returned covering the whole batch.
       c. On confirmation, every placeholder is replaced with the real result
          (destructive calls execute only if confirmed) and the loop continues.
  4. When LLM returns plain text, that is the final reply.
"""

import dataclasses
import json
import logging
import os
from typing import Any

import llm
import tz as _tz
from backlog_tools import list_backlog
from categories import categories_for_prompt
from tasks_tools import list_tasks
from tools_registry import REQUIRE_CONFIRMATION, TOOLS, dispatch
from tracking_state import get_state as _get_tracking_state

logger = logging.getLogger(__name__)

_PROFILE_PATH = os.getenv("USER_PROFILE_PATH", "data/user_profile.json")


def _profile_context() -> str:
    try:
        with open(_PROFILE_PATH, encoding="utf-8") as f:
            import json as _json
            profile = _json.load(f)
    except FileNotFoundError:
        return ""
    except Exception:
        logger.exception("Failed to load user profile")
        return ""
    if not profile:
        return ""
    lines = ["Información sobre el usuario:"]
    for key, label in [("name", "Nombre"), ("location", "Ubicación"),
                       ("timezone_label", "Zona horaria"), ("education", "Educación"),
                       ("work", "Trabajo")]:
        if profile.get(key):
            lines.append(f"  - {label}: {profile[key]}")
    schedule = profile.get("schedule", {})
    if schedule:
        parts = []
        if schedule.get("work_days"):
            parts.append(f"trabajo {schedule['work_days']}")
        if schedule.get("work_hours"):
            parts.append(schedule["work_hours"])
        if schedule.get("class_days"):
            parts.append(f"clases {schedule['class_days']}")
        if parts:
            lines.append(f"  - Horario: {', '.join(parts)}")
    for fact in profile.get("facts", []):
        if fact:
            lines.append(f"  - {fact}")
    return "\n".join(lines)


def _system_prompt() -> str:
    now = _tz.now().strftime("%A, %d de %B de %Y, %H:%M")
    base = (
        f"Eres un asistente personal. Hoy es {now}. "
        "Tienes acceso al Google Calendar del usuario (calendario 'Eventos'), su lista de tareas, su backlog "
        "y un calendario de registro de tiempo ('Tracking'). "
        "Las tareas son acciones inmediatas; el backlog son ideas o proyectos a largo plazo. "
        "REGLAS DE TRACKING DE TIEMPO: "
        "(1) create_timeblock → SOLO para registrar intervalos 100% pasados. NO toca ni interrumpe ninguna sesión en vivo. "
        "(2) start_tracking → arranca una sesión en vivo. Si el usuario dice 'llevo N minutos/horas haciendo X', usa el parámetro opcional started_at con la hora de inicio real (now − N minutos) para que el elapsed y el bloque en Calendar reflejen el tiempo real. "
        "(3) stop_tracking → termina la sesión activa con hora exacta. Solo cuando el usuario diga que terminó. "
        "(4) resume_as_live → cuando el usuario dice que SIGUE haciendo algo ya registrado como bloque pasado: adopta ese evento como sesión activa. Falla si hay otros bloques entre el fin de ese evento y ahora. "
        "(5) get_tracking_status → estado actual. elapsed_minutes = now - started_at. Si el usuario cuestiona el tiempo, explícalo; NUNCA reinicies la sesión. "
        "(6) NUNCA llames stop_tracking para registrar un bloque pasado. Los dos modos son completamente independientes. "
        "(7) start_tracking con planned_minutes → modo planificado. Úsalo cuando el usuario diga 'voy a hacer X por N minutos/horas'. El bot avisará 5 min antes del fin y al terminar el tiempo. "
        "(8) extend_tracking(minutes) → cuando el usuario quiere continuar N minutos más en una sesión planificada. Solo válido en modo planificado. "
        "(9) CATEGORÍAS: al llamar create_timeblock o start_tracking, SIEMPRE incluye el parámetro category. Infiere la categoría más apropiada a partir del nombre de la actividad y el contexto. Si hay duda genuina, usa 'unclassified'. "
        "Interpreta las solicitudes en lenguaje natural y llama las herramientas correspondientes. "
        "REGLAS para el campo 'due' al crear o editar tareas: "
        "(1) Si el usuario NO menciona fecha ni plazo, NO incluyas 'due'. "
        "(2) Si menciona una fecha sin hora (ej. 'mañana', 'el lunes'), usa SOLO formato YYYY-MM-DD. "
        "(3) Solo usa formato con hora (YYYY-MM-DDTHH:MM:SSZ) si el usuario dice hora explícita (ej. 'a las 3pm'). "
        "(4) NUNCA uses T00:00:00Z ni ninguna hora inventada. "
        "Responde siempre en español neutro: sin modismos, regionalismos ni expresiones coloquiales de ningún país. "
        "Usa el contexto del usuario para personalizar respuestas (horario, ubicación, etc.). "
        "Usa Markdown de Telegram (v1): *negrita* con un solo asterisco, _cursiva_ con guion bajo. "
        "NUNCA uses ** para negrita ni __ para subrayado — Telegram no los soporta. "
        "NUNCA uses tablas — Telegram no las renderiza. Para listas de registros de tiempo u otros datos, usa lista cronológica con viñetas (•). "
        "Puedes usar emojis ligeros como titular de sección (ej. ✅ para tareas, 📅 para eventos). "
        "Respuestas cortas y directas. "
        "NUNCA menciones doc_id, event_id ni ningún identificador interno al usuario. "
        "Refierete a tareas y eventos solo por su nombre."
    )
    try:
        base += "\n\n" + categories_for_prompt()
    except Exception:
        pass
    profile_ctx = _profile_context()
    if profile_ctx:
        base += "\n\n" + profile_ctx
    try:
        ts = _get_tracking_state()
        if ts.get("status") == "ACTIVO":
            ts_lines = [f"Tracking activo: {ts['activity']} (modo {ts.get('mode', 'indefinido')}, {ts.get('elapsed_minutes', 0)} min transcurridos)"]
            if ts.get("mode") == "planificado":
                ts_lines.append(f"  Fin planificado: {ts.get('planned_end', '?')} ({ts.get('minutes_remaining', '?')} min restantes)")
            base += "\n\n" + "\n".join(ts_lines)
    except Exception:
        pass
    try:
        tasks = list_tasks(show_done=False)
        if tasks:
            lines = ["Tareas pendientes actuales:"]
            for t in tasks:
                due = f" (vence {t['due']})" if t.get("due") else ""
                lines.append(f"  - [doc_id={t['doc_id']}] {t['title']}{due}")
            base += "\n\n" + "\n".join(lines)
    except Exception:
        pass
    try:
        items = list_backlog()
        if items:
            lines = ["Backlog actual:"]
            for item in items:
                lines.append(f"  - [doc_id={item['doc_id']}] {item['title']}")
            base += "\n\n" + "\n".join(lines)
    except Exception:
        pass
    return base


@dataclasses.dataclass
class ConfirmationRequest:
    """
    Returned when destructive tool calls are pending user confirmation.

    pending_calls: ALL remaining calls in the batch (safe + destructive),
                   each as {name, args_json, call_id}.
    pending_messages: history snapshot with placeholder tool messages already
                      in place for every pending call.
    """
    pending_calls: list[dict[str, Any]]
    pending_messages: list[dict]


def _trim_history(history: list[dict], max_turns: int = 8) -> None:
    user_indices = [i for i, m in enumerate(history) if m.get("role") == "user"]
    if len(user_indices) > max_turns:
        cut = user_indices[-max_turns]
        del history[1:cut]


def _placeholder(call_id: str) -> dict:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps({"status": "awaiting_confirmation"}),
    }


async def process(
    user_message: str,
    history: list[dict],
) -> str | ConfirmationRequest:
    if not history or history[0].get("role") != "system":
        history.insert(0, {"role": "system", "content": _system_prompt()})
    else:
        history[0]["content"] = _system_prompt()

    history.append({"role": "user", "content": user_message})

    _trim_history(history)
    while True:
        response = await llm.chat(history, tools=TOOLS)
        history.append(response)

        tool_calls = response.get("tool_calls")
        if not tool_calls:
            reply = response["content"]
            logger.info("LLM reply: %s", reply.splitlines()[0][:120] if reply else "(empty)")
            return reply

        logger.info("LLM requested %d tool call(s): %s", len(tool_calls),
                    ", ".join(tc["function"]["name"] for tc in tool_calls))

        for i, tc in enumerate(tool_calls):
            name = tc["function"]["name"]
            args_json = tc["function"]["arguments"]

            if name in REQUIRE_CONFIRMATION:
                logger.info("Pausing for confirmation on destructive call: %s %s", name, args_json)
                remaining = tool_calls[i:]
                for r in remaining:
                    history.append(_placeholder(r["id"]))
                return ConfirmationRequest(
                    pending_calls=[
                        {
                            "name": r["function"]["name"],
                            "args_json": r["function"]["arguments"],
                            "call_id": r["id"],
                        }
                        for r in remaining
                    ],
                    pending_messages=list(history),
                )

            logger.info("Calling tool: %s %s", name, args_json)
            try:
                result = dispatch(name, args_json)
                logger.info("Tool %s result: %s", name, result[:120] if isinstance(result, str) else result)
            except Exception as exc:
                logger.exception("Tool %s raised an error", name)
                result = json.dumps({"error": str(exc)})
            history.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })


async def resume_after_confirmation(
    confirmed: bool,
    request: ConfirmationRequest,
    history: list[dict],
) -> str:
    history.clear()
    history.extend(request.pending_messages)

    for call in request.pending_calls:
        name = call["name"]
        args_json = call["args_json"]
        call_id = call["call_id"]

        is_destructive = name in REQUIRE_CONFIRMATION
        if is_destructive and not confirmed:
            result = json.dumps({"cancelled": True})
        else:
            try:
                result = dispatch(name, args_json)
            except Exception as exc:
                result = json.dumps({"error": str(exc)})

        for msg in history:
            if msg.get("role") == "tool" and msg.get("tool_call_id") == call_id:
                msg["content"] = result
                break

    while True:
        response = await llm.chat(history, tools=TOOLS)
        history.append(response)
        if not response.get("tool_calls"):
            return response["content"]
        for tc in response["tool_calls"]:
            try:
                result = dispatch(tc["function"]["name"], tc["function"]["arguments"])
            except Exception as exc:
                result = json.dumps({"error": str(exc)})
            history.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })
