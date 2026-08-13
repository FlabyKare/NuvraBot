from __future__ import annotations

import base64
import io
import json
import logging
import math
import re
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from pypdf import PdfReader

from .config import Settings
from .database import Database

logger = logging.getLogger(__name__)
SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")


class AIService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.ai_enabled else None

    @property
    def enabled(self) -> bool:
        return self.client is not None

    async def embed(self, text: str) -> list[float] | None:
        if not self.client or not text.strip():
            return None
        try:
            response = await self.client.embeddings.create(
                model=self.settings.openai_embedding_model,
                input=text[:24_000].replace("\n", " "),
            )
            return response.data[0].embedding
        except Exception:
            logger.exception("Unable to create an embedding")
            return None

    async def summarize(self, text: str) -> str:
        cleaned = " ".join(text.split()).strip()
        if not cleaned:
            return "В сохранении нет текста для суммаризации."
        if self.client:
            try:
                response = await self.client.responses.create(
                    model=self.settings.openai_text_model,
                    instructions=(
                        "Кратко суммаризируй сохранённый материал на русском языке. "
                        "Дай 2–4 содержательных пункта без вводных фраз и домыслов."
                    ),
                    input=cleaned[:16_000],
                )
                if response.output_text.strip():
                    return response.output_text.strip()
            except Exception:
                logger.exception("Unable to summarize with OpenAI")
        sentences = SENTENCE_RE.split(cleaned)
        excerpt = " ".join(sentences[:3])
        return (excerpt[:697] + "…") if len(excerpt) > 700 else excerpt

    async def recognize_image(self, content: bytes, mime_type: str = "image/jpeg") -> str:
        if not self.client:
            raise RuntimeError("Для OCR нужен работающий OpenAI API")
        if not content:
            raise ValueError("Изображение пустое")
        encoded = base64.b64encode(content).decode("ascii")
        try:
            response = await self.client.responses.create(
                model=self.settings.openai_text_model,
                instructions=(
                    "Распознай содержимое изображения для личной базы знаний. Сначала дословно "
                    "перепиши весь читаемый текст, затем кратко опиши важные объекты и контекст. "
                    "Отвечай по-русски, без вводных фраз. Не выдумывай нечитаемые детали."
                ),
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Извлеки текст и смысл изображения."},
                            {
                                "type": "input_image",
                                "image_url": f"data:{mime_type};base64,{encoded}",
                                "detail": "high",
                            },
                        ],
                    }
                ],
            )
        except Exception as exc:
            logger.exception("Unable to recognize image")
            raise RuntimeError("OpenAI не смог распознать изображение. Проверь баланс API") from exc
        result = response.output_text.strip()
        if not result:
            raise RuntimeError("На изображении не удалось распознать содержимое")
        return result

    async def transcribe_media(
        self,
        content: bytes,
        *,
        filename: str,
        mime_type: str | None = None,
    ) -> str:
        if not self.client:
            raise RuntimeError("Для расшифровки нужен работающий OpenAI API")
        if not content:
            raise ValueError("Медиафайл пустой")
        try:
            response = await self.client.audio.transcriptions.create(
                model=self.settings.openai_transcription_model,
                file=(filename, content, mime_type or "application/octet-stream"),
                response_format="text",
            )
        except Exception as exc:
            logger.exception("Unable to transcribe media")
            raise RuntimeError("OpenAI не смог расшифровать файл. Проверь формат и баланс API") from exc
        result = response if isinstance(response, str) else getattr(response, "text", "")
        if not result.strip():
            raise RuntimeError("В записи не удалось распознать речь")
        return result.strip()

    def extract_document_text(
        self,
        content: bytes,
        *,
        filename: str | None,
        mime_type: str | None,
    ) -> str:
        suffix = Path(filename or "").suffix.casefold()
        if mime_type == "application/pdf" or suffix == ".pdf":
            try:
                pages = [page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages]
            except Exception as exc:
                raise ValueError("Не удалось прочитать PDF") from exc
            result = "\n\n".join(page.strip() for page in pages if page.strip())
            if not result:
                raise ValueError("В PDF нет текстового слоя — отправь страницы как изображения для OCR")
            return result[:100_000]
        text_suffixes = {".txt", ".md", ".csv", ".json", ".xml", ".html", ".htm", ".py", ".js", ".ts"}
        if (mime_type or "").startswith("text/") or suffix in text_suffixes:
            for encoding in ("utf-8-sig", "utf-8", "cp1251"):
                try:
                    return content.decode(encoding)[:100_000].strip()
                except UnicodeDecodeError:
                    continue
            raise ValueError("Не удалось определить кодировку текстового файла")
        raise ValueError(
            "Этот формат пока нельзя распознать. "
            "Поддерживаются изображения, PDF, текст, аудио и видео"
        )

    async def search(
        self,
        database: Database,
        telegram_id: int,
        query: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        lexical = await database.search_fts(telegram_id, query, limit=max(limit, 30))
        if not self.client:
            return lexical[:limit]

        query_embedding = await self.embed(query)
        if not query_embedding:
            return lexical[:limit]
        candidates = await database.semantic_candidates(
            telegram_id,
            self.settings.search_candidate_limit,
        )

        combined: dict[int, dict[str, Any]] = {}
        for item in lexical:
            item = dict(item)
            item["score"] = min(1.0, 0.35 + float(item.get("score") or 0.0))
            combined[item["id"]] = item

        for candidate in candidates:
            try:
                vector = json.loads(candidate["embedding"])
                semantic_score = (cosine_similarity(query_embedding, vector) + 1.0) / 2.0
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            item = database._public_item(candidate, score=semantic_score)
            previous = combined.get(item["id"])
            if previous:
                previous["score"] = min(1.0, 0.7 * semantic_score + 0.3 * float(previous["score"]))
            elif semantic_score >= 0.5:
                combined[item["id"]] = item

        return sorted(combined.values(), key=lambda item: float(item.get("score") or 0), reverse=True)[:limit]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
