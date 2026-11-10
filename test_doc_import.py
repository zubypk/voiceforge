"""PDF / PowerPoint import -> scenes (real pypdfium2, python-pptx and, when installed, LibreOffice)."""
import io
import shutil
from pathlib import Path

import pytest
from PIL import Image

import doc_import
import video

FIX = Path(__file__).parent / "tests_fixtures"


@pytest.fixture
def store(tmp_path):
    return video.AssetStore(tmp_path / "a")


def test_pdf_pages_become_full_screen_scenes(store):
    res = doc_import.import_document((FIX / "deck.pdf").read_bytes(), "deck.pdf", store, narration="text")
    assert res["pages"] == 3 and res["imported"] == 3 and len(res["assets"]) == 3
    s0 = res["scenes"][0]
    assert s0["layout"] == "media" and s0["media"]["position"] == "full"
    assert "Photosynthesis" in s0["narration"]
    with Image.open(store.path(s0["media"]["asset"])) as im:
        assert max(im.size) == doc_import.RENDER_LONG_SIDE
    # validates and renders a preview frame
    proj = video.validate_project({"ratio": "16:9", "resolution": "720", "scenes": res["scenes"]}, store)
    assert proj["scenes"][0]["media"]["position"] == "full"
    png = video.render_preview_png(proj, 0, store)
    assert png[:4] == b"\x89PNG"


def test_pdf_narration_none_sets_duration(store):
    res = doc_import.import_document((FIX / "deck.pdf").read_bytes(), "deck.pdf", store, narration="none", max_pages=2)
    assert res["imported"] == 2 and res["pages"] == 3
    assert all(s["narration"] == "" and s["duration"] == doc_import.DEFAULT_SECONDS for s in res["scenes"])


@pytest.mark.skipif(not doc_import._soffice(), reason="LibreOffice not installed")
def test_pptx_via_libreoffice_uses_speaker_notes(store):
    res = doc_import.import_document((FIX / "deck.pptx").read_bytes(), "deck.pptx", store, narration="notes")
    assert res["method"] == "libreoffice" and res["imported"] == 3
    assert res["scenes"][0]["narration"].startswith("Welcome.")
    assert "الضوء" in res["scenes"][1]["narration"]
    assert res["scenes"][2]["narration"] == "" and res["scenes"][2]["duration"] == 5.0
    assert res["scenes"][1]["label"] == "البناء الضوئي"


def test_pptx_editable_fallback(store, monkeypatch):
    monkeypatch.setattr(doc_import, "_soffice", lambda: None)
    res = doc_import.import_document((FIX / "deck.pptx").read_bytes(), "deck.pptx", store, narration="notes")
    assert res["method"] == "editable"
    s = res["scenes"]
    assert s[0]["title"] == "Photosynthesis" and s[0]["narration"].startswith("Welcome.")
    assert s[1]["layout"] == "bullets" and s[1]["body"].count("\n") == 2
    assert s[2]["media"] and store.kind(s[2]["media"]["asset"]) == "image"
    video.validate_project({"scenes": s}, store)


def test_old_ppt_without_libreoffice_is_clear_error(store, monkeypatch):
    monkeypatch.setattr(doc_import, "_soffice", lambda: None)
    with pytest.raises(video.VideoError, match="LibreOffice"):
        doc_import.import_document(b"xx", "old.ppt", store)


@pytest.mark.parametrize("name,data,msg", [("a.exe", b"x", "Unsupported"), ("a.pdf", b"", "empty"), ("a.pdf", b"not a pdf", "could not")])
def test_bad_inputs(store, name, data, msg):
    with pytest.raises(video.VideoError, match=msg):
        doc_import.import_document(data, name, store)


def test_import_endpoint(tmp_path, monkeypatch):
    import app as appmod
    c = appmod.app.test_client()
    r = c.post("/api/video/import", data={"file": (io.BytesIO((FIX / "deck.pdf").read_bytes()), "deck.pdf"), "narration": "text"},
               content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    j = r.get_json()
    assert j["imported"] == 3
    assert c.get(f"/api/assets/{j['assets'][0]['id']}/thumb").status_code == 200
    assert "pdf" in "".join(c.get("/api/video/config").get_json()["import_formats"])
    bad = c.post("/api/video/import", data={"file": (io.BytesIO(b"x"), "a.exe")}, content_type="multipart/form-data")
    assert bad.status_code == 400


@pytest.mark.skipif(not doc_import._soffice(), reason="LibreOffice not installed")
@pytest.mark.parametrize("name", ["lesson.docx", "marks.xlsx"])
def test_word_and_excel_via_libreoffice(store, name):
    res = doc_import.import_document((FIX / name).read_bytes(), name, store, narration="text")
    assert res["method"] == "libreoffice" and res["imported"] >= 1
    assert res["scenes"][0]["media"]["position"] == "full"


def test_docx_without_libreoffice_becomes_text_scenes(store, monkeypatch):
    monkeypatch.setattr(doc_import, "_soffice", lambda: None)
    res = doc_import.import_document((FIX / "lesson.docx").read_bytes(), "lesson.docx", store)
    titles = [s["title"] for s in res["scenes"]]
    assert res["method"] == "text" and "Water cycle" in titles and "دورة الماء" in titles
    water = res["scenes"][titles.index("Water cycle")]
    assert water["layout"] == "bullets" and water["body"].split("\n") == ["Evaporation", "Condensation", "Rain"]
    video.validate_project({"scenes": res["scenes"]}, store)
    with pytest.raises(video.VideoError, match="LibreOffice"):
        doc_import.import_document((FIX / "marks.xlsx").read_bytes(), "marks.xlsx", store)
