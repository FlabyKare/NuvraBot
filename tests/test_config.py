from pathlib import Path

from app.config import Settings


def test_public_url_adds_https_for_bare_domain() -> None:
    settings = Settings(public_url="nuvrabot-production.up.railway.app")

    assert settings.public_url == "https://nuvrabot-production.up.railway.app"


def test_public_url_strips_spaces_and_trailing_slash() -> None:
    settings = Settings(public_url="  https://example.com/  ")

    assert settings.public_url == "https://example.com"


def test_railway_volume_is_used_for_relative_sqlite_path(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        database_path="data/second_brain.sqlite3",
        railway_volume_mount_path=tmp_path,
    )

    assert settings.database_path == (tmp_path / "second_brain.sqlite3").resolve()
    assert settings.storage_persistent is True


def test_production_without_volume_is_reported_as_ephemeral(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        database_path=tmp_path / "second_brain.sqlite3",
    )

    assert settings.storage_persistent is False
