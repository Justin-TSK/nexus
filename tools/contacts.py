from services.contacts_store import ContactsStore
from tools.registry import BaseTool


class ContactsTool(BaseTool):
    name = "contacts"
    description = (
        "Carnet de contacts de l'utilisateur (liste locale). Utilise-le pour chercher un "
        "contact (nom, téléphone, email), ajouter un contact, ou lister les contacts. "
        "Toujours prioritaire pour retrouver un numéro ou une adresse d'une personne."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "add", "list"],
                "description": "search: chercher | add: ajouter | list: tout lister",
            },
            "query": {"type": "string", "description": "Nom, numéro ou email recherché (search)."},
            "name": {"type": "string", "description": "Nom complet du contact (add)."},
            "phone": {"type": "string", "description": "Téléphone (add)."},
            "email": {"type": "string", "description": "Email (add)."},
            "notes": {"type": "string", "description": "Notes (add)."},
        },
        "required": ["action"],
    }

    def __init__(self) -> None:
        self._store = ContactsStore()

    def run(self, args: dict, user_id: int) -> dict:
        action = args.get("action")
        if action == "search":
            query = (args.get("query") or "").strip()
            if not query:
                return self._err("Indique un nom, numéro ou email à chercher.")
            results = self._store.search(query)
            return {"count": len(results), "contacts": results}
        if action == "add":
            name = (args.get("name") or "").strip()
            if not name:
                return self._err("Le nom du contact est requis.")
            entry = self._store.add(name, args.get("phone") or "", args.get("email") or "", args.get("notes") or "")
            return {"message": "Contact ajouté.", "contact": entry}
        if action == "list":
            contacts = self._store.all()
            return {"count": len(contacts), "contacts": contacts}
        return self._err(f"Action inconnue : {action}")
