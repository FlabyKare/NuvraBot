from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.bot import configure_bot, create_bot  # noqa: E402
from app.config import Settings  # noqa: E402


async def main() -> None:
    settings = Settings()
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is missing in .env")

    bot = create_bot(settings)
    try:
        me = await bot.get_me()
        await configure_bot(bot, settings)
        print(f"Telegram bot verified and commands configured: @{me.username}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
