import asyncio
from dataclasses import dataclass

from services.deepl import DeeplService
from services.gemini import GeminiService
from services.store import Store
from tools.registry import ToolRegistry

MAX_TURNS = 20          # paires (utilisateur + agent) gardées en mémoire par utilisateur
MAX_TOOL_ROUNDS = 5     # appels d'outils maximum par tour de conversation


@dataclass
class PendingConfirmation:
    """Action différée en attente d'un « oui » explicite de l'utilisateur."""

    token: str
    details: str


class Agent:
    """Orchestrateur : garde le contexte de chaque utilisateur (persisté dans SQLite),
    verrouille les messages (anti-flood) et exécute les appels d'outils demandés par Gemini."""

    def __init__(
        self,
        gemini: GeminiService,
        deepl: DeeplService,
        registry: ToolRegistry,
    ) -> None:
        self.gemini = gemini
        self.deepl = deepl
        self.registry = registry
        self.store = Store.get()
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock(self, user_id: int) -> asyncio.Lock:
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    def reset(self, user_id: int) -> None:
        self.store.clear_history(user_id)

    def _remember(self, user_id: int, user_msg: str, agent_reply: str) -> None:
        self.store.append_history(user_id, "user", user_msg)
        self.store.append_history(user_id, "model", agent_reply)

    # ── Boucle de fonction-calling ──────────────────────────────────
    async def _chat_with_tools(self, user_id: int, prompt: str) -> str:
        tools = self.registry.gemini_tool()
        contents = self.store.load_history(user_id, MAX_TURNS) + [{"role": "user", "parts": [prompt]}]

        for _ in range(MAX_TOOL_ROUNDS):
            response = await asyncio.to_thread(self.gemini.generate, contents, tools)
            try:
                content = response.candidates[0].content
            except (IndexError, AttributeError):
                break
            if content is None:
                break
            parts = content.parts or []

            calls = [p.function_call for p in parts if p.function_call]
            if not calls:
                text = "".join(p.text for p in parts if p.text).strip()
                return text or "Je n'ai pas compris, peux-tu reformuler ?"

            model_parts = [p for p in parts if p.function_call]
            user_parts = []
            for c in calls:
                result = await self.registry.call(c.name, c.args or {}, user_id)
                if result.get("requires_confirmation"):
                    return PendingConfirmation(
                        token=result["token"], details=result.get("details", "Confirmer cette action ?")
                    )
                user_parts.append({"function_response": {"name": c.name, "response": result}})

            contents = contents + [
                {"role": "model", "parts": model_parts},
                {"role": "user", "parts": user_parts},
            ]

        return "Trop d'appels d'outils d'affilée, essaie de reformuler."

    # ── Points d'entrée ─────────────────────────────────────────────
    async def reply_to_text(self, user_id: int, text: str) -> str | PendingConfirmation:
        async with self._lock(user_id):
            reply = await self._chat_with_tools(user_id, text)
            if isinstance(reply, str):
                self._remember(user_id, text, reply)
            return reply

    async def handle_voice(self, user_id: int, audio_data: bytes, mime_type: str) -> tuple[str, str | PendingConfirmation]:
        """Transcrit le vocal puis répond. Retourne (transcription, réponse)."""
        async with self._lock(user_id):
            transcript = await asyncio.to_thread(
                self.gemini.transcribe_audio, audio_data, mime_type
            )
            reply = await self._chat_with_tools(user_id, transcript)
            if isinstance(reply, str):
                self._remember(user_id, transcript, reply)
            return transcript, reply

    async def handle_document(self, user_id: int, file_path: str, filename: str) -> str:
        async with self._lock(user_id):
            summary = await asyncio.to_thread(self.gemini.summarize_file, file_path, filename)
            return summary

    def translate(self, text: str, target_lang: str = "FR") -> str:
        return self.deepl.translate(text, target_lang)
