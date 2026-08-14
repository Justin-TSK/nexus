from config import settings
from services.icloud import IcloudMailClient, IcloudMailError
from tools.registry import BaseTool


class IcloudMailTool(BaseTool):
    name = "icloud_mail"
    description = (
        "Boîte mail iCloud/Apple de l'utilisateur (IMAP). À n'utiliser que "
        "s'il mentionne EXPLICITEMENT Apple, iCloud ou sa boîte @icloud.com. "
        "Pour toute demande générique de type « mes emails » / « ma boîte mail », "
        "utilise TOUJOURS l'outil gmail en priorité. Actions : lister, compter, lire, "
        "supprimer. La suppression iCloud déplace vers la corbeille (récupérable ~30 jours, "
        "comme l'app Mail) — demande quand même une confirmation à l'utilisateur."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "unread", "read", "delete"],
                "description": "list: lister les messages | unread: compter les non-lus | read: lire un message | delete: déplacer vers la corbeille (après confirmation)",
            },
            "criteria": {
                "type": "string",
                "description": "Critère IMAP (ex: 'UNSEEN', 'FROM \"prof\"', 'SINCE 01-Jan-2026'). Défaut ALL.",
            },
            "limit": {"type": "integer", "description": "Nombre max de résultats (défaut 5)."},
            "message_id": {"type": "string", "description": "ID du message à lire ou supprimer (retourné par list)."},
            "message_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Liste d'IDs pour supprimer plusieurs messages EN UN SEUL appel (au lieu d'un appel par mail).",
            },
        },
        "required": ["action"],
    }

    @property
    def enabled(self) -> bool:
        return bool(settings.ICLOUD_EMAIL and settings.ICLOUD_APP_PASSWORD)

    def run(self, args: dict, user_id: int) -> dict:
        action = args.get("action")
        try:
            client = IcloudMailClient()
            if action == "list":
                items = client.list_inbox(args.get("criteria") or "ALL", int(args.get("limit") or 5))
                return {"count": len(items), "messages": items}
            if action == "unread":
                return {"unread": client.unread_count()}
            if action == "read":
                msg = client.read_email(args.get("message_id") or "")
                return msg
            if action == "delete":
                ids = args.get("message_ids") or ([args["message_id"]] if args.get("message_id") else [])
                if not ids:
                    return self._err("message_id (ou message_ids) manquant.")
                return client.delete_emails(ids)
            return self._err(f"Action inconnue : {action}")
        except IcloudMailError as exc:
            return self._err(str(exc))
