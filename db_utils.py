from tinydb import TinyDB


def db_list(path: str) -> list[dict]:
    with TinyDB(path) as db:
        return [{"doc_id": d.doc_id, **d} for d in db.all()]


def db_insert(path: str, record: dict) -> int:
    with TinyDB(path) as db:
        return db.insert(record)


def db_update(path: str, doc_id: int, fields: dict) -> None:
    with TinyDB(path) as db:
        db.update(fields, doc_ids=[doc_id])


def db_remove(path: str, doc_id: int) -> None:
    with TinyDB(path) as db:
        db.remove(doc_ids=[doc_id])
