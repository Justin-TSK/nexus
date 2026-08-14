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
        "supprimer, lister les dossiers. Le dossier Junk contient le SPAM : pour les "
        "spams/pourriels, utilise folder=\"Junk\". ATTENTION : la suppression iCloud est "
        "DÉFINITIVE et irréversible — iCloud ne permet pas de déplacer vers la corbeille "
        "via IMAP (seule l'app Mail d'Apple peut le faire). La confirmation de la "
        "suppression est gérée AUTOMATIQUEMENT par l'outil (boutons affichés à "
        "l'utilisateur) : quand il demande une suppression, appelle directement l'action "
        "delete sans poser de question préalable en texte."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "unread", "read", "delete", "folders"],
                "description": "list: lister les messages | unread: compter les non-lus | read: lire un message | delete: supprimer (confirmation par boutons automatique) | folders: lister les dossiers disponibles",
            },
            "folder": {
                "type": "string",
                "description": "Dossier IMAP ciblé : INBOX (défaut), Junk (spam), Archive, Deleted Messages… Utilise folders pour la liste.",
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
        folder = args.get("folder") or "INBOX"
        try:
            client = IcloudMailClient()
            if action == "folders":
                return {"folders": client.list_folders()}
            if action == "list":
                items = client.list_inbox(
                    args.get("criteria") or "ALL", int(args.get("limit") or 5), folder=folder
                )
                return {"count": len(items), "folder": folder, "messages": items}
            if action == "unread":
                return {"unread": client.unread_count(folder=folder)}
            if action == "read":
                msg = client.read_email(args.get("message_id") or "", folder=folder)
                return msg
            if action == "delete":
                ids = args.get("message_ids") or ([args["message_id"]] if args.get("message_id") else [])
                if not ids:
                    return self._err("message_id (ou message_ids) manquant.")
                if not args.get("_skip_confirm"):
                    return self.defer(
                        self.name, args, user_id,
                        f"Supprimer définitivement {len(ids)} mail(s) iCloud (irréversible).",
                    )
                return client.delete_emails(ids, folder=folder)
            return self._err(f"Action inconnue : {action}")
        except IcloudMailError as exc:
            return self._err(str(exc))
