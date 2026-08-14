#!/usr/bin/env python3
"""Diagnostic de configuration : vérifie quelles intégrations sont prêtes.

Usage : python scripts/check_config.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402


def status(label: str, ok: bool, detail: str = "") -> None:
    mark = "✅" if ok else "❌"
    print(f"{mark} {label}" + (f" — {detail}" if detail else ""))


def main() -> None:
    print("═" * 50)
    print("DIAGNOSTIC NEXUS")
    print("═" * 50)

    print("\n── Cœur du bot ──")
    status("Token Telegram", bool(settings.TELEGRAM_BOT_TOKEN))
    status("Clé Gemini", bool(settings.GEMINI_API_KEY))
    status("DeepL", bool(settings.DEEPL_API_KEY))
    if settings.allowed_user_ids:
        status("Accès restreint à", True, f"IDs {sorted(settings.allowed_user_ids)}")
    else:
        status("Accès restreint à", False, "ALLOWED_USER_IDS vide (tout le monde)")

    from services.media import ffmpeg_available
    status("ffmpeg (vocaux)", ffmpeg_available(), "convertit les messages vocaux")
    if not ffmpeg_available():
        print("  → Installer : macOS `brew install ffmpeg` | Debian/Ubuntu `sudo apt install ffmpeg`")

    print("\n── Google (Gmail + Agenda) ──")
    secret = Path(settings.GOOGLE_CLIENT_SECRET_FILE)
    gmail_token = Path(settings.GMAIL_TOKEN_FILE)
    cal_token = Path(settings.CALENDAR_TOKEN_FILE)
    status("client_secret.json présent", secret.exists(), str(secret))
    status("Gmail autorisé (token)", gmail_token.exists())
    status("Agenda autorisé (token)", cal_token.exists())
    if not secret.exists():
        print("  → À créer sur Google Cloud Console (API Gmail + Agenda) puis lancer :")
        print("    python scripts/auth_setup.py google calendar")

    print("\n── iCloud Mail ──")
    status("ICLOUD_EMAIL + mot de passe applicatif", bool(settings.ICLOUD_EMAIL and settings.ICLOUD_APP_PASSWORD))

    print("\n── Notion ──")
    status("Token Notion", bool(settings.NOTION_TOKEN))
    status(
        "Zone de notes",
        bool(settings.NOTION_DATABASE_ID or settings.NOTION_PARENT_PAGE_ID),
        f"database={settings.NOTION_DATABASE_ID or '—'} / page={settings.NOTION_PARENT_PAGE_ID or '—'}",
    )

    print("\n── Spotify ──")
    status("Client ID + Secret", bool(settings.SPOTIFY_CLIENT_ID and settings.SPOTIFY_CLIENT_SECRET))
    spotify_token = Path(settings.SPOTIFY_TOKEN_FILE)
    status("Spotify autorisé (token)", spotify_token.exists())
    if not spotify_token.exists() and settings.SPOTIFY_CLIENT_ID:
        print("  → Lance : python scripts/auth_setup.py spotify")

    print("\n── Perplexity ──")
    status("PERPLEXITY_API_KEY", bool(settings.PERPLEXITY_API_KEY))

    print("\n── Météo ──")
    status("Ville par défaut", bool(settings.WEATHER_LOCATION), f"{settings.WEATHER_LOCATION} (wttr.in, sans clé)")

    print("\n── Contacts locaux ──")
    status("Fichier contacts", Path(settings.CONTACTS_FILE).exists(), settings.CONTACTS_FILE)

    print("\n" + "═" * 50)


if __name__ == "__main__":
    main()
