from datetime import date, datetime, time, timezone

import auth
from calendar_tools import list_events
from tasks_tools import list_tasks


def build_digest() -> str:
    """
    Build the standard digest: today's calendar events + pending tasks.
    Used by /ls and the scheduled morning/evening jobs.
    """
    today = date.today()
    label = datetime.now().strftime("%A, %B %d")
    lines = [f"📅 *{label}*\n"]

    # ── Calendar ──────────────────────────────────────────────────────────────
    if not auth.get_refresh_token():
        lines.append("🗓 _Calendar not authenticated — use /login_")
    else:
        try:
            start = datetime.combine(today, time.min).astimezone(timezone.utc).isoformat()
            end   = datetime.combine(today, time.max).astimezone(timezone.utc).isoformat()
            events = list_events(max_results=20, time_min=start, time_max=end)
            if events:
                lines.append("🗓 *Today's events:*")
                for e in events:
                    raw = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", "")
                    t = datetime.fromisoformat(raw).strftime("%H:%M") if "T" in raw else "All day"
                    lines.append(f"  • {t} — {e.get('summary', '(no title)')}")
            else:
                lines.append("🗓 No events today")
        except Exception as exc:
            lines.append(f"🗓 _Could not fetch events: {exc}_")

    lines.append("")

    # ── Tasks ─────────────────────────────────────────────────────────────────
    tasks = list_tasks(show_done=False)
    if tasks:
        lines.append(f"📋 *Pending tasks ({len(tasks)}):*")
        for t in tasks:
            due = f"  — due {t['due']}" if t.get("due") else ""
            lines.append(f"  • [{t.doc_id}] {t['title']}{due}")
            if t.get("notes"):
                lines.append(f"      _{t['notes']}_")
    else:
        lines.append("📋 No pending tasks")

    return "\n".join(lines)
