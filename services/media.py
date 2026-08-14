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
# Extensions dont le texte est extrait avant analyse (Office).
OFFICE_SUFFIXES = {".pptx", ".docx", ".xlsx", ".ods"}

_PPTX_TEXT_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_DOCX_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_ODS_TABLE_NS = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_ODS_TEXT_NS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


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
                slide_num = re.search(r"\d+", name).group()
                root = ET.fromstring(archive.read(name))
                texts = [t.text or "" for t in root.iter(f"{_PPTX_TEXT_NS}t")]
                body = "\n".join(texts).strip()
                if body:
                    out.append(f"--- Diapositive {slide_num} ---\n{body}")
            return "\n\n".join(out) or None
    except (zipfile.BadZipFile, ET.ParseError, OSError):
        return None


def extract_docx_text(path: str | Path) -> str | None:
    """Extrait le texte d'un .docx (archive zip/XML, paragraphes w:p)."""
    try:
        with zipfile.ZipFile(path) as archive:
            if "word/document.xml" not in archive.namelist():
                return None
            root = ET.fromstring(archive.read("word/document.xml"))
            out = []
            for para in root.iter(f"{_DOCX_NS}p"):
                texts = [t.text or "" for t in para.iter(f"{_DOCX_NS}t")]
                line = "".join(texts).strip()
                if line:
                    out.append(line)
            return "\n".join(out) or None
    except (zipfile.BadZipFile, ET.ParseError, OSError):
        return None


def extract_xlsx_text(path: str | Path) -> str | None:
    """Extrait le texte de toutes les feuilles d'un .xlsx (zip/XML + sharedStrings)."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if not any(re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n) for n in names):
                return None
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                sst = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                for si in sst:
                    parts = [t.text or "" for t in si.iter(f"{_XLSX_NS}t")]
                    shared.append("".join(parts))
            sheets = sorted(
                (n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)),
                key=lambda n: int(re.search(r"\d+", n).group()),
            )
            out = []
            for name in sheets:
                root = ET.fromstring(archive.read(name))
                sheet_no = re.search(r"\d+", name).group()
                rows = []
                for row in root.iter(f"{_XLSX_NS}row"):
                    cells = []
                    for cell in row.iter(f"{_XLSX_NS}c"):
                        cell_type = cell.get("t")
                        v = cell.find(f"{_XLSX_NS}v")
                        inline = cell.find(f"{_XLSX_NS}is")
                        if cell_type == "s" and v is not None:
                            idx = int(v.text or 0)
                            cells.append(shared[idx] if idx < len(shared) else "")
                        elif cell_type == "inlineStr" and inline is not None:
                            cells.append(
                                "".join(t.text or "" for t in inline.iter(f"{_XLSX_NS}t"))
                            )
                        elif cell_type == "b" and v is not None:
                            cells.append("VRAI" if v.text == "1" else "FAUX")
                        elif v is not None:
                            cells.append(v.text or "")
                    line = " | ".join(c for c in cells if c.strip())
                    if line.strip():
                        rows.append(line)
                if rows:
                    out.append(f"--- Feuille {sheet_no} ---\n" + "\n".join(rows))
            return "\n\n".join(out) or None
    except (zipfile.BadZipFile, ET.ParseError, OSError):
        return None


def extract_ods_text(path: str | Path) -> str | None:
    """Extrait le texte des feuilles d'un .ods (OpenDocument, content.xml)."""
    try:
        with zipfile.ZipFile(path) as archive:
            if "content.xml" not in archive.namelist():
                return None
            root = ET.fromstring(archive.read("content.xml"))
            out = []
            for table in root.iter(f"{_ODS_TABLE_NS}table"):
                rows = []
                for row in table.iter(f"{_ODS_TABLE_NS}table-row"):
                    cells = []
                    for cell in row.iter(f"{_ODS_TABLE_NS}table-cell"):
                        txt = "".join(p.text or "" for p in cell.iter(f"{_ODS_TEXT_NS}p"))
                        cells.append(txt.strip())
                    line = " | ".join(c for c in cells if c.strip())
                    if line.strip():
                        rows.append(line)
                if rows:
                    name = table.get(f"{_ODS_TABLE_NS}name", "Feuille")
                    out.append(f"--- {name} ---\n" + "\n".join(rows))
            return "\n\n".join(out) or None
    except (zipfile.BadZipFile, ET.ParseError, OSError):
        return None
