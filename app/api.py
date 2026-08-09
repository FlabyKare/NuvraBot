import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .ai_service import AIService
from .bot import configure_bot, create_bot, create_dispatcher, reminder_worker
from .config import BASE_DIR, Settings, get_settings
from .database import Database
from .models import ItemPatch, TelegramUser
from .telegram_auth import TelegramAuthError, validate_init_data

logger = logging.getLogger(__name__)
WEB_DIR = BASE_DIR / "web"


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    ai_service: AIService | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    db = database or Database(app_settings.database_path)
    ai = ai_service or AIService(app_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await db.init()
        tasks: list[asyncio.Task[object]] = []
        bot = None
        try:
            if app_settings.run_bot and app_settings.telegram_bot_token:
                bot = create_bot(app_settings)
                dispatcher = create_dispatcher(app_settings, db, ai)
                await configure_bot(bot, app_settings)
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

    @app.patch("/api/items/{item_id}")
    async def patch_item(item_id: int, patch: ItemPatch, user: UserDependency) -> dict[str, object]:
        item = await db.patch_item(user.id, item_id, patch)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        return item

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

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(Path(WEB_DIR) / "index.html")

    return app
