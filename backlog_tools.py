import os

from db_utils import db_insert, db_list, db_remove, db_update

DB_PATH = os.getenv("BACKLOG_DB_PATH", "data/backlog.json")


def create_backlog_item(title: str, description: str = "") -> int:
    return db_insert(DB_PATH, {"title": title, "description": description})


def list_backlog() -> list[dict]:
    return db_list(DB_PATH)


def delete_backlog_item(doc_id: int) -> None:
    db_remove(DB_PATH, doc_id)
