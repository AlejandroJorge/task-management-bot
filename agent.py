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
import tz as _tz
import user_profile
from typing import Any

import llm

logger = logging.getLogger(__name__)
from backlog_tools import list_backlog
from tasks_tools import list_tasks
from tools_registry import REQUIRE_CONFIRMATION, TOOLS, dispatch


def _system_prompt() -> str:
    now = _tz.now().strftime("%A, %d de %B de %Y, %H:%M")
    base = (
        f"Eres un asistente personal. Hoy es {now}. "
        "Tienes acceso al Google Calendar del usuario (calendario 'Eventos'), su lista de tareas, su backlog "
        "y un calendario de registro de tiempo ('Tracking'). "
        "Las tareas son acciones inmediatas; el backlog son ideas o proyectos a largo plazo. "
        "El registro de tiempo permite anotar bloques de tiempo pasados sobre actividades (solo tiempos ya transcurridos, sin solapamientos). "
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
        "Puedes usar emojis ligeros como titular de sección (ej. ✅ para tareas, 📅 para eventos). "
        "Respuestas cortas y directas. "
        "NUNCA menciones doc_id, event_id ni ningún identificador interno al usuario. "
        "Refierete a tareas y eventos solo por su nombre."
    )
    profile_ctx = user_profile.as_context()
    if profile_ctx:
        base += "\n\n" + profile_ctx
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
