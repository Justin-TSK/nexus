import asyncio
from collections import defaultdict

from services.deepl import DeeplService
from services.gemini import GeminiService
from tools.registry import ToolRegistry

MAX_TURNS = 20          # paires (utilisateur + agent) gardées en mémoire par utilisateur
MAX_TOOL_ROUNDS = 5     # appels d'outils maximum par tour de conversation


class Agent:
    """Orchestrateur : garde le contexte de chaque utilisateur, verrouille les
    messages (anti-flood) et exécute les appels d'outils demandés par Gemini."""

    def __init__(
        self,
        gemini: GeminiService,
        deepl: DeeplService,
        registry: ToolRegistry,
    ) -> None:
        self.gemini = gemini
        self.deepl = deepl
        self.registry = registry
        self._history: dict[int, list[dict]] = defaultdict(list)
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock(self, user_id: int) -> asyncio.Lock:
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    def reset(self, user_id: int) -> None:
        self._history[user_id] = []

    def _remember(self, user_id: int, user_msg: str, agent_reply: str) -> None:
        history = self._history[user_id]
        history.append({"role": "user", "parts": [user_msg]})
        history.append({"role": "model", "parts": [agent_reply]})
        if len(history) > MAX_TURNS * 2:
            del history[: len(history) - MAX_TURNS * 2]

    # ── Boucle de fonction-calling ──────────────────────────────────
    async def _chat_with_tools(self, user_id: int, prompt: str) -> str:
        tools = self.registry.gemini_tool()
        contents = self._history[user_id] + [{"role": "user", "parts": [prompt]}]

        for _ in range(MAX_TOOL_ROUNDS):
            response = await asyncio.to_thread(self.gemini.generate, contents, tools)
            parts = []
            try:
                parts = response.candidates[0].content.parts
            except (IndexError, AttributeError):
                break

            calls = [p.function_call for p in parts if p.function_call]
            if not calls:
                text = "".join(p.text for p in parts if p.text).strip()
                return text or "Je n'ai pas compris, peux-tu reformuler ?"

            model_parts = [p for p in parts if p.function_call]
            user_parts = []
            for c in calls:
                result = await self.registry.call(c.name, c.args or {}, user_id)
                user_parts.append({"function_response": {"name": c.name, "response": result}})

            contents = contents + [
                {"role": "model", "parts": model_parts},
                {"role": "user", "parts": user_parts},
            ]

        return "Trop d'appels d'outils d'affilée, essaie de reformuler."

    # ── Points d'entrée ─────────────────────────────────────────────
    async def reply_to_text(self, user_id: int, text: str) -> str:
        async with self._lock(user_id):
            reply = await self._chat_with_tools(user_id, text)
            self._remember(user_id, text, reply)
            return reply

    async def handle_voice(self, user_id: int, audio_data: bytes, mime_type: str) -> tuple[str, str]:
        """Transcrit le vocal puis répond. Retourne (transcription, réponse)."""
        async with self._lock(user_id):
            transcript = await asyncio.to_thread(
                self.gemini.transcribe_audio, audio_data, mime_type
            )
            reply = await self._chat_with_tools(user_id, transcript)
            self._remember(user_id, transcript, reply)
            return transcript, reply

    async def handle_document(self, user_id: int, file_path: str, filename: str) -> str:
        async with self._lock(user_id):
            summary = await asyncio.to_thread(self.gemini.summarize_file, file_path, filename)
            return summary

    def translate(self, text: str, target_lang: str = "FR") -> str:
        return self.deepl.translate(text, target_lang)
