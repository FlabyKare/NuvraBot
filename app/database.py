from __future__ import annotations

import asyncio
import json
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from .categories import DEFAULT_CATEGORIES
from .models import ItemPatch, NewItem, TelegramUser

FTS_WORD_RE = re.compile(r"[\w\-]+", re.UNICODE)
MAX_CUSTOM_CATEGORIES = 20
SEARCH_STOP_WORDS = {
    "а",
    "в",
    "во",
    "где",
    "для",
    "и",
    "из",
    "как",
    "какой",
    "который",
    "мне",
    "мой",
    "на",
    "найди",
    "но",
    "о",
    "от",
    "по",
    "покажи",
    "про",
    "с",
    "сохранял",
    "сохранённый",
    "тот",
    "у",
    "хотел",
    "что",
    "я",
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_iso(value: datetime | None = None) -> str:
    current = value or utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.connection: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()
        self.fts_enabled = True

    async def connect(self) -> None:
        if self.connection is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(self.path)
        self.connection.row_factory = aiosqlite.Row
        await self.connection.execute("PRAGMA foreign_keys = ON")
        await self.connection.execute("PRAGMA journal_mode = WAL")
        await self.connection.execute("PRAGMA busy_timeout = 5000")

    @property
    def conn(self) -> aiosqlite.Connection:
        if self.connection is None:
            raise RuntimeError("Database is not connected")
        return self.connection

    async def init(self) -> None:
        await self.connect()
        await self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL UNIQUE,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                language_code TEXT,
                is_pro INTEGER NOT NULL DEFAULT 0,
                pro_until TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                telegram_payment_charge_id TEXT NOT NULL UNIQUE,
                currency TEXT NOT NULL,
                amount INTEGER NOT NULL,
                invoice_payload TEXT NOT NULL,
                is_recurring INTEGER NOT NULL DEFAULT 0,
                is_first_recurring INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                kind TEXT NOT NULL DEFAULT 'text',
                category TEXT NOT NULL DEFAULT 'inbox',
                title TEXT NOT NULL,
                text TEXT NOT NULL DEFAULT '',
                url TEXT,
                telegram_file_id TEXT,
                telegram_file_unique_id TEXT,
                file_name TEXT,
                mime_type TEXT,
                source_chat TEXT,
                source_author TEXT,
                source_message_id INTEGER,
                raw_json TEXT,
                embedding TEXT,
                summary TEXT,
                recognized_text TEXT,
                recognition_kind TEXT,
                recognized_at TEXT,
                favorite INTEGER NOT NULL DEFAULT 0,
                read_at TEXT,
                reminder_at TEXT,
                reminder_sent_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                category_key TEXT NOT NULL,
                name TEXT NOT NULL COLLATE NOCASE,
                icon TEXT NOT NULL DEFAULT '🗂',
                is_system INTEGER NOT NULL DEFAULT 0,
                position INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, category_key),
                UNIQUE(user_id, name)
            );

            CREATE TABLE IF NOT EXISTS schema_migrations (
                migration_key TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_items_user_created
                ON items(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_items_user_category
                ON items(user_id, category, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_items_due_reminders
                ON items(reminder_at, reminder_sent_at);
            """
        )
        await self._ensure_item_columns()
        try:
            await self.conn.executescript(
                """
                DROP TRIGGER IF EXISTS items_ai;
                DROP TRIGGER IF EXISTS items_ad;
                DROP TRIGGER IF EXISTS items_au;
                DROP TABLE IF EXISTS items_fts;

                CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
                    title,
                    text,
                    recognized_text,
                    url,
                    source_chat,
                    category,
                    content='items',
                    content_rowid='id',
                    tokenize='unicode61 remove_diacritics 2'
                );

                CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
                    INSERT INTO items_fts(rowid, title, text, recognized_text, url, source_chat, category)
                    VALUES (
                        new.id, new.title, new.text, new.recognized_text,
                        new.url, new.source_chat, new.category
                    );
                END;
                CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
                    INSERT INTO items_fts(
                        items_fts, rowid, title, text, recognized_text, url, source_chat, category
                    ) VALUES (
                        'delete', old.id, old.title, old.text, old.recognized_text,
                        old.url, old.source_chat, old.category
                    );
                END;
                CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN
                    INSERT INTO items_fts(
                        items_fts, rowid, title, text, recognized_text, url, source_chat, category
                    ) VALUES (
                        'delete', old.id, old.title, old.text, old.recognized_text,
                        old.url, old.source_chat, old.category
                    );
                    INSERT INTO items_fts(rowid, title, text, recognized_text, url, source_chat, category)
                    VALUES (
                        new.id, new.title, new.text, new.recognized_text,
                        new.url, new.source_chat, new.category
                    );
                END;

                INSERT INTO items_fts(items_fts) VALUES ('rebuild');
                """
            )
        except aiosqlite.OperationalError:
            self.fts_enabled = False
        await self._migrate_video_titles()
        now = to_iso()
        for category in DEFAULT_CATEGORIES:
            await self.conn.execute(
                """
                INSERT OR IGNORE INTO user_categories(
                    user_id, category_key, name, icon, is_system, position, created_at, updated_at
                )
                SELECT id, ?, ?, ?, 1, ?, ?, ? FROM users
                """,
                (
                    category["id"],
                    category["name"],
                    category["icon"],
                    category["position"],
                    now,
                    now,
                ),
            )
        await self.conn.commit()

    async def _ensure_item_columns(self) -> None:
        rows = await (await self.conn.execute("PRAGMA table_info(items)")).fetchall()
        existing = {row["name"] for row in rows}
        for name in ("recognized_text", "recognition_kind", "recognized_at"):
            if name not in existing:
                await self.conn.execute(f"ALTER TABLE items ADD COLUMN {name} TEXT")

    async def _migrate_video_titles(self) -> None:
        migration_key = "video_topics_from_captions_v1"
        applied = await (
            await self.conn.execute(
                "SELECT 1 FROM schema_migrations WHERE migration_key = ?",
                (migration_key,),
            )
        ).fetchone()
        if applied:
            return
        rows = await (
            await self.conn.execute(
                """
                SELECT id, title, text, file_name FROM items
                WHERE kind = 'video'
                  AND (title = 'Видео' OR (file_name IS NOT NULL AND title = file_name))
                """
            )
        ).fetchall()
        now = to_iso()
        for row in rows:
            lines = [line.strip() for line in (row["text"] or "").splitlines() if line.strip()]
            topic = lines[0][:300] if lines else "Видео"
            await self.conn.execute(
                "UPDATE items SET title = ?, updated_at = ? WHERE id = ?",
                (topic, now, row["id"]),
            )
        await self.conn.execute(
            "INSERT INTO schema_migrations(migration_key, applied_at) VALUES (?, ?)",
            (migration_key, now),
        )

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()
            self.connection = None

    async def upsert_user(self, user: TelegramUser | int) -> int:
        if isinstance(user, int):
            user = TelegramUser(id=user)
        now = to_iso()
        async with self._write_lock:
            await self.conn.execute(
                """
                INSERT INTO users(
                    telegram_id, username, first_name, last_name, language_code, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    username = COALESCE(excluded.username, users.username),
                    first_name = COALESCE(excluded.first_name, users.first_name),
                    last_name = COALESCE(excluded.last_name, users.last_name),
                    language_code = COALESCE(excluded.language_code, users.language_code),
                    updated_at = excluded.updated_at
                """,
                (
                    user.id,
                    user.username,
                    user.first_name,
                    user.last_name,
                    user.language_code,
                    now,
                    now,
                ),
            )
            row = await (
                await self.conn.execute("SELECT id FROM users WHERE telegram_id = ?", (user.id,))
            ).fetchone()
            if row is None:
                raise RuntimeError("Unable to create user")
            user_id = int(row["id"])
            await self._insert_default_categories(user_id, now)
            await self.conn.commit()
        return user_id

    async def _insert_default_categories(self, user_id: int, now: str) -> None:
        for category in DEFAULT_CATEGORIES:
            await self.conn.execute(
                """
                INSERT OR IGNORE INTO user_categories(
                    user_id, category_key, name, icon, is_system, position, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    user_id,
                    category["id"],
                    category["name"],
                    category["icon"],
                    category["position"],
                    now,
                    now,
                ),
            )

    async def list_categories(self, telegram_id: int) -> list[dict[str, Any]]:
        await self.upsert_user(telegram_id)
        rows = await self._fetchall(
            """
            SELECT categories.category_key, categories.name, categories.icon,
                   categories.is_system, categories.position, COUNT(items.id) AS amount
            FROM user_categories AS categories
            JOIN users ON users.id = categories.user_id
            LEFT JOIN items
              ON items.user_id = categories.user_id
             AND items.category = categories.category_key
            WHERE users.telegram_id = ?
            GROUP BY categories.id
            ORDER BY categories.position, categories.id
            """,
            (telegram_id,),
        )
        return [
            {
                "id": row["category_key"],
                "name": row["name"],
                "icon": row["icon"],
                "label": f"{row['icon']} {row['name']}",
                "is_system": bool(row["is_system"]),
                "position": int(row["position"]),
                "count": int(row["amount"] or 0),
            }
            for row in rows
        ]

    async def category_labels(self, telegram_id: int) -> dict[str, str]:
        return {category["id"]: category["label"] for category in await self.list_categories(telegram_id)}

    async def has_category(self, telegram_id: int, category_key: str) -> bool:
        row = await self._fetchone(
            """
            SELECT 1 FROM user_categories AS categories
            JOIN users ON users.id = categories.user_id
            WHERE users.telegram_id = ? AND categories.category_key = ?
            """,
            (telegram_id, category_key),
        )
        return row is not None

    async def create_category(self, telegram_id: int, name: str, icon: str = "🗂") -> dict[str, Any]:
        user_id = await self.upsert_user(telegram_id)
        now = to_iso()
        category_key = f"c_{secrets.token_hex(5)}"
        async with self._write_lock:
            count_row = await (
                await self.conn.execute(
                    "SELECT COUNT(*) AS amount FROM user_categories WHERE user_id = ? AND is_system = 0",
                    (user_id,),
                )
            ).fetchone()
            if count_row and int(count_row["amount"]) >= MAX_CUSTOM_CATEGORIES:
                raise ValueError(f"Можно создать не больше {MAX_CUSTOM_CATEGORIES} своих категорий")
            position_row = await (
                await self.conn.execute(
                    """
                    SELECT COALESCE(MAX(position), 0) + 1 AS next_position
                    FROM user_categories WHERE user_id = ?
                    """,
                    (user_id,),
                )
            ).fetchone()
            try:
                await self.conn.execute(
                    """
                    INSERT INTO user_categories(
                        user_id, category_key, name, icon, is_system, position, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 0, ?, ?, ?)
                    """,
                    (user_id, category_key, name, icon, int(position_row["next_position"]), now, now),
                )
            except aiosqlite.IntegrityError as exc:
                raise ValueError("Категория с таким названием уже существует") from exc
            await self.conn.commit()
        return next(
            category for category in await self.list_categories(telegram_id)
            if category["id"] == category_key
        )

    async def rename_category(
        self,
        telegram_id: int,
        category_key: str,
        name: str,
    ) -> dict[str, Any] | None:
        async with self._write_lock:
            try:
                cursor = await self.conn.execute(
                    """
                    UPDATE user_categories SET name = ?, updated_at = ?
                    WHERE user_id = (SELECT id FROM users WHERE telegram_id = ?)
                      AND category_key = ?
                    """,
                    (name, to_iso(), telegram_id, category_key),
                )
            except aiosqlite.IntegrityError as exc:
                raise ValueError("Категория с таким названием уже существует") from exc
            await self.conn.commit()
        if not cursor.rowcount:
            return None
        return next(
            category for category in await self.list_categories(telegram_id)
            if category["id"] == category_key
        )

    async def get_user(self, telegram_id: int) -> dict[str, Any] | None:
        row = await self._fetchone("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        if not row:
            return None
        result = dict(row)
        result["is_pro"] = bool(
            result["is_pro"]
            and (result["pro_until"] is None or result["pro_until"] > to_iso())
        )
        return result

    async def activate_pro(
        self,
        telegram_id: int,
        *,
        charge_id: str,
        currency: str,
        amount: int,
        invoice_payload: str,
        pro_until: datetime,
        is_recurring: bool = False,
        is_first_recurring: bool = False,
    ) -> bool:
        user_id = await self.upsert_user(telegram_id)
        now = to_iso()
        async with self._write_lock:
            cursor = await self.conn.execute(
                """
                INSERT OR IGNORE INTO payments(
                    user_id, telegram_payment_charge_id, currency, amount, invoice_payload,
                    is_recurring, is_first_recurring, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    charge_id,
                    currency,
                    amount,
                    invoice_payload,
                    int(is_recurring),
                    int(is_first_recurring),
                    now,
                ),
            )
            if cursor.rowcount:
                await self.conn.execute(
                    "UPDATE users SET is_pro = 1, pro_until = ?, updated_at = ? WHERE id = ?",
                    (to_iso(pro_until), now, user_id),
                )
            await self.conn.commit()
        return cursor.rowcount > 0

    async def latest_subscription_charge(self, telegram_id: int) -> str | None:
        row = await self._fetchone(
            """
            SELECT payments.telegram_payment_charge_id
            FROM payments JOIN users ON users.id = payments.user_id
            WHERE users.telegram_id = ?
            ORDER BY payments.created_at DESC, payments.id DESC
            LIMIT 1
            """,
            (telegram_id,),
        )
        return str(row["telegram_payment_charge_id"]) if row else None

    async def create_item(
        self,
        telegram_id: int,
        item: NewItem,
        *,
        embedding: list[float] | None = None,
    ) -> dict[str, Any]:
        user_id = await self.upsert_user(telegram_id)
        now = to_iso()
        values = item.model_dump()
        async with self._write_lock:
            cursor = await self.conn.execute(
                """
                INSERT INTO items(
                    user_id, kind, category, title, text, url,
                    telegram_file_id, telegram_file_unique_id, file_name, mime_type,
                    source_chat, source_author, source_message_id, raw_json, embedding,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    values["kind"],
                    values["category"],
                    values["title"],
                    values["text"],
                    values["url"],
                    values["telegram_file_id"],
                    values["telegram_file_unique_id"],
                    values["file_name"],
                    values["mime_type"],
                    values["source_chat"],
                    values["source_author"],
                    values["source_message_id"],
                    values["raw_json"],
                    json.dumps(embedding) if embedding else None,
                    now,
                    now,
                ),
            )
            item_id = cursor.lastrowid
            await self.conn.commit()
        result = await self.get_item(telegram_id, int(item_id))
        if result is None:
            raise RuntimeError("Saved item disappeared")
        return result

    async def get_item(self, telegram_id: int, item_id: int) -> dict[str, Any] | None:
        row = await self._fetchone(
            """
            SELECT items.* FROM items
            JOIN users ON users.id = items.user_id
            WHERE users.telegram_id = ? AND items.id = ?
            """,
            (telegram_id, item_id),
        )
        return self._public_item(row) if row else None

    async def get_media_item(self, telegram_id: int, item_id: int) -> dict[str, Any] | None:
        row = await self._fetchone(
            """
            SELECT items.id, items.kind, items.telegram_file_id, items.file_name, items.mime_type
            FROM items
            JOIN users ON users.id = items.user_id
            WHERE users.telegram_id = ? AND items.id = ? AND items.telegram_file_id IS NOT NULL
            """,
            (telegram_id, item_id),
        )
        return dict(row) if row else None

    async def list_items(
        self,
        telegram_id: int,
        *,
        category: str | None = None,
        favorite: bool | None = None,
        unread: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        conditions = ["users.telegram_id = ?"]
        params: list[Any] = [telegram_id]
        if category:
            conditions.append("items.category = ?")
            params.append(category)
        if favorite is not None:
            conditions.append("items.favorite = ?")
            params.append(int(favorite))
        if unread is not None:
            conditions.append("items.read_at IS NULL" if unread else "items.read_at IS NOT NULL")
        params.extend([limit, offset])
        rows = await self._fetchall(
            f"""
            SELECT items.* FROM items
            JOIN users ON users.id = items.user_id
            WHERE {' AND '.join(conditions)}
            ORDER BY items.created_at DESC, items.id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params),
        )
        return [self._public_item(row) for row in rows]

    async def search_fts(self, telegram_id: int, query: str, limit: int = 30) -> list[dict[str, Any]]:
        all_terms = FTS_WORD_RE.findall(query.casefold())
        terms = [term for term in all_terms if len(term) > 1 and term not in SEARCH_STOP_WORDS]
        if not terms:
            terms = all_terms
        if not terms:
            return []
        if self.fts_enabled:
            fts_query = " OR ".join(f'"{term}"*' for term in terms[:12])
            try:
                rows = await self._fetchall(
                    """
                    SELECT items.*, bm25(items_fts, 5.0, 2.0, 2.0, 1.0, 1.0, 0.5) AS fts_rank
                    FROM items_fts
                    JOIN items ON items.id = items_fts.rowid
                    JOIN users ON users.id = items.user_id
                    WHERE users.telegram_id = ? AND items_fts MATCH ?
                    ORDER BY fts_rank
                    LIMIT ?
                    """,
                    (telegram_id, fts_query, limit),
                )
                return [self._public_item(row, score=1.0 / (1.0 + abs(row["fts_rank"]))) for row in rows]
            except aiosqlite.OperationalError:
                pass

        searchable = (
            "lower(items.title || ' ' || items.text || ' ' || "
            "COALESCE(items.recognized_text, '') || ' ' || COALESCE(items.url, '') || ' ' || "
            "COALESCE(items.file_name, '') || ' ' || COALESCE(items.source_chat, ''))"
        )
        like_conditions = " OR ".join(f"{searchable} LIKE ?" for _ in terms[:12])
        like_params = [f"%{term}%" for term in terms[:12]]
        rows = await self._fetchall(
            f"""
            SELECT items.* FROM items
            JOIN users ON users.id = items.user_id
            WHERE users.telegram_id = ?
              AND ({like_conditions})
            ORDER BY items.created_at DESC
            LIMIT ?
            """,
            (telegram_id, *like_params, limit),
        )
        return [self._public_item(row, score=0.5) for row in rows]

    async def semantic_candidates(self, telegram_id: int, limit: int) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            """
            SELECT items.* FROM items
            JOIN users ON users.id = items.user_id
            WHERE users.telegram_id = ? AND items.embedding IS NOT NULL
            ORDER BY items.created_at DESC
            LIMIT ?
            """,
            (telegram_id, limit),
        )
        return [dict(row) for row in rows]

    async def stats(self, telegram_id: int) -> dict[str, Any]:
        category_rows = await self.list_categories(telegram_id)
        categories = {category["id"]: category["count"] for category in category_rows}
        counters = await self._fetchone(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN items.favorite = 1 THEN 1 ELSE 0 END) AS favorites,
                   SUM(CASE WHEN items.read_at IS NULL THEN 1 ELSE 0 END) AS unread
            FROM items JOIN users ON users.id = items.user_id
            WHERE users.telegram_id = ?
            """,
            (telegram_id,),
        )
        return {
            "total": int(counters["total"] or 0),
            "favorites": int(counters["favorites"] or 0),
            "unread": int(counters["unread"] or 0),
            "categories": categories,
        }

    async def patch_item(self, telegram_id: int, item_id: int, patch: ItemPatch) -> dict[str, Any] | None:
        updates: list[str] = []
        params: list[Any] = []
        fields_set = patch.model_fields_set
        if "title" in fields_set and patch.title:
            updates.append("title = ?")
            params.append(patch.title)
        if "favorite" in fields_set and patch.favorite is not None:
            updates.append("favorite = ?")
            params.append(int(patch.favorite))
        if "read" in fields_set and patch.read is not None:
            updates.append("read_at = ?")
            params.append(to_iso() if patch.read else None)
        if "category" in fields_set and patch.category:
            updates.append("category = ?")
            params.append(patch.category)
        if patch.clear_reminder:
            updates.extend(["reminder_at = NULL", "reminder_sent_at = NULL"])
        elif "reminder_at" in fields_set and patch.reminder_at is not None:
            updates.extend(["reminder_at = ?", "reminder_sent_at = NULL"])
            params.append(to_iso(patch.reminder_at))
        if not updates:
            return await self.get_item(telegram_id, item_id)
        updates.append("updated_at = ?")
        params.append(to_iso())
        params.extend([telegram_id, item_id])
        async with self._write_lock:
            await self.conn.execute(
                f"""
                UPDATE items SET {', '.join(updates)}
                WHERE user_id = (SELECT id FROM users WHERE telegram_id = ?) AND id = ?
                """,
                tuple(params),
            )
            await self.conn.commit()
        return await self.get_item(telegram_id, item_id)

    async def set_recognition(
        self,
        telegram_id: int,
        item_id: int,
        text: str,
        kind: str,
        *,
        embedding: list[float] | None = None,
    ) -> dict[str, Any] | None:
        cleaned = text.strip()
        async with self._write_lock:
            await self.conn.execute(
                """
                UPDATE items SET recognized_text = ?, recognition_kind = ?, recognized_at = ?,
                                 embedding = COALESCE(?, embedding), updated_at = ?
                WHERE user_id = (SELECT id FROM users WHERE telegram_id = ?) AND id = ?
                """,
                (
                    cleaned,
                    kind,
                    to_iso(),
                    json.dumps(embedding) if embedding else None,
                    to_iso(),
                    telegram_id,
                    item_id,
                ),
            )
            await self.conn.commit()
        return await self.get_item(telegram_id, item_id)

    async def bulk_patch_items(
        self,
        telegram_id: int,
        item_ids: list[int],
        *,
        favorite: bool | None = None,
        read: bool | None = None,
        category: str | None = None,
        reminder_at: datetime | None = None,
        clear_reminder: bool = False,
    ) -> int:
        unique_ids = list(dict.fromkeys(item_ids))
        if not unique_ids:
            return 0
        updates: list[str] = []
        params: list[Any] = []
        if favorite is not None:
            updates.append("favorite = ?")
            params.append(int(favorite))
        if read is not None:
            updates.append("read_at = ?")
            params.append(to_iso() if read else None)
        if category:
            updates.append("category = ?")
            params.append(category)
        if clear_reminder:
            updates.extend(["reminder_at = NULL", "reminder_sent_at = NULL"])
        elif reminder_at is not None:
            updates.extend(["reminder_at = ?", "reminder_sent_at = NULL"])
            params.append(to_iso(reminder_at))
        if not updates:
            return 0
        updates.append("updated_at = ?")
        params.append(to_iso())
        placeholders = ",".join("?" for _ in unique_ids)
        params.extend([telegram_id, *unique_ids])
        async with self._write_lock:
            cursor = await self.conn.execute(
                f"""
                UPDATE items SET {', '.join(updates)}
                WHERE user_id = (SELECT id FROM users WHERE telegram_id = ?)
                  AND id IN ({placeholders})
                """,
                tuple(params),
            )
            await self.conn.commit()
        return cursor.rowcount

    async def bulk_delete_items(self, telegram_id: int, item_ids: list[int]) -> int:
        unique_ids = list(dict.fromkeys(item_ids))
        if not unique_ids:
            return 0
        placeholders = ",".join("?" for _ in unique_ids)
        async with self._write_lock:
            cursor = await self.conn.execute(
                f"""
                DELETE FROM items
                WHERE user_id = (SELECT id FROM users WHERE telegram_id = ?)
                  AND id IN ({placeholders})
                """,
                (telegram_id, *unique_ids),
            )
            await self.conn.commit()
        return cursor.rowcount

    async def set_summary(self, telegram_id: int, item_id: int, summary: str) -> dict[str, Any] | None:
        async with self._write_lock:
            await self.conn.execute(
                """
                UPDATE items SET summary = ?, updated_at = ?
                WHERE user_id = (SELECT id FROM users WHERE telegram_id = ?) AND id = ?
                """,
                (summary, to_iso(), telegram_id, item_id),
            )
            await self.conn.commit()
        return await self.get_item(telegram_id, item_id)

    async def delete_item(self, telegram_id: int, item_id: int) -> bool:
        async with self._write_lock:
            cursor = await self.conn.execute(
                """
                DELETE FROM items
                WHERE user_id = (SELECT id FROM users WHERE telegram_id = ?) AND id = ?
                """,
                (telegram_id, item_id),
            )
            await self.conn.commit()
        return cursor.rowcount > 0

    async def delete_user_data(self, telegram_id: int) -> bool:
        async with self._write_lock:
            cursor = await self.conn.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))
            await self.conn.commit()
        return cursor.rowcount > 0

    async def due_reminders(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            """
            SELECT items.*, users.telegram_id
            FROM items JOIN users ON users.id = items.user_id
            WHERE items.reminder_at IS NOT NULL
              AND items.reminder_at <= ?
              AND items.reminder_sent_at IS NULL
            ORDER BY items.reminder_at
            LIMIT ?
            """,
            (to_iso(), limit),
        )
        return [dict(row) for row in rows]

    async def mark_reminder_sent(self, item_id: int) -> None:
        async with self._write_lock:
            await self.conn.execute(
                "UPDATE items SET reminder_sent_at = ?, updated_at = ? WHERE id = ?",
                (to_iso(), to_iso(), item_id),
            )
            await self.conn.commit()

    async def _fetchone(self, query: str, params: tuple[Any, ...]) -> aiosqlite.Row | None:
        cursor = await self.conn.execute(query, params)
        return await cursor.fetchone()

    async def _fetchall(self, query: str, params: tuple[Any, ...]) -> list[aiosqlite.Row]:
        cursor = await self.conn.execute(query, params)
        return list(await cursor.fetchall())

    @staticmethod
    def _public_item(row: aiosqlite.Row, *, score: float | None = None) -> dict[str, Any]:
        values = dict(row)
        title = values["title"]
        if values["kind"] == "video" and values["file_name"] and title == values["file_name"]:
            title = "Видео"
        return {
            "id": values["id"],
            "kind": values["kind"],
            "category": values["category"],
            "title": title,
            "text": values["text"],
            "url": values["url"],
            "has_media": bool(values["telegram_file_id"]),
            "file_name": values["file_name"],
            "mime_type": values["mime_type"],
            "source_chat": values["source_chat"],
            "source_author": values["source_author"],
            "favorite": bool(values["favorite"]),
            "read": values["read_at"] is not None,
            "summary": values["summary"],
            "recognized_text": values.get("recognized_text"),
            "recognition_kind": values.get("recognition_kind"),
            "recognized_at": values.get("recognized_at"),
            "reminder_at": values["reminder_at"],
            "created_at": values["created_at"],
            "score": score,
        }
