from services.deepl import DeeplService
from tools.registry import BaseTool

# Codes génériques DeepL encore acceptés mais remplacés par des variantes
# plus précises dans la liste officielle (ex : EN → EN-US, PT → PT-PT).
_LANG_ALIASES = {
    "EN": "EN-US",
    "PT": "PT-PT",
    "ZH": "ZH-HANS",
}

_BASE_LANGS = ["FR", "EN-US", "EN-GB", "DE", "ES", "IT", "PT-PT", "PT-BR", "RU", "JA", "KO", "ZH-HANS", "ZH-HANT", "AR", "TR"]


class TranslateTool(BaseTool):
    """Traduction d'un texte vers une langue cible via DeepL.

    Supporte toutes les langues cibles de DeepL (chargeables dynamiquement via
    l'API) : la liste est récupérée au démarrage et partagée entre instances.
    """

    name = "translate"
    description = (
        "Traduit un texte (phrase, note, message, extrait de documentation) dans "
        "presque n'importe quelle langue avec DeepL (110 langues cibles : "
        "anglais EN-US/EN-GB, russe RU, allemand DE, espagnol ES, italien IT, "
        "japonais JA, coréen KO, chinois ZH-HANS/ZH-HANT, arabe AR, turc TR, etc.). "
        "Utilise cet outil dès que l'utilisateur demande de traduire quelque chose ; "
        "passe dans target_lang le code de la langue cible demandée (ex : « en russe » "
        "→ RU, « en japonais » → JA, « en anglais britannique » → EN-GB)."
    )

    _codes: list[str] | None = None

    def __init__(self, deepl: DeeplService | None = None) -> None:
        self._deepl = deepl or DeeplService()
        self.enabled = self._deepl.available
        if self.enabled and TranslateTool._codes is None:
            try:
                TranslateTool._codes = [
                    lang.code for lang in self._deepl._client.get_target_languages()
                ]
            except Exception:  # noqa: BLE001 — DeepL injoignable : on garde une liste de base
                TranslateTool._codes = list(_BASE_LANGS)

    @classmethod
    def target_codes(cls) -> list[str]:
        return list(cls._codes or _BASE_LANGS)

    @classmethod
    def normalize_target(cls, code: str) -> str | None:
        """Normalise un code utilisateur en code DeepL valide (ou None)."""
        c = code.strip().upper()
        c = _LANG_ALIASES.get(c, c)
        if c in cls.target_codes():
            return c
        return None

    @property
    def parameters(self) -> dict:
        codes = self.target_codes()
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Le texte exact à traduire.",
                },
                "target_lang": {
                    "type": "string",
                    "description": "Code de la langue cible (liste complète des langues DeepL ci-dessous).",
                    "enum": codes,
                },
            },
            "required": ["text", "target_lang"],
        }

    def run(self, args: dict, user_id: int) -> dict:
        text = (args.get("text") or "").strip()
        target = self.normalize_target(args.get("target_lang") or "FR")
        if not text:
            return self._err("Texte vide à traduire.")
        if target is None:
            return self._err(
                f"Code de langue invalide : « {args.get('target_lang')} ». "
                f"Langues supportées (exemples) : EN-US, FR, DE, ES, IT, PT-PT, RU, "
                f"JA, KO, ZH-HANS, AR, TR… ({len(self.target_codes())} au total)."
            )
        if not self._deepl.available:
            return self._err("DeepL n'est pas configuré (DEEPL_API_KEY manquante).")
        result = self._deepl.translate(text, target)
        return {"message": f"Traduction ({target}) :\n{result}"}
