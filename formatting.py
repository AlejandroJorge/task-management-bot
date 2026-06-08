"""MarkdownV2 helpers for bot-generated messages."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

_LIMA = ZoneInfo("America/Lima")

SEP = "──────────────"  # Unicode line, safe in MarkdownV2 (no escaping needed)


def esc(text: str) -> str:
    """Escape all MarkdownV2 special characters in plain text."""
    text = str(text)
    text = text.replace("\\", "\\\\")  # backslash first
    for ch in r"_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def esc_md1(text: str) -> str:
    """Escape Markdown v1 special characters (* _ ` [)."""
    for ch in r"*_`[":
        text = str(text).replace(ch, f"\\{ch}")
    return text


def bold(text: str) -> str:
    return f"*{esc(text)}*"


def italic(text: str) -> str:
    return f"_{esc(text)}_"


# Spanish date helpers — avoids locale dependency
_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_DIAS_CORTOS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
_MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def fecha_es(dt) -> str:
    """Return a fully Spanish date string, e.g. 'Domingo, 07 de junio de 2026'."""
    dia = _DIAS[dt.weekday()].capitalize()
    mes = _MESES[dt.month - 1]
    return f"{dia}, {dt.day:02d} de {mes} de {dt.year}"


def fmt_due(due_str: str) -> str:
    """Format an ISO due date as a short readable string, e.g. '7 de junio' or '7 de junio, 23:59'."""
    try:
        has_time = "T" in due_str or (" " in due_str.strip() and ":" in due_str)
        if has_time:
            dt_utc = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
            # Midnight UTC means the LLM used a date-only intent — show date only
            if dt_utc.hour == 0 and dt_utc.minute == 0 and dt_utc.second == 0:
                mes = _MESES[dt_utc.month - 1]
                return f"{dt_utc.day} de {mes}"
            dt = dt_utc.astimezone(_LIMA)
            mes = _MESES[dt.month - 1]
            return f"{dt.day} de {mes}, {dt.hour:02d}:{dt.minute:02d}"
        else:
            d = date.fromisoformat(due_str[:10])
            mes = _MESES[d.month - 1]
            return f"{d.day} de {mes}"
    except Exception:
        return due_str
