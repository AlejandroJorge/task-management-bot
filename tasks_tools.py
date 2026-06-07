import os

from tinydb import Query, TinyDB

DB_PATH = os.getenv("TASKS_DB_PATH", "data/tasks.json")

Task = Query()


def _db() -> TinyDB:
    return TinyDB(DB_PATH)


def create_task(title: str, notes: str = "", due: str | None = None) -> int:
    """Insert a task. Returns the new task's doc_id."""
    with _db() as db:
        return db.insert({"title": title, "notes": notes, "due": due, "done": False})


def list_tasks(show_done: bool = False) -> list[dict]:
    """Return tasks sorted by due date ascending; tasks without due date go last."""
    with _db() as db:
        docs = db.all() if show_done else db.search(Task.done == False)  # noqa: E712
        tasks = [{"doc_id": d.doc_id, **d} for d in docs]
    tasks.sort(key=lambda t: (t.get("due") is None, t.get("due") or ""))
    return tasks


def update_task(doc_id: int, **fields) -> None:
    """
    Update a task by doc_id. Accepted fields:
      title, notes, due   → strings
      done                → bool
    """
    allowed = {k: fields[k] for k in ("title", "notes", "due", "done") if k in fields}
    with _db() as db:
        db.update(allowed, doc_ids=[doc_id])


def delete_task(doc_id: int) -> None:
    """Delete a task by doc_id."""
    with _db() as db:
        db.remove(doc_ids=[doc_id])
