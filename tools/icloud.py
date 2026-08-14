from config import settings
from services.icloud import IcloudMailClient, IcloudMailError
from tools.registry import BaseTool


class IcloudMailTool(BaseTool):
    name = "icloud_mail"
    description = (
        "Boîte mail iCloud/Apple de l'utilisateur (IMAP, lecture seule). À n'utiliser que "
        "s'il mentionne EXPLICITEMENT Apple, iCloud ou sa boîte @icloud.com. "
        "Pour toute demande générique de type « mes emails » / « ma boîte mail », "
        "utilise TOUJOURS l'outil gmail en priorité. Lecture seule : lister, compter, lire."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "unread", "read"],
                "description": "list: lister les messages | unread: compter les non-lus | read: lire un message",
            },
            "criteria": {
                "type": "string",
                "description": "Critère IMAP (ex: 'UNSEEN', 'FROM \"prof\"', 'SINCE 01-Jan-2026'). Défaut ALL.",
            },
            "limit": {"type": "integer", "description": "Nombre max de résultats (défaut 5)."},
            "message_id": {"type": "string", "description": "ID du message à lire (retourné par list)."},
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
            return self._err(f"Action inconnue : {action}")
        except IcloudMailError as exc:
            return self._err(str(exc))
