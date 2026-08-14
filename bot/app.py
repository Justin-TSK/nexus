import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot import handlers
from config import settings
from core.agent import Agent
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


def build_application() -> Application:
    registry = build_registry()
    agent = Agent(GeminiService(), DeeplService(), registry)

    application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    application.bot_data["agent"] = agent
    application.bot_data["registry"] = registry

    application.add_handler(CommandHandler("start", handlers.cmd_start))
    application.add_handler(CommandHandler("help", handlers.cmd_help))
    application.add_handler(CommandHandler("tools", handlers.cmd_tools))
    application.add_handler(CommandHandler("reset", handlers.cmd_reset))
    application.add_handler(CommandHandler("traduire", handlers.cmd_translate))

    application.add_handler(MessageHandler(filters.VOICE, handlers.on_voice))
    application.add_handler(
        MessageHandler(filters.Document.ALL | filters.PHOTO, handlers.on_document)
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_text)
    )

    application.add_error_handler(handlers.on_error)
    logger.info(
        "Application Telegram construite : outils actifs = %s",
        ", ".join(registry.names) if registry.names else "aucun",
    )
    return application
