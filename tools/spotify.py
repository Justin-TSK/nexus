import threading
from pathlib import Path

from spotipy import Spotify, SpotifyException
from spotipy.oauth2 import SpotifyOAuth

from config import settings
from tools.registry import BaseTool

SCOPES = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-currently-playing "
    "playlist-read-private "
    "user-library-read"
)


class _SpotifyClient:
    _lock = threading.Lock()
    _instance = None

    @classmethod
    def get(cls) -> Spotify:
        with cls._lock:
            if cls._instance is None:
                auth = SpotifyOAuth(
                    client_id=settings.SPOTIFY_CLIENT_ID,
                    client_secret=settings.SPOTIFY_CLIENT_SECRET,
                    redirect_uri=settings.SPOTIFY_REDIRECT_URI,
                    scope=SCOPES,
                    cache_path=settings.SPOTIFY_TOKEN_FILE,
                )
                cls._instance = Spotify(auth_manager=auth)
            return cls._instance


def _current_info(sp: Spotify) -> dict:
    playback = sp.current_playback()
    if not playback or not playback.get("item"):
        return {"is_playing": False, "message": "Aucune lecture en cours."}
    item = playback["item"]
    artists = ", ".join(a["name"] for a in item.get("artists", []))
    return {
        "is_playing": playback.get("is_playing", False),
        "track": item.get("name"),
        "artists": artists,
        "album": item.get("album", {}).get("name"),
        "uri": item.get("uri"),
        "progress_ms": playback.get("progress_ms"),
        "duration_ms": item.get("duration_ms"),
        "device": playback.get("device", {}).get("name"),
    }


class SpotifyTool(BaseTool):
    name = "spotify"
    description = (
        "Musique Spotify de l'utilisateur. Utilise-le pour la musique de fond, des "
        "playlists de concentration (Lo-fi, Deep Focus) quand il travaille ou révise, le "
        "morceau en cours, jouer/pause/musique suivante, chercher un titre, ajouter à la "
        "file, lister ses playlists. IMPORTANT — appareils : si l'utilisateur nomme un "
        "appareil précis (« sur mon téléphone », « sur mon iPhone », « sur le Mac »), "
        "appelle D'ABORD l'action devices pour récupérer les ids, puis passe device_id. "
        "Sinon l'appareil actif est utilisé, sinon le premier disponible."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["current", "search", "play", "pause", "next", "previous", "queue", "devices", "playlists"],
                "description": "current: morceau en cours | search: chercher des titres | play: lire/relancer (uri optionnel) | pause: pause | next/previous: suivant/précédent | queue: ajouter à la file | devices: appareils actifs | playlists: mes playlists",
            },
            "query": {"type": "string", "description": "Recherche (search)."},
            "uri": {
                "type": "string",
                "description": "URI Spotify d'un titre (spotify:track:...) ou d'une playlist (spotify:playlist:...).",
            },
            "device_id": {
                "type": "string",
                "description": "ID de l'appareil Spotify ciblé (retourné par l'action devices). Optionnel : sinon l'appareil actif ou le premier disponible est choisi.",
            },
            "limit": {"type": "integer", "description": "Nombre max de résultats (défaut 5)."},
        },
        "required": ["action"],
    }

    @property
    def enabled(self) -> bool:
        return bool(settings.SPOTIFY_CLIENT_ID and settings.SPOTIFY_CLIENT_SECRET)

    @staticmethod
    def _pick_device(sp: Spotify) -> str | None:
        try:
            devices = sp.devices().get("devices", [])
        except SpotifyException:
            return None
        active = next((d["id"] for d in devices if d.get("is_active")), None)
        return active or (devices[0]["id"] if devices else None)

    def run(self, args: dict, user_id: int) -> dict:
        action = args.get("action")
        if not Path(settings.SPOTIFY_TOKEN_FILE).exists():
            return self._err(
                "Spotify n'est pas encore connecté au compte. "
                "Lance la commande : python scripts/auth_setup.py spotify"
            )
        try:
            sp = _SpotifyClient.get()
            if action == "current":
                return _current_info(sp)
            if action == "search":
                query = args.get("query") or ""
                if not query:
                    return self._err("Indique une recherche.")
                result = sp.search(query, type="track", limit=max(1, min(int(args.get("limit") or 5), 10)))
                tracks = []
                for t in result.get("tracks", {}).get("items", []):
                    tracks.append({
                        "uri": t["uri"],
                        "name": t["name"],
                        "artists": ", ".join(a["name"] for a in t.get("artists", [])),
                        "album": t.get("album", {}).get("name"),
                        "duration_ms": t.get("duration_ms"),
                    })
                return {"count": len(tracks), "tracks": tracks}
            if action == "play":
                uri = args.get("uri")
                if not uri and args.get("query"):
                    search = sp.search(
                        args["query"], type="track", limit=1, market=None
                    )
                    tracks = search.get("tracks", {}).get("items", [])
                    if not tracks:
                        return self._err(f"Aucun résultat pour « {args['query']} ».")
                    uri = tracks[0]["uri"]
                device_id = args.get("device_id") or self._pick_device(sp)
                if not device_id:
                    return self._err(
                        "Aucun appareil Spotify actif détecté. Ouvre l'appli Spotify "
                        "(téléphone ou ordinateur), puis relance la musique."
                    )
                if not uri:
                    sp.start_playback(device_id=device_id)
                    return {"message": "Lecture relancée."}
                if uri.startswith("spotify:playlist:"):
                    sp.start_playback(context_uri=uri, device_id=device_id)
                    return {"message": f"Playlist lancée : {uri}"}
                sp.start_playback(uris=[uri], device_id=device_id)
                return {"message": f"Lecture lancée : {uri}"}
            if action == "pause":
                sp.pause_playback()
                return {"message": "Lecture en pause."}
            if action == "next":
                sp.next_track()
                return {"message": "Morceau suivant."}
            if action == "previous":
                sp.previous_track()
                return {"message": "Morceau précédent."}
            if action == "queue":
                uri = args.get("uri")
                if not uri:
                    return self._err("Indique une URI à ajouter à la file.")
                sp.add_to_queue(uri)
                return {"message": "Ajouté à la file."}
            if action == "devices":
                devices = sp.devices()
                items = [
                    {"id": d.get("id"), "name": d.get("name"), "type": d.get("type"), "active": d.get("is_active")}
                    for d in devices.get("devices", [])
                ]
                return {"devices": items}
            if action == "playlists":
                result = sp.current_user_playlists(limit=max(1, min(int(args.get("limit") or 10), 50)))
                items = [
                    {"uri": p["uri"], "name": p["name"], "tracks": p.get("tracks", {}).get("total", 0)}
                    for p in result.get("items", [])
                ]
                return {"count": len(items), "playlists": items}
            return self._err(f"Action inconnue : {action}")
        except SpotifyException as exc:
            return self._err(f"Spotify : {exc.msg} — vérifie qu'un appareil est actif et connecté.")
