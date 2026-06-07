from datetime import date, datetime, timedelta, timezone

import auth
from calendar_tools import list_events
from formatting import (
    SEP,
    _DIAS_CORTOS,
    _MESES_CORTOS,
    bold,
    esc,
    fecha_es,
    fmt_due,
    italic,
)
from tasks_tools import list_tasks


def _fmt_event_time(raw: str) -> str:
    today = date.today()
    if "T" in raw:
        dt = datetime.fromisoformat(raw).astimezone()
        if dt.date() == today:
            return dt.strftime("%H:%M")
        mes = _MESES_CORTOS[dt.month - 1]
        dia = _DIAS_CORTOS[dt.weekday()]
        return f"{dia} {dt.day} {mes}, {dt.strftime('%H:%M')}"
    else:
        d = date.fromisoformat(raw[:10])
        if d == today:
            return "Todo el día"
        mes = _MESES_CORTOS[d.month - 1]
        dia = _DIAS_CORTOS[d.weekday()]
        return f"{dia} {d.day} {mes}"


def build_digest() -> str:
    """Build the daily digest in MarkdownV2 format."""
    now = datetime.now()
    lines = [bold(fecha_es(now)), ""]

    # ── Calendario ────────────────────────────────────────────────────────────
    if not auth.get_refresh_token():
        lines.append(italic("Calendario no autenticado — usa /login"))
    else:
        try:
            now_utc = datetime.now(timezone.utc)
            time_min = now_utc.isoformat()
            time_max = (now_utc + timedelta(days=3)).isoformat()
            events = list_events(max_results=7, time_min=time_min, time_max=time_max)
            lines.append(f"📅 {bold('Próximos eventos')}")
            lines.append(SEP)
            if events:
                for e in events:
                    raw = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", "")
                    t_str = _fmt_event_time(raw) if raw else "?"
                    summary = e.get("summary", "(sin título)")
                    lines.append(f"• {esc(t_str)}  {esc(summary)}")
            else:
                lines.append(italic("Sin eventos en los próximos 3 días"))
        except Exception as exc:
            lines.append(f"📅 {bold('Próximos eventos')}")
            lines.append(SEP)
            lines.append(italic(f"Error: {exc}"))

    lines.append("")

    # ── Tareas ────────────────────────────────────────────────────────────────
    tasks = list_tasks(show_done=False)
    lines.append(f"✅ {bold(f'Tareas pendientes ({len(tasks)})')}" if tasks else f"✅ {bold('Tareas pendientes')}")
    lines.append(SEP)
    if tasks:
        for t in tasks:
            due = f"  — vence {esc(fmt_due(t['due']))}" if t.get("due") else ""
            lines.append(f"• {esc(t['title'])}{due}")
            if t.get("notes"):
                lines.append(f"  {italic(t['notes'])}")
    else:
        lines.append(italic("Sin tareas pendientes"))

    return "\n".join(lines)
