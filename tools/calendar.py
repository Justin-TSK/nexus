import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build

from config import settings
from services.google_auth import credentials_for
from tools.registry import BaseTool

CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


class _CalendarClient:
    _lock = threading.Lock()
    _instance = None

    @classmethod
    def get(cls):
        with cls._lock:
            if cls._instance is None:
                creds = credentials_for("calendar", CALENDAR_SCOPES)
                cls._instance = build("calendar", "v3", credentials=creds)
            return cls._instance


def _event_summary(ev: dict) -> dict:
    start = ev.get("start", {})
    end = ev.get("end", {})
    return {
        "id": ev.get("id"),
        "summary": ev.get("summary"),
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "all_day": "date" in start,
        "location": ev.get("location"),
        "description": (ev.get("description") or "")[:500],
    }


class CalendarTool(BaseTool):
    name = "calendar"
    description = (
        "Google Agenda de l'utilisateur. Utilise-le pour ses rendez-vous, cours, "
        "examens, rendus de projets, plages de révision : lister les événements à venir "
        "ou créer un événement. À utiliser quand l'utilisateur veut planifier, organiser "
        "son planning, ou savoir ce qu'il a au programme."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "create"],
                "description": "list: événements à venir | create: créer un événement",
            },
            "max": {"type": "integer", "description": "Nombre max d'événements (défaut 10)."},
            "days": {"type": "integer", "description": "Horizon en jours pour list (défaut 7)."},
            "summary": {"type": "string", "description": "Titre de l'événement (create)."},
            "description": {"type": "string", "description": "Détails (create)."},
            "location": {"type": "string", "description": "Lieu (create)."},
            "start": {
                "type": "string",
                "description": "Début : date '2026-01-15' (journée entière) ou '2026-01-15 14:00' (avec heure).",
            },
            "duration_minutes": {"type": "integer", "description": "Durée en minutes (défaut 60)."},
        },
        "required": ["action"],
    }

    def run(self, args: dict, user_id: int) -> dict:
        client = _CalendarClient.get()
        action = args.get("action")
        if action == "list":
            return self._list(client, int(args.get("max") or 10), int(args.get("days") or 7))
        if action == "create":
            if not args.get("_skip_confirm"):
                return self.defer(
                    self.name,
                    args,
                    user_id,
                    f"Ajouter à l'agenda : « {args.get('summary') or '?'} » le {args.get('start') or '?'}.",
                )
            return self._create(client, args)
        return self._err(f"Action inconnue : {action}")

    @staticmethod
    def _list(client, limit: int, days: int) -> dict:
        tz = ZoneInfo(settings.CALENDAR_TIMEZONE)
        now = datetime.now(tz)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=max(1, min(days, 90)))).isoformat()
        result = (
            client.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=max(1, min(limit, 50)),
            )
            .execute()
        )
        events = [_event_summary(ev) for ev in result.get("items", [])]
        return {"count": len(events), "events": events}

    @staticmethod
    def _create(client, args: dict) -> dict:
        summary = (args.get("summary") or "").strip()
        if not summary:
            return {"error": "Un titre (summary) est requis."}
        start_raw = (args.get("start") or "").strip()
        if not start_raw:
            return {"error": "Indique une date de début (start)."}
        tz = settings.CALENDAR_TIMEZONE

        body = {"summary": summary}
        if args.get("description"):
            body["description"] = args["description"]
        if args.get("location"):
            body["location"] = args["location"]

        if len(start_raw) == 10:  # date seule → journée entière
            start_date = start_raw
            end_date = (datetime.fromisoformat(start_date) + timedelta(days=1)).date().isoformat()
            body["start"] = {"date": start_date}
            body["end"] = {"date": end_date}
        else:
            try:
                start_dt = datetime.fromisoformat(start_raw).replace(tzinfo=ZoneInfo(tz))
            except ValueError:
                return {"error": f"Date invalide : {start_raw} (attendu 'AAAA-MM-JJ' ou 'AAAA-MM-JJ HH:MM')."}
            end_dt = start_dt + timedelta(minutes=int(args.get("duration_minutes") or 60))
            body["start"] = {"dateTime": start_dt.isoformat(), "timeZone": tz}
            body["end"] = {"dateTime": end_dt.isoformat(), "timeZone": tz}

        event = client.events().insert(calendarId="primary", body=body).execute()
        return {
            "message": "Événement créé.",
            "summary": event.get("summary"),
            "start": event.get("start", {}).get("dateTime") or event.get("start", {}).get("date"),
            "link": event.get("htmlLink"),
        }
