#!/usr/bin/env python3
"""Authentification interactive : Google (Gmail) et Spotify.

Usage :
    python scripts/auth_setup.py            # tout
    python scripts/auth_setup.py google     # seulement Google/Gmail
    python scripts/auth_setup.py calendar   # seulement Google Agenda
    python scripts/auth_setup.py spotify    # seulement Spotify
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402


def setup_google() -> None:
    from services.google_auth import GMAIL_SCOPES, credentials_for

    try:
        credentials_for("gmail", GMAIL_SCOPES)
    except RuntimeError as exc:
        print(f"✗ {exc}")
        print("→ Crée un projet dans Google Cloud Console, active l'API Gmail,")
        print("  télécharge le fichier client_secret.json et place-le dans credentials/.")
        return
    print(f"✓ Google autorisé — token : {settings.GMAIL_TOKEN_FILE}")


def setup_calendar() -> None:
    from services.google_auth import credentials_for
    from tools.calendar import CALENDAR_SCOPES

    try:
        credentials_for("calendar", CALENDAR_SCOPES)
    except RuntimeError as exc:
        print(f"✗ {exc}")
        return
    print(f"✓ Google Agenda autorisé — token : {settings.CALENDAR_TOKEN_FILE}")


def setup_spotify() -> None:
    if not settings.SPOTIFY_CLIENT_ID or not settings.SPOTIFY_CLIENT_SECRET:
        print("✗ SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET manquants dans .env")
        return
    from tools.spotify import _SpotifyClient

    sp = _SpotifyClient.get()
    user = sp.current_user()
    print(f"✓ Spotify connecté — {user.get('display_name')} ({user.get('email')})")


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "google", "gmail"):
        setup_google()
    if which in ("all", "calendar"):
        setup_calendar()
    if which in ("all", "spotify"):
        setup_spotify()


if __name__ == "__main__":
    main()
