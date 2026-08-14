import json
import urllib.error
import urllib.request

from config import settings
from tools.registry import BaseTool

PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"


class PerplexityTool(BaseTool):
    name = "perplexity"
    description = (
        "Recherche web approfondie et à jour via Perplexity (avec sources). Utilise-le "
        "pour l'actualité, de la documentation technique, des bugs de code, des concepts "
        "algorithmiques, de la veille technologique, ou toute question qui nécessite une "
        "recherche internet récente et sourcée. Résultats accompagnés de citations."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "La question ou la recherche à effectuer (peut être en français).",
            }
        },
        "required": ["query"],
    }

    @property
    def enabled(self) -> bool:
        return bool(settings.PERPLEXITY_API_KEY)

    def run(self, args: dict, user_id: int) -> dict:
        query = (args.get("query") or "").strip()
        if not query:
            return self._err("Indique une requête de recherche.")

        payload = json.dumps(
            {
                "model": settings.PERPLEXITY_MODEL,
                "messages": [{"role": "user", "content": query}],
                "max_tokens": 2000,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            PERPLEXITY_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {settings.PERPLEXITY_API_KEY}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return self._err(f"Perplexity a répondu {exc.code} : {exc.read().decode('utf-8', 'replace')[:300]}")
        except urllib.error.URLError as exc:
            return self._err(f"Réseau : {exc.reason}")

        try:
            answer = data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError):
            return self._err("Réponse Perplexity inattendue.")

        citations = data.get("citations") or []
        return {"answer": answer, "citations": citations}
