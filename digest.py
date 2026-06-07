from datetime import date, datetime, timedelta

import auth
import tz as _tz
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


def _fmt_event_time(start_raw: str, end_raw: str = "") -> str:
    today = _tz.now().date()
    if "T" in start_raw:
        dt_start = datetime.fromisoformat(start_raw).astimezone(_tz.LIMA)
        time_str = dt_start.strftime("%H:%M")
        if end_raw and "T" in end_raw:
            dt_end = datetime.fromisoformat(end_raw).astimezone(_tz.LIMA)
            time_str += f"–{dt_end.strftime('%H:%M')}"
        if dt_start.date() == today:
            return time_str
        mes = _MESES_CORTOS[dt_start.month - 1]
        dia = _DIAS_CORTOS[dt_start.weekday()]
        return f"{dia} {dt_start.day} {mes}, {time_str}"
    else:
        d = date.fromisoformat(start_raw[:10])
        if d == today:
            return "Todo el día"
        mes = _MESES_CORTOS[d.month - 1]
        dia = _DIAS_CORTOS[d.weekday()]
        return f"{dia} {d.day} {mes}"


def build_digest() -> str:
    """Build the daily digest in MarkdownV2 format."""
    now = _tz.now()
    lines = [bold(fecha_es(now)), ""]

    # ── Calendario ────────────────────────────────────────────────────────────
    if not auth.get_refresh_token():
        lines.append(italic("Calendario no autenticado — usa /login"))
    else:
        try:
            time_min = now.isoformat()
            time_max = (now + timedelta(days=3)).isoformat()
            events = list_events(max_results=7, time_min=time_min, time_max=time_max)
            lines.append(f"📅 {bold('Próximos eventos')}")
            lines.append(SEP)
            if events:
                for e in events:
                    start_raw = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", "")
                    end_raw = e.get("end", {}).get("dateTime") or e.get("end", {}).get("date", "")
                    t_str = _fmt_event_time(start_raw, end_raw) if start_raw else "?"
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
