import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.bot import (
    UserMessageSequencer,
    category_keyboard,
    is_context_text_message,
    item_keyboard,
)


def test_item_keyboard_offers_category_and_active_reminder_cancel() -> None:
    keyboard = item_keyboard(
        {
            "id": 42,
            "category": "watch",
            "favorite": False,
            "read": False,
            "reminder_at": datetime.now(UTC) + timedelta(days=1),
        }
    )
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.callback_data == "item:cancel:42" for button in buttons)
    assert any(button.callback_data == "item:category:42" for button in buttons)


def test_category_keyboard_contains_every_category_and_back() -> None:
    keyboard = category_keyboard({"id": 7, "category": "read"})
    callback_data = {
        button.callback_data for row in keyboard.inline_keyboard for button in row
    }

    assert "itemcat:inbox:7" in callback_data
    assert "itemcat:read:7" in callback_data
    assert "item:back:7" in callback_data


def test_category_keyboard_supports_custom_category_names() -> None:
    categories = [
        {
            "id": "inbox",
            "name": "Входящие",
            "icon": "🧠",
            "label": "🧠 Входящие",
        },
        {
            "id": "c_123",
            "name": "Путешествия",
            "icon": "✈️",
            "label": "✈️ Путешествия",
        },
    ]
    keyboard = category_keyboard({"id": 9, "category": "c_123"}, categories)
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.callback_data == "itemcat:c_123:9" for button in buttons)
    assert any(button.text == "✓ ✈️ Путешествия" for button in buttons)


def test_plain_text_can_be_media_context_but_commands_and_media_cannot() -> None:
    def message(text: str | None, **media):
        return SimpleNamespace(
            text=text,
            document=media.get("document"),
            video=media.get("video"),
            audio=media.get("audio"),
            voice=media.get("voice"),
            photo=media.get("photo"),
        )

    assert is_context_text_message(message("Описание видео")) is True
    assert is_context_text_message(message("/search видео")) is False
    assert is_context_text_message(message("Подпись", photo=[object()])) is False


@pytest.mark.asyncio
async def test_user_messages_are_processed_in_delivery_order() -> None:
    sequencer = UserMessageSequencer()
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    order: list[str] = []

    async def first_message() -> None:
        async with sequencer.hold(101):
            order.append("video:start")
            first_started.set()
            await release_first.wait()
            order.append("video:end")

    async def second_message() -> None:
        await first_started.wait()
        async with sequencer.hold(101):
            order.append("description:start")
            order.append("description:end")

    video_task = asyncio.create_task(first_message())
    description_task = asyncio.create_task(second_message())
    await first_started.wait()
    await asyncio.sleep(0)

    assert order == ["video:start"]

    release_first.set()
    await asyncio.gather(video_task, description_task)

    assert order == ["video:start", "video:end", "description:start", "description:end"]


@pytest.mark.asyncio
async def test_messages_from_different_users_do_not_block_each_other() -> None:
    sequencer = UserMessageSequencer()
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    second_finished = asyncio.Event()

    async def first_user() -> None:
        async with sequencer.hold(101):
            first_started.set()
            await release_first.wait()

    async def second_user() -> None:
        await first_started.wait()
        async with sequencer.hold(202):
            second_finished.set()

    first_task = asyncio.create_task(first_user())
    second_task = asyncio.create_task(second_user())
    await first_started.wait()
    await asyncio.wait_for(second_finished.wait(), timeout=1)

    release_first.set()
    await asyncio.gather(first_task, second_task)
