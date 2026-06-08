import os

from db_utils import db_insert, db_list, db_remove, db_update

DB_PATH = os.getenv("TASKS_DB_PATH", "data/tasks.json")


def create_task(title: str, notes: str = "", due: str | None = None) -> int:
    return db_insert(DB_PATH, {"title": title, "notes": notes, "due": due, "done": False})


def list_tasks(show_done: bool = False) -> list[dict]:
    tasks = db_list(DB_PATH)
    if not show_done:
        tasks = [t for t in tasks if not t.get("done")]
    tasks.sort(key=lambda t: (t.get("due") is None, t.get("due") or ""))
    return tasks


def update_task(doc_id: int, **fields) -> None:
    allowed = {k: fields[k] for k in ("title", "notes", "due", "done") if k in fields}
    db_update(DB_PATH, doc_id, allowed)


def delete_task(doc_id: int) -> None:
    db_remove(DB_PATH, doc_id)
