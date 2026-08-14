import deepl

from config import settings


class DeeplService:
    """Traduction via DeepL. Désactivée si DEEPL_API_KEY n'est pas renseignée."""

    def __init__(self) -> None:
        self._client = None
        if settings.DEEPL_API_KEY:
            self._client = deepl.Translator(settings.DEEPL_API_KEY)

    @property
    def available(self) -> bool:
        return self._client is not None

    def translate(self, text: str, target_lang: str = "FR") -> str:
        if not self.available:
            raise RuntimeError("DeepL n'est pas configuré (DEEPL_API_KEY manquante).")
        result = self._client.translate_text(text, target_lang=target_lang)
        return result.text
