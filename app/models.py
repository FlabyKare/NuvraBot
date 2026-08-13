from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator

Category = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[a-z][a-z0-9_]{0,31}$"),
]
ItemKind = Literal["text", "link", "photo", "video", "audio", "voice", "file", "code"]


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    icon: str = Field(default="🗂", min_length=1, max_length=8)

    @field_validator("name", "icon", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CategoryPatch(BaseModel):
    name: str = Field(min_length=1, max_length=40)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


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
    title: str | None = Field(default=None, min_length=1, max_length=300)
    favorite: bool | None = None
    read: bool | None = None
    category: Category | None = None
    reminder_at: datetime | None = None
    clear_reminder: bool = False

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class SmartReminderRequest(BaseModel):
    text: str = Field(min_length=2, max_length=160)
    timezone_offset_minutes: int = Field(default=180, ge=-720, le=840)

    @field_validator("text", mode="before")
    @classmethod
    def strip_reminder_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


BulkOperation = Literal[
    "mark_read",
    "mark_unread",
    "favorite",
    "unfavorite",
    "move",
    "remind",
    "clear_reminder",
    "delete",
]


class BulkItemsRequest(BaseModel):
    item_ids: list[int] = Field(min_length=1, max_length=100)
    operation: BulkOperation
    category: Category | None = None
    reminder_text: str | None = Field(default=None, min_length=2, max_length=160)
    timezone_offset_minutes: int = Field(default=180, ge=-720, le=840)

    @field_validator("item_ids")
    @classmethod
    def unique_item_ids(cls, value: list[int]) -> list[int]:
        if any(item_id < 1 for item_id in value):
            raise ValueError("item_ids must be positive")
        return list(dict.fromkeys(value))

    @field_validator("reminder_text", mode="before")
    @classmethod
    def strip_bulk_reminder_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class DeleteAccountRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=20)


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
    recognized_text: str | None = None
    recognition_kind: str | None = None
    recognized_at: str | None = None
    reminder_at: str | None
    created_at: str
    score: float | None = None


class TelegramUser(BaseModel):
    id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None
