import json
import logging
import os

logger = logging.getLogger(__name__)

_PATH = os.getenv("USER_PROFILE_PATH", "user_profile.json")


def load() -> dict:
    try:
        with open(_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        logger.exception("Failed to load user_profile.json")
        return {}


def as_context() -> str:
    """Return a formatted string to inject into the system prompt, or '' if no profile."""
    profile = load()
    if not profile:
        return ""

    lines = ["Información sobre el usuario:"]

    if profile.get("name"):
        lines.append(f"  - Nombre: {profile['name']}")
    if profile.get("location"):
        lines.append(f"  - Ubicación: {profile['location']}")
    if profile.get("timezone_label"):
        lines.append(f"  - Zona horaria: {profile['timezone_label']}")
    if profile.get("education"):
        lines.append(f"  - Educación: {profile['education']}")
    if profile.get("work"):
        lines.append(f"  - Trabajo: {profile['work']}")

    schedule = profile.get("schedule", {})
    if schedule:
        parts = []
        if schedule.get("work_days"):
            parts.append(f"trabajo {schedule['work_days']}")
        if schedule.get("work_hours"):
            parts.append(schedule["work_hours"])
        if schedule.get("class_days"):
            parts.append(f"clases {schedule['class_days']}")
        if parts:
            lines.append(f"  - Horario: {', '.join(parts)}")

    for fact in profile.get("facts", []):
        if fact:
            lines.append(f"  - {fact}")

    return "\n".join(lines)
