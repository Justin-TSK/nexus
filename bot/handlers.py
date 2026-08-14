import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.helpers import escape_markdown
from telegram.ext import ContextTypes

from config import settings
from core.agent import Agent, PendingConfirmation
from services import media
from services.proactive import build_digest_text
from tools.registry import BaseTool

logger = logging.getLogger(__name__)

# Anti-double traitement : garde-mémoire des updates déjà vues (redélivraison réseau)
# et des derniers /start par utilisateur (double envoi du bouton Start par le client).
_seen_updates: dict[int, float] = {}
_last_start: dict[int, tuple[float, int]] = {}  # user_id -> (timestamp, message_id du menu)
_START_WINDOW = 30.0


def _seen(update: Update) -> bool:
    """Retourne True si cette update a déjà été traitée (et l'enregistre sinon)."""
    now = time.monotonic()
    for key, ts in list(_seen_updates.items()):
        if now - ts > 60:
            _seen_updates.pop(key, None)
    uid = update.update_id
    if uid in _seen_updates:
        return True
    _seen_updates[uid] = now
    return False

HELP_TEXT = (
    "🤖 *Mon agent IA — aide*\n\n"
    "Je suis ton assistant d'études. Voici ce que je sais faire :\n\n"
    "📝 *Texte* : discute avec moi, pose tes questions de cours, demande des explications.\n"
    "🎤 *Vocal* : envoie-moi un message vocal, je le transcris puis je te réponds.\n"
    "📄 *Fichiers* : envoie un PDF, une image, un fichier de code (py, txt, md, js…) :\n"
    "je le lis et je t'en fais un résumé ou de l'aide.\n\n"
    "⚙️ *Commandes*\n"
    "• /traduire <texte> [FR|EN|ES] — traduction via DeepL\n"
    "• /digest — point du jour (météo, agenda, mails)\n"
    "• /tools — liste les intégrations actives (Gmail, Notion, Spotify…)\n"
    "• /reset — efface la mémoire de la conversation\n"
    "• /help — cette aide\n"
)



MENU_BUTTONS = [
    [InlineKeyboardButton("📅 Digest du jour", callback_data="menu:digest")],
    [InlineKeyboardButton("🔧 Intégrations", callback_data="menu:tools")],
    [InlineKeyboardButton("🌐 Traduire", callback_data="menu:translate")],
    [InlineKeyboardButton("🧹 Effacer la mémoire", callback_data="menu:reset")],
    [InlineKeyboardButton("❓ Aide", callback_data="menu:help")],
]
MENU_KEYBOARD = InlineKeyboardMarkup(MENU_BUTTONS)


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
    if user is None or user.id not in allowed:
        return False
    if update.effective_chat:
        from services.proactive import save_chat
        save_chat(user.id, update.effective_chat.id)
    return True


def _clean_markdown(text: str) -> str:
    """Nettoie les artefacts markdown du modèle pour un affichage brut propre."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.S)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text, flags=re.S)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^>\s?", "", text, flags=re.M)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1 (\2)", text)
    return text


async def _send(update: Update, text: str) -> None:
    """Nettoie les symboles markdown, découpe et envoie la réponse."""
    for chunk in _split_long(_clean_markdown(text)):
        await update.message.reply_text(chunk)


def _confirmation_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Confirmer", callback_data=f"confirm:{token}"),
                InlineKeyboardButton("❌ Annuler", callback_data=f"cancel:{token}"),
            ]
        ]
    )


def _format_tool_result(result: dict) -> str:
    """Transforme le dict retourné par un outil en texte clair pour l'utilisateur."""
    if result.get("error"):
        return "❌ " + str(result["error"])
    parts = [str(result.get("message") or "✅ Fait.")]
    for key in ("summary", "start", "subject", "link"):
        if key in result:
            parts.append(f"{key} : {result[key]}")
    return "\n".join(parts)


async def _maybe_confirmation(update: Update, reply) -> bool:
    """Si la réponse exige une confirmation, envoie les boutons et renvoie True."""
    if not isinstance(reply, PendingConfirmation):
        return False
    await update.message.reply_text(
        f"⚠️ {reply.details}\n\nConfirmer ?",
        reply_markup=_confirmation_keyboard(reply.token),
    )
    return True


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gère les boutons : confirmation (confirm/cancel) et menu principal (menu:)."""
    query = update.callback_query
    if query is None or not query.data:
        return
    if _seen(update):
        return
    await query.answer()
    if settings.allowed_user_ids and query.from_user.id not in settings.allowed_user_ids:
        return

    action, _, token = query.data.partition(":")
    registry = context.bot_data["registry"]

    if action == "menu":
        await _menu_action(query, context)
        return

    if action == "cancel":
        BaseTool.discard(token)
        await query.edit_message_text("Annulé ✅")
        return

    pending = BaseTool.resolve(token)
    if pending is None:
        await query.edit_message_text("⏳ Cette demande a expiré ou a déjà été traitée.")
        return

    args = dict(pending["args"])
    args["_skip_confirm"] = True
    result = await registry.call(pending["tool"], args, pending["user_id"])
    await query.edit_message_text(_format_tool_result(result))


async def _deny(update: Update) -> None:
    if update.effective_chat:
        await update.effective_chat.send_message(
            "Désolé, ce bot est privé et ne t'est pas accessible."
        )


@asynccontextmanager
async def _typing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maintient l'indicateur « en train d'écrire… » jusqu'à la fin du traitement."""
    chat = update.effective_chat
    if chat is None:
        yield
        return
    stop = asyncio.Event()

    async def _pulse() -> None:
        while not stop.is_set():
            try:
                await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
            except Exception:
                return
            await asyncio.sleep(4)

    task = asyncio.create_task(_pulse())
    try:
        yield
    finally:
        stop.set()
        task.cancel()


# ── Commandes ────────────────────────────────────────────────────────
def _START_TEXT(update: Update) -> str:
    user = update.effective_user
    first = user.first_name if user else ""
    return (
        f"Salut {first} 👋 Je suis ton agent d'études.\n"
        "Choisis une action ci-dessous, ou envoie-moi simplement un message, "
        "un vocal ou un fichier."
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    if _seen(update):
        return
    user_id = update.effective_user.id if update.effective_user else 0
    now = time.monotonic()
    logger.info("cmd_start: user=%s update_id=%s", user_id, update.update_id)
    if user_id in _last_start:
        prev_ts, prev_msg = _last_start[user_id]
        if now - prev_ts < _START_WINDOW:
            # Double envoi du bouton Start : édite le menu existant au lieu d'en envoyer un 2e.
            logger.info("cmd_start: doublon ignoré (%.1fs), édition du menu %s", now - prev_ts, prev_msg)
            try:
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=prev_msg,
                    text=_START_TEXT(update),
                    reply_markup=MENU_KEYBOARD,
                )
            except Exception:
                pass
            return
    user = update.effective_user
    msg = await update.message.reply_text(
        _START_TEXT(update),
        reply_markup=MENU_KEYBOARD,
    )
    _last_start[user_id] = (time.monotonic(), msg.message_id)


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    await update.message.reply_text("Voici le menu :", reply_markup=MENU_KEYBOARD)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


def _tools_text(registry) -> str:
    labels = {
        "gmail": "📧 Gmail",
        "icloud_mail": "🍎 iCloud Mail",
        "calendar": "🗓️ Google Agenda",
        "notion": "📘 Notion",
        "spotify": "🎧 Spotify",
        "perplexity": "🔎 Perplexity",
        "weather": "🌤️ Météo",
        "contacts": "👤 Contacts",
        "translate": "🌐 DeepL",
    }
    if not registry.names:
        return "Aucune intégration active. Renseigne le .env puis redémarre."
    return "Intégrations actives :\n" + "\n".join(
        "• " + labels.get(n, n) for n in registry.names
    )


async def _menu_action(query, context) -> None:
    """Gère les boutons du menu principal (/start, /menu)."""
    sub = query.data.partition(":")[2]
    if sub == "digest":
        await query.edit_message_text("⏳ Génération du digest…")
        try:
            text = await asyncio.to_thread(build_digest_text)
        except Exception:
            logger.exception("Digest depuis le menu")
            text = "❌ Impossible de générer le digest."
        for chunk in _split_long(text):
            await query.edit_message_text(chunk)
    elif sub == "tools":
        await query.edit_message_text(_tools_text(context.bot_data["registry"]))
    elif sub == "translate":
        await query.edit_message_text(
            "🌐 *Traduire*\n\n"
            "Envoie : `/traduire <texte> [langue]`\n"
            "Langues : FR, EN, ES, DE, IT, PT.\n\n"
            "Ex : `/traduire Bonjour comment ça va ? EN`",
            parse_mode="Markdown",
        )
    elif sub == "reset":
        context.bot_data["agent"].reset(query.from_user.id)
        await query.edit_message_text("🧹 Mémoire de la conversation effacée.")
    elif sub == "help":
        await query.edit_message_text(HELP_TEXT, parse_mode="Markdown")


async def cmd_tools(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    await update.message.reply_text(_tools_text(context.bot_data["registry"]))


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    try:
        async with _typing(update, context):
            message = await asyncio.to_thread(build_digest_text)
    except Exception:
        logger.exception("Erreur lors du digest manuel")
        await update.message.reply_text("❌ Impossible de générer le digest.")
        return
    for chunk in _split_long(message):
        await update.message.reply_text(chunk)



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
    if _seen(update):
        return
    message = update.effective_message
    if message is None or not message.text:
        return
    agent: Agent = context.bot_data["agent"]
    user_id = update.effective_user.id
    text = message.text
    try:
        async with _typing(update, context):
            reply = await agent.reply_to_text(user_id, text)
    except Exception:
        logger.exception("Erreur lors du traitement du texte")
        await update.message.reply_text("❌ Oups, une erreur est survenue. Réessaie.")
        return
    if await _maybe_confirmation(update, reply):
        return
    await _send(update, reply)


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    if _seen(update):
        return
    message = update.effective_message
    if message is None or message.voice is None:
        return
    agent: Agent = context.bot_data["agent"]
    user_id = update.effective_user.id
    voice = message.voice
    try:
        async with _typing(update, context):
            file = await context.bot.get_file(voice.file_id)
            audio_data, mime_type = await media.ensure_audio_for_gemini(context.application, file)
            transcript, reply = await agent.handle_voice(user_id, audio_data, mime_type)
    except Exception:
        logger.exception("Erreur lors du traitement du vocal")
        await update.message.reply_text("❌ Impossible de traiter ce vocal. Réessaie.")
        return
    if await _maybe_confirmation(update, reply):
        return
    await _send(update, reply)


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _deny(update)
        return
    if _seen(update):
        return
    message = update.effective_message
    if message is None:
        return
    agent: Agent = context.bot_data["agent"]
    user_id = update.effective_user.id

    file_obj = message.document or (message.photo[-1] if message.photo else None)
    if file_obj is None:
        return
    if message.photo:
        filename = "photo.jpg"
    else:
        filename = getattr(file_obj, "file_name", None) or "fichier"

    path = None
    try:
        async with _typing(update, context):
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
    await _send(update, summary)


# ── Erreurs ──────────────────────────────────────────────────────────
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception non gérée : %s", context.error, exc_info=context.error)
