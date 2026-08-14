import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import settings
from services.store import Store
from tools.calendar import _CalendarClient
from tools.gmail import GmailTool
from tools.weather import WeatherTool

logger = logging.getLogger(__name__)

DIGEST_HOUR = 8
REMINDER_WINDOW_MIN = 30
CHECK_INTERVAL_SEC = 300


def save_chat(user_id: int, chat_id: int) -> None:
    """Mémorise le chat Telegram de l'utilisateur pour les messages proactifs."""
    Store.get().set_kv(f"chat:{user_id}", chat_id)


def _chat_ids() -> list[int]:
    store = Store.get()
    return [
        chat
        for uid in settings.allowed_user_ids
        if (chat := store.get_kv(f"chat:{uid}")) is not None
    ]


# ── Digest matinal ────────────────────────────────────────────────
def build_digest_text() -> str:
    tz = ZoneInfo(settings.CALENDAR_TIMEZONE)
    now = datetime.now(tz)
    lines = [f"Bonjour Justin, ton point du {now.strftime('%A %d %B')} :", ""]

    try:
        weather = WeatherTool().run({}, 0)
        cur = weather.get("current", {})
        lines.append(f"🌤 Météo : {cur.get('temp_c')} °C, {cur.get('description')}")
    except Exception:
        logger.exception("Digest — météo")
        lines.append("🌤 Météo indisponible.")
    lines.append("")

    try:
        client = _CalendarClient.get()
        time_max = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
        result = (
            client.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=15,
            )
            .execute()
        )
        events = result.get("items", [])
        if events:
            lines.append("📅 Aujourd'hui :")
            for ev in events:
                start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date", "")
                hour = ""
                if "T" in str(start):
                    try:
                        hour = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(tz).strftime("%H:%M") + " — "
                    except ValueError:
                        pass
                lines.append(f"• {hour}{ev.get('summary', 'Sans titre')}")
        else:
            lines.append("📅 Rien de prévu aujourd'hui.")
    except Exception:
        logger.exception("Digest — agenda")
        lines.append("📅 Agenda indisponible.")
    lines.append("")

    try:
        gmail = GmailTool().run({"action": "search", "query": "is:unread", "max": 3}, 0)
        msgs = gmail.get("messages", [])
        if msgs:
            lines.append("📬 Non lus (Gmail) :")
            for m in msgs:
                lines.append(f"• {m.get('from', '')} : {m.get('subject', '')}")
        else:
            lines.append("📬 Aucun email non lu sur Gmail.")
    except Exception:
        logger.exception("Digest — gmail")
        lines.append("📬 Emails indisponibles.")

    return "\n".join(lines)


async def send_digest(app) -> None:
    message = build_digest_text()
    for chat in _chat_ids():
        try:
            await app.bot.send_message(chat_id=chat, text=message)
        except Exception:
            logger.exception("Digest — envoi impossible (chat %s)", chat)


# ── Rappels agenda ─────────────────────────────────────────────────
async def check_reminders(app) -> None:
    """Vérifie régulièrement l'agenda et signale les événements imminents.
    Met aussi à jour le heartbeat utilisé par le healthcheck."""
    Store.get().set_kv("heartbeat", time.time())
    tz = ZoneInfo(settings.CALENDAR_TIMEZONE)
    now = datetime.now(tz)
    horizon = now + timedelta(minutes=REMINDER_WINDOW_MIN)
    store = Store.get()
    try:
        client = _CalendarClient.get()
        result = (
            client.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=horizon.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=10,
            )
            .execute()
        )
    except Exception:
        logger.exception("Rappels — lecture agenda")
        return

    for uid in settings.allowed_user_ids:
        chat = store.get_kv(f"chat:{uid}")
        if not chat:
            continue
        notified = set(store.get_kv(f"notified:{uid}", []))
        changed = False
        for ev in result.get("items", []):
            ev_id = ev.get("id")
            start = ev.get("start", {}).get("dateTime")
            if not start or "T" not in start:
                continue
            try:
                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(tz)
            except ValueError:
                continue
            delta_min = (start_dt - now).total_seconds() / 60
            if 0 <= delta_min <= REMINDER_WINDOW_MIN and ev_id not in notified:
                try:
                    await app.bot.send_message(
                        chat_id=chat,
                        text=f"⏰ Rappel : {ev.get('summary', 'Événement')} à {start_dt.strftime('%H:%M')}.",
                    )
                except Exception:
                    logger.exception("Rappel — envoi impossible")
                notified.add(ev_id)
                changed = True
        if changed:
            store.set_kv(f"notified:{uid}", sorted(notified))
