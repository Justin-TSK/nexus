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

    def _select(self, conn: imaplib.IMAP4_SSL, folder: str) -> None:
        status, _ = conn.select(folder)
        if status != "OK":
            raise IcloudMailError(f"Dossier « {folder} » introuvable sur iCloud.")

    def list_folders(self) -> list[str]:
        """Liste les dossiers disponibles (INBOX, Junk=spam, Archive, Deleted Messages…)."""
        with self._connect() as conn:
            status, data = conn.list()
            names = []
            for line in data:
                text = line.decode("utf-8", "replace")
                import re
                match = re.search(r'"([^"]*)"\s*$', text)
                if match:
                    names.append(match.group(1))
            return names

    def list_inbox(self, criteria: str = "ALL", limit: int = 10, folder: str = "INBOX") -> list[dict]:
        with self._connect() as conn:
            self._select(conn, folder)
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

    def unread_count(self, folder: str = "INBOX") -> int:
        with self._connect() as conn:
            self._select(conn, folder)
            _, data = conn.search(None, "UNSEEN")
            return len(data[0].split())

    def read_email(self, seq: str, folder: str = "INBOX") -> dict:
        with self._connect() as conn:
            self._select(conn, folder)
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

    def delete_emails(self, seqs: list[str], folder: str = "INBOX") -> dict:
        """Supprime des messages. Essaie d'abord de les déplacer vers la corbeille
        (serveurs qui acceptent COPY) ; sinon (cas d'iCloud, qui rejette COPY/APPEND),
        suppression définitive.
        """
        moved = False
        with self._connect() as conn:
            self._select(conn, folder)
            trash = self._trash_folder(conn)
            if trash:
                try:
                    for seq in seqs:
                        conn.copy(seq.encode(), trash)
                    moved = True
                except imaplib.IMAP4.error:
                    logger.warning(
                        "COPY vers la corbeille refusé par le serveur (%s) — suppression définitive.",
                        trash,
                    )
                    moved = False
            for seq in seqs:
                status, _ = conn.store(seq.encode(), "+FLAGS", "\\Deleted")
                if status != "OK":
                    raise IcloudMailError(f"Impossible de marquer le message {seq} comme supprimé.")
            conn.expunge()
        return {
            "deleted": seqs,
            "count": len(seqs),
            "moved_to_trash": moved,
        }

    @staticmethod
    def _trash_folder(conn: imaplib.IMAP4_SSL) -> str | None:
        """Retourne le nom du dossier corbeille si présent (ex: « Deleted Messages »)."""
        status, data = conn.list()
        if status != "OK":
            return None
        for line in data:
            text = line.decode("utf-8", "replace")
            import re
            match = re.search(r'"([^"]*)"\s*$', text)
            name = match.group(1) if match else ""
            if name.lower() in {"deleted messages", "trash", "corbeille", "messages supprimés"}:
                return name
        return None

    def delete_email(self, seq: str) -> dict:
        """Déplace un message vers la corbeille (récupérable)."""
        return self.delete_emails([seq])

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
