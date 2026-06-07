from datetime import date, datetime, time, timezone

import auth
from calendar_tools import list_events
from tasks_tools import list_tasks


def build_digest() -> str:
    today = date.today()
    label = datetime.now().strftime("%A, %d de %B de %Y")
    lines = [f"*{label}*\n"]

    # ── Calendario ────────────────────────────────────────────────────────────
    if not auth.get_refresh_token():
        lines.append("_Calendario no autenticado — usa /login_")
    else:
        try:
            start = datetime.combine(today, time.min).astimezone(timezone.utc).isoformat()
            end   = datetime.combine(today, time.max).astimezone(timezone.utc).isoformat()
            events = list_events(max_results=20, time_min=start, time_max=end)
            if events:
                lines.append("*Eventos de hoy:*")
                for e in events:
                    raw = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", "")
                    t = datetime.fromisoformat(raw).strftime("%H:%M") if "T" in raw else "Todo el dia"
                    lines.append(f"- {t}  {e.get('summary', '(sin titulo)')}")
            else:
                lines.append("Sin eventos hoy.")
        except Exception as exc:
            lines.append(f"_Error al obtener eventos: {exc}_")

    lines.append("")

    # ── Tareas ────────────────────────────────────────────────────────────────
    tasks = list_tasks(show_done=False)
    if tasks:
        lines.append(f"*Tareas pendientes ({len(tasks)}):*")
        for t in tasks:
            due = f"  — vence {t['due']}" if t.get("due") else ""
            lines.append(f"- [{t.doc_id}] {t['title']}{due}")
            if t.get("notes"):
                lines.append(f"  _{t['notes']}_")
    else:
        lines.append("Sin tareas pendientes.")

    return "\n".join(lines)
