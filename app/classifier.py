from __future__ import annotations

import re
from pathlib import PurePath
from urllib.parse import urlparse

from .models import Category, ItemKind

URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
CODE_RE = re.compile(
    r"(?:```|\b(?:def|class|function|const|let|var|import|from|SELECT|CREATE TABLE)\b|[{};]\s*$)",
    re.IGNORECASE | re.MULTILINE,
)

VIDEO_HOSTS = {"youtube.com", "youtu.be", "rutube.ru", "vimeo.com", "vkvideo.ru", "tiktok.com"}
DEV_HOSTS = {
    "github.com",
    "gitlab.com",
    "stackoverflow.com",
    "developer.mozilla.org",
    "docs.python.org",
    "pypi.org",
    "npmjs.com",
}

BUY_WORDS = {
    "купить",
    "заказать",
    "цена",
    "скидка",
    "товар",
    "маркетплейс",
    "озон",
    "wildberries",
    "авито",
    "монитор",
}
WATCH_WORDS = {"посмотреть", "фильм", "сериал", "видео", "видос", "ютуб", "youtube", "триллер"}
READ_WORDS = {"почитать", "статья", "книга", "лонгрид", "гайд", "инструкция", "совет", "пост"}
DEV_WORDS = {
    "github",
    "gitlab",
    "репозиторий",
    "код",
    "python",
    "javascript",
    "typescript",
    "docker",
    "linux",
    "wireguard",
    "api",
}


def first_url(text: str) -> str | None:
    match = URL_RE.search(text or "")
    return match.group(0).rstrip(".,);!?]}") if match else None


def host_of(url: str | None) -> str:
    if not url:
        return ""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return host


def classify(
    text: str,
    *,
    url: str | None = None,
    has_file: bool = False,
    media_kind: str | None = None,
) -> tuple[ItemKind, Category]:
    normalized = text.casefold()
    detected_url = url or first_url(text)
    host = host_of(detected_url)

    if has_file and media_kind not in {"photo", "video", "audio", "voice"}:
        return "file", "files"
    if media_kind == "video":
        return "video", "watch"
    if media_kind in {"audio", "voice", "photo"}:
        return media_kind, "files"
    if CODE_RE.search(text) or host in DEV_HOSTS or any(word in normalized for word in DEV_WORDS):
        return "code" if CODE_RE.search(text) else ("link" if detected_url else "text"), "development"
    if host in VIDEO_HOSTS or any(word in normalized for word in WATCH_WORDS):
        return "link" if detected_url else "text", "watch"
    if any(word in normalized for word in BUY_WORDS):
        return "link" if detected_url else "text", "buy"
    if any(word in normalized for word in READ_WORDS):
        return "link" if detected_url else "text", "read"
    if detected_url:
        return "link", "links"
    return "text", "inbox"


def make_title(text: str, *, url: str | None = None, file_name: str | None = None) -> str:
    if file_name:
        return PurePath(file_name).name[:300]
    meaningful_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if meaningful_lines:
        first = meaningful_lines[0]
        if first_url(first) == first and url:
            return host_of(url) or "Ссылка"
        return (first[:297] + "…") if len(first) > 300 else first
    if url:
        return host_of(url) or "Ссылка"
    return "Сохранённое сообщение"
