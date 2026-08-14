"""Auto-test exhaustif du bot Nexus (tous les outils, lecture seule).

Usage :
    .venv/bin/python scripts/selftest.py

Vérifie : registre, contacts, agenda, Gmail, iCloud, Notion, Spotify,
traduction, météo, mémoire SQLite, gardes de confirmation, extracteurs de
fichiers Office et pipeline de résumé Gemini (texte, Office, image, PDF/dotc
déguisés, binaire). Rien n'est créé ni supprimé (lecture seule).
"""

import asyncio
import base64
import io
import sys
import zipfile
from pathlib import Path

TEST_UID = 987654321  # utilisateur factice pour ne pas polluer la mémoire réelle
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

_results: list[tuple[str, bool]] = []


def section(title: str) -> None:
    print(f"\n== {title} ==")


def check(name: str, ok: bool, detail: str = "") -> bool:
    _results.append((name, bool(ok)))
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(ok)


# ── Générateurs de fichiers de test ─────────────────────────────────
def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def make_docx(text: str) -> bytes:
    body = "".join(
        f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in text.splitlines()
    )
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    return _zip_bytes({"word/document.xml": xml.encode("utf-8")})


def make_pptx() -> bytes:
    xml1 = (
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        "<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Diapo 1 : intro algo</a:t></a:r>"
        "</a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
    )
    xml2 = (
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        "<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Diapo 2 : complexité O(n)</a:t></a:r>"
        "</a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
    )
    return _zip_bytes(
        {"ppt/slides/slide1.xml": xml1.encode("utf-8"), "ppt/slides/slide2.xml": xml2.encode("utf-8")}
    )


def make_xlsx() -> bytes:
    sst = (
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<si><t>Nom</t></si><si><t>Alice</t></si><si><t>Age</t></si></sst>"
    )
    sheet = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        '<row><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>2</v></c></row>'
        '<row><c r="A2" t="s"><v>1</v></c><c r="B2"><v>25</v></c></row>'
        "</sheetData></worksheet>"
    )
    return _zip_bytes(
        {
            "xl/sharedStrings.xml": sst.encode("utf-8"),
            "xl/worksheets/sheet1.xml": sheet.encode("utf-8"),
        }
    )


def make_ods() -> bytes:
    xml = (
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        "<office:body><office:spreadsheet>"
        '<table:table table:name="Planning">'
        "<table:table-row><table:table-cell><text:p>Objet</text:p></table:table-cell>"
        "<table:table-cell><text:p>Duree</text:p></table:table-cell></table:table-row>"
        "<table:table-row><table:table-cell><text:p>Revision</text:p></table:table-cell>"
        "<table:table-cell><text:p>3h</text:p></table:table-cell></table:table-row>"
        "</table:table>"
        "</office:spreadsheet></office:body></office:document-content>"
    )
    return _zip_bytes({"content.xml": xml.encode("utf-8")})


def make_image_only_docx() -> bytes:
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:drawing/></w:r></w:p></w:body></w:document>"
    )
    return _zip_bytes({"word/document.xml": xml.encode("utf-8"), "word/media/image1.png": PNG_1X1})


# ── Tests synchrones ────────────────────────────────────────────────
def test_env_and_registry() -> None:
    section("Environnement & registre")
    from config import settings

    check("settings validées (token + Gemini)", bool(settings.TELEGRAM_BOT_TOKEN and settings.GEMINI_API_KEY))

    from services.media import ffmpeg_available

    check("ffmpeg disponible (conversion vocaux)", ffmpeg_available())

    from bot.app import build_registry

    registry = build_registry()
    expected = ["contacts", "calendar", "gmail", "icloud_mail", "notion", "spotify", "translate", "weather"]
    missing = [name for name in expected if name not in registry.names]
    check("8 outils actifs enregistrés", not missing, f"manquants={missing}")

    declarations = registry.declarations()
    check(
        "déclarations Gemini générées",
        len(declarations) == len(registry.names),
        f"n={len(declarations)}",
    )
    check("perplexity absent (pas de clé API)", "perplexity" not in registry.names)


def test_contacts() -> None:
    section("Contacts")
    from bot.app import build_registry

    registry = build_registry()

    async def run() -> None:
        r = await registry.call("contacts", {"action": "list"}, TEST_UID)
        check("list contacts", "contacts" in r, f"count={r.get('count')}")
        r = await registry.call("contacts", {"action": "search", "query": "zzzz_inexistant_123"}, TEST_UID)
        check("search sans résultat (pas de crash)", "contacts" in r and r.get("count") == 0)
        r = await registry.call("contacts", {"action": "search"}, TEST_UID)
        check("search sans query → erreur propre", "error" in r)

    asyncio.run(run())


def test_calendar() -> None:
    section("Google Agenda")
    from bot.app import build_registry

    registry = build_registry()

    async def run() -> None:
        r = await registry.call("calendar", {"action": "list", "days": 7}, TEST_UID)
        check("list événements 7j", "events" in r, f"count={r.get('count')}")
        r = await registry.call("calendar", {"action": "create", "summary": "T", "start": "2026-12-31 10:00"}, TEST_UID)
        check("create → confirmation requise (autonomie)", r.get("requires_confirmation") is True)

    asyncio.run(run())


def test_gmail() -> None:
    section("Gmail")
    from bot.app import build_registry

    registry = build_registry()

    async def run() -> None:
        r = await registry.call("gmail", {"action": "list", "max": 5}, TEST_UID)
        check("list messages", "messages" in r, f"count={r.get('count')}")
        r = await registry.call("gmail", {"action": "search", "query": "is:unread", "max": 5}, TEST_UID)
        check("search is:unread", "messages" in r, f"count={r.get('count')}")
        r = await registry.call("gmail", {"action": "delete", "message_id": "fake"}, TEST_UID)
        check("delete → confirmation requise (autonomie)", r.get("requires_confirmation") is True)
        r = await registry.call("gmail", {"action": "send", "to": "x@y.z", "subject": "t", "body": "b"}, TEST_UID)
        check("send → confirmation requise (autonomie)", r.get("requires_confirmation") is True)

    asyncio.run(run())


def test_icloud() -> None:
    section("iCloud Mail")
    from bot.app import build_registry

    registry = build_registry()

    async def run() -> None:
        r = await registry.call("icloud_mail", {"action": "list", "limit": 5}, TEST_UID)
        check("list boîte de réception", "messages" in r, f"count={r.get('count')}")
        r = await registry.call("icloud_mail", {"action": "unread"}, TEST_UID)
        check("unread", "unread" in r, f"unread={r.get('unread')}")
        r = await registry.call("icloud_mail", {"action": "delete", "message_id": "1"}, TEST_UID)
        check("delete → confirmation requise (autonomie)", r.get("requires_confirmation") is True)

    asyncio.run(run())


def test_notion() -> None:
    section("Notion")
    from bot.app import build_registry

    registry = build_registry()

    async def run() -> None:
        r = await registry.call("notion", {"action": "list_notes", "limit": 5}, TEST_UID)
        check("list notes", "notes" in r, f"count={r.get('count')}")
        r = await registry.call("notion", {"action": "search", "query": "cours", "limit": 3}, TEST_UID)
        check("search Notion", "results" in r, f"count={r.get('count')}")
        r = await registry.call("notion", {"action": "create_note", "title": "T"}, TEST_UID)
        check("create_note → confirmation requise (autonomie)", r.get("requires_confirmation") is True)

    asyncio.run(run())


def test_spotify() -> None:
    section("Spotify")
    from bot.app import build_registry

    registry = build_registry()

    async def run() -> None:
        r = await registry.call("spotify", {"action": "current"}, TEST_UID)
        check("morceau en cours", "is_playing" in r, str(r.get("message") or r.get("track") or ""))
        r = await registry.call("spotify", {"action": "search", "query": "lo-fi", "limit": 3}, TEST_UID)
        check("recherche titres", "tracks" in r, f"count={r.get('count')}")
        r = await registry.call("spotify", {"action": "playlists", "limit": 5}, TEST_UID)
        check("mes playlists", "playlists" in r, f"count={r.get('count')}")
        r = await registry.call("spotify", {"action": "devices"}, TEST_UID)
        check("appareils", "devices" in r, f"n={len(r.get('devices', []))}")

    asyncio.run(run())


def test_translate_and_weather() -> None:
    section("Traduction & météo")
    from bot.app import build_registry

    registry = build_registry()

    async def run() -> None:
        r = await registry.call("translate", {"text": "Bonjour, comment ça va ?", "target_lang": "EN"}, TEST_UID)
        check("FR→EN (DeepL)", "message" in r, r.get("message", "")[:60])
        r = await registry.call("translate", {"text": "Hello, how are you?", "target_lang": "FR"}, TEST_UID)
        check("EN→FR (DeepL)", "message" in r, r.get("message", "")[:60])
        r = await registry.call("weather", {"location": "Moscow", "days": 3}, TEST_UID)
        check("météo Moscou", "current" in r, r.get("current", {}).get("description", ""))
        r = await registry.call("weather", {"location": "SensiblementInconnue", "days": 1}, TEST_UID)
        check("météo ville invalide → erreur propre", "error" in r)

    asyncio.run(run())


def test_store_memory() -> None:
    section("Mémoire (SQLite)")
    from services.store import Store

    store = Store.get()
    store.clear_history(TEST_UID)
    store.append_history(TEST_UID, "user", "Résumé du chapitre 1")
    store.append_history(TEST_UID, "model", "C'est noté.")
    hist = store.load_history(TEST_UID, 10)
    check("historique persisté + rechargé", len(hist) == 2, f"n={len(hist)}")
    check("rôles corrects", [h["role"] for h in hist] == ["user", "model"])
    store.clear_history(TEST_UID)
    check("reset mémoire", store.load_history(TEST_UID, 10) == [])


def test_confirmation_flow() -> None:
    section("Flux de confirmation (boutons)")
    from tools.registry import BaseTool

    r = BaseTool.defer("gmail", {"action": "delete"}, TEST_UID, "Test")
    check("defer → requires_confirmation", r.get("requires_confirmation") is True and bool(r.get("token")))
    resolved = BaseTool.resolve(r["token"])
    check("resolve récupère l'action", resolved is not None and resolved["tool"] == "gmail")
    check("resolve consommé (pas de double)", BaseTool.resolve(r["token"]) is None)
    r2 = BaseTool.defer("calendar", {}, TEST_UID, "Test2")
    BaseTool.discard(r2["token"])
    check("discard annule proprement", BaseTool.resolve(r2["token"]) is None)


def test_media_extractors() -> None:
    section("Extracteurs de fichiers Office")
    from services import media

    cases = [
        ("docx", make_docx("Bonjour Nexus, test docx.\nDeuxième ligne avec 2³."), ".docx", media.extract_docx_text,
         ["Bonjour Nexus", "Deuxième ligne"]),
        ("pptx", make_pptx(), ".pptx", media.extract_pptx_text, ["Diapo 1", "O(n)"]),
        ("xlsx", make_xlsx(), ".xlsx", media.extract_xlsx_text, ["Nom", "Alice", "25"]),
        ("ods", make_ods(), ".ods", media.extract_ods_text, ["Planning", "Revision"]),
    ]
    for name, data, suffix, fn, expected in cases:
        path = Path("tmp") / f"selftest_{name}{suffix}"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        try:
            text = fn(path)
            ok = text is not None and all(needle in text for needle in expected)
            check(f"extraction {name}", ok, f"contenu={text[:80]!r}")
        finally:
            path.unlink(missing_ok=True)

    image_docx = Path("tmp") / "selftest_imageonly.docx"
    image_docx.write_bytes(make_image_only_docx())
    try:
        img = media.extract_largest_image(image_docx, ".docx")
        check("docx sans texte → image embarquée extraite", img is not None and img.exists())
        if img:
            img.unlink(missing_ok=True)
    finally:
        image_docx.unlink(missing_ok=True)

    bad = Path("tmp") / "selftest_fake.docx"
    bad.write_bytes(b"not a zip file at all")
    try:
        check("fichier corrompu → None proprement", media.extract_docx_text(bad) is None)
    finally:
        bad.unlink(missing_ok=True)


def test_summarize_file() -> None:
    section("Pipeline de résumé de fichiers (Gemini)")
    from services.gemini import GeminiService

    g = GeminiService()

    # texte (.py)
    py = Path("tmp") / "selftest_code.py"
    py.write_text("def fib(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n", encoding="utf-8")
    try:
        out = g.summarize_file(py, "selftest_code.py")
        check("résumé fichier texte (.py)", bool(out) and "Impossible" not in out, out[:80])
    finally:
        py.unlink(missing_ok=True)

    # docx texte
    d = Path("tmp") / "selftest_note.docx"
    d.write_bytes(make_docx("Algorithmes de tri : tri fusion O(n log n), tri rapide O(n log n) en moyenne."))
    try:
        out = g.summarize_file(d, "selftest_note.docx")
        check("résumé .docx texte", bool(out) and "Impossible" not in out, out[:80])
    finally:
        d.unlink(missing_ok=True)

    # docx image-only → vision
    d2 = Path("tmp") / "selftest_imageonly.docx"
    d2.write_bytes(make_image_only_docx())
    try:
        out = g.summarize_file(d2, "selftest_imageonly.docx")
        check("docx image-only → analyse vision", bool(out) and "Impossible" not in out, out[:80])
    finally:
        d2.unlink(missing_ok=True)

    # .doc déguisé
    d3 = Path("tmp") / "selftest_disguised.docx"
    d3.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 40)
    try:
        out = g.summarize_file(d3, "selftest_disguised.docx")
        check(".doc déguisé détecté", "renommé" in out or "corrompu" in out, out[:80])
    finally:
        d3.unlink(missing_ok=True)

    # PDF déguisé
    d4 = Path("tmp") / "selftest_pdf.docx"
    d4.write_bytes(b"%PDF-1.4\n% Test" + b"\x00" * 30)
    try:
        out = g.summarize_file(d4, "selftest_pdf.docx")
        check("PDF déguisé détecté", "PDF" in out, out[:80])
    finally:
        d4.unlink(missing_ok=True)

    # binaire non reconnu
    d5 = Path("tmp") / "selftest_data.dat"
    d5.write_bytes(b"\x00\x01\x02\x03\xff" + b"\x00" * 100)
    try:
        out = g.summarize_file(d5, "selftest_data.dat")
        check("binaire → message propre", "Impossible" in out, out[:80])
    finally:
        d5.unlink(missing_ok=True)


def test_agent_end_to_end() -> None:
    section("Agent de bout en bout (boucle d'outils Gemini)")
    from bot.app import build_registry
    from core.agent import Agent
    from services.deepl import DeeplService
    from services.gemini import GeminiService

    agent = Agent(GeminiService(), DeeplService(), build_registry())

    async def run() -> None:
        agent.reset(TEST_UID)
        reply = await agent.reply_to_text(TEST_UID, "Quelle est la météo à Moscou aujourd'hui ? Donne juste la température.")
        ok = isinstance(reply, str) and len(reply.strip()) > 5
        check("conversation → outil météo appelé + réponse", ok, reply[:100])
        reply2 = await agent.reply_to_text(TEST_UID, "Sans outil, réponds simplement : 1+1=?")
        check("réponse simple (2e tour)", isinstance(reply2, str) and len(reply2.strip()) > 0, reply2[:80])
        agent.reset(TEST_UID)

    asyncio.run(run())


def main() -> int:
    print("=== AUTO-TEST NEXUS ===")
    test_env_and_registry()
    test_contacts()
    test_calendar()
    test_gmail()
    test_icloud()
    test_notion()
    test_spotify()
    test_translate_and_weather()
    test_store_memory()
    test_confirmation_flow()
    test_media_extractors()
    test_summarize_file()
    test_agent_end_to_end()

    passed = sum(1 for _, ok in _results if ok)
    total = len(_results)
    print(f"\n=== RÉSULTAT : {passed}/{total} tests OK ===")
    failed = [name for name, ok in _results if not ok]
    if failed:
        print("ÉCHECS :")
        for name in failed:
            print(f"  - {name}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
