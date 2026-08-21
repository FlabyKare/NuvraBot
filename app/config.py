from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Telegram Second Brain"
    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    public_url: str = ""
    database_path: Path = Path("data/second_brain.sqlite3")
    railway_volume_mount_path: Path | None = None

    telegram_bot_token: str = ""
    run_bot: bool = True
    dev_mode: bool = True
    telegram_auth_max_age_seconds: int = 86_400

    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    openai_text_model: str = "gpt-5.4-nano"
    openai_transcription_model: str = "gpt-4o-mini-transcribe"
    recognition_max_bytes: int = Field(default=20_000_000, ge=100_000, le=25_000_000)

    free_items_limit: int = Field(default=500, ge=1)
    pro_price_stars: int = Field(default=299, ge=1, le=10_000)
    pro_subscription_days: int = 30
    support_username: str = "your_support_username"
    terms_url: str = "https://example.com/terms"
    reminder_poll_seconds: int = Field(default=30, ge=5)
    search_candidate_limit: int = Field(default=500, ge=20, le=5000)
    media_context_window_seconds: int = Field(default=600, ge=30, le=3600)

    @field_validator("public_url")
    @classmethod
    def strip_public_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if normalized and "://" not in normalized:
            normalized = f"https://{normalized.lstrip('/')}"
        return normalized

    @model_validator(mode="after")
    def resolve_database_storage(self) -> Settings:
        path = self.database_path
        if self.railway_volume_mount_path and not path.is_absolute():
            path = self.railway_volume_mount_path / path.name
        elif not path.is_absolute():
            path = BASE_DIR / path
        self.database_path = path.resolve()
        return self

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def mini_app_url(self) -> str:
        return self.public_url

    @property
    def storage_persistent(self) -> bool:
        if not self.railway_volume_mount_path:
            return self.app_env.lower() != "production"
        try:
            self.database_path.relative_to(self.railway_volume_mount_path.resolve())
        except ValueError:
            return False
        return True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
