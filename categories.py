import json
import os

_CATEGORIES_PATH = os.getenv("CATEGORIES_PATH", "data/categories.json")
_categories: dict | None = None


def load_categories() -> dict:
    global _categories
    if _categories is None:
        with open(_CATEGORIES_PATH, encoding="utf-8") as f:
            _categories = json.load(f)
    return _categories


def color_id_for(category: str) -> str | None:
    cat = load_categories().get(category)
    return cat["color_id"] if cat else None
