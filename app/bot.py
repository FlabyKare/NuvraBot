from __future__ import annotations

import asyncio
import html
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    MenuButtonWebApp,
    Message,
    PreCheckoutQuery,
    WebAppInfo,
)

from .ai_service import AIService
from .categories import DEFAULT_CATEGORY_LABELS, default_category_views
from .classifier import classify, first_url, make_title
from .config import Settings
from .database import Database
from .models import ItemPatch, NewItem, TelegramUser
from .reminders import parse_smart_reminder

logger = logging.getLogger(__name__)

CATEGORY_LABELS = DEFAULT_CATEGORY_LABELS


class ReminderForm(StatesGroup):
    waiting_for_time = State()


def create_bot(settings: Settings) -> Bot:
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def configure_bot(bot: Bot, settings: Settings) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Открыть Second Brain"),
            BotCommand(command="app", description="Мои сохранённые"),
            BotCommand(command="search", description="Найти по смыслу"),
            BotCommand(command="stats", description="Статистика"),
            BotCommand(command="pro", description="Second Brain PRO"),
            BotCommand(command="help", description="Как пользоваться"),
            BotCommand(command="terms", description="Условия использования"),
            BotCommand(command="paysupport", description="Поддержка по оплате"),
        ]
    )
    if settings.mini_app_url:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Мои сохранённые",
                web_app=WebAppInfo(url=settings.mini_app_url),
            )
        )


def create_dispatcher(settings: Settings, database: Database, ai: AIService) -> Dispatcher:
    router = Router(name="second-brain")

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        await remember_user(database, message)
        keyboard = mini_app_keyboard(settings)
        await message.answer(
            "<b>🧠 Telegram Second Brain</b>\n\n"
            "Перешли мне полезный пост, ссылку, файл, видео или просто отправь заметку. "
            "Я сохраню её, разложу по категориям и помогу найти позже.\n\n"
            "Искать можно обычной фразой:\n"
            "<i>/search какой монитор я хотел купить?</i>",
            reply_markup=keyboard,
        )

    @router.message(Command("help"))
    async def help_message(message: Message) -> None:
        await message.answer(
            "<b>Как пользоваться</b>\n\n"
            "1. Перешли сюда любое сообщение или файл.\n"
            "   Если у медиа нет подписи, пришли описание следующим сообщением — я объединю их.\n"
            "2. Выбери категорию, нажми ⭐, ✅ или поставь напоминание.\n"
            "3. Используй <code>/search запрос</code> или открой Mini App.\n\n"
            "AI-функции включаются автоматически, если на сервере задан OPENAI_API_KEY."
        )

    @router.message(Command("app"))
    async def open_app(message: Message) -> None:
        keyboard = mini_app_keyboard(settings)
        if keyboard:
            await message.answer("Твоя личная база открывается здесь:", reply_markup=keyboard)
        else:
            await message.answer(
                "Mini App ещё не опубликован. Укажи публичный HTTPS-адрес в <code>PUBLIC_URL</code>."
            )

    @router.message(Command("terms"))
    async def terms(message: Message) -> None:
        await message.answer(
            "Условия использования и подписки Second Brain:\n"
            f'<a href="{html.escape(settings.terms_url, quote=True)}">{html.escape(settings.terms_url)}</a>'
        )

    @router.message(Command("paysupport"))
    async def payment_support(message: Message) -> None:
        await message.answer(
            "По вопросам оплаты и возвратов напиши: "
            f"@{html.escape(settings.support_username.removeprefix('@'))}\n\n"
            "Поддержка Telegram не обрабатывает покупки внутри этого бота."
        )

    @router.message(Command("pro"))
    async def buy_pro(message: Message) -> None:
        await remember_user(database, message)
        await message.answer_invoice(
            title="Second Brain PRO · 30 дней",
            description=(
                "Безлимитные сохранения, AI-поиск по смыслу, суммаризация и будущие "
                "OCR/расшифровка аудио. Подписка продлевается каждый месяц."
            ),
            payload="second-brain-pro-v1",
            currency="XTR",
            prices=[LabeledPrice(label="PRO на 30 дней", amount=settings.pro_price_stars)],
            subscription_period=2_592_000,
        )

    @router.pre_checkout_query()
    async def approve_checkout(query: PreCheckoutQuery) -> None:
        valid = (
            query.invoice_payload == "second-brain-pro-v1"
            and query.currency == "XTR"
            and query.total_amount == settings.pro_price_stars
        )
        await query.answer(
            ok=valid,
            error_message=(
                None if valid else "Параметры подписки изменились. Запроси новый счёт командой /pro."
            ),
        )

    @router.message(F.successful_payment)
    async def successful_payment(message: Message) -> None:
        payment = message.successful_payment
        if not message.from_user or not payment or payment.invoice_payload != "second-brain-pro-v1":
            return
        expiration_timestamp = getattr(payment, "subscription_expiration_date", None)
        pro_until = (
            datetime.fromtimestamp(expiration_timestamp, UTC)
            if expiration_timestamp
            else datetime.now(UTC) + timedelta(days=settings.pro_subscription_days)
        )
        await database.activate_pro(
            message.from_user.id,
            charge_id=payment.telegram_payment_charge_id,
            currency=payment.currency,
            amount=payment.total_amount,
            invoice_payload=payment.invoice_payload,
            pro_until=pro_until,
            is_recurring=bool(getattr(payment, "is_recurring", False)),
            is_first_recurring=bool(getattr(payment, "is_first_recurring", False)),
        )
        await message.answer(
            "<b>⭐ PRO активирован!</b>\n\n"
            f"Доступ открыт до {pro_until.astimezone().strftime('%d.%m.%Y')}. "
            "Спасибо, что поддерживаешь Second Brain."
        )

    @router.message(Command("stats"))
    async def stats(message: Message) -> None:
        user_id = await remember_user(database, message)
        counters = await database.stats(user_id)
        categories = await database.list_categories(user_id)
        lines = [f"<b>Сохранено: {counters['total']}</b>"]
        for category in categories:
            amount = counters["categories"].get(category["id"], 0)
            if amount:
                lines.append(f"{html.escape(category['label'])}: {amount}")
        lines.append(f"\n⭐ В избранном: {counters['favorites']}")
        lines.append(f"📥 Не прочитано: {counters['unread']}")
        await message.answer("\n".join(lines), reply_markup=mini_app_keyboard(settings))

    @router.message(Command("search"))
    async def search(message: Message, command: CommandObject) -> None:
        user_id = await remember_user(database, message)
        query = (command.args or "").strip()
        if not query:
            await message.answer(
                "Напиши запрос после команды, например:\n<code>/search монитор для работы</code>"
            )
            return
        wait_message = await message.answer("🔎 Ищу по смыслу…")
        results = await ai.search(database, user_id, query, limit=5)
        if not results:
            await wait_message.edit_text("Ничего похожего не нашлось. Попробуй сформулировать иначе.")
            return
        labels = await database.category_labels(user_id)
        lines = [f"<b>Нашёл по запросу:</b> {html.escape(query)}"]
        for index, item in enumerate(results, start=1):
            title = html.escape(item["title"])
            category = html.escape(labels.get(item["category"], "🧠 Без категории"))
            if item.get("url"):
                title = f'<a href="{html.escape(item["url"], quote=True)}">{title}</a>'
            lines.append(f"\n{index}. {category}\n<b>{title}</b>")
        await wait_message.edit_text("\n".join(lines), disable_web_page_preview=True)

    @router.callback_query(F.data.startswith("item:"))
    async def item_action(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.from_user or not callback.data:
            return
        try:
            _, action, raw_id = callback.data.split(":", 2)
            item_id = int(raw_id)
        except (ValueError, TypeError):
            await callback.answer("Некорректное действие", show_alert=True)
            return
        user_id = callback.from_user.id
        item = await database.get_item(user_id, item_id)
        if not item:
            await callback.answer("Сохранение не найдено", show_alert=True)
            return
        categories = await database.list_categories(user_id)

        notice = "Готово"
        if action == "favorite":
            item = await database.patch_item(user_id, item_id, ItemPatch(favorite=not item["favorite"]))
            notice = "Добавлено в избранное" if item and item["favorite"] else "Убрано из избранного"
        elif action == "read":
            item = await database.patch_item(user_id, item_id, ItemPatch(read=not item["read"]))
            notice = "Отмечено прочитанным" if item and item["read"] else "Вернул в непрочитанное"
        elif action in {"tomorrow", "month"}:
            delta = timedelta(days=1 if action == "tomorrow" else 30)
            item = await database.patch_item(
                user_id,
                item_id,
                ItemPatch(reminder_at=datetime.now(UTC) + delta),
            )
            notice = "Напомню завтра" if action == "tomorrow" else "Напомню через месяц"
        elif action == "cancel":
            item = await database.patch_item(user_id, item_id, ItemPatch(clear_reminder=True))
            notice = "Напоминание отменено"
        elif action == "smart":
            await state.set_state(ReminderForm.waiting_for_time)
            await state.update_data(item_id=item_id)
            await callback.answer()
            if callback.message:
                await callback.message.answer(
                    "⏰ <b>Когда напомнить?</b>\n\n"
                    "Напиши обычной фразой, например:\n"
                    "• завтра в 19:00\n"
                    "• через две недели\n"
                    "• в пятницу вечером"
                )
            return
        elif action == "category":
            await callback.answer("Выбери категорию")
            if callback.message:
                await callback.message.edit_reply_markup(
                    reply_markup=category_keyboard(item, categories)
                )
            return
        elif action == "back":
            await callback.answer()
            if callback.message:
                await callback.message.edit_reply_markup(reply_markup=item_keyboard(item, categories))
            return
        elif action == "summary":
            await callback.answer("Готовлю краткое содержание…")
            summary = await ai.summarize(f"{item['title']}\n{item['text']}")
            await database.set_summary(user_id, item_id, summary)
            if callback.message:
                await callback.message.answer(f"<b>Кратко:</b>\n{html.escape(summary)}")
            return
        else:
            await callback.answer("Неизвестное действие", show_alert=True)
            return

        await callback.answer(notice)
        if callback.message and item:
            try:
                await callback.message.edit_reply_markup(reply_markup=item_keyboard(item, categories))
            except Exception:
                logger.debug("Unable to refresh inline keyboard", exc_info=True)

    @router.message(ReminderForm.waiting_for_time)
    async def receive_smart_reminder(message: Message, state: FSMContext) -> None:
        if not message.from_user or not message.text:
            await message.answer("Напиши дату и время текстом или отправь /cancel")
            return
        if message.text.strip().casefold() == "/cancel":
            await state.clear()
            await message.answer("Настройка напоминания отменена")
            return
        data = await state.get_data()
        item_id = int(data.get("item_id", 0))
        try:
            reminder_at = parse_smart_reminder(message.text, timezone_offset_minutes=180)
        except ValueError as exc:
            await message.answer(f"Не получилось: {html.escape(str(exc))}")
            return
        item = await database.patch_item(
            message.from_user.id,
            item_id,
            ItemPatch(reminder_at=reminder_at),
        )
        await state.clear()
        if not item:
            await message.answer("Сохранение больше не найдено")
            return
        local_time = reminder_at.astimezone().strftime("%d.%m.%Y в %H:%M")
        await message.answer(f"⏰ Готово, напомню {local_time}")

    @router.callback_query(F.data.startswith("itemcat:"))
    async def choose_item_category(callback: CallbackQuery) -> None:
        if not callback.from_user or not callback.data:
            return
        try:
            _, category, raw_id = callback.data.split(":", 2)
            item_id = int(raw_id)
        except (ValueError, TypeError):
            await callback.answer("Некорректная категория", show_alert=True)
            return
        if not await database.has_category(callback.from_user.id, category):
            await callback.answer("Неизвестная категория", show_alert=True)
            return
        item = await database.patch_item(
            callback.from_user.id,
            item_id,
            ItemPatch(category=category),
        )
        if not item:
            await callback.answer("Сохранение не найдено", show_alert=True)
            return
        categories = await database.list_categories(callback.from_user.id)
        labels = {row["id"]: row["label"] for row in categories}
        await callback.answer(f"Категория: {labels[category]}")
        if callback.message:
            try:
                await callback.message.edit_reply_markup(reply_markup=item_keyboard(item, categories))
            except Exception:
                logger.debug("Unable to refresh category keyboard", exc_info=True)

    @router.message()
    async def save_message(message: Message) -> None:
        if not message.from_user:
            return
        user_id = await remember_user(database, message)
        new_item = extract_item(message)

        if is_context_text_message(message):
            pending = await database.get_pending_media_context(user_id)
            if pending:
                context_title = make_title(new_item.text, url=new_item.url)
                context_url = pending["url"] or new_item.url
                searchable = "\n".join(
                    part
                    for part in (
                        context_title,
                        new_item.text,
                        context_url or "",
                        pending.get("file_name") or "",
                        pending.get("source_chat") or "",
                        pending.get("recognized_text") or "",
                    )
                    if part
                )
                embedding = await ai.embed(searchable)
                attached = await database.attach_pending_media_context(
                    user_id,
                    pending["id"],
                    title=context_title,
                    text=new_item.text,
                    url=new_item.url,
                    embedding=embedding,
                )
                if attached:
                    categories = await database.list_categories(user_id)
                    media_label = {
                        "video": "видео",
                        "audio": "аудио",
                        "voice": "голосовому сообщению",
                        "photo": "изображению",
                        "file": "файлу",
                    }.get(attached["kind"], "медиа")
                    await message.answer(
                        f"<b>Описание добавлено к {media_label}</b>\n"
                        f"{html.escape(attached['title'])}",
                        reply_markup=item_keyboard(attached, categories),
                        disable_web_page_preview=True,
                    )
                    return

        user = await database.get_user(user_id)
        counters = await database.stats(user_id)
        if not (user and user["is_pro"]) and counters["total"] >= settings.free_items_limit:
            await message.answer(
                f"Бесплатный лимит — {settings.free_items_limit} сохранений. "
                "Подключи PRO через Telegram Stars командой /pro."
            )
            return

        embedding = await ai.embed(new_item.searchable_text)
        saved = await database.create_item(user_id, new_item, embedding=embedding)
        awaiting_context = bool(saved["has_media"] and not new_item.text)
        if awaiting_context:
            await database.set_pending_media_context(
                user_id,
                saved["id"],
                datetime.now(UTC) + timedelta(seconds=settings.media_context_window_seconds),
            )
        else:
            await database.clear_pending_media_context(user_id)
        categories = await database.list_categories(user_id)
        labels = {row["id"]: row["label"] for row in categories}
        category = labels.get(saved["category"], "🧠 Без категории")
        title_line = "" if saved["kind"] == "video" else f"\n{html.escape(saved['title'])}"
        await message.answer(
            f"<b>Сохранено</b> · {html.escape(category)}{title_line}"
            + (
                "\n\nПришли описание следующим сообщением в течение "
                f"{max(1, settings.media_context_window_seconds // 60)} мин. — "
                "я добавлю его к этой карточке."
                if awaiting_context
                else ""
            ),
            reply_markup=item_keyboard(saved, categories),
            disable_web_page_preview=True,
        )
        recognizable_kinds = {"photo", "audio", "voice", "video", "file"}
        if ai.enabled and saved["has_media"] and saved["kind"] in recognizable_kinds:
            await message.answer(
                "🔎 Хочешь извлечь текст или расшифровать содержимое? Открой Mini App и нажми "
                "«Распознать» на карточке."
            )

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


async def remember_user(database: Database, message: Message) -> int:
    if not message.from_user:
        raise ValueError("Message has no user")
    user = message.from_user
    await database.upsert_user(
        TelegramUser(
            id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
        )
    )
    return user.id


def extract_item(message: Message) -> NewItem:
    text = (message.text or message.caption or "").strip()
    url = first_url(text)
    for entity in message.entities or message.caption_entities or []:
        if entity.type == "text_link" and entity.url:
            url = url or entity.url

    file_id: str | None = None
    file_unique_id: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    media_kind: str | None = None
    file_object: Any = None
    if message.document:
        file_object = message.document
        file_name = message.document.file_name
        mime_type = message.document.mime_type
    elif message.video:
        file_object = message.video
        file_name = message.video.file_name
        mime_type = message.video.mime_type
        media_kind = "video"
    elif message.audio:
        file_object = message.audio
        file_name = message.audio.file_name
        mime_type = message.audio.mime_type
        media_kind = "audio"
    elif message.voice:
        file_object = message.voice
        mime_type = message.voice.mime_type
        media_kind = "voice"
    elif message.photo:
        file_object = message.photo[-1]
        media_kind = "photo"
    if file_object:
        file_id = file_object.file_id
        file_unique_id = file_object.file_unique_id

    source_chat, source_author, source_message_id, forwarded_url = forward_source(message)
    url = url or forwarded_url
    kind, category = classify(
        text,
        url=url,
        has_file=bool(file_object),
        media_kind=media_kind,
    )
    return NewItem(
        kind=kind,
        category=category,
        title=(
            "Видео"
            if kind == "video" and not text and not url
            else make_title(text, url=url, file_name=None if kind == "video" else file_name)
        ),
        text=text,
        url=url,
        telegram_file_id=file_id,
        telegram_file_unique_id=file_unique_id,
        file_name=file_name,
        mime_type=mime_type,
        source_chat=source_chat,
        source_author=source_author,
        source_message_id=source_message_id,
        raw_json=message.model_dump_json(exclude_none=True),
    )


def is_context_text_message(message: Message) -> bool:
    text = (message.text or "").strip()
    return bool(
        text
        and not text.startswith("/")
        and not any((message.document, message.video, message.audio, message.voice, message.photo))
    )


def forward_source(message: Message) -> tuple[str | None, str | None, int | None, str | None]:
    origin = message.forward_origin
    if not origin:
        return None, None, None, None
    chat = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)
    sender_user = getattr(origin, "sender_user", None)
    source_chat = getattr(chat, "title", None)
    source_author = getattr(sender_user, "full_name", None) or getattr(origin, "sender_user_name", None)
    message_id = getattr(origin, "message_id", None)
    username = getattr(chat, "username", None)
    url = f"https://t.me/{username}/{message_id}" if username and message_id else None
    return source_chat, source_author, message_id, url


def mini_app_keyboard(settings: Settings) -> InlineKeyboardMarkup | None:
    if not settings.mini_app_url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🧠 Открыть мои сохранённые",
                    web_app=WebAppInfo(url=settings.mini_app_url),
                )
            ]
        ]
    )


def item_keyboard(
    item: dict[str, Any],
    categories: list[dict[str, Any]] | None = None,
) -> InlineKeyboardMarkup:
    item_id = item["id"]
    category_rows = categories or default_category_views()
    labels = {category["id"]: category["label"] for category in category_rows}
    rows = [
            [
                InlineKeyboardButton(
                    text="★ В избранном" if item.get("favorite") else "☆ В избранное",
                    callback_data=f"item:favorite:{item_id}",
                ),
                InlineKeyboardButton(
                    text="↩ Не прочитано" if item.get("read") else "✓ Прочитано",
                    callback_data=f"item:read:{item_id}",
                ),
            ],
            [
                InlineKeyboardButton(text="⏰ Завтра", callback_data=f"item:tomorrow:{item_id}"),
                InlineKeyboardButton(text="🗓 Через месяц", callback_data=f"item:month:{item_id}"),
            ],
            [InlineKeyboardButton(text="🗣 Когда угодно…", callback_data=f"item:smart:{item_id}")],
        ]
    if item.get("reminder_at"):
        rows.append(
            [InlineKeyboardButton(text="🔕 Отменить напоминание", callback_data=f"item:cancel:{item_id}")]
        )
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text=f"📂 Категория · {labels.get(item.get('category'), 'Без категории')}",
                    callback_data=f"item:category:{item_id}",
                )
            ],
            [InlineKeyboardButton(text="✨ Суммаризировать", callback_data=f"item:summary:{item_id}")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def category_keyboard(
    item: dict[str, Any],
    categories: list[dict[str, Any]] | None = None,
) -> InlineKeyboardMarkup:
    item_id = item["id"]
    current = item.get("category")
    category_rows = categories or default_category_views()
    buttons = [
        InlineKeyboardButton(
            text=f"{'✓ ' if category['id'] == current else ''}{category['label']}",
            callback_data=f"itemcat:{category['id']}:{item_id}",
        )
        for category in category_rows
    ]
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="← Назад", callback_data=f"item:back:{item_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def reminder_worker(bot: Bot, database: Database, poll_seconds: int) -> None:
    while True:
        try:
            for item in await database.due_reminders():
                title = html.escape(item["title"])
                text = f"<b>⏰ Ты хотел вернуться к этому:</b>\n\n{title}"
                if item.get("url"):
                    text += f'\n<a href="{html.escape(item["url"], quote=True)}">Открыть ссылку</a>'
                categories = await database.list_categories(item["telegram_id"])
                await bot.send_message(
                    item["telegram_id"],
                    text,
                    reply_markup=item_keyboard(item, categories),
                    disable_web_page_preview=True,
                )
                await database.mark_reminder_sent(item["id"])
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Reminder worker iteration failed")
        await asyncio.sleep(poll_seconds)
