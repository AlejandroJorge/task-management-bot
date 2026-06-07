import os

from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url="https://api.deepseek.com",
        )
    return _client


async def chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str = "deepseek-chat",
) -> dict:
    """
    Send messages to DeepSeek and return the raw response message as a dict.
    If tools are provided, the model may return tool_calls instead of content.
    """
    kwargs: dict = {"model": model, "messages": messages}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    response = await _get_client().chat.completions.create(**kwargs)
    msg = response.choices[0].message

    # Normalise to a plain dict so callers don't depend on the SDK model
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
    return result
