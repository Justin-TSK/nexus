import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    DEEPL_API_KEY: str = os.getenv("DEEPL_API_KEY", "")

    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    TRANSCRIPTION_LANG: str = os.getenv("TRANSCRIPTION_LANG", "fr")

    # Profil de l'utilisateur (injecté dans le prompt pour que le bot le connaisse).
    USER_PROFILE: str = os.getenv("USER_PROFILE", "")

    BOT_MODE: str = os.getenv("BOT_MODE", "polling").lower()
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")
    WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8443"))

    # IDs Telegram autorisés. Vide = aucun filtrage.
    _allowed: str = os.getenv("ALLOWED_USER_IDS", "")

    TEMP_DIR: str = os.getenv("TEMP_DIR", "tmp")
    LOG_DIR: str = os.getenv("LOG_DIR", "logs")
    DATA_DIR: str = os.getenv("DATA_DIR", "data")

    # ── Notion ──────────────────────────────────────────────────────
    NOTION_TOKEN: str = os.getenv("NOTION_TOKEN", "")
    NOTION_DATABASE_ID: str = os.getenv("NOTION_DATABASE_ID", "")
    NOTION_TITLE_PROPERTY: str = os.getenv("NOTION_TITLE_PROPERTY", "Name")
    # Page parente où créer les nouvelles notes (alternative à la base de données)
    NOTION_PARENT_PAGE_ID: str = os.getenv("NOTION_PARENT_PAGE_ID", "")

    # ── Gmail (OAuth Google) ────────────────────────────────────────
    GOOGLE_CLIENT_SECRET_FILE: str = os.getenv(
        "GOOGLE_CLIENT_SECRET_FILE", "credentials/client_secret.json"
    )
    GMAIL_TOKEN_FILE: str = os.getenv("GMAIL_TOKEN_FILE", "credentials/gmail_token.json")

    # ── Google Calendar (OAuth Google) ──────────────────────────────
    CALENDAR_TOKEN_FILE: str = os.getenv("CALENDAR_TOKEN_FILE", "credentials/calendar_token.json")
    CALENDAR_TIMEZONE: str = os.getenv("CALENDAR_TIMEZONE", "Europe/Paris")

    # ── iCloud Mail (IMAP) ──────────────────────────────────────────
    ICLOUD_EMAIL: str = os.getenv("ICLOUD_EMAIL", "")
    ICLOUD_APP_PASSWORD: str = os.getenv("ICLOUD_APP_PASSWORD", "")

    # ── Spotify ─────────────────────────────────────────────────────
    SPOTIFY_CLIENT_ID: str = os.getenv("SPOTIFY_CLIENT_ID", "")
    SPOTIFY_CLIENT_SECRET: str = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    SPOTIFY_REDIRECT_URI: str = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback")
    SPOTIFY_TOKEN_FILE: str = os.getenv("SPOTIFY_TOKEN_FILE", "credentials/spotify_token.json")

    # ── Contacts locaux ─────────────────────────────────────────────
    CONTACTS_FILE: str = os.getenv("CONTACTS_FILE", "data/contacts.json")

    # ── Perplexity (recherche web) ──────────────────────────────────
    PERPLEXITY_API_KEY: str = os.getenv("PERPLEXITY_API_KEY", "")
    PERPLEXITY_MODEL: str = os.getenv("PERPLEXITY_MODEL", "sonar-pro")

    # ── Météo ───────────────────────────────────────────────────────
    WEATHER_LOCATION: str = os.getenv("WEATHER_LOCATION", "Moscow")

    @property
    def allowed_user_ids(self) -> set[int]:
        raw = [part.strip() for part in self._allowed.split(",") if part.strip()]
        try:
            return {int(uid) for uid in raw}
        except ValueError:
            return set()

    def validate(self) -> None:
        missing = []
        if not self.TELEGRAM_BOT_TOKEN:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")
        if missing:
            raise RuntimeError(
                "Variables d'environnement manquantes dans .env : " + ", ".join(missing)
            )


settings = Settings()
