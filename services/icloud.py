import imaplib
import logging
from email.header import decode_header
from email.message import Message
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from io import BytesIO

from config import settings

logger = logging.getLogger(__name__)

IMAP_HOST = "imap.mail.me.com"
IMAP_PORT = 993
MAX_BODY_CHARS = 20_000


class IcloudMailError(RuntimeError):
    pass


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    result = []
    for text, encoding in parts:
        if isinstance(text, bytes):
            text = text.decode(encoding or "utf-8", errors="replace")
        result.append(text)
    return "".join(result)


class IcloudMailClient:
    """Accès iCloud Mail via IMAP (mot de passe d'application)."""

    def __init__(self) -> None:
        if not settings.ICLOUD_EMAIL or not settings.ICLOUD_APP_PASSWORD:
            raise IcloudMailError("iCloud non configuré (ICLOUD_EMAIL / ICLOUD_APP_PASSWORD).")
        self._user = settings.ICLOUD_EMAIL
        self._password = settings.ICLOUD_APP_PASSWORD

    def _connect(self) -> imaplib.IMAP4_SSL:
        try:
            conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
            conn.login(self._user, self._password)
        except imaplib.IMAP4.error as exc:
            raise IcloudMailError(f"Connexion iCloud impossible : {exc}") from exc
        return conn

    def list_inbox(self, criteria: str = "ALL", limit: int = 10) -> list[dict]:
        with self._connect() as conn:
            conn.select("INBOX")
            try:
                status, data = conn.search(None, criteria or "ALL")
            except imaplib.IMAP4.error as exc:
                raise IcloudMailError(f"Recherche iCloud invalide : {exc}") from exc
            seqs = data[0].split()
            if not seqs:
                return []
            seqs = seqs[-max(1, min(limit, 20)):]
            items = []
            for seq in seqs:
                _, msg_data = conn.fetch(seq, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                raw = b""
                for part in msg_data:
                    if isinstance(part, tuple):
                        raw = part[1]
                        break
                parsed = BytesParser().parsebytes(raw)
                date_str = parsed.get("Date")
                try:
                    date = parsedate_to_datetime(date_str).isoformat() if date_str else ""
                except (TypeError, ValueError):
                    date = date_str or ""
                items.append({
                    "id": seq.decode(),
                    "from": _decode(parsed.get("From")),
                    "subject": _decode(parsed.get("Subject")),
                    "date": date,
                })
            return items

    def unread_count(self) -> int:
        with self._connect() as conn:
            conn.select("INBOX")
            _, data = conn.search(None, "UNSEEN")
            return len(data[0].split())

    def read_email(self, seq: str) -> dict:
        with self._connect() as conn:
            conn.select("INBOX")
            status, data = conn.fetch(seq.encode(), "(RFC822)")
            raw = b""
            for part in data:
                if isinstance(part, tuple):
                    raw = part[1]
                    break
            if not raw:
                raise IcloudMailError("Message introuvable.")
            parsed: Message = BytesParser().parsebytes(raw)
            body = self._plain_body(parsed)
            if len(body) > MAX_BODY_CHARS:
                body = body[:MAX_BODY_CHARS] + "\n… [tronqué]"
            return {
                "id": seq,
                "from": _decode(parsed.get("From")),
                "to": _decode(parsed.get("To")),
                "subject": _decode(parsed.get("Subject")),
                "date": parsed.get("Date") or "",
                "body": body,
            }

    def delete_email(self, seq: str) -> dict:
        """Supprime définitivement un message (\\Deleted + expunge, irréversible)."""
        with self._connect() as conn:
            conn.select("INBOX")
            status, _ = conn.store(seq.encode(), "+FLAGS", "\\Deleted")
            if status != "OK":
                raise IcloudMailError("Impossible de marquer le message comme supprimé.")
            conn.expunge()
        return {"id": seq, "deleted": True}

    @staticmethod
    def _plain_body(msg: Message) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    try:
                        return part.get_content()
                    except Exception:  # noqa: BLE001
                        continue
        try:
            return msg.get_content()
        except Exception:  # noqa: BLE001
            return "(contenu non lisible)"
