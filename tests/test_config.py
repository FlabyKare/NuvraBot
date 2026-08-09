from app.config import Settings


def test_public_url_adds_https_for_bare_domain() -> None:
    settings = Settings(public_url="nuvrabot-production.up.railway.app")

    assert settings.public_url == "https://nuvrabot-production.up.railway.app"


def test_public_url_strips_spaces_and_trailing_slash() -> None:
    settings = Settings(public_url="  https://example.com/  ")

    assert settings.public_url == "https://example.com"
