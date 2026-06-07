from datetime import date, datetime, time, timezone

import auth
from calendar_tools import list_events
from formatting import bold, esc, fecha_es, italic
from tasks_tools import list_tasks


def build_digest() -> str:
    """Build the daily digest in MarkdownV2 format."""
    today = date.today()
    now = datetime.now()
    lines = [bold(fecha_es(now)), ""]

    # ── Calendario ────────────────────────────────────────────────────────────
    if not auth.get_refresh_token():
        lines.append(italic("Calendario no autenticado — usa /login"))
    else:
        try:
            start = datetime.combine(today, time.min).astimezone(timezone.utc).isoformat()
            end   = datetime.combine(today, time.max).astimezone(timezone.utc).isoformat()
            events = list_events(max_results=20, time_min=start, time_max=end)
            if events:
                lines.append(bold("Eventos de hoy:"))
                for e in events:
                    raw = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", "")
                    t = datetime.fromisoformat(raw).strftime("%H:%M") if "T" in raw else "Todo el día"
                    summary = e.get("summary", "(sin título)")
                    lines.append(f"• {esc(t)}  {esc(summary)}")
            else:
                lines.append(esc("Sin eventos hoy."))
        except Exception as exc:
            lines.append(italic(f"Error al obtener eventos: {exc}"))

    lines.append("")

    # ── Tareas ────────────────────────────────────────────────────────────────
    tasks = list_tasks(show_done=False)
    if tasks:
        lines.append(bold(f"Tareas pendientes ({len(tasks)}):"))
        for t in tasks:
            due = f"  — vence {esc(t['due'])}" if t.get("due") else ""
            lines.append(f"• {esc(t['title'])}{due}")
            if t.get("notes"):
                lines.append(f"  {italic(t['notes'])}")
    else:
        lines.append(esc("Sin tareas pendientes."))

    return "\n".join(lines)
