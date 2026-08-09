from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.database import Database


def test_health_and_dev_auth(tmp_path) -> None:
    settings = Settings(
        database_path=tmp_path / "api.sqlite3",
        run_bot=False,
        dev_mode=True,
        telegram_bot_token="",
        openai_api_key="",
    )
    app = create_app(settings, Database(settings.database_path))
    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/stats").status_code == 401
        response = client.get("/api/stats", headers={"X-Dev-Telegram-User": "77"})
        assert response.status_code == 200
        assert response.json()["total"] == 0
