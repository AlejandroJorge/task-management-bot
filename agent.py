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
from datetime import datetime
from typing import Any

import llm
from backlog_tools import list_backlog
from tasks_tools import list_tasks
from tools_registry import REQUIRE_CONFIRMATION, TOOLS, dispatch


def _system_prompt() -> str:
    now = datetime.now().strftime("%A, %d de %B de %Y, %H:%M")
    base = (
        f"Eres un asistente personal. Hoy es {now}. "
        "Tienes acceso al Google Calendar del usuario, su lista de tareas y su backlog. "
        "Las tareas son acciones inmediatas; el backlog son ideas o proyectos a largo plazo. "
        "Interpreta las solicitudes en lenguaje natural y llama las herramientas correspondientes. "
        "REGLAS para el campo 'due' al crear o editar tareas: "
        "(1) Si el usuario NO menciona fecha ni plazo, NO incluyas 'due'. "
        "(2) Si menciona una fecha sin hora (ej. 'mañana', 'el lunes'), usa SOLO formato YYYY-MM-DD. "
        "(3) Solo usa formato con hora (YYYY-MM-DDTHH:MM:SSZ) si el usuario dice hora explícita (ej. 'a las 3pm'). "
        "(4) NUNCA uses T00:00:00Z ni ninguna hora inventada. "
        "Responde siempre en español. "
        "Usa Markdown de Telegram (v1): *negrita* con un solo asterisco, _cursiva_ con guion bajo. "
        "NUNCA uses ** para negrita ni __ para subrayado — Telegram no los soporta. "
        "Sin emojis, sin encabezados grandes. Respuestas cortas y directas. "
        "NUNCA menciones doc_id, event_id ni ningún identificador interno al usuario. "
        "Refierete a tareas y eventos solo por su nombre."
    )
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
            return response["content"]

        for i, tc in enumerate(tool_calls):
            name = tc["function"]["name"]
            args_json = tc["function"]["arguments"]

            if name in REQUIRE_CONFIRMATION:
                # Add placeholders for ALL remaining calls (this one onward)
                # so history is valid while we wait for user confirmation.
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

            try:
                result = dispatch(name, args_json)
            except Exception as exc:
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
