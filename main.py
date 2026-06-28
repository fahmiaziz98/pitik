import asyncio
import logging
import sys

from bot.telegram_handler import build_app
from core.config import settings
from db.client import init_db


def setup_logging() -> None:
    """Configure application-wide logging format and level."""
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
        stream=sys.stdout,
    )
    # Silence noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)


async def _startup() -> None:
    """Run async startup tasks before the bot start polling"""
    await init_db()


def main() -> None:
    """
    Validate config, then start the Pitik Telegram bot.

    Exits with a non-zero status code if configuration is invalid.
    """
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("Pitik is starting...")

    asyncio.run(_startup())
    app = build_app()
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
