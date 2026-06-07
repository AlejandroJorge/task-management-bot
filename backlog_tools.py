import os

from tinydb import TinyDB

DB_PATH = os.getenv("BACKLOG_DB_PATH", "data/backlog.json")


def _db() -> TinyDB:
    return TinyDB(DB_PATH)


def create_backlog_item(title: str, description: str = "") -> int:
    """Add an idea to the backlog. Returns its doc_id."""
    with _db() as db:
        return db.insert({"title": title, "description": description})


def list_backlog() -> list[dict]:
    """Return all backlog items."""
    with _db() as db:
        return [{"doc_id": d.doc_id, **d} for d in db.all()]


def update_backlog_item(doc_id: int, **fields) -> None:
    """Edit a backlog item's title or description."""
    allowed = {k: fields[k] for k in ("title", "description") if k in fields}
    with _db() as db:
        db.update(allowed, doc_ids=[doc_id])


def delete_backlog_item(doc_id: int) -> None:
    """Permanently delete a backlog item."""
    with _db() as db:
        db.remove(doc_ids=[doc_id])
