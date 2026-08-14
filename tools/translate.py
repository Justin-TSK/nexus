from services.deepl import DeeplService
from tools.registry import BaseTool

_LANG_ALIASES = {"EN": "EN-US"}


class TranslateTool(BaseTool):
    """Traduction d'un texte vers une langue cible via DeepL."""

    name = "translate"
    description = (
        "Traduit un texte (phrase, note, message) dans une autre langue avec DeepL. "
        "Utilise cet outil dès que l'utilisateur demande de traduire quelque chose "
        "(ex : « traduis ceci en anglais », « traduis la note en espagnol »). Le texte "
        "à traduire doit être passé dans le paramètre text."
    )
    parameters = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Le texte exact à traduire.",
            },
            "target_lang": {
                "type": "string",
                "description": "Code de la langue cible.",
                "enum": ["FR", "EN", "ES", "DE", "IT", "PT"],
            },
        },
        "required": ["text", "target_lang"],
    }

    def __init__(self, deepl: DeeplService | None = None) -> None:
        self._deepl = deepl or DeeplService()
        self.enabled = self._deepl.available

    def run(self, args: dict, user_id: int) -> dict:
        text = (args.get("text") or "").strip()
        target = (args.get("target_lang") or "FR").upper()
        target = _LANG_ALIASES.get(target, target)
        if not text:
            return self._err("Texte vide à traduire.")
        if not self._deepl.available:
            return self._err("DeepL n'est pas configuré (DEEPL_API_KEY manquante).")
        result = self._deepl.translate(text, target)
        return {"message": f"Traduction ({target}) :\n{result}"}
