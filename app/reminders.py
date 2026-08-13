from __future__ import annotations

import calendar
import re
from datetime import UTC, datetime, timedelta, timezone

MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
WEEKDAYS = {
    "понедельник": 0,
    "понедельника": 0,
    "вторник": 1,
    "вторника": 1,
    "среду": 2,
    "среда": 2,
    "четверг": 3,
    "четверга": 3,
    "пятницу": 4,
    "пятница": 4,
    "субботу": 5,
    "суббота": 5,
    "воскресенье": 6,
}
NUMBER_WORDS = {
    "один": 1,
    "одну": 1,
    "два": 2,
    "две": 2,
    "пару": 2,
    "три": 3,
    "четыре": 4,
}


def parse_smart_reminder(
    value: str,
    *,
    now: datetime | None = None,
    timezone_offset_minutes: int = 180,
) -> datetime:
    """Parse common Russian reminder phrases and return a future UTC datetime."""
    text = " ".join(value.casefold().replace("ё", "е").split())
    if not text:
        raise ValueError("Напиши, когда напомнить")

    tz = timezone(timedelta(minutes=timezone_offset_minutes))
    current = (now or datetime.now(UTC)).astimezone(tz)
    hour, minute, has_explicit_time = _extract_time(text)

    relative = re.search(
        r"через\s+(?:(\d+|один|одну|два|две|пару|три|четыре)\s+)?"
        r"(минут\w*|час\w*|дн\w*|день|дня|недел\w*|месяц\w*)",
        text,
    )
    if relative:
        amount_text = relative.group(1) or "1"
        amount = int(amount_text) if amount_text.isdigit() else NUMBER_WORDS[amount_text]
        unit = relative.group(2)
        if unit.startswith("минут"):
            result = current + timedelta(minutes=amount)
        elif unit.startswith("час"):
            result = current + timedelta(hours=amount)
        elif unit.startswith("недел"):
            result = current + timedelta(weeks=amount)
        elif unit.startswith("месяц"):
            result = _add_months(current, amount)
        else:
            result = current + timedelta(days=amount)
        if has_explicit_time and not (unit.startswith("минут") or unit.startswith("час")):
            result = result.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return _ensure_future(result, current)

    target_date = None
    if "послезавтра" in text:
        target_date = (current + timedelta(days=2)).date()
    elif "завтра" in text:
        target_date = (current + timedelta(days=1)).date()
    elif "сегодня" in text:
        target_date = current.date()

    numeric_date = re.search(r"\b([0-3]?\d)[./-]([01]?\d)(?:[./-](\d{2,4}))?\b", text)
    if numeric_date:
        day, month = int(numeric_date.group(1)), int(numeric_date.group(2))
        year = _normalize_year(numeric_date.group(3), current.year)
        target_date = _future_date(year, month, day, current)

    named_date = re.search(
        rf"\b([0-3]?\d)\s+({'|'.join(MONTHS)})(?:\s+(\d{{4}}))?\b",
        text,
    )
    if named_date:
        day = int(named_date.group(1))
        month = MONTHS[named_date.group(2)]
        year = int(named_date.group(3) or current.year)
        target_date = _future_date(year, month, day, current)

    for name, weekday in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", text):
            days = (weekday - current.weekday()) % 7
            if days == 0:
                days = 7
            target_date = (current + timedelta(days=days)).date()
            break

    if target_date is None and has_explicit_time:
        target_date = current.date()
    if target_date is None:
        raise ValueError(
            "Не понял дату. Попробуй: «завтра в 19:00», «через 2 недели» или «25 августа утром»"
        )

    result = datetime.combine(target_date, datetime.min.time(), tzinfo=tz).replace(
        hour=hour,
        minute=minute,
    )
    if result <= current and target_date == current.date():
        result += timedelta(days=1)
    return _ensure_future(result, current)


def _extract_time(text: str) -> tuple[int, int, bool]:
    match = re.search(r"(?:\bв\s*)?\b([01]?\d|2[0-3])(?::([0-5]\d))\b", text)
    if match:
        return int(match.group(1)), int(match.group(2)), True
    hour_match = re.search(r"\bв\s+([01]?\d|2[0-3])\b", text)
    if hour_match:
        return int(hour_match.group(1)), 0, True
    if "утром" in text:
        return 9, 0, True
    if "днем" in text:
        return 14, 0, True
    if "вечером" in text:
        return 19, 0, True
    if "ночью" in text:
        return 22, 0, True
    return 19, 0, False


def _add_months(value: datetime, months: int) -> datetime:
    total = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(total, 12)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _normalize_year(value: str | None, default: int) -> int:
    if not value:
        return default
    year = int(value)
    return 2000 + year if year < 100 else year


def _future_date(year: int, month: int, day: int, current: datetime):
    try:
        candidate = datetime(year, month, day, tzinfo=current.tzinfo).date()
    except ValueError as exc:
        raise ValueError("Такой даты не существует") from exc
    if year == current.year and candidate < current.date():
        try:
            candidate = datetime(year + 1, month, day, tzinfo=current.tzinfo).date()
        except ValueError as exc:
            raise ValueError("Такой даты не существует") from exc
    return candidate


def _ensure_future(result: datetime, current: datetime) -> datetime:
    if result <= current:
        raise ValueError("Время напоминания должно быть в будущем")
    return result.astimezone(UTC)
