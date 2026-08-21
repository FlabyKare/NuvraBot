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

    recognized = await database.set_recognition(
        101,
        video["id"],
        "В видео рассказывают про настройку сервера WireGuard",
        "transcript",
    )
    assert recognized and recognized["recognized_text"].startswith("В видео")
    recognized_search = await database.search_fts(101, "сервер WireGuard")
    assert video["id"] in {item["id"] for item in recognized_search}

    affected = await database.bulk_patch_items(
        101,
        [video["id"], legacy_video["id"]],
        favorite=True,
        read=True,
    )
    assert affected == 2
    assert all(item["favorite"] and item["read"] for item in await database.list_items(101))

    assert await database.delete_item(101, saved["id"]) is True
    assert (await database.stats(101))["total"] == 2


@pytest.mark.asyncio
async def test_delete_user_data_is_scoped_and_cascades(database: Database) -> None:
    await database.create_item(501, NewItem(title="Удалить меня"))
    await database.create_category(501, "Личное")
    await database.create_item(502, NewItem(title="Оставить меня"))

    assert await database.delete_user_data(501) is True
    assert await database.get_user(501) is None
    assert (await database.stats(502))["total"] == 1


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


@pytest.mark.asyncio
async def test_next_text_is_attached_to_pending_media(database: Database) -> None:
    video = await database.create_item(
        606,
        NewItem(
            kind="video",
            category="watch",
            title="Видео",
            telegram_file_id="context-video-id",
            file_name="clip.mp4",
            mime_type="video/mp4",
        ),
    )
    assert await database.set_pending_media_context(
        606,
        video["id"],
        datetime.now(UTC) + timedelta(minutes=10),
    )
    pending = await database.get_pending_media_context(606)
    assert pending and pending["id"] == video["id"]

    attached = await database.attach_pending_media_context(
        606,
        video["id"],
        title="Тактика выхода на точку B",
        text="Тактика выхода на точку B на карте Mirage",
        url="https://example.com/tactics",
        embedding=[0.1, 0.2],
    )

    assert attached and attached["title"] == "Тактика выхода на точку B"
    assert attached["text"] == "Тактика выхода на точку B на карте Mirage"
    assert attached["url"] == "https://example.com/tactics"
    assert await database.get_pending_media_context(606) is None
    assert await database.attach_pending_media_context(
        606,
        video["id"],
        title="Второй текст",
        text="Не должен перезаписать видео",
    ) is None
    found = await database.search_fts(606, "тактика Mirage")
    assert [item["id"] for item in found] == [video["id"]]


@pytest.mark.asyncio
async def test_expired_media_context_is_not_attached(database: Database) -> None:
    video = await database.create_item(
        607,
        NewItem(
            kind="video",
            category="watch",
            title="Видео",
            telegram_file_id="expired-video-id",
        ),
    )
    await database.set_pending_media_context(
        607,
        video["id"],
        datetime.now(UTC) - timedelta(seconds=1),
    )

    assert await database.get_pending_media_context(607) is None
    assert await database.attach_pending_media_context(
        607,
        video["id"],
        title="Позднее описание",
        text="Этот текст должен стать отдельной карточкой",
    ) is None
    unchanged = await database.get_item(607, video["id"])
    assert unchanged and unchanged["text"] == ""
