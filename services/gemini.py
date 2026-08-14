import time
from pathlib import Path

from google import genai
from google.genai import types

from config import settings

MAX_FILE_CHARS = 60_000


class GeminiService:
    """Encapsule toutes les interactions avec l'API Gemini (nouveau SDK google.genai)."""

    def __init__(self) -> None:
        self._client = None
        self.model_name = settings.GEMINI_MODEL

    def _get_client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return self._client

    @staticmethod
    def _system_prompt() -> str:
        profile = settings.USER_PROFILE.strip()
        profile_block = (
            "\n\nPROFIL DE L'UTILISATEUR (utilise-le pour le personnaliser, s'adresser à lui "
            f"par son prénom et répondre à « qui suis-je / qui es-tu ») :\n{profile}"
            if profile
            else ""
        )
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        try:
            from zoneinfo import ZoneInfo
            local = now.astimezone(ZoneInfo(settings.CALENDAR_TIMEZONE))
        except Exception:
            local = now
        now_block = (
            "\n\nDATE ET HEURE ACTUELLES : nous sommes le "
            f"{local.strftime('%A %d %B %Y à %H:%M')} (fuseau {settings.CALENDAR_TIMEZONE}). "
            "Base-toi sur cette date pour interpréter « aujourd'hui », « demain », « samedi », "
            "« dans 2 jours », etc. Le jour de la semaine actuel est indiqué par cette date."
        )
        return (
            "Tu es « Nexus », un assistant personnel intelligent, ultra-compétent et "
            "dynamique, conçu pour accompagner un étudiant en informatique tout au long "
            "de son année universitaire.\n\n"
            "OBJECTIF : l'aider à optimiser son temps, organiser ses cours, coder plus "
            "efficacement, gérer son stress et automatiser son quotidien via Telegram.\n\n"
            "TON ET STYLE : professionnel, encourageant, direct, légèrement geek et "
            "complice. Format clair et concis (affichage smartphone Telegram) : phrases "
            "courtes, listes à puces avec « • », emojis pertinents. Jamais de pavés. "
            "STYLE TEXTE : texte SIMPLE, lisible sur téléphone, sans symboles markdown "
            "inutiles : n'utilise JAMAIS « * », « ** », « _ », « # », « > », « ^ » ni "
            "crochets pour du formatage ; n'écris pas « 2^3 » mais « 2³ » ; mets le code "
            "informatique uniquement dans des blocs à trois backticks, sinon écris en "
            "texte clair.{profile_block}{now_block}\n\n"
            "OUTILS À TA DISPOSITION (appelle-les de façon autonome quand c'est pertinent) :\n"
            "- Notion : stocker des résumés de cours, fiches de révision, To-Do list.\n"
            "- Google Agenda : planifier examens, rendus de projets, plages de révision.\n"
            "- Gmail : trier, résumer, rédiger des mails administratifs (stages, profs) et les envoyer.\n"
            "- Gmail : boîte mail PRINCIPALE. Pour « mes emails », « ma boîte mail », "
            "« mes messages » sans précision, utilise TOUJOURS gmail en premier.\n"
            "- iCloud Mail : boîte Apple en lecture seule — uniquement si l'utilisateur "
            "mentionne explicitement iCloud / Apple / @icloud.com.\n"
            "- Spotify : lancer de la musique, notamment des playlists de concentration (Lo-fi, Deep Focus).\n"
            "- DeepL (via /traduire) : traduire de la documentation technique, des articles, des PDF en anglais.\n"
            "- Perplexity : recherches web approfondies (bugs de code, concepts algorithmiques, veille).\n"
            "- Météo : prévisions actuelles et à venir (ville par défaut : l'utilisateur est à Moscou).\n"
            "- Contacts : retrouver ou ajouter un numéro / email.\n\n"
            "RÈGLES DE FONCTIONNEMENT :\n"
            "- Multimodalité : analyse avec attention les textes, notes vocales transcrites "
            "et fichiers PDF (cours, sujets de TD) pour en extraire l'essentiel.\n"
            "- Proactivité : si l'utilisateur partage un sujet de TD ou du code (PDF, vocal, "
            "fichier), propose directement de l'aider à le décortiquer ou de créer une tâche "
            "associée dans Notion.\n"
            "- Efficacité : utilise l'outil correspondant sans demander de validation superflue.\n"
            "- Réponds toujours en français sauf si l'utilisateur écrit dans une autre langue ; "
            "si une demande est ambiguë, pose une question de clarification.\n"
        )

    @staticmethod
    def _normalize_contents(contents: list) -> list:
        """Le SDK google.genai exige des objets Part (dict), pas des chaînes brutes."""
        normalized = []
        for item in contents:
            if isinstance(item, dict) and isinstance(item.get("parts"), list):
                item = {**item, "parts": [
                    {"text": p} if isinstance(p, str) else p for p in item["parts"]
                ]}
            normalized.append(item)
        return normalized

    def generate(
        self, contents: list, tools: types.Tool | None = None
    ) -> types.GenerateContentResponse:
        contents = self._normalize_contents(contents)
        config = types.GenerateContentConfig(system_instruction=self._system_prompt())
        if tools is not None:
            config.tools = [tools]
        return self._get_client().models.generate_content(
            model=self.model_name, contents=contents, config=config
        )

    def _extract_text(self, response: types.GenerateContentResponse) -> str:
        try:
            content = response.candidates[0].content
        except (IndexError, AttributeError):
            return ""
        if content is None:
            return ""
        parts = content.parts or []
        return "".join(p.text for p in parts if p.text).strip()

    # ── Conversation ────────────────────────────────────────────────
    def chat(self, history: list[dict], prompt: str) -> str:
        contents = history + [{"role": "user", "parts": [prompt]}]
        return self._extract_text(self.generate(contents))

    # ── Transcription vocale ────────────────────────────────────────
    def transcribe_audio(self, data: bytes, mime_type: str) -> str:
        lang = settings.TRANSCRIPTION_LANG
        instruction = (
            "Tu es un moteur de transcription. Transcris intégralement le message audio "
            f"suivant en corrigeant l'orthographe et la ponctuation. Réponds uniquement "
            f"avec la transcription, sans aucun commentaire. "
            f"Langue cible : {lang or 'la langue parlée dans le message'}."
        )
        response = self._get_client().models.generate_content(
            model=self.model_name,
            contents=[instruction, types.Part.from_bytes(data=data, mime_type=mime_type)],
        )
        return self._extract_text(response)

    # ── Fichiers ────────────────────────────────────────────────────
    def summarize_file(self, file_path: str | Path, filename: str) -> str:
        prompt = (
            f"Voici un fichier nommé « {filename} ». Analyse-le pour un étudiant en "
            "informatique : résume son contenu, souligne les points importants et propose "
            "de l'aide si nécessaire."
        )
        path = Path(file_path)
        if path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}:
            return self._analyze_binary(path, prompt)
        if path.suffix.lower() in {".pptx", ".docx"}:
            from services.media import extract_pptx_text, extract_docx_text
            text = extract_pptx_text(path) if path.suffix.lower() == ".pptx" else extract_docx_text(path)
            if text is None:
                return "Impossible de lire ce fichier Office."
            if len(text) > MAX_FILE_CHARS:
                text = text[:MAX_FILE_CHARS] + "\n… [contenu tronqué]"
            return self._extract_text(self.generate([prompt, text]))
        return self._analyze_text(path, prompt)

    def _analyze_text(self, path: Path, prompt: str) -> str:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "Impossible de lire ce fichier."
        if len(raw) > MAX_FILE_CHARS:
            raw = raw[:MAX_FILE_CHARS] + "\n… [contenu tronqué]"
        return self._extract_text(self.generate([prompt, raw]))

    def _analyze_binary(self, path: Path, prompt: str) -> str:
        client = self._get_client()
        uploaded = client.files.upload(file=str(path))
        try:
            uploaded = self._wait_ready(uploaded)
            return self._extract_text(self.generate([uploaded, prompt]))
        finally:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass

    def _wait_ready(self, f, timeout: float = 30.0):
        start = time.time()
        while f.state == types.FileState.PROCESSING and time.time() - start < timeout:
            time.sleep(0.5)
            f = self._get_client().files.get(name=f.name)
        return f
