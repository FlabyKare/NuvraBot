from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from .models import TelegramUser


class TelegramAuthError(ValueError):
    pass


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86_400) -> TelegramUser:
    if not init_data or not bot_token:
        raise TelegramAuthError("Telegram initData or bot token is missing")

    values = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = values.pop("hash", "")
    if not received_hash:
        raise TelegramAuthError("Telegram initData has no hash")

    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise TelegramAuthError("Telegram initData signature is invalid")

    try:
        auth_date = int(values.get("auth_date", "0"))
    except ValueError as exc:
        raise TelegramAuthError("Telegram auth_date is invalid") from exc
    if auth_date <= 0 or time.time() - auth_date > max_age_seconds:
        raise TelegramAuthError("Telegram initData has expired")

    try:
        user_data = json.loads(values["user"])
        return TelegramUser.model_validate(user_data)
    except (KeyError, json.JSONDecodeError, ValueError) as exc:
        raise TelegramAuthError("Telegram user data is invalid") from exc
