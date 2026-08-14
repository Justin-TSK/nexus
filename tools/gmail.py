import base64
import threading
from email.message import EmailMessage

from googleapiclient.discovery import build

from services.google_auth import GMAIL_SCOPES, credentials_for
from tools.registry import BaseTool

MAX_BODY_CHARS = 20_000


class _GmailClient:
    """Service Gmail paresseux et partagé entre appels."""

    _lock = threading.Lock()
    _instance = None

    @classmethod
    def get(cls):
        with cls._lock:
            if cls._instance is None:
                creds = credentials_for("gmail", GMAIL_SCOPES)
                cls._instance = build("gmail", "v1", credentials=creds)
            return cls._instance


def _header(msg: dict, name: str) -> str:
    for h in msg.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _extract_body(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "replace")
    parts = payload.get("parts") or []
    for part in parts:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", "replace")
    # dernier recours : tout premier texte trouvé
    for part in parts:
        if part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", "replace")
    return "(contenu non textuel : image, PDF, …)"


class GmailTool(BaseTool):
    name = "gmail"
    description = (
        "Boîte mail Gmail de l'utilisateur. Utilise-le quand il parle de mails, courriels, "
        "boîte de réception, messages non lus, ou pour trier, résumer et rédiger des "
        "e-mails administratifs ou professionnels (stages, profs, université). Peut lister, "
        "chercher, lire ou envoyer un mail Gmail."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "search", "read", "send"],
                "description": "list: messages récents | search: recherche par requête Gmail | read: lire un message | send: envoyer un mail",
            },
            "query": {
                "type": "string",
                "description": "Requête Gmail (ex: 'is:unread', 'from:prof@univ.fr', 'sujet examen'). Requise pour search et optionnelle pour list.",
            },
            "message_id": {
                "type": "string",
                "description": "ID du message à lire (retourné par list/search).",
            },
            "max": {"type": "integer", "description": "Nombre maximum de résultats (défaut 5, max 20)."},
            "to": {"type": "string", "description": "Destinataire pour send."},
            "subject": {"type": "string", "description": "Objet du mail pour send."},
            "body": {"type": "string", "description": "Corps du mail pour send."},
        },
        "required": ["action"],
    }

    def run(self, args: dict, user_id: int) -> dict:
        action = args.get("action")
        client = _GmailClient.get()
        if action == "list":
            return self._list(client, args.get("query") or "", int(args.get("max") or 5))
        if action == "search":
            return self._list(client, args.get("query") or "in:anywhere", int(args.get("max") or 5))
        if action == "read":
            return self._read(client, args.get("message_id") or "")
        if action == "send":
            return self._send(client, args.get("to"), args.get("subject"), args.get("body"))
        return self._err(f"Action inconnue : {action}")

    @staticmethod
    def _list(client, query: str, limit: int) -> dict:
        limit = max(1, min(limit, 20))
        result = client.users().messages().list(userId="me", q=query, maxResults=limit).execute()
        messages = result.get("messages") or []
        items = []
        for m in messages:
            full = client.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            items.append({
                "id": full["id"],
                "from": _header(full, "From"),
                "subject": _header(full, "Subject"),
                "date": _header(full, "Date"),
                "snippet": full.get("snippet", ""),
            })
        return {"count": len(items), "query": query, "messages": items}

    @staticmethod
    def _read(client, message_id: str) -> dict:
        if not message_id:
            return {"error": "message_id manquant."}
        full = client.users().messages().get(userId="me", id=message_id, format="full").execute()
        body = _extract_body(full.get("payload", {}))
        if len(body) > MAX_BODY_CHARS:
            body = body[:MAX_BODY_CHARS] + "\n… [tronqué]"
        return {
            "id": full["id"],
            "from": _header(full, "From"),
            "to": _header(full, "To"),
            "subject": _header(full, "Subject"),
            "date": _header(full, "Date"),
            "body": body,
        }

    @staticmethod
    def _send(client, to: str, subject: str, body: str) -> dict:
        if not to or not subject:
            return {"error": "Il faut au minimum 'to' et 'subject' pour envoyer un mail."}
        message = EmailMessage()
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body or "")
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        sent = client.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"message": "Mail envoyé.", "id": sent.get("id")}
