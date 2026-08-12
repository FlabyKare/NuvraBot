from typing import Any

DEFAULT_CATEGORIES = (
    {"id": "inbox", "name": "Без категории", "icon": "🧠", "position": 0},
    {"id": "links", "name": "Ссылки", "icon": "🔗", "position": 1},
    {"id": "watch", "name": "Посмотреть", "icon": "🎬", "position": 2},
    {"id": "development", "name": "Разработка", "icon": "💻", "position": 3},
    {"id": "buy", "name": "Купить", "icon": "🛒", "position": 4},
    {"id": "read", "name": "Почитать", "icon": "📚", "position": 5},
    {"id": "files", "name": "Файлы", "icon": "📁", "position": 6},
)

DEFAULT_CATEGORY_KEYS = tuple(category["id"] for category in DEFAULT_CATEGORIES)
DEFAULT_CATEGORY_LABELS = {
    category["id"]: f"{category['icon']} {category['name']}" for category in DEFAULT_CATEGORIES
}


def default_category_views() -> list[dict[str, Any]]:
    return [
        {
            **category,
            "label": f"{category['icon']} {category['name']}",
            "is_system": True,
            "count": 0,
        }
        for category in DEFAULT_CATEGORIES
    ]
