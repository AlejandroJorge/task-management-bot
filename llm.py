import json
import logging
import os

from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None
logger = logging.getLogger(__name__)


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url="https://api.deepseek.com",
        )
    return _client


def _summarise_messages(messages: list[dict]) -> list[dict]:
    """Return a log-friendly version of messages (truncate long content)."""
    out = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content") or ""
        if role == "system":
            out.append({"role": role, "chars": len(content), "preview": content[:300]})
        elif role == "tool":
            out.append({"role": role, "tool_call_id": m.get("tool_call_id"), "content": content[:200]})
        elif role == "assistant" and m.get("tool_calls"):
            out.append({"role": role, "tool_calls": m["tool_calls"]})
        else:
            out.append({"role": role, "content": content[:500]})
    return out


async def chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str = "deepseek-chat",
) -> dict:
    kwargs: dict = {"model": model, "messages": messages}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    logger.info(
        "LLM REQUEST — model=%s  messages=%d  tools=%d\n%s",
        model,
        len(messages),
        len(tools) if tools else 0,
        json.dumps(_summarise_messages(messages), ensure_ascii=False, indent=2),
    )

    response = await _get_client().chat.completions.create(**kwargs)
    msg = response.choices[0].message
    usage = response.usage

    result: dict = {"role": msg.role, "content": msg.content or ""}
    if msg.tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]

    logger.info(
        "LLM RESPONSE — finish=%s  tokens: prompt=%s  completion=%s  total=%s\n%s",
        response.choices[0].finish_reason,
        usage.prompt_tokens if usage else "?",
        usage.completion_tokens if usage else "?",
        usage.total_tokens if usage else "?",
        json.dumps(
            result.get("tool_calls") or {"content": (result["content"] or "")[:500]},
            ensure_ascii=False,
            indent=2,
        ),
    )

    return result
