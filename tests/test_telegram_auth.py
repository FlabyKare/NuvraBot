import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from app.telegram_auth import TelegramAuthError, validate_init_data


def make_init_data(bot_token: str, user_id: int = 42) -> str:
    values = {
        "auth_date": str(int(time.time())),
        "query_id": "AAH_test_query",
        "user": json.dumps({"id": user_id, "first_name": "Ada"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_valid_init_data() -> None:
    user = validate_init_data(make_init_data("123:secret"), "123:secret")
    assert user.id == 42
    assert user.first_name == "Ada"


def test_rejects_tampered_init_data() -> None:
    with pytest.raises(TelegramAuthError, match="signature"):
        validate_init_data(make_init_data("123:secret").replace("Ada", "Eve"), "123:secret")
