"""Media library: built-in shapes / clip art / sfx are real; Openverse is faked (no network in tests)."""
import io
import json

import pytest
from PIL import Image

import library
import video


@pytest.fixture
def store(tmp_path):
    return video.AssetStore(tmp_path / "a")


@pytest.mark.parametrize("name", library.SHAPES)
def test_every_shape_is_transparent_png(name):
    im = Image.open(io.BytesIO(library.make_shape(name, "#2f6bff", 256)))
    assert im.mode == "RGBA" and im.getpixel((0, 0))[3] < 255 or name in ("square",)


def test_clipart_and_bad_input():
    assert library.clipart_catalog()[0][0] == "education"
    assert Image.open(io.BytesIO(library.make_emoji("📚"))).size[0] > 100
    for bad in (lambda: library.make_emoji("<script>"), lambda: library.make_shape("nope")):
        with pytest.raises(video.VideoError):
            bad()


def test_sfx_are_cached_mp3(tmp_path):
    p = library.sfx_file("whoosh", tmp_path)
    assert p.read_bytes()[:3] in (b"ID3", b"\xff\xfb", b"\xff\xf3") and library.sfx_file("whoosh", tmp_path) == p
    with pytest.raises(video.VideoError):
        library.sfx_file("../../etc/passwd", tmp_path)


class FakeResp:
    def __init__(self, payload=None, content=b"", ctype="application/json", status=200):
        self.payload, self.content, self.status_code = payload, content, status
        self.headers = {"Content-Type": ctype}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http")

    def json(self):
        return self.payload

    def iter_content(self, n):
        yield self.content

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


ID = "0d7c2a0e-1111-4c2b-9d3e-123456789abc"


class FakeSession:
    def __init__(self, png):
        self.png, self.calls = png, []

    def get(self, url, params=None, **kw):
        self.calls.append((url, params))
        if url.endswith("/images/"):
            return FakeResp({"result_count": 1, "page_count": 1, "results": [
                {"id": ID, "title": "Kids in class", "creator": "Ann", "license": "by", "license_version": "4.0",
                 "url": "https://example.org/a.png", "foreign_landing_url": "https://example.org/p"}]})
        if url.endswith(f"/images/{ID}/"):
            return FakeResp({"id": ID, "title": "Kids in class", "creator": "Ann", "license": "by", "license_version": "4.0",
                             "url": "https://example.org/a.png", "filetype": "png"})
        if url == "https://example.org/a.png":
            return FakeResp(content=self.png, ctype="image/png")
        return FakeResp(status=404)


def test_openverse_search_and_import(store):
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (1, 2, 3)).save(buf, "PNG")
    sess = FakeSession(buf.getvalue())
    res = library.search("image", "class room", "photograph", session=sess)
    assert res["items"][0]["attribution"] == '"Kids in class" by Ann (CC BY 4.0) via Openverse'
    assert sess.calls[0][1]["license_type"] == "commercial" and sess.calls[0][1]["category"] == "photograph"
    meta = library.import_item("image", ID, store, session=sess)
    assert store.kind(meta["id"]) == "image" and store.meta(meta["id"])["attribution"].startswith('"Kids')
    with pytest.raises(video.VideoError):
        library.import_item("image", "../x", store, session=sess)


def test_library_endpoints(monkeypatch):
    import app as appmod
    c = appmod.app.test_client()
    cfg = c.get("/api/library").get_json()
    assert "star" in cfg["shapes"] and cfg["sfx"] and "educational" in cfg["music_topics"]
    m = c.post("/api/library/shape", json={"name": "star", "color": "#ff0000"}).get_json()
    assert m["kind"] == "image"
    assert c.post("/api/library/clipart", json={"char": "💡"}).status_code == 200
    assert c.get("/api/library/sfx/pop.mp3").status_code == 200
    assert c.post("/api/library/sfx/pop").get_json()["kind"] == "audio"
    monkeypatch.setattr(library, "search", lambda *a, **k: (_ for _ in ()).throw(library.LibraryError("offline")))
    assert c.get("/api/library/search?kind=audio&q=x").status_code == 400
