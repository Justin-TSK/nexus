import logging
from datetime import time as dtime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot import handlers
from config import settings
from core.agent import Agent
from services import proactive
from services.deepl import DeeplService
from services.gemini import GeminiService
from tools.calendar import CalendarTool
from tools.contacts import ContactsTool
from tools.gmail import GmailTool
from tools.icloud import IcloudMailTool
from tools.notion import NotionTool
from tools.perplexity import PerplexityTool
from tools.registry import ToolRegistry
from tools.spotify import SpotifyTool
from tools.translate import TranslateTool
from tools.weather import WeatherTool

logger = logging.getLogger(__name__)


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    candidates = [
        ContactsTool(),
        CalendarTool(),
        GmailTool(),
        IcloudMailTool(),
        NotionTool(),
        PerplexityTool(),
        SpotifyTool(),
        TranslateTool(),
        WeatherTool(),
    ]
    for tool in candidates:
        if getattr(tool, "enabled", True):
            registry.register(tool)
    return registry


async def _notify_startup(app: Application) -> None:
    """Prévient l'utilisateur qu'un redémarrage vient d'avoir lieu."""
    for uid in settings.allowed_user_ids:
        chat = app.bot_data.get("agent").store.get_kv(f"chat:{uid}")
        if chat is None:
            chat = uid
        try:
            await app.bot.send_message(
                chat_id=chat, text="🔋 Nexus est en ligne (redémarrage effectué)."
            )
        except Exception:
            logger.exception("Notification de démarrage impossible (chat %s)", chat)


def build_application() -> Application:
    registry = build_registry()
    agent = Agent(GeminiService(), DeeplService(), registry)

    application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    application.bot_data["agent"] = agent
    application.bot_data["registry"] = registry

    # ── Tâches proactives (JobQueue) ────────────────────────────────
    tz = ZoneInfo(settings.CALENDAR_TIMEZONE)
    application.job_queue.run_daily(proactive.send_digest, dtime(hour=8, minute=0, tzinfo=tz))
    application.job_queue.run_repeating(
        proactive.check_reminders,
        interval=proactive.CHECK_INTERVAL_SEC,
        first=60,
    )
    application.job_queue.run_once(_notify_startup, when=3)

    application.add_handler(CommandHandler("start", handlers.cmd_start))
    application.add_handler(CommandHandler("help", handlers.cmd_help))
    application.add_handler(CommandHandler("tools", handlers.cmd_tools))
    application.add_handler(CommandHandler("reset", handlers.cmd_reset))
    application.add_handler(CommandHandler("traduire", handlers.cmd_translate))
    application.add_handler(CommandHandler("digest", handlers.cmd_digest))

    application.add_handler(MessageHandler(filters.VOICE, handlers.on_voice))
    application.add_handler(
        MessageHandler(filters.Document.ALL | filters.PHOTO, handlers.on_document)
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_text)
    )

    application.add_error_handler(handlers.on_error)
    application.add_handler(CallbackQueryHandler(handlers.on_callback))
    logger.info(
        "Application Telegram construite : outils actifs = %s",
        ", ".join(registry.names) if registry.names else "aucun",
    )
    return application
