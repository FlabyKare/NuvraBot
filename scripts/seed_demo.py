from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.database import Database  # noqa: E402
from app.models import NewItem, TelegramUser  # noqa: E402

DEMO_ITEMS = [
    NewItem(
        kind="link",
        category="development",
        title="Настройка WireGuard на домашнем сервере",
        text="Пошаговая инструкция: ключи, маршрутизация, firewall и автозапуск контейнера.",
        url="https://example.com/wireguard-guide",
        source_chat="Dev Notes",
    ),
    NewItem(
        kind="link",
        category="buy",
        title="LG UltraFine 27 — монитор для рабочего стола",
        text="Надо сравнить с Dell: 4K, USB-C 90W, хорошая заводская калибровка.",
        url="https://example.com/monitor",
    ),
    NewItem(
        kind="link",
        category="watch",
        title="Документальный фильм про дизайн городов",
        text="Посмотреть на выходных. Автор разбирает транспорт и человеческий масштаб.",
        url="https://youtube.com/watch?v=example",
        source_chat="Неочевидные фильмы",
    ),
    NewItem(
        kind="text",
        category="read",
        title="Как вести заметки, которые не превращаются в кладбище ссылок",
        text=(
            "Хороший совет: каждая заметка должна отвечать на вопрос — "
            "в каком будущем проекте она пригодится?"
        ),
        source_author="Анна",
    ),
    NewItem(
        kind="file",
        category="files",
        title="product-research.pdf",
        text="Исследование рынка персональных knowledge base приложений.",
        file_name="product-research.pdf",
        mime_type="application/pdf",
    ),
    NewItem(
        kind="link",
        category="links",
        title="Коллекция минималистичных интерфейсов",
        text="Референсы для мобильных приложений и каталогов.",
        url="https://example.com/interfaces",
    ),
]


async def main() -> None:
    settings = Settings(run_bot=False)
    database = Database(settings.database_path)
    await database.init()
    await database.upsert_user(TelegramUser(id=1, first_name="Demo"))
    if (await database.stats(1))["total"] == 0:
        for item in DEMO_ITEMS:
            await database.create_item(1, item)
        print(f"Added {len(DEMO_ITEMS)} demo items to {settings.database_path}")
    else:
        print("Demo user already has items; nothing changed")
    await database.close()


if __name__ == "__main__":
    asyncio.run(main())
