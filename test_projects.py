"""Saved projects: store, per-user isolation, bundles, and the HTTP API."""
import io
import json
import time
import zipfile

import pytest
from PIL import Image

import app as web
import projects as pj
import video


def png(size=(200, 120), color=(10, 120, 200)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def proj(**over):
    p = {"ratio": "16:9", "resolution": "1080", "theme": "academy", "captions": True,
         "voice": {"lang": "ar-SA", "gender": "male", "voice": "", "rate": 0, "pitch": 0},
         "scenes": [{"layout": "title", "title": "مرحبا", "body": "", "narration": "", "background": {"type": "theme"}}]}
    p.update(over)
    return p


OWNER_A, OWNER_B = "a" * 32, "b" * 32


@pytest.fixture
def store(tmp_path):
    return pj.ProjectStore(tmp_path / "projects")


# ---------------------------------------------------------------- store

def test_create_list_open_update_delete(store):
    first = store.save(OWNER_A, "  My   first lesson ", proj())
    assert first["name"] == "My first lesson"
    assert [p["name"] for p in store.list(OWNER_A)] == ["My first lesson"]
    assert store.list(OWNER_A)[0]["scenes"] == 1 and store.list(OWNER_A)[0]["ratio"] == "16:9"
    rec = store.get(OWNER_A, first["id"])
    assert rec["project"]["scenes"][0]["title"] == "مرحبا"
    time.sleep(0.01)
    store.save(OWNER_A, "Renamed", proj(theme="clean"), first["id"])          # update in place
    assert len(store.list(OWNER_A)) == 1 and store.get(OWNER_A, first["id"])["name"] == "Renamed"
    store.delete(OWNER_A, first["id"])
    assert store.list(OWNER_A) == []
    with pytest.raises(pj.ProjectError):
        store.get(OWNER_A, first["id"])


def test_most_recent_project_is_listed_first(store):
    a = store.save(OWNER_A, "old", proj())
    time.sleep(0.02)
    b = store.save(OWNER_A, "new", proj())
    assert [p["id"] for p in store.list(OWNER_A)] == [b["id"], a["id"]]


def test_duplicate_makes_an_independent_copy(store):
    a = store.save(OWNER_A, "Lesson", proj())
    b = store.duplicate(OWNER_A, a["id"])
    assert b["id"] != a["id"] and b["name"] == "Lesson (copy)"
    store.save(OWNER_A, "Lesson", proj(theme="bold"), a["id"])
    assert store.get(OWNER_A, b["id"])["project"]["theme"] == "academy"


def test_names_are_cleaned_and_defaulted():
    assert pj.clean_name("") == "Untitled project" and pj.clean_name(None) == "Untitled project"
    assert len(pj.clean_name("x" * 500)) == 80 and pj.clean_name("a\n\n b\t c") == "a b c"


def test_users_cannot_see_or_touch_each_others_projects(store):
    a = store.save(OWNER_A, "private", proj())
    assert store.list(OWNER_B) == []
    for call in (lambda: store.get(OWNER_B, a["id"]), lambda: store.delete(OWNER_B, a["id"]),
                 lambda: store.save(OWNER_B, "x", proj(), a["id"]), lambda: store.duplicate(OWNER_B, a["id"])):
        with pytest.raises(pj.ProjectError):
            call()
    assert store.get(OWNER_A, a["id"])["name"] == "private"


def test_bad_ids_and_owners_are_refused(store):
    for pid in ["../x", "..", "x" * 16, "", None, "A" * 16]:
        with pytest.raises(pj.ProjectError):
            store.get(OWNER_A, pid)
    for owner in ["../etc", "", "x", None]:
        with pytest.raises(pj.ProjectError):
            store.list(owner)


def test_invalid_and_oversized_projects_are_refused(store, monkeypatch):
    for bad in [None, [], {}, {"scenes": "nope"}]:
        with pytest.raises(pj.ProjectError):
            store.save(OWNER_A, "x", bad)
    big = proj()
    big["scenes"][0]["body"] = "x" * (pj.MAX_PROJECT_BYTES + 10)
    with pytest.raises(pj.ProjectError):
        store.save(OWNER_A, "x", big)
    monkeypatch.setattr(pj, "MAX_PROJECTS_PER_OWNER", 2)
    store.save(OWNER_A, "1", proj()), store.save(OWNER_A, "2", proj())
    with pytest.raises(pj.ProjectError):
        store.save(OWNER_A, "3", proj())


def test_referenced_assets_covers_backgrounds_media_and_music(store):
    ids = [f"{c}" * 32 for c in "123"] + ["4" * 32]
    p = proj(music={"asset": ids[2], "volume": 0.2})
    p["scenes"] = [{"layout": "media", "title": "x", "background": {"type": "image", "asset": ids[0]}, "media": {"asset": ids[1]}},
                   {"layout": "title", "title": "y", "background": {"type": "theme"}}]
    store.save(OWNER_A, "m", p)
    assert store.referenced_assets() == {ids[0], ids[1], ids[2]}
    assert sorted(pj.asset_ids(p)) == sorted(ids[:3])


# ---------------------------------------------------------------- bundles

@pytest.fixture
def stores(tmp_path):
    mgr = video.JobManager(tmp_path)
    return pj.ProjectStore(tmp_path / "projects"), mgr


def test_bundle_round_trip_moves_the_media_with_the_project(stores):
    store, mgr = stores
    a_assets, b_assets = mgr.assets_for(OWNER_A), mgr.assets_for(OWNER_B)
    pic = a_assets.save(png((300, 200), (255, 0, 0)), "photo.png")["id"]
    p = proj()
    p["scenes"] = [{"layout": "media", "title": "x", "background": {"type": "theme"}, "media": {"asset": pic, "fit": "cover"}}]
    saved = store.save(OWNER_A, "With photo", p)
    data = store.export_bundle(OWNER_A, saved["id"], a_assets)
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert "project.json" in names and any(n.startswith("assets/") and n.endswith(".png") for n in names)

    imported = store.import_bundle(OWNER_B, data, b_assets)                    # a different user imports it
    got = store.get(OWNER_B, imported["id"])
    new_id = got["project"]["scenes"][0]["media"]["asset"]
    assert got["name"] == "With photo" and new_id != pic
    assert b_assets.path(new_id) is not None and b_assets.meta(new_id)["name"] == "photo.png"
    assert got["project"]["scenes"][0]["media"]["fit"] == "cover"


def test_importing_plain_json_drops_media_the_user_does_not_have(stores):
    store, mgr = stores
    p = proj(music={"asset": "c" * 32, "volume": 0.3})
    p["scenes"] = [{"layout": "media", "title": "x", "background": {"type": "image", "asset": "d" * 32},
                    "media": {"asset": "e" * 32}}]
    out = store.import_bundle(OWNER_A, json.dumps({"name": "From file", "project": p}).encode(), mgr.assets_for(OWNER_A))
    got = store.get(OWNER_A, out["id"])["project"]
    assert got["music"] is None and got["scenes"][0]["media"] is None and got["scenes"][0]["background"]["type"] == "theme"
    video.validate_project(got, mgr.assets_for(OWNER_A))                       # the cleaned project is renderable


def test_import_rejects_garbage_and_zip_bombs(stores):
    store, mgr = stores
    a = mgr.assets_for(OWNER_A)
    for junk in [b"hello", b"PK\x03\x04broken", b"[]", b"{}", json.dumps({"project": {"nope": 1}}).encode()]:
        with pytest.raises(pj.ProjectError):
            store.import_bundle(OWNER_A, junk, a)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("project.json", json.dumps({"project": proj()}))
        for i in range(600):
            z.writestr(f"assets/{i:032x}.png", b"x")
    with pytest.raises(pj.ProjectError):
        store.import_bundle(OWNER_A, buf.getvalue(), a)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../../evil.txt", b"x")
        z.writestr("project.json", json.dumps({"project": proj()}))
    store.import_bundle(OWNER_A, buf.getvalue(), a)                           # path tricks are ignored, not extracted
    assert not list(a.root.parent.glob("**/evil*"))


# ---------------------------------------------------------------- HTTP API

@pytest.fixture
def client(tmp_path, monkeypatch):
    mgr = video.JobManager(tmp_path)
    monkeypatch.setattr(web, "jobs", mgr)
    monkeypatch.setattr(web, "projects", pj.ProjectStore(tmp_path / "projects"))
    mgr.referenced_fn = web.projects.referenced_assets
    web.app.config.update(TESTING=True)
    return web.app.test_client()


def test_save_open_rename_duplicate_delete_over_http(client):
    r = client.post("/api/projects", json={"name": "Lesson 1", "project": proj()})
    assert r.status_code == 200
    pid = r.get_json()["id"]
    assert [p["name"] for p in client.get("/api/projects").get_json()["projects"]] == ["Lesson 1"]
    assert client.get(f"/api/projects/{pid}").get_json()["project"]["theme"] == "academy"
    assert client.post("/api/projects", json={"id": pid, "name": "Lesson 1 v2", "project": proj(theme="bold")}).status_code == 200
    got = client.get(f"/api/projects/{pid}").get_json()
    assert got["name"] == "Lesson 1 v2" and got["project"]["theme"] == "bold"
    copy = client.post(f"/api/projects/{pid}/duplicate", json={"name": "Copy"}).get_json()
    assert len(client.get("/api/projects").get_json()["projects"]) == 2
    assert client.delete(f"/api/projects/{copy['id']}").status_code == 200
    assert client.delete(f"/api/projects/{copy['id']}").status_code == 404
    assert client.get(f"/api/projects/{'0' * 16}").status_code == 404


def test_projects_are_private_to_each_browser(client):
    pid = client.post("/api/projects", json={"name": "mine", "project": proj()}).get_json()["id"]
    stranger = web.app.test_client()
    assert stranger.get("/api/projects").get_json()["projects"] == []
    assert stranger.get(f"/api/projects/{pid}").status_code == 404
    assert stranger.delete(f"/api/projects/{pid}").status_code == 404
    assert stranger.get(f"/api/projects/{pid}/bundle").status_code == 404
    assert stranger.post("/api/projects", json={"id": pid, "name": "hijack", "project": proj()}).status_code == 400


def test_the_same_browser_keeps_its_projects_across_requests(client):
    client.post("/api/projects", json={"name": "persist", "project": proj()})
    assert client.get_cookie("vf_uid") is not None                   # the browser was given an id on first use
    assert len(client.get("/api/projects").get_json()["projects"]) == 1


def test_export_and_import_a_bundle_over_http(client):
    pic = client.post("/api/video/assets", data={"file": (io.BytesIO(png()), "photo.png")}, content_type="multipart/form-data").get_json()["id"]
    p = proj()
    p["scenes"] = [{"layout": "media", "title": "x", "background": {"type": "theme"}, "media": {"asset": pic}}]
    pid = client.post("/api/projects", json={"name": "Bundle me", "project": p}).get_json()["id"]
    r = client.get(f"/api/projects/{pid}/bundle")
    assert r.status_code == 200 and r.mimetype == "application/zip" and ".voiceforge.zip" in r.headers["Content-Disposition"]

    friend = web.app.test_client()
    up = friend.post("/api/projects/import", data={"file": (io.BytesIO(r.data), "x.zip")}, content_type="multipart/form-data")
    assert up.status_code == 200
    got = friend.get(f"/api/projects/{up.get_json()['id']}").get_json()
    assert got["name"] == "Bundle me"
    new_id = got["project"]["scenes"][0]["media"]["asset"]
    assert new_id != pic and friend.get(f"/api/assets/{new_id}/thumb").status_code == 200
    assert friend.post("/api/projects/import").status_code == 400
    assert friend.post("/api/projects/import", data={"file": (io.BytesIO(b"nope"), "x.zip")}, content_type="multipart/form-data").status_code == 400


def test_saved_projects_keep_their_media_but_unused_files_expire(client, tmp_path):
    import os

    kept = client.post("/api/video/assets", data={"file": (io.BytesIO(png()), "kept.png")}, content_type="multipart/form-data").get_json()["id"]
    gone = client.post("/api/video/assets", data={"file": (io.BytesIO(png((50, 50))), "gone.png")}, content_type="multipart/form-data").get_json()["id"]
    p = proj()
    p["scenes"] = [{"layout": "media", "title": "x", "background": {"type": "theme"}, "media": {"asset": kept}}]
    client.post("/api/projects", json={"name": "keeper", "project": p})
    old = time.time() - 3 * 86400
    for store_dir in (tmp_path / "assets").iterdir():
        for f in store_dir.glob("*.json"):
            os.utime(f, (old, old))
    web.jobs.cleanup()
    ids = {a["id"] for a in client.get("/api/assets").get_json()["assets"]}
    assert ids == {kept} and gone not in ids


# ---------------------------------------------------------------- security

def test_security_headers_and_no_open_cors():
    import app as appmod
    r = appmod.app.test_client().get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and "frame-ancestors 'self'" in r.headers["Content-Security-Policy"]
    assert "microphone=(self)" in r.headers["Permissions-Policy"] and "Access-Control-Allow-Origin" not in r.headers


def test_rate_limit_returns_429(monkeypatch):
    import app as appmod
    import security
    monkeypatch.setitem(security.LIMITS, "api_translate", (2, 60))
    security._hits.clear()
    c = appmod.app.test_client()
    codes = [c.post("/api/translate", json={"text": ""}, environ_base={"REMOTE_ADDR": "10.0.0.9"}).status_code for _ in range(3)]
    assert codes[:2] == [400, 400] and codes[2] == 429
    # another client is not affected; spoofed proxy headers from a non-local address are ignored
    assert c.post("/api/translate", json={"text": ""}, environ_base={"REMOTE_ADDR": "10.0.0.8"}).status_code == 400
    assert c.post("/api/translate", json={"text": ""}, headers={"X-Forwarded-For": "1.2.3.4"},
                  environ_base={"REMOTE_ADDR": "10.0.0.9"}).status_code == 429


def test_playlist_disguised_as_video_is_refused(tmp_path):
    import video
    store = video.AssetStore(tmp_path / "a")
    hls = b"#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:10.0,\nfile:///etc/passwd\n#EXT-X-ENDLIST\n"
    for name in ("evil.mp4", "evil.mp3", "evil.weba"):
        with pytest.raises(video.VideoError):
            store.save(hls, name)
    assert not any(store.root.iterdir())


def test_adsense_off_by_default_and_configurable(monkeypatch):
    import importlib
    import app as appmod
    c = appmod.app.test_client()
    assert c.get("/api/config").get_json()["ads"] is None and c.get("/ads.txt").status_code == 404
    monkeypatch.setenv("ADSENSE_CLIENT", "ca-pub-1234567890123456")
    monkeypatch.setenv("ADSENSE_SLOTS", "top=1111111111,bad=1,footer=x")
    client, slots = appmod._adsense()
    assert client == "ca-pub-1234567890123456" and slots == {"top": "1111111111"}
    monkeypatch.setattr(appmod, "ADSENSE_CLIENT", client)
    assert c.get("/ads.txt").data.decode() == "google.com, pub-1234567890123456, DIRECT, f08c47fec0942fa0\n"
    assert "pagead2.googlesyndication.com" in c.get("/").headers["Content-Security-Policy"]
    monkeypatch.setenv("ADSENSE_CLIENT", "<script>")
    assert appmod._adsense() == ("", {})
