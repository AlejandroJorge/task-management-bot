"""MarkdownV2 helpers for bot-generated messages."""


def esc(text: str) -> str:
    """Escape all MarkdownV2 special characters in plain text."""
    text = str(text)
    text = text.replace("\\", "\\\\")  # backslash first
    for ch in r"_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def bold(text: str) -> str:
    return f"*{esc(text)}*"


def italic(text: str) -> str:
    return f"_{esc(text)}_"


# Spanish date helpers — avoids locale dependency
_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def fecha_es(dt) -> str:
    """Return a fully Spanish date string, e.g. 'Domingo, 07 de junio de 2026'."""
    dia = _DIAS[dt.weekday()].capitalize()
    mes = _MESES[dt.month - 1]
    return f"{dia}, {dt.day:02d} de {mes} de {dt.year}"
