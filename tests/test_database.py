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

    legacy_video = await database.create_item(
        101,
        NewItem(
            kind="video",
            category="watch",
            title="IMG_1328.MP4",
            telegram_file_id="legacy-video-id",
            file_name="IMG_1328.MP4",
        ),
    )
    assert legacy_video["title"] == "Видео"

    renamed_video = await database.patch_item(
        101,
        legacy_video["id"],
        ItemPatch(title="Тактика на Inferno"),
    )
    assert renamed_video and renamed_video["title"] == "Тактика на Inferno"

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
    assert (await database.stats(101))["total"] == 2


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


@pytest.mark.asyncio
async def test_custom_categories_are_created_renamed_and_counted(database: Database) -> None:
    await database.upsert_user(303)
    categories = await database.list_categories(303)
    assert {category["id"] for category in categories} >= {"inbox", "watch", "files"}

    custom = await database.create_category(303, "Путешествия", "✈️")
    assert custom["name"] == "Путешествия"
    assert custom["is_system"] is False
    assert await database.has_category(303, custom["id"]) is True

    renamed = await database.rename_category(303, custom["id"], "Поездки")
    assert renamed and renamed["name"] == "Поездки"

    saved = await database.create_item(
        303,
        NewItem(title="Маршрут", category="inbox"),
    )
    moved = await database.patch_item(
        303,
        saved["id"],
        ItemPatch(category=custom["id"]),
    )
    assert moved and moved["category"] == custom["id"]
    assert (await database.stats(303))["categories"][custom["id"]] == 1


@pytest.mark.asyncio
async def test_legacy_video_title_is_migrated_from_caption_once(tmp_path) -> None:
    path = tmp_path / "video-migration.sqlite3"
    database = Database(path)
    await database.init()
    video = await database.create_item(
        404,
        NewItem(
            kind="video",
            category="watch",
            title="Видео",
            text="Inferno, моменталка на банан\nРазбор раскидки",
            telegram_file_id="video-id",
            file_name="IMG_1328.MP4",
        ),
    )
    await database.conn.execute(
        "DELETE FROM schema_migrations WHERE migration_key = ?",
        ("video_topics_from_captions_v1",),
    )
    await database.conn.commit()
    await database.close()

    migrated_database = Database(path)
    await migrated_database.init()
    migrated = await migrated_database.get_item(404, video["id"])
    assert migrated and migrated["title"] == "Inferno, моменталка на банан"

    await migrated_database.patch_item(404, video["id"], ItemPatch(title="Моё название"))
    await migrated_database.close()
    reopened_database = Database(path)
    await reopened_database.init()
    reopened = await reopened_database.get_item(404, video["id"])
    assert reopened and reopened["title"] == "Моё название"
    await reopened_database.close()
