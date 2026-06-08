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


def categories_for_prompt() -> str:
    cats = load_categories()
    lines = ["Categorías para timeblocks (usa la key exacta al llamar herramientas):"]
    for key, cat in cats.items():
        examples = ", ".join(cat.get("examples", [])[:3])
        ex_str = f" (ej: {examples})" if examples else ""
        lines.append(f"  - {key}: {cat['label']} — {cat['description']}{ex_str}")
    return "\n".join(lines)
