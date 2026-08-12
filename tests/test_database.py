from datetime import UTC, datetime, timedelta

import pytest

from app.database import Database
from app.models import ItemPatch, NewItem, TelegramUser


@pytest.fixture
async def database(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    await db.init()
    yield db
    await db.close()


@pytest.mark.asyncio
async def test_item_lifecycle_and_stats(database: Database) -> None:
    await database.upsert_user(TelegramUser(id=101, first_name="Test"))
    saved = await database.create_item(
        101,
        NewItem(
            kind="link",
            category="development",
            title="Настройка WireGuard",
            text="Подробный гайд для домашнего сервера",
            url="https://example.com/wireguard",
        ),
    )

    assert saved["category"] == "development"
    assert (await database.stats(101))["total"] == 1

    found = await database.search_fts(101, "Найди тот пост про настройку WireGuard")
    assert [item["id"] for item in found] == [saved["id"]]

    video = await database.create_item(
        101,
        NewItem(
            kind="video",
            category="watch",
            title="Видео из Telegram",
            telegram_file_id="telegram-file-id",
            telegram_file_unique_id="unique-file-id",
            file_name="guide.mp4",
            mime_type="video/mp4",
        ),
    )
    assert video["has_media"] is True
    media = await database.get_media_item(101, video["id"])
    assert media and media["telegram_file_id"] == "telegram-file-id"

    updated = await database.patch_item(101, saved["id"], ItemPatch(favorite=True, read=True))
    assert updated and updated["favorite"] is True
    assert updated["read"] is True

    reminder = datetime.now(UTC) + timedelta(days=1)
    updated = await database.patch_item(
        101,
        saved["id"],
        ItemPatch(category="read", reminder_at=reminder),
    )
    assert updated and updated["category"] == "read"
    assert updated["reminder_at"] is not None

    updated = await database.patch_item(101, saved["id"], ItemPatch(clear_reminder=True))
    assert updated and updated["reminder_at"] is None

    assert await database.delete_item(101, saved["id"]) is True
    assert (await database.stats(101))["total"] == 1


@pytest.mark.asyncio
async def test_payment_is_idempotent(database: Database) -> None:
    expiration = datetime.now(UTC) + timedelta(days=30)
    payment = {
        "charge_id": "charge-1",
        "currency": "XTR",
        "amount": 299,
        "invoice_payload": "second-brain-pro-v1",
        "pro_until": expiration,
    }
    assert await database.activate_pro(202, **payment) is True
    assert await database.activate_pro(202, **payment) is False
    user = await database.get_user(202)
    assert user and user["is_pro"] is True
