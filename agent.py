"""
Agentic loop: natural language message → LLM → tool calls → final reply.

Flow:
  1. User message appended to history.
  2. LLM called with full history + tool schemas.
  3. If LLM returns tool_calls:
       a. Tools marked REQUIRE_CONFIRMATION are held — execution paused,
          caller receives a ConfirmationRequest.
       b. Safe tools are executed immediately; results fed back to LLM.
       c. Loop repeats from step 2.
  4. When LLM returns plain text, that is the final reply.

Conversation history is managed externally (per chat_id) so sessions persist
across Telegram messages.
"""

import dataclasses
import json
from datetime import datetime
from typing import Any

import llm
from tools_registry import REQUIRE_CONFIRMATION, TOOLS, dispatch


def _system_prompt() -> str:
    now = datetime.now().strftime("%A, %B %d %Y, %H:%M")
    return (
        f"You are a personal assistant. Today is {now}. "
        "You have access to the user's Google Calendar and a personal task list. "
        "Interpret natural language requests and call the appropriate tools. "
        "Be concise in your final responses."
    )


@dataclasses.dataclass
class ConfirmationRequest:
    """Returned when a destructive tool call is pending user confirmation."""
    tool_name: str
    tool_args: dict[str, Any]
    call_id: str
    # Full messages snapshot to resume from after confirmation
    pending_messages: list[dict]


async def process(
    user_message: str,
    history: list[dict],
) -> str | ConfirmationRequest:
    """
    Process one user message against the current history.
    Mutates history in place (appends messages).
    Returns either a final text reply or a ConfirmationRequest.
    """
    if not history or history[0].get("role") != "system":
        history.insert(0, {"role": "system", "content": _system_prompt()})
    else:
        # Refresh timestamp on every call so the model always knows the current time
        history[0]["content"] = _system_prompt()

    history.append({"role": "user", "content": user_message})

    while True:
        response = await llm.chat(history, tools=TOOLS)
        history.append(response)

        tool_calls = response.get("tool_calls")
        if not tool_calls:
            # Plain text reply — done
            return response["content"]

        for tc in tool_calls:
            name = tc["function"]["name"]
            args_json = tc["function"]["arguments"]

            if name in REQUIRE_CONFIRMATION:
                return ConfirmationRequest(
                    tool_name=name,
                    tool_args=json.loads(args_json),
                    call_id=tc["id"],
                    pending_messages=list(history),
                )

            # Execute safe tool and append result
            result = dispatch(name, args_json)
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
    """
    Called after the user answers yes/no to a ConfirmationRequest.
    Executes (or skips) the held tool call and continues the loop.
    """
    if confirmed:
        result = dispatch(request.tool_name, json.dumps(request.tool_args))
    else:
        result = json.dumps({"cancelled": True})

    # Restore to the snapshot and append the tool result
    history.clear()
    history.extend(request.pending_messages)
    history.append({
        "role": "tool",
        "tool_call_id": request.call_id,
        "content": result,
    })

    # Continue the loop
    while True:
        response = await llm.chat(history, tools=TOOLS)
        history.append(response)
        if not response.get("tool_calls"):
            return response["content"]
        for tc in response["tool_calls"]:
            result = dispatch(tc["function"]["name"], tc["function"]["arguments"])
            history.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })
