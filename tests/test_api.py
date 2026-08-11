from fastapi.testclient import TestClient

from app.api import create_app, media_signature
from app.config import Settings
from app.database import Database
from app.models import NewItem


def test_health_and_dev_auth(tmp_path) -> None:
    settings = Settings(
        database_path=tmp_path / "api.sqlite3",
        run_bot=False,
        dev_mode=True,
        telegram_bot_token="123456:TEST_TOKEN",
        openai_api_key="",
    )
    database = Database(settings.database_path)
    app = create_app(settings, database)
    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/stats").status_code == 401
        response = client.get("/api/stats", headers={"X-Dev-Telegram-User": "77"})
        assert response.status_code == 200
        assert response.json()["total"] == 0

        saved = client.portal.call(
            database.create_item,
            77,
            NewItem(
                kind="video",
                category="watch",
                title="Видео",
                telegram_file_id="file-id",
                mime_type="video/mp4",
            ),
        )
        media_response = client.get(
            f"/api/items/{saved['id']}/media-url",
            headers={"X-Dev-Telegram-User": "77"},
        )
        assert media_response.status_code == 200
        assert "TEST_TOKEN" not in media_response.json()["url"]
        assert media_response.json()["url"].startswith(f"/api/items/{saved['id']}/media?")

        invalid_media_response = client.get(
            f"/api/items/{saved['id']}/media",
            params={"telegram_id": 77, "expires": 123456, "signature": "invalid"},
        )
        assert invalid_media_response.status_code == 403


def test_media_signature_is_scoped_to_user_and_item() -> None:
    signature = media_signature("secret", telegram_id=77, item_id=12, expires=123456)

    assert signature == media_signature("secret", telegram_id=77, item_id=12, expires=123456)
    assert signature != media_signature("secret", telegram_id=78, item_id=12, expires=123456)
    assert signature != media_signature("secret", telegram_id=77, item_id=13, expires=123456)
