from types import SimpleNamespace

import pytest

from app.ai_service import AIService, cosine_similarity
from app.config import Settings


class FakeResponses:
    def __init__(self) -> None:
        self.request: dict[str, str] | None = None

    async def create(self, **kwargs: str) -> SimpleNamespace:
        self.request = kwargs
        return SimpleNamespace(output_text="• Первый вывод\n• Второй вывод")


def test_cosine_similarity() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([], []) == 0.0


@pytest.mark.asyncio
async def test_summary_uses_configured_openai_responses_model(tmp_path) -> None:
    service = AIService(
        Settings(
            database_path=tmp_path / "ai.sqlite3",
            run_bot=False,
            openai_api_key="",
            openai_text_model="gpt-5.4-nano",
        )
    )
    responses = FakeResponses()
    service.client = SimpleNamespace(responses=responses)

    summary = await service.summarize("Большой сохранённый текст. В нём есть важные мысли.")

    assert summary == "• Первый вывод\n• Второй вывод"
    assert responses.request
    assert responses.request["model"] == "gpt-5.4-nano"
    assert "Кратко суммаризируй" in responses.request["instructions"]
