import asyncio
import sys

import structlog

from bot.telegram_handler import build_app
from core.logging import setup_logging


async def _startup() -> None:
    """Run async startup tasks before the bot start polling"""
    from db.client import init_db

    await init_db()


def main() -> None:
    """
    Validate config, then start the Pitik Telegram bot.

    Exits with a non-zero status code if configuration is invalid.
    """
    try:
        from core.config import settings
    except Exception as exc:
        (f"[FATAL] Config error: {exc}")
        sys.exit(1)

    setup_logging(log_level=settings.LOG_LEVEL, log_format=settings.LOG_FORMAT)
    logger = structlog.get_logger(__name__)

    logger.info("Pitik is starting...")

    asyncio.run(_startup())
    app = build_app()
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message"],
    )


if __name__ == "__main__":
    main()
