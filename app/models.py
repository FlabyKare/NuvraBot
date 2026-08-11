from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["inbox", "links", "watch", "development", "buy", "read", "files"]
ItemKind = Literal["text", "link", "photo", "video", "audio", "voice", "file", "code"]


class NewItem(BaseModel):
    kind: ItemKind = "text"
    category: Category = "inbox"
    title: str = Field(min_length=1, max_length=300)
    text: str = ""
    url: str | None = None
    telegram_file_id: str | None = None
    telegram_file_unique_id: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    source_chat: str | None = None
    source_author: str | None = None
    source_message_id: int | None = None
    raw_json: str | None = None

    @property
    def searchable_text(self) -> str:
        parts = [self.title, self.text, self.url or "", self.file_name or "", self.source_chat or ""]
        return "\n".join(part for part in parts if part).strip()


class ItemPatch(BaseModel):
    favorite: bool | None = None
    read: bool | None = None
    category: Category | None = None
    reminder_at: datetime | None = None
    clear_reminder: bool = False


class ItemView(BaseModel):
    id: int
    kind: str
    category: str
    title: str
    text: str
    url: str | None
    has_media: bool = False
    file_name: str | None
    mime_type: str | None
    source_chat: str | None
    source_author: str | None
    favorite: bool
    read: bool
    summary: str | None
    reminder_at: str | None
    created_at: str
    score: float | None = None


class TelegramUser(BaseModel):
    id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None
