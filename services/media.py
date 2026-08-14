import asyncio
import re
import shutil
import subprocess
import uuid
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from telegram import File
from telegram.ext import Application

from config import settings

# Types d'audio Telegram (voix) — OGG/Opus n'est pas fiable pour Gemini.
VOICE_SUFFIXES = {".oga", ".ogg", ".opus"}
# Extensions lues comme texte pur.
TEXT_SUFFIXES = {".txt", ".md", ".py", ".json", ".csv", ".yaml", ".yml", ".js", ".ts", ".html", ".css", ".java", ".c", ".h", ".cpp", ".rs", ".go"}
# Extensions envoyées telles quelles à Gemini (pdf, images).
BINARY_UPLOAD_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}
# Extensions dont le texte est extrait avant analyse (PowerPoint).
OFFICE_SUFFIXES = {".pptx"}

_PPTX_TEXT_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def to_mp3(src: Path) -> Path | None:
    """Convertit un fichier audio en MP3 16 kHz mono (léger et bien supporté)."""
    if not ffmpeg_available():
        return None
    out = src.with_name(src.stem + "_conv.mp3")
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-ar", "16000", "-ac", "1", str(out)],
        capture_output=True,
    )
    return out if result.returncode == 0 and out.exists() else None


async def download_to_temp(app: Application, file: File) -> Path:
    """Télécharge un fichier Telegram dans tmp/ et retourne son chemin local."""
    tmp_dir = Path(settings.TEMP_DIR)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.file_path or "fichier.bin").suffix.lower() or ".bin"
    dest = tmp_dir / f"{uuid.uuid4().hex}{suffix}"
    await file.download_to_drive(dest)
    return dest


def async_cleanup(path: Path) -> None:
    """Supprime un fichier temporaire (best-effort)."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


async def ensure_audio_for_gemini(app: Application, file: File) -> tuple[bytes, str]:
    """Télécharge un vocal et retourne (données, mime_type) prêts pour Gemini."""
    src = await download_to_temp(app, file)
    try:
        if src.suffix in VOICE_SUFFIXES:
            mp3 = to_mp3(src)
            if mp3 is not None:
                data = mp3.read_bytes()
                async_cleanup(mp3)
                return data, "audio/mpeg"
        data = src.read_bytes()
        mime = "audio/ogg" if src.suffix in VOICE_SUFFIXES else "audio/mpeg" if src.suffix == ".mp3" else "application/octet-stream"
        return data, mime
    finally:
        async_cleanup(src)


def file_kind(suffix: str) -> str:
    """Retourne 'text', 'binary', 'office' ou 'unsupported' selon l'extension."""
    if suffix in TEXT_SUFFIXES:
        return "text"
    if suffix in BINARY_UPLOAD_SUFFIXES:
        return "binary"
    if suffix in OFFICE_SUFFIXES:
        return "office"
    return "unsupported"


def extract_pptx_text(path: str | Path) -> str | None:
    """Extrait le texte de toutes les diapositives d'un .pptx (archive zip/XML)."""
    try:
        with zipfile.ZipFile(path) as archive:
            slides = sorted(
                (n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                key=lambda n: int(re.search(r"\d+", n).group()),
            )
            if not slides:
                return None
            out = []
            for name in slides:
                root = ET.fromstring(archive.read(name))
                texts = [t.text or "" for t in root.iter(f"{_PPTX_TEXT_NS}t")]
                body = "\n".join(texts).strip()
                if body:
                    out.append(f"--- Diapositive {re.search(r'\d+', name).group()} ---\n{body}")
            return "\n\n".join(out) or None
    except (zipfile.BadZipFile, ET.ParseError, OSError):
        return None
