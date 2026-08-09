from app.classifier import classify, first_url, make_title


def test_extracts_and_cleans_url() -> None:
    assert first_url("Вот ссылка https://example.com/post).") == "https://example.com/post"


def test_classifies_development_link() -> None:
    kind, category = classify("Полезный репозиторий", url="https://github.com/example/project")
    assert kind == "link"
    assert category == "development"


def test_classifies_purchase_intent() -> None:
    kind, category = classify("Этот монитор надо купить со скидкой")
    assert kind == "text"
    assert category == "buy"


def test_file_takes_files_category() -> None:
    assert classify("Отчёт", has_file=True) == ("file", "files")


def test_title_prefers_first_line() -> None:
    assert make_title("Настройка WireGuard\nПодробная инструкция") == "Настройка WireGuard"
