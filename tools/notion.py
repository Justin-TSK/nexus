import threading

from notion_client import Client

from config import settings
from tools.registry import BaseTool


class _NotionClient:
    _lock = threading.Lock()
    _instance = None

    @classmethod
    def get(cls) -> Client:
        with cls._lock:
            if cls._instance is None:
                cls._instance = Client(auth=settings.NOTION_TOKEN)
            return cls._instance


def _paragraphs(content: str) -> list[dict]:
    return [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": line}}]},
        }
        for line in (content or "").splitlines()
        if line.strip()
    ]


class NotionTool(BaseTool):
    name = "notion"
    description = (
        "Base de notes Notion de l'utilisateur (cours, idées, tâches). Utilise-le pour "
        "créer une note, chercher dans Notion, lister les notes, ou ajouter du contenu à "
        "une note existante."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_note", "search", "list_notes", "append"],
                "description": "create_note: créer une note | search: chercher partout dans Notion | list_notes: lister les notes de la base | append: ajouter du texte à une page",
            },
            "title": {"type": "string", "description": "Titre de la note (create_note)."},
            "content": {"type": "string", "description": "Contenu de la note (create_note, append)."},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags pour la note (create_note, optionnel).",
            },
            "query": {"type": "string", "description": "Texte à chercher (search)."},
            "limit": {"type": "integer", "description": "Nombre max de résultats (défaut 5)."},
            "page_id": {"type": "string", "description": "ID de la page cible (append)."},
        },
        "required": ["action"],
    }

    @property
    def enabled(self) -> bool:
        return bool(settings.NOTION_TOKEN)

    def run(self, args: dict, user_id: int) -> dict:
        client = _NotionClient.get()
        action = args.get("action")
        if action == "create_note":
            return self._create_note(client, args)
        if action == "search":
            return self._search(client, args.get("query") or "", int(args.get("limit") or 5))
        if action == "list_notes":
            return self._list_notes(client, int(args.get("limit") or 5))
        if action == "append":
            return self._append(client, args.get("page_id") or "", args.get("content") or "")
        return self._err(f"Action inconnue : {action}")

    def _create_note(self, client: Client, args: dict) -> dict:
        title = (args.get("title") or "").strip()
        if not title:
            return {"error": "Un titre est requis pour créer une note."}
        children = _paragraphs(args.get("content") or "")

        if settings.NOTION_DATABASE_ID:
            page = client.pages.create(
                parent={"database_id": settings.NOTION_DATABASE_ID},
                properties={
                    settings.NOTION_TITLE_PROPERTY: {
                        "title": [{"type": "text", "text": {"content": title}}]
                    }
                },
                children=children,
            )
        elif settings.NOTION_PARENT_PAGE_ID:
            page = client.pages.create(
                parent={"page_id": settings.NOTION_PARENT_PAGE_ID},
                properties={
                    "title": {"title": [{"type": "text", "text": {"content": title}}]}
                },
                children=children,
            )
        else:
            return {
                "error": "Ni NOTION_DATABASE_ID ni NOTION_PARENT_PAGE_ID configuré "
                "pour créer des notes. Renseigne l'un des deux dans .env."
            }
        return {"message": "Note créée.", "title": title, "page_id": page["id"], "url": page.get("url")}

    @staticmethod
    def _search(client: Client, query: str, limit: int) -> dict:
        result = client.search(query=query, page_size=limit)
        items = [
            {
                "id": r["id"],
                "title": "".join(
                    t.get("plain_text", "")
                    for t in r.get("properties", {}).get("title", {}).get("title", [])
                )
                if r.get("properties")
                else r.get("title", [])[0].get("plain_text", "") if r.get("title") else "",
                "url": r.get("url"),
                "last_edited": r.get("last_edited_time"),
            }
            for r in result.get("results", [])
        ]
        return {"count": len(items), "results": items}

    @staticmethod
    def _list_notes(client: Client, limit: int) -> dict:
        limit = max(1, min(limit, 50))
        items = []

        if settings.NOTION_DATABASE_ID:
            result = client.databases.query(
                database_id=settings.NOTION_DATABASE_ID,
                page_size=limit,
            )
            for r in result.get("results", []):
                title = "".join(
                    t.get("plain_text", "")
                    for t in r.get("properties", {})
                    .get(settings.NOTION_TITLE_PROPERTY, {})
                    .get("title", [])
                )
                items.append({"id": r["id"], "title": title, "url": r.get("url"), "last_edited": r.get("last_edited_time")})

        elif settings.NOTION_PARENT_PAGE_ID:
            result = client.blocks.children.list(
                block_id=settings.NOTION_PARENT_PAGE_ID,
                page_size=limit,
            )
            for b in result.get("results", []):
                if b.get("type") == "child_page":
                    items.append({
                        "id": b["id"],
                        "title": b.get("child_page", {}).get("title", ""),
                        "url": None,
                    })

        else:
            return {
                "error": "Ni NOTION_DATABASE_ID ni NOTION_PARENT_PAGE_ID configuré. "
                "Renseigne l'un des deux dans .env."
            }

        return {"count": len(items), "notes": items}

    @staticmethod
    def _append(client: Client, page_id: str, content: str) -> dict:
        if not page_id:
            return {"error": "page_id manquant."}
        blocks = _paragraphs(content)
        if not blocks:
            return {"error": "Contenu vide."}
        client.blocks.children.append(block_id=page_id, children=blocks)
        return {"message": "Contenu ajouté.", "page_id": page_id}
