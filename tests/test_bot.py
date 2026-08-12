from datetime import UTC, datetime, timedelta

from app.bot import category_keyboard, item_keyboard


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
