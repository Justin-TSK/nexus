import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from telegram import Update

from bot.app import build_application
from config import settings


def setup_logging() -> None:
    log_dir = Path(settings.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        log_dir / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def main() -> None:
    settings.validate()
    setup_logging()
    logger = logging.getLogger(__name__)

    application = build_application()

    if settings.BOT_MODE == "webhook":
        if not settings.WEBHOOK_URL:
            raise RuntimeError("BOT_MODE=webhook exige WEBHOOK_URL dans .env")
        logger.info(
            "Démarrage en mode webhook sur le port %s (%s)",
            settings.WEBHOOK_PORT,
            settings.WEBHOOK_URL,
        )
        application.run_webhook(
            listen="0.0.0.0",
            port=settings.WEBHOOK_PORT,
            url_path=settings.TELEGRAM_BOT_TOKEN,
            webhook_url=settings.WEBHOOK_URL,
        )
    else:
        logger.info("Démarrage en mode polling")
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            skip_pending=True,  # ignore les updates en attente pendant un redémarrage
        )


if __name__ == "__main__":
    main()
