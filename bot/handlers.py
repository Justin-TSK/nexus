import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.helpers import escape_markdown
from telegram.ext import ContextTypes

from config import settings
from core.agent import Agent
from services import media

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "🤖 *Mon agent IA — aide*\n\n"
    "Je suis ton assistant d'études. Voici ce que je sais faire :\n\n"
    "📝 *Texte* : discute avec moi, pose tes questions de cours, demande des explications.\n"
    "🎤 *Vocal* : envoie-moi un message vocal, je le transcris puis je te réponds.\n"
    "📄 *Fichiers* : envoie un PDF, une image, un fichier de code (py, txt, md, js…) :\n"
    "je le lis et je t'en fais un résumé ou de l'aide.\n\n"
    "⚙️ *Commandes*\n"
    "• /traduire <texte> [FR|EN|ES] — traduction via DeepL\n"
    "• /tools — liste les intégrations actives (Gmail, Notion, Spotify…)\n"
    "• /reset — efface la mémoire de la conversation\n"
    "• /help — cette aide\n"
)



def _split_long(text: str, limit: int = 4000) -> list[str]:
    """Découpe un texte trop long pour les limites de Telegram (4096 caractères)."""
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            parts.append(current)
            current = ""
        current += line
    if current:
        parts.append(current)
    return [p for p in parts if p]


def _authorized(update: Update) -> bool:
    allowed = settings.allowed_user_ids
    if not allowed:
        return True
    user = update.effective_user
    return user is not None and user.id in allowed


async def _deny(update: Update) -> None:
    if update.effective_chat:
        await update.effective_chat.send_message(
            "Désolé, ce bot est privé et ne t'est pas accessible."
        )


async def _typing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action=ChatAction.TYPING
        )


# ── Commandes ────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    user = update.effective_user
    first = user.first_name if user else ""
    await update.message.reply_text(
        f"Salut {first} 👋 Je suis ton agent d'études.\n"
        "Envoie-moi un message, un vocal ou un fichier. Tape /help pour les commandes."
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def cmd_tools(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    registry = context.bot_data["registry"]
    labels = {
        "gmail": "📧 Gmail",
        "icloud_mail": "🍎 iCloud Mail",
        "calendar": "🗓️ Google Agenda",
        "notion": "📘 Notion",
        "spotify": "🎧 Spotify",
        "perplexity": "🔎 Perplexity",
        "weather": "🌤️ Météo",
        "contacts": "👤 Contacts",
    }
    if not registry.names:
        text = "Aucune intégration active. Renseigne le .env puis redémarre."
    else:
        text = "Intégrations actives :\n" + "\n".join(
            "• " + labels.get(n, n) for n in registry.names
        )
    await update.message.reply_text(text)



async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    user_id = update.effective_user.id
    agent: Agent = context.bot_data["agent"]
    agent.reset(user_id)
    await update.message.reply_text("Mémoire effacée. On repart de zéro ✅")


async def cmd_translate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    agent: Agent = context.bot_data["agent"]
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage : /traduire <texte> [FR|EN|ES]\nExemple : /traduire hello world FR"
        )
        return
    target = "FR"
    if args and args[-1].upper() in {"FR", "EN", "ES", "DE", "IT", "PT"}:
        target = args.pop().upper()
    text = " ".join(args)
    try:
        result = agent.translate(text, target_lang=target)
    except RuntimeError as exc:
        await update.message.reply_text(str(exc))
        return
    await update.message.reply_text(f"*{target}* : {escape_markdown(result)}", parse_mode="Markdown")


# ── Messages ─────────────────────────────────────────────────────────
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    agent: Agent = context.bot_data["agent"]
    user_id = update.effective_user.id
    text = update.message.text
    await _typing(update, context)
    try:
        reply = await agent.reply_to_text(user_id, text)
    except Exception:
        logger.exception("Erreur lors du traitement du texte")
        await update.message.reply_text("❌ Oups, une erreur est survenue. Réessaie.")
        return
    for chunk in _split_long(reply):
        await update.message.reply_text(chunk)


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    agent: Agent = context.bot_data["agent"]
    user_id = update.effective_user.id
    voice = update.message.voice
    await _typing(update, context)
    try:
        file = await context.bot.get_file(voice.file_id)
        audio_data, mime_type = await media.ensure_audio_for_gemini(context.application, file)
        transcript, reply = await agent.handle_voice(user_id, audio_data, mime_type)
    except Exception:
        logger.exception("Erreur lors du traitement du vocal")
        await update.message.reply_text("❌ Impossible de traiter ce vocal. Réessaie.")
        return
    for chunk in _split_long(reply):
        await update.message.reply_text(chunk)


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    agent: Agent = context.bot_data["agent"]
    user_id = update.effective_user.id

    file_obj = update.message.document or (
        update.message.photo[-1] if update.message.photo else None
    )
    if file_obj is None:
        return
    if update.message.photo:
        suffix = ".jpg"
    else:
        filename = getattr(file_obj, "file_name", None) or "fichier"
        suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ".bin"
    if media.file_kind(suffix) == "unsupported":
        await update.message.reply_text(
            f"Format « {suffix} » non supporté pour l'instant. "
            "Formats acceptés : " + ", ".join(sorted(media.TEXT_SUFFIXES | media.BINARY_UPLOAD_SUFFIXES))
        )
        return

    await _typing(update, context)
    path = None
    try:
        file = await context.bot.get_file(file_obj.file_id)
        path = await media.download_to_temp(context.application, file)
        summary = await agent.handle_document(user_id, str(path), filename)
    except Exception:
        logger.exception("Erreur lors du traitement du fichier")
        await update.message.reply_text("❌ Impossible de traiter ce fichier.")
        return
    finally:
        if path is not None:
            try:
                media.async_cleanup(path)
            except Exception:
                pass
    for chunk in _split_long(summary):
        await update.message.reply_text(chunk)


# ── Erreurs ──────────────────────────────────────────────────────────
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception non gérée : %s", context.error, exc_info=context.error)
