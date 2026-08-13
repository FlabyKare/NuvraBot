from datetime import UTC, datetime

import pytest

from app.reminders import parse_smart_reminder


def test_parse_relative_and_human_dates() -> None:
    now = datetime(2026, 8, 13, 10, 0, tzinfo=UTC)

    tomorrow = parse_smart_reminder("завтра в 19:30", now=now, timezone_offset_minutes=180)
    assert tomorrow == datetime(2026, 8, 14, 16, 30, tzinfo=UTC)

    weeks = parse_smart_reminder("через две недели", now=now, timezone_offset_minutes=180)
    assert weeks == datetime(2026, 8, 27, 10, 0, tzinfo=UTC)

    named = parse_smart_reminder("25 августа утром", now=now, timezone_offset_minutes=180)
    assert named == datetime(2026, 8, 25, 6, 0, tzinfo=UTC)


def test_parse_rejects_unknown_phrase() -> None:
    with pytest.raises(ValueError, match="Не понял дату"):
        parse_smart_reminder("когда-нибудь потом")
