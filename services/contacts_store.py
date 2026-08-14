import json
import threading
from pathlib import Path

from config import settings


class ContactsStore:
    """Contacts locaux persistés dans un fichier JSON (thread-safe)."""

    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or settings.CONTACTS_FILE)
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write([])

    def _read(self) -> list[dict]:
        with self._lock:
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, FileNotFoundError):
                return []

    def _write(self, data: list[dict]) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def all(self) -> list[dict]:
        return self._read()

    def search(self, query: str) -> list[dict]:
        q = query.lower().strip()
        return [
            c
            for c in self._read()
            if q in c.get("name", "").lower()
            or q in (c.get("phone") or "").lower()
            or q in (c.get("email") or "").lower()
        ]

    def add(self, name: str, phone: str = "", email: str = "", notes: str = "") -> dict:
        data = self._read()
        entry = {
            "id": max((c.get("id", 0) for c in data), default=0) + 1,
            "name": name,
            "phone": phone or "",
            "email": email or "",
            "notes": notes or "",
        }
        data.append(entry)
        self._write(data)
        return entry
