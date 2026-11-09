"""Tests for the video engine and API. Speech is faked with ffmpeg tones; everything else is real."""
import io
import json
import subprocess
import time
from pathlib import Path

import pytest
from PIL import Image

import app as web
import tts_module as tts
import video


# ---------------------------------------------------------------- helpers / fixtures

def ffprobe(path, entries):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", entries, "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@pytest.fixture(scope="session")
def fake_tts(tmp_path_factory):
    d = tmp_path_factory.mktemp("fake")

    def make(text, voice, rate, pitch):
        dur = max(1.2, len(text) / 20)
        out = d / "t.mp3"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=220:duration={dur}",
                        "-codec:a", "libmp3lame", "-b:a", "48k", str(out)], check=True)
        return out.read_bytes()

    return make


@pytest.fixture
def assets(tmp_path):
    return video.AssetStore(tmp_path / "assets")


def png_bytes(size=(400, 300), color=(200, 40, 40)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture(scope="session")
def mp4_bytes(tmp_path_factory):
    p = tmp_path_factory.mktemp("clip") / "c.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=2",
                    "-pix_fmt", "yuv420p", str(p)], check=True)
    return p.read_bytes()


def base_project(**over):
    p = {"size": "youtube-720", "theme": "academy", "captions": True, "quality": "draft",
         "voice": {"lang": "ar-SA", "gender": "male"},
         "scenes": [{"layout": "title", "title": "مرحبا", "body": "درس", "narration": "مرحبا بكم. هذا درس قصير."}]}
    p.update(over)
    return p


# ---------------------------------------------------------------- validation

def test_valid_project_gets_voice_and_defaults():
    p = video.validate_project(base_project())
    assert p["voice"]["voice"] == "ar-SA-HamedNeural"
    assert p["scenes"][0]["background"]["type"] == "theme"
    assert p["scenes"][0]["transition"] == "fade"


@pytest.mark.parametrize("patch,msg", [
    ({"size": "nope"}, "size"),
    ({"theme": "nope"}, "theme"),
    ({"scenes": []}, "scene"),
    ({"scenes": [{"layout": "weird", "title": "x"}]}, "layout"),
    ({"scenes": [{"layout": "title"}]}, "empty"),
    ({"scenes": [{"layout": "title", "title": "x", "duration": 0.5}]}, "duration"),
    ({"scenes": [{"layout": "title", "title": "x", "background": {"type": "image", "asset": "a" * 32}}]}, "image"),
    ({"voice": {"voice": "bad-Voice"}}, "voice"),
    ({"voice": {"lang": "ar-SA", "rate": 999}}, "range"),
])
def test_invalid_projects_rejected(patch, msg):
    with pytest.raises(video.VideoError) as e:
        video.validate_project(base_project(**patch), video.AssetStore(Path("/tmp/vf-none")))
    assert msg in str(e.value).lower()


def test_too_many_scenes_and_too_long_narration():
    scenes = [{"layout": "title", "title": "x"}] * 41
    with pytest.raises(video.VideoError):
        video.validate_project(base_project(scenes=scenes))
    big = [{"layout": "title", "title": "x", "narration": "a" * 3000}] * 8
    with pytest.raises(video.VideoError):
        video.validate_project(base_project(scenes=big))


def test_canvas_sizes():
    for key, spec in video.SIZES.items():
        full = video.canvas_size({"size": key, "quality": "final"})
        assert full == (spec["w"], spec["h"])
        draft = video.canvas_size({"size": key, "quality": "draft"})
        assert draft[0] % 2 == 0 and draft[1] % 2 == 0 and draft[0] < full[0]


def test_every_preset_ratio_is_correct():
    for spec in video.SIZES.values():
        a, b = (int(x) for x in spec["ratio"].split(":"))
        assert abs(spec["w"] / spec["h"] - a / b) < 0.01


# ---------------------------------------------------------------- text helpers

def test_is_rtl():
    assert video.is_rtl("مرحبا بالعالم") and video.is_rtl("שלום")
    assert video.is_rtl("مرحبا Hello")          # first strong character decides the paragraph direction
    assert not video.is_rtl("Hello مرحبا")
    assert not video.is_rtl("123")


def test_split_captions_and_timing():
    text = "First sentence here. Second one is a bit longer than the first one, with a comma. Third!"
    chunks = video.split_captions(text, 40)
    assert len(chunks) >= 3 and all(len(c) <= 60 for c in chunks)
    segs = video.caption_timing(chunks, 10.0)
    assert segs[0][0] == 0 and abs(segs[-1][1] - 10.0) < 1e-6
    assert all(abs(segs[i][1] - segs[i + 1][0]) < 1e-9 for i in range(len(segs) - 1))
    assert video.split_captions("") == []
    assert video.split_captions("مرحبا. كيف حالك؟ بخير.") == ["مرحبا. كيف حالك؟ بخير."]  # tiny sentences merge


def test_srt_time():
    assert video.srt_time(3661.5) == "01:01:01,500"
    assert video.srt_time(0) == "00:00:00,000"


# ---------------------------------------------------------------- drawing

@pytest.mark.parametrize("layout", video.LAYOUTS)
def test_overlay_draws_arabic_and_english_in_every_layout(layout):
    for title, body in [("أهداف الدرس", "فهم الفكرة\nتطبيق عملي"), ("Lesson goals", "Understand\nPractice")]:
        project = video.validate_project(base_project(scenes=[{"layout": layout, "title": title, "body": body}]))
        layer = video.render_overlay(project, project["scenes"][0], (640, 360), None, scrim=False)
        assert layer.size == (640, 360)
        assert layer.getchannel("A").getbbox() is not None  # something was drawn


def test_long_text_shrinks_to_fit_and_stays_in_bounds():
    body = " ".join(["كلمة"] * 200)
    project = video.validate_project(base_project(scenes=[{"layout": "text", "title": "عنوان", "body": body[:1400]}]))
    layer = video.render_overlay(project, project["scenes"][0], (1280, 720), None, scrim=False)
    box = layer.getchannel("A").getbbox()
    assert box and box[1] >= 0 and box[3] <= 720


def test_preview_png_has_requested_aspect():
    for key in ("shorts", "square", "youtube-1080"):
        project = video.validate_project(base_project(size=key))
        img = Image.open(io.BytesIO(video.render_preview_png(project, 0, None, max_width=480)))
        spec = video.SIZES[key]
        assert abs(img.width / img.height - spec["w"] / spec["h"]) < 0.02


# ---------------------------------------------------------------- assets

def test_asset_store_accepts_images_and_video(assets, mp4_bytes):
    img = assets.save(png_bytes(), "a.png")
    assert img["kind"] == "image" and assets.kind(img["id"]) == "image"
    vid = assets.save(mp4_bytes, "clip.mp4")
    assert vid["kind"] == "video" and assets.kind(vid["id"]) == "video"


def test_asset_store_rejects_bad_files(assets):
    with pytest.raises(video.VideoError):
        assets.save(b"not an image", "x.png")
    with pytest.raises(video.VideoError):
        assets.save(b"not a video", "x.mp4")
    with pytest.raises(video.VideoError):
        assets.save(b"GIF89a" + b"0" * 20, "x.gif")


def test_asset_ids_cannot_escape_the_store(assets):
    for bad in ["../etc/passwd", "..", "a" * 31, "A" * 32, "x" * 32, None, "", "../../x"]:
        assert assets.path(bad) is None


# ---------------------------------------------------------------- full render

def test_render_produces_valid_mp4_with_audio_and_srt(tmp_path, fake_tts):
    raw = base_project(scenes=[
        {"layout": "title", "title": "مقدمة", "body": "درس", "narration": "مرحبا بكم في هذا الدرس. سنبدأ الآن."},
        {"layout": "bullets", "title": "Goals", "body": "One\nTwo", "narration": "Here are the goals.", "transition": "none"},
        {"layout": "quote", "title": "Someone", "body": "A short quote", "narration": "", "duration": 2,
         "background": {"type": "color", "color": "#223344"}},
    ])
    project = video.validate_project(raw)
    steps = []
    info = video.render_project(project, tmp_path / "o.mp4", None, lambda p, m: steps.append(p), fake_tts)
    meta = ffprobe(tmp_path / "o.mp4", "stream=codec_type,codec_name,width,height:format=duration")
    kinds = {s["codec_type"] for s in meta["streams"]}
    assert kinds == {"video", "audio"}
    v = next(s for s in meta["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == video.canvas_size(project) and v["codec_name"] == "h264"
    assert abs(float(meta["format"]["duration"]) - info["duration"]) < 0.5
    assert steps[-1] == 1.0 and steps == sorted(steps)
    assert "مرحبا بكم" in info["srt"] and info["srt"].startswith("1\n00:00:00,000 -->")


def test_render_vertical_preset_and_final_quality_dimensions(tmp_path, fake_tts):
    project = video.validate_project(base_project(size="shorts", quality="draft"))
    video.render_project(project, tmp_path / "s.mp4", None, None, fake_tts)
    v = ffprobe(tmp_path / "s.mp4", "stream=width,height")["streams"][0]
    assert v["height"] > v["width"] and abs(v["width"] / v["height"] - 9 / 16) < 0.01


def test_render_with_image_and_video_backgrounds(tmp_path, assets, fake_tts, mp4_bytes):
    img = assets.save(png_bytes((800, 500), (30, 90, 160)), "bg.png")["id"]
    vid = assets.save(mp4_bytes, "bg.mp4")["id"]
    raw = base_project(scenes=[
        {"layout": "title", "title": "Image scene", "narration": "Over an image.", "background": {"type": "image", "asset": img}},
        {"layout": "text", "title": "Video scene", "body": "Text over moving footage", "narration": "Over a video. It loops under the narration while captions appear.",
         "background": {"type": "video", "asset": vid}},
    ])
    project = video.validate_project(raw, assets)
    info = video.render_project(project, tmp_path / "bg.mp4", assets, None, fake_tts)
    assert info["duration"] > 3
    assert {s["codec_type"] for s in ffprobe(tmp_path / "bg.mp4", "stream=codec_type")["streams"]} == {"video", "audio"}


def test_failed_speech_surfaces_as_error(tmp_path):
    def boom(*a):
        raise tts.TTSUnavailable("no network")

    project = video.validate_project(base_project())
    with pytest.raises(tts.TTSUnavailable):
        video.render_project(project, tmp_path / "x.mp4", None, None, boom)
    assert not list(tmp_path.glob("vf-render-*"))  # temp work dir cleaned up


# ---------------------------------------------------------------- job manager

def wait(mgr, job_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        job = mgr.get(job_id)
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.2)
    raise AssertionError("job timed out")


def test_job_manager_success_and_failure(tmp_path, fake_tts):
    mgr = video.JobManager(tmp_path)
    ok = mgr.submit(video.validate_project(base_project()), fake_tts)
    job = wait(mgr, ok)
    assert job["status"] == "done" and mgr.file(ok, "video.mp4").stat().st_size > 1000
    assert mgr.file(ok, "captions.srt").read_text(encoding="utf-8").startswith("1\n")
    assert mgr.file(ok, "../job.json") is None

    def boom(*a):
        raise tts.TTSUnavailable("Speech service unavailable: x")

    bad = wait(mgr, mgr.submit(video.validate_project(base_project()), boom))
    assert bad["status"] == "error" and "unavailable" in bad["error"].lower()


def test_job_state_is_visible_from_a_second_manager(tmp_path, fake_tts):
    a, b = video.JobManager(tmp_path), video.JobManager(tmp_path)  # like two gunicorn workers
    job_id = a.submit(video.validate_project(base_project()), fake_tts)
    assert wait(b, job_id)["status"] == "done"


def test_busy_server_rejects_extra_jobs(tmp_path, fake_tts, monkeypatch):
    mgr = video.JobManager(tmp_path)
    monkeypatch.setattr(mgr, "active_count", lambda: video.JobManager.MAX_ACTIVE)
    with pytest.raises(video.VideoError):
        mgr.submit(video.validate_project(base_project()), fake_tts)


def test_stale_running_jobs_are_reported_as_interrupted(tmp_path):
    mgr = video.JobManager(tmp_path)
    jid = "a" * 32
    d = mgr.jobs_dir / jid
    d.mkdir()
    (d / "job.json").write_text(json.dumps({"id": jid, "status": "running", "progress": 0.3, "message": "x",
                                           "error": None, "duration": None, "dir": str(d)}))
    old = time.time() - 3600
    import os
    os.utime(d / "job.json", (old, old))
    assert mgr.get(jid)["status"] == "error"


# ---------------------------------------------------------------- HTTP API

@pytest.fixture
def client(tmp_path, monkeypatch, fake_tts):
    monkeypatch.setattr(web, "jobs", video.JobManager(tmp_path))
    monkeypatch.setattr(tts, "synthesize_mp3", fake_tts)
    web.app.config.update(TESTING=True)
    return web.app.test_client()


def test_video_config_lists_sizes_themes_and_presets(client):
    data = client.get("/api/video/config").get_json()
    ids = {s["id"] for s in data["sizes"]}
    assert {"youtube-1080", "shorts", "square", "portrait", "classroom"} <= ids
    assert {"academy", "chalkboard", "clean", "bold", "midnight"} == {t["id"] for t in data["themes"]}
    lesson = next(p for p in data["presets"] if p["id"] == "lesson")
    assert lesson["scenes"]["ar"] and lesson["scenes"]["en"] and lesson["size"] == "youtube-1080"


def test_upload_preview_render_download_flow(client):
    up = client.post("/api/video/assets", data={"file": (io.BytesIO(png_bytes()), "bg.png")}, content_type="multipart/form-data")
    assert up.status_code == 200
    asset = up.get_json()["id"]
    project = base_project(scenes=[{"layout": "title", "title": "مرحبا", "narration": "مرحبا بكم.",
                                    "background": {"type": "image", "asset": asset}}])

    prev = client.post("/api/video/preview", json={"project": project, "index": 0})
    assert prev.status_code == 200 and prev.mimetype == "image/png"
    assert Image.open(io.BytesIO(prev.data)).width > 100

    r = client.post("/api/video/render", json={"project": project})
    assert r.status_code == 202
    job_id = r.get_json()["job_id"]
    for _ in range(300):
        st = client.get(f"/api/video/jobs/{job_id}").get_json()
        if st["status"] in ("done", "error"):
            break
        time.sleep(0.2)
    assert st["status"] == "done", st
    mp4 = client.get(f"/api/video/jobs/{job_id}/video.mp4?download=1")
    assert mp4.status_code == 200 and mp4.mimetype == "video/mp4" and "attachment" in mp4.headers["Content-Disposition"]
    assert mp4.data[4:8] == b"ftyp"
    srt = client.get(f"/api/video/jobs/{job_id}/captions.srt")
    assert srt.status_code == 200 and "مرحبا بكم" in srt.data.decode("utf-8")


def test_api_rejects_bad_input_and_unknown_files(client):
    assert client.post("/api/video/render", json={"project": {"scenes": []}}).status_code == 400
    assert client.post("/api/video/render", json={}).status_code == 400
    assert client.post("/api/video/assets", data={"file": (io.BytesIO(b"junk"), "x.png")}, content_type="multipart/form-data").status_code == 400
    assert client.post("/api/video/assets").status_code == 400
    assert client.get("/api/video/jobs/nothing").status_code == 404
    assert client.get("/api/video/jobs/" + "0" * 32).status_code == 404
    assert client.get("/api/video/jobs/" + "0" * 32 + "/video.mp4").status_code == 404
    assert client.post("/api/video/preview", json={"project": base_project(), "index": 9}).status_code == 400


def test_job_file_names_cannot_traverse(client):
    for name in ["job.json", "..%2Fjob.json", "etc"]:
        assert client.get(f"/api/video/jobs/{'0' * 32}/{name}").status_code in (404, 405)  # refused either way


def test_video_endpoints_respect_login_gate(client, monkeypatch):
    monkeypatch.setattr(web, "REQUIRE_LOGIN", True)
    assert client.post("/api/video/render", json={"project": base_project()}).status_code == 401
    assert client.post("/api/video/preview", json={"project": base_project(), "index": 0}).status_code == 401
    assert client.post("/api/video/assets", data={"file": (io.BytesIO(png_bytes()), "a.png")}, content_type="multipart/form-data").status_code == 401
    assert client.get("/api/video/config").status_code == 200  # public info


def test_preview_ignores_other_unfinished_scenes_but_render_does_not(client):
    project = base_project(scenes=[
        {"layout": "title", "title": "Done", "narration": "ok"},
        {"layout": "title", "title": "", "body": "", "narration": ""},       # freshly added, still empty
    ])
    for i in (0, 1):  # the finished scene and the empty one both preview fine
        assert client.post("/api/video/preview", json={"project": project, "index": i}).status_code == 200
    r = client.post("/api/video/render", json={"project": project})
    assert r.status_code == 400 and "empty" in r.get_json()["error"].lower()
