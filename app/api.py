import asyncio
import contextlib
import hashlib
import hmac
import io
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

import aiohttp
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .ai_service import AIService
from .bot import configure_bot, create_bot, create_dispatcher, reminder_worker
from .config import BASE_DIR, Settings, get_settings
from .database import Database
from .models import (
    BulkItemsRequest,
    CategoryCreate,
    CategoryPatch,
    DeleteAccountRequest,
    ItemPatch,
    SmartReminderRequest,
    TelegramUser,
)
from .reminders import parse_smart_reminder
from .telegram_auth import TelegramAuthError, validate_init_data

logger = logging.getLogger(__name__)
WEB_DIR = BASE_DIR / "web"
MEDIA_URL_TTL_SECONDS = 15 * 60


def media_signature(secret: str, telegram_id: int, item_id: int, expires: int) -> str:
    payload = f"{telegram_id}:{item_id}:{expires}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    ai_service: AIService | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    db = database or Database(app_settings.database_path)
    ai = ai_service or AIService(app_settings)

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
        if app_settings.app_env.lower() == "production" and not app_settings.storage_persistent:
            logger.critical(
                "Persistent storage is not configured. Attach a Railway Volume at /app/data; "
                "otherwise SQLite data will be lost on redeploy."
            )
        await db.init()
        tasks: list[asyncio.Task[object]] = []
        bot = None
        app_instance.state.bot = None
        try:
            if app_settings.run_bot and app_settings.telegram_bot_token:
                bot = create_bot(app_settings)
                app_instance.state.bot = bot
                dispatcher = create_dispatcher(app_settings, db, ai)
                try:
                    await configure_bot(bot, app_settings)
                except Exception:
                    logger.exception(
                        "Unable to configure Telegram commands or Mini App button; "
                        "API and bot polling will continue"
                    )
                tasks.append(asyncio.create_task(dispatcher.start_polling(bot), name="telegram-polling"))
                tasks.append(
                    asyncio.create_task(
                        reminder_worker(bot, db, app_settings.reminder_poll_seconds),
                        name="reminder-worker",
                    )
                )
                logger.info("Telegram polling and reminder worker started")
            elif app_settings.run_bot:
                logger.warning("TELEGRAM_BOT_TOKEN is empty; API started without Telegram polling")
            yield
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.gather(*tasks, return_exceptions=True)
            if bot is not None:
                await bot.session.close()
            app_instance.state.bot = None
            await db.close()

    app = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if app_settings.dev_mode else None,
        redoc_url=None,
    )
    app.state.settings = app_settings
    app.state.database = db
    app.state.ai = ai

    async def current_user(
        init_data: Annotated[str | None, Header(alias="X-Telegram-Init-Data")] = None,
        dev_user_id: Annotated[int | None, Header(alias="X-Dev-Telegram-User")] = None,
    ) -> TelegramUser:
        if init_data:
            try:
                user = validate_init_data(
                    init_data,
                    app_settings.telegram_bot_token,
                    app_settings.telegram_auth_max_age_seconds,
                )
            except TelegramAuthError as exc:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
            await db.upsert_user(user)
            return user
        if app_settings.dev_mode and dev_user_id:
            user = TelegramUser(id=dev_user_id, first_name="Local developer")
            await db.upsert_user(user)
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Open this page inside Telegram Mini App",
        )

    UserDependency = Annotated[TelegramUser, Depends(current_user)]

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "bot_enabled": bool(app_settings.run_bot and app_settings.telegram_bot_token),
            "ai_enabled": ai.enabled,
            "storage": "sqlite",
            "storage_persistent": app_settings.storage_persistent,
        }

    @app.get("/api/me")
    async def me(user: UserDependency) -> dict[str, object]:
        record = await db.get_user(user.id)
        return {
            "id": user.id,
            "first_name": user.first_name,
            "username": user.username,
            "is_pro": bool(record and record["is_pro"]),
            "free_limit": app_settings.free_items_limit,
            "ai_enabled": ai.enabled,
        }

    @app.get("/api/stats")
    async def stats(user: UserDependency) -> dict[str, object]:
        return await db.stats(user.id)

    @app.get("/api/categories")
    async def categories(user: UserDependency) -> dict[str, object]:
        return {"categories": await db.list_categories(user.id)}

    @app.post("/api/categories", status_code=status.HTTP_201_CREATED)
    async def create_category(category: CategoryCreate, user: UserDependency) -> dict[str, object]:
        try:
            return await db.create_category(user.id, category.name, category.icon)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @app.patch("/api/categories/{category_key}")
    async def rename_category(
        category_key: str,
        patch: CategoryPatch,
        user: UserDependency,
    ) -> dict[str, object]:
        try:
            category = await db.rename_category(user.id, category_key, patch.name)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")
        return category

    @app.get("/api/items")
    async def items(
        user: UserDependency,
        category: str | None = None,
        favorite: bool | None = None,
        unread: bool | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, object]:
        result = await db.list_items(
            user.id,
            category=category,
            favorite=favorite,
            unread=unread,
            limit=limit,
            offset=offset,
        )
        return {"items": result, "limit": limit, "offset": offset}

    @app.get("/api/search")
    async def search(
        user: UserDependency,
        q: Annotated[str, Query(min_length=2, max_length=500)],
        limit: Annotated[int, Query(ge=1, le=50)] = 30,
    ) -> dict[str, object]:
        result = await ai.search(db, user.id, q, limit=limit)
        return {"items": result, "query": q, "mode": "semantic" if ai.enabled else "full-text"}

    @app.get("/api/items/{item_id}/media-url")
    async def media_url(item_id: int, user: UserDependency) -> dict[str, object]:
        if not app_settings.telegram_bot_token:
            raise HTTPException(status_code=503, detail="Просмотр файлов временно недоступен")
        item = await db.get_media_item(user.id, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="У этого сохранения нет доступного файла")
        expires = int(time.time()) + MEDIA_URL_TTL_SECONDS
        signature = media_signature(app_settings.telegram_bot_token, user.id, item_id, expires)
        return {
            "url": (
                f"/api/items/{item_id}/media?telegram_id={user.id}"
                f"&expires={expires}&signature={signature}"
            ),
            "kind": item["kind"],
            "file_name": item["file_name"],
            "mime_type": item["mime_type"],
        }

    @app.get("/api/items/{item_id}/media")
    async def stream_media(
        item_id: int,
        request: Request,
        telegram_id: int,
        expires: int,
        signature: str,
    ) -> StreamingResponse:
        now = int(time.time())
        expected = media_signature(app_settings.telegram_bot_token, telegram_id, item_id, expires)
        if (
            not app_settings.telegram_bot_token
            or expires < now
            or expires > now + MEDIA_URL_TTL_SECONDS + 60
            or not hmac.compare_digest(signature, expected)
        ):
            raise HTTPException(status_code=403, detail="Ссылка на файл недействительна или устарела")

        item = await db.get_media_item(telegram_id, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Файл не найден")

        bot = app.state.bot
        temporary_bot = None
        if bot is None:
            temporary_bot = create_bot(app_settings)
            bot = temporary_bot
        try:
            telegram_file = await bot.get_file(item["telegram_file_id"])
        except Exception as exc:
            logger.exception("Unable to resolve Telegram file for item %s", item_id)
            raise HTTPException(status_code=502, detail="Telegram не смог подготовить файл") from exc
        finally:
            if temporary_bot is not None:
                await temporary_bot.session.close()

        if not telegram_file.file_path:
            raise HTTPException(status_code=404, detail="Telegram больше не хранит этот файл")

        telegram_url = (
            f"https://api.telegram.org/file/bot{app_settings.telegram_bot_token}/"
            f"{quote(telegram_file.file_path, safe='/')}"
        )
        upstream_headers = {}
        if range_header := request.headers.get("range"):
            upstream_headers["Range"] = range_header
        session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=90)
        )
        try:
            upstream = await session.get(telegram_url, headers=upstream_headers)
        except aiohttp.ClientError as exc:
            await session.close()
            raise HTTPException(status_code=502, detail="Не удалось загрузить файл из Telegram") from exc
        if upstream.status not in {200, 206}:
            upstream.release()
            await session.close()
            raise HTTPException(status_code=502, detail="Telegram временно не отдаёт этот файл")

        response_headers = {
            "Accept-Ranges": upstream.headers.get("Accept-Ranges", "bytes"),
            "Cache-Control": "private, max-age=300",
        }
        for header in ("Content-Length", "Content-Range", "ETag", "Last-Modified"):
            if value := upstream.headers.get(header):
                response_headers[header] = value
        if item["file_name"]:
            response_headers["Content-Disposition"] = (
                f"inline; filename*=UTF-8''{quote(item['file_name'])}"
            )

        async def telegram_chunks() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream.content.iter_chunked(64 * 1024):
                    yield chunk
            finally:
                upstream.release()
                await session.close()

        return StreamingResponse(
            telegram_chunks(),
            status_code=upstream.status,
            media_type=item["mime_type"] or upstream.headers.get("Content-Type"),
            headers=response_headers,
        )

    @app.patch("/api/items/{item_id}")
    async def patch_item(item_id: int, patch: ItemPatch, user: UserDependency) -> dict[str, object]:
        if patch.category and not await db.has_category(user.id, patch.category):
            raise HTTPException(status_code=400, detail="Неизвестная категория")
        item = await db.patch_item(user.id, item_id, patch)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        return item

    @app.post("/api/items/{item_id}/reminder")
    async def smart_reminder(
        item_id: int,
        reminder: SmartReminderRequest,
        user: UserDependency,
    ) -> dict[str, object]:
        if not await db.get_item(user.id, item_id):
            raise HTTPException(status_code=404, detail="Сохранение не найдено")
        try:
            reminder_at = parse_smart_reminder(
                reminder.text,
                timezone_offset_minutes=reminder.timezone_offset_minutes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        item = await db.patch_item(user.id, item_id, ItemPatch(reminder_at=reminder_at))
        if not item:
            raise HTTPException(status_code=404, detail="Сохранение не найдено")
        return item

    @app.post("/api/bulk/items")
    async def bulk_items(payload: BulkItemsRequest, user: UserDependency) -> dict[str, object]:
        operation = payload.operation
        if operation == "move":
            if not payload.category:
                raise HTTPException(status_code=422, detail="Выбери категорию")
            if not await db.has_category(user.id, payload.category):
                raise HTTPException(status_code=400, detail="Неизвестная категория")
            affected = await db.bulk_patch_items(user.id, payload.item_ids, category=payload.category)
        elif operation == "remind":
            if not payload.reminder_text:
                raise HTTPException(status_code=422, detail="Напиши, когда напомнить")
            try:
                reminder_at = parse_smart_reminder(
                    payload.reminder_text,
                    timezone_offset_minutes=payload.timezone_offset_minutes,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            affected = await db.bulk_patch_items(user.id, payload.item_ids, reminder_at=reminder_at)
        elif operation == "delete":
            affected = await db.bulk_delete_items(user.id, payload.item_ids)
        else:
            patches = {
                "mark_read": {"read": True},
                "mark_unread": {"read": False},
                "favorite": {"favorite": True},
                "unfavorite": {"favorite": False},
                "clear_reminder": {"clear_reminder": True},
            }
            affected = await db.bulk_patch_items(user.id, payload.item_ids, **patches[operation])
        return {"affected": affected, "operation": operation}

    @app.post("/api/items/{item_id}/recognize")
    async def recognize_item(item_id: int, user: UserDependency) -> dict[str, object]:
        item = await db.get_media_item(user.id, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="У этого сохранения нет доступного файла")
        kind = item["kind"]
        mime_type = item["mime_type"] or "application/octet-stream"
        needs_openai = kind in {"photo", "audio", "voice", "video"} or mime_type.startswith(
            ("image/", "audio/", "video/")
        )
        if needs_openai and not ai.enabled:
            raise HTTPException(status_code=503, detail="Для OCR и расшифровки подключи и пополни OpenAI API")
        bot = app.state.bot
        temporary_bot = None
        if bot is None:
            temporary_bot = create_bot(app_settings)
            bot = temporary_bot
        try:
            telegram_file = await bot.get_file(item["telegram_file_id"])
            if not telegram_file.file_path:
                raise HTTPException(status_code=404, detail="Telegram больше не хранит этот файл")
            buffer = io.BytesIO()
            await bot.download_file(telegram_file.file_path, destination=buffer)
            content = buffer.getvalue()
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Unable to download item %s for recognition", item_id)
            raise HTTPException(status_code=502, detail="Не удалось скачать файл из Telegram") from exc
        finally:
            if temporary_bot is not None:
                await temporary_bot.session.close()
        if len(content) > app_settings.recognition_max_bytes:
            raise HTTPException(
                status_code=413,
                detail=(
                    "Для распознавания файл должен быть меньше "
                    f"{app_settings.recognition_max_bytes // 1_000_000} МБ"
                ),
            )
        try:
            filename = item["file_name"] or f"telegram-{item_id}{media_extension(mime_type, kind)}"
            if kind == "photo" or mime_type.startswith("image/"):
                recognized = await ai.recognize_image(content, mime_type)
                recognition_kind = "ocr"
            elif kind in {"audio", "voice", "video"} or mime_type.startswith(("audio/", "video/")):
                recognized = await ai.transcribe_media(
                    content,
                    filename=filename,
                    mime_type=mime_type,
                )
                recognition_kind = "transcript"
            else:
                recognized = ai.extract_document_text(
                    content,
                    filename=filename,
                    mime_type=mime_type,
                )
                recognition_kind = "document"
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        original = await db.get_item(user.id, item_id)
        searchable = "\n".join((original or {}).get(key, "") or "" for key in ("title", "text"))
        embedding = await ai.embed(f"{searchable}\n{recognized}")
        updated = await db.set_recognition(
            user.id,
            item_id,
            recognized,
            recognition_kind,
            embedding=embedding,
        )
        return updated or original or {}

    @app.post("/api/items/{item_id}/summary")
    async def summarize(item_id: int, user: UserDependency) -> dict[str, object]:
        item = await db.get_item(user.id, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        summary = await ai.summarize(f"{item['title']}\n{item['text']}")
        updated = await db.set_summary(user.id, item_id, summary)
        return updated or item

    @app.delete("/api/items/{item_id}", status_code=204)
    async def delete_item(item_id: int, user: UserDependency) -> None:
        if not await db.delete_item(user.id, item_id):
            raise HTTPException(status_code=404, detail="Item not found")

    @app.delete("/api/account", status_code=204)
    async def delete_account(payload: DeleteAccountRequest, user: UserDependency) -> None:
        if payload.confirmation.strip().casefold() != "удалить":
            raise HTTPException(status_code=422, detail="Для подтверждения введи слово УДАЛИТЬ")
        charge_id = await db.latest_subscription_charge(user.id)
        if charge_id and app.state.bot is not None:
            try:
                await app.state.bot.edit_user_star_subscription(
                    user_id=user.id,
                    telegram_payment_charge_id=charge_id,
                    is_canceled=True,
                )
            except Exception:
                logger.exception("Unable to cancel Stars subscription for deleted user %s", user.id)
        if not await db.delete_user_data(user.id):
            raise HTTPException(status_code=404, detail="Профиль уже удалён")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(Path(WEB_DIR) / "index.html")

    return app


def media_extension(mime_type: str, kind: str) -> str:
    extensions = {
        "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "video/mp4": ".mp4",
        "image/jpeg": ".jpg",
        "image/png": ".png",
    }
    return extensions.get(mime_type, ".ogg" if kind == "voice" else ".bin")
