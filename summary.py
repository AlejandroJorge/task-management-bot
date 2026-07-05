"""Daily activity summary: last 24h of timeblocks narrated by DeepSeek."""
import logging
import os
from datetime import datetime, timedelta

import tz as _tz
from tracking_tools import list_timeblocks

logger = logging.getLogger(__name__)

NO_TRACKING_TEXT = "Está bien fallar, puedes seguir intentándolo"

_SYSTEM_PROMPT = (
    "Eres el asistente personal de una persona que registra en qué usa su tiempo. "
    "Recibirás sus bloques de tiempo de las últimas 24 horas. "
    "Escribe en español un resumen breve (3-5 frases) de lo que hizo: "
    "qué actividades dominaron el día y cuánto tiempo total registró. "
    "Tono cálido y directo, sin juicios ni sermones. Texto plano, sin markdown."
)


def build_daily_summary() -> str:
    """Summarize the last 24h of tracking. Blocking (network) — run in a thread."""
    now = _tz.now()
    since = now - timedelta(days=1)
    blocks = list_timeblocks(since.isoformat(), now.isoformat())
    if not blocks:
        return NO_TRACKING_TEXT

    lines = []
    for b in blocks:
        s = datetime.fromisoformat(b["start"]).astimezone(_tz.LIMA)
        e = datetime.fromisoformat(b["end"]).astimezone(_tz.LIMA)
        mins = round((e - s).total_seconds() / 60)
        day = "hoy" if s.date() == now.date() else "ayer"
        lines.append(f"- {day} {s.strftime('%H:%M')}–{e.strftime('%H:%M')} ({mins} min): {b['activity']}")

    from openai import OpenAI
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com")
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": "Bloques registrados:\n" + "\n".join(lines)},
        ],
    )
    return resp.choices[0].message.content.strip()
