import asyncio
import logging
import secrets
import threading
import time
from typing import Any

from google.genai import types

logger = logging.getLogger(__name__)

_TYPE_MAP = {
    "string": types.Type.STRING,
    "integer": types.Type.INTEGER,
    "number": types.Type.NUMBER,
    "boolean": types.Type.BOOLEAN,
    "array": types.Type.ARRAY,
    "object": types.Type.OBJECT,
}


def _to_schema(spec: dict) -> types.Schema:
    """Convertit un schéma JSON simplifié en types.Schema pour Gemini."""
    schema = types.Schema(type=_TYPE_MAP.get(spec.get("type", "string"), types.Type.STRING))
    if spec.get("description"):
        schema.description = spec["description"]
    if spec.get("enum"):
        schema.enum = spec["enum"]
    if spec.get("type") == "array":
        schema.items = _to_schema(spec.get("items", {"type": "string"}))
    if spec.get("properties"):
        schema.properties = {k: _to_schema(v) for k, v in spec["properties"].items()}
        schema.required = spec.get("required")
    return schema


class BaseTool:
    """Une intégration exposée à Gemini (function calling).

    Sous-classes à définir :
      - name            : nom de l'outil (identifiant pour Gemini)
      - description     : description en français de quand/comment l'utiliser
      - parameters      : schéma JSON simplifié des arguments
      - run(args, user_id) : exécution asynchrone, retourne un dict JSON-serialisable
    """

    name: str = ""
    description: str = ""
    parameters: dict = {}

    # Actions en attente de confirmation (token → détails).
    _pending: dict[str, dict] = {}
    _pending_lock = threading.Lock()

    @classmethod
    def defer(cls, tool_name: str, args: dict, user_id: int, details: str) -> dict:
        """Place une action en attente de confirmation et renvoie le jeton."""
        token = secrets.token_urlsafe(10)
        with cls._pending_lock:
            cls._pending[token] = {
                "tool": tool_name,
                "args": dict(args),
                "user_id": user_id,
                "details": details,
                "created": time.monotonic(),
            }
        return {"requires_confirmation": True, "token": token, "details": details}

    @classmethod
    def resolve(cls, token: str) -> dict | None:
        """Récupère (et retire) une action confirmée par son jeton."""
        with cls._pending_lock:
            return cls._pending.pop(token, None)

    @classmethod
    def discard(cls, token: str) -> None:
        with cls._pending_lock:
            cls._pending.pop(token, None)

    @property
    def declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters=_to_schema(self.parameters) if self.parameters else None,
        )

    def run(self, args: dict[str, Any], user_id: int) -> dict[str, Any]:
        """Exécution synchrone (I/O bloquant). Appelée via asyncio.to_thread."""
        raise NotImplementedError

    def _msg(self, **kwargs) -> dict[str, Any]:
        return {"message": kwargs.pop("message", "OK"), **kwargs}

    def _err(self, message: str) -> dict[str, Any]:
        return {"error": message}


class ToolRegistry:
    """Collection des outils disponibles, convertie en déclarations Gemini."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if not tool.name:
            raise ValueError(f"Outil {type(tool).__name__} sans nom")
        self._tools[tool.name] = tool
        logger.info("Outil enregistré : %s", tool.name)

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def declarations(self) -> list[types.FunctionDeclaration]:
        return [tool.declaration for tool in self._tools.values()]

    def gemini_tool(self) -> types.Tool | None:
        if not self._tools:
            return None
        return types.Tool(function_declarations=self.declarations())

    async def call(self, name: str, args: dict[str, Any], user_id: int) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"Outil inconnu : {name}"}
        try:
            action = (args or {}).get("action")
            logger.info("Appel outil %s (action=%s, user=%s)", name, action, user_id)
            return await asyncio.to_thread(tool.run, args or {}, user_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Erreur pendant l'appel à %s", name)
            return {"error": f"Erreur dans {name} : {exc}"}
