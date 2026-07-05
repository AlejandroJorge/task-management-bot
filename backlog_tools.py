import os
from datetime import datetime, timedelta

import tz as _tz
from db_utils import db_insert, db_list, db_remove, db_update

DB_PATH = os.getenv("BACKLOG_DB_PATH", "data/backlog.json")


def create_backlog_item(title: str, description: str = "", next_step: str = "") -> int:
    return db_insert(DB_PATH, {
        "title": title,
        "description": description,
        "next_step": next_step,
        "created_at": _tz.now().isoformat(),
    })


def list_backlog() -> list[dict]:
    return db_list(DB_PATH)


def set_backlog_step(doc_id: int, next_step: str) -> None:
    db_update(DB_PATH, doc_id, {"next_step": next_step})


def backlog_missing_steps(min_age_hours: int = 24) -> list[dict]:
    """Items that have been sitting without a first actionable step.
    Items without created_at (pre-feature) count as old."""
    now = _tz.now()
    stale = []
    for item in list_backlog():
        if item.get("next_step"):
            continue
        created = item.get("created_at")
        try:
            fresh = created and now - datetime.fromisoformat(created) < timedelta(hours=min_age_hours)
        except ValueError:
            fresh = False
        if not fresh:
            stale.append(item)
    return stale


def delete_backlog_item(doc_id: int) -> None:
    db_remove(DB_PATH, doc_id)
