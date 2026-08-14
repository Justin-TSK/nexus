import json
import sqlite3
import threading
from pathlib import Path

from config import settings


class Store:
    """Persistance locale (SQLite) : historique de conversation + paires clé/valeur."""

    _lock = threading.Lock()
    _instance = None

    @classmethod
    def get(cls) -> "Store":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        db = Path(settings.DATA_DIR) / "nexus.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._db_lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._db_lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    ts TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS kv (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    # ── Historique de conversation ───────────────────────────────
    def load_history(self, user_id: int, max_turns: int = 20) -> list[dict]:
        with self._db_lock:
            rows = self._conn.execute(
                "SELECT role, content FROM history WHERE user_id=? "
                "ORDER BY id DESC LIMIT ?",
                (user_id, max_turns * 2),
            ).fetchall()
        items = []
        for row in reversed(rows):
            try:
                content = json.loads(row["content"])
            except (json.JSONDecodeError, TypeError):
                content = str(row["content"])
            items.append({"role": row["role"], "parts": [content]})
        return items

    def append_history(self, user_id: int, role: str, content: str) -> None:
        with self._db_lock, self._conn:
            self._conn.execute(
                "INSERT INTO history (user_id, role, content) VALUES (?,?,?)",
                (user_id, role, json.dumps(content)),
            )

    def clear_history(self, user_id: int) -> None:
        with self._db_lock, self._conn:
            self._conn.execute("DELETE FROM history WHERE user_id=?", (user_id,))

    # ── Clé/valeur (chat_id, rappels déjà notifiés, …) ────────────
    def get_kv(self, key: str, default=None):
        with self._db_lock:
            row = self._conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]

    def set_kv(self, key: str, value) -> None:
        with self._db_lock, self._conn:
            self._conn.execute(
                "INSERT INTO kv (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )
