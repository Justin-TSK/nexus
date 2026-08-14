import json
import threading
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from config import settings

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

_lock = threading.Lock()
_cache: dict[str, Credentials] = {}


def _token_path(kind: str) -> Path:
    if kind == "gmail":
        return Path(settings.GMAIL_TOKEN_FILE)
    if kind == "calendar":
        return Path(settings.CALENDAR_TOKEN_FILE)
    return Path(f"credentials/{kind}_token.json")


def credentials_for(kind: str, scopes: list[str]) -> Credentials:
    """Retourne des credentials Google valides (auto-refresh + premier flow interactif).

    kind : 'gmail' pour la boîte mail.
    """
    with _lock:
        cached = _cache.get(kind)
        if cached and cached.valid:
            return cached

        path = _token_path(kind)
        creds = None
        dirty = False
        if path.exists():
            creds = Credentials.from_authorized_user_file(path, scopes)

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            dirty = True

        if not creds or not creds.valid:
            secret = Path(settings.GOOGLE_CLIENT_SECRET_FILE)
            if not secret.exists():
                raise RuntimeError(
                    "Fichier OAuth Google introuvable : "
                    f"{secret}\n→ Lance d'abord : python scripts/auth_setup.py"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(secret), scopes)
            creds = flow.run_local_server(port=0, prompt="consent")
            dirty = True

        if dirty:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(creds.to_json())
        _cache[kind] = creds
        return creds
