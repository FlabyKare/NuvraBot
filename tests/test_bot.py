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
