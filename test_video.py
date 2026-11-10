"""Tests for the video engine and API. Speech is faked with ffmpeg tones; everything else is real."""
import io
import json
import os
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

    def make(text, voice, rate, pitch, **_):
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


@pytest.fixture(scope="session")
def music_bytes(tmp_path_factory):
    p = tmp_path_factory.mktemp("music") / "m.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=3",
                    "-codec:a", "libmp3lame", "-b:a", "64k", str(p)], check=True)
    return p.read_bytes()


def base_project(**over):
    p = {"ratio": "16:9", "resolution": "480", "theme": "academy", "captions": True,
         "voice": {"lang": "ar-SA", "gender": "male"},
         "scenes": [{"layout": "title", "title": "مرحبا", "body": "درس", "narration": "مرحبا بكم. هذا درس قصير."}]}
    p.update(over)
    return p


# ---------------------------------------------------------------- ratios and resolutions

def test_standard_sizes():
    assert video.dimensions("16:9", "720") == (1280, 720)
    assert video.dimensions("16:9", "1080") == (1920, 1080)
    assert video.dimensions("16:9", "1440") == (2560, 1440)      # 2K
    assert video.dimensions("16:9", "2160") == (3840, 2160)      # 4K
    assert video.dimensions("9:16", "1080") == (1080, 1920)
    assert video.dimensions("1:1", "1080") == (1080, 1080)
    assert video.dimensions("4:5", "1080") == (1080, 1350)
    assert video.dimensions("4:3", "1080") == (1440, 1080)


@pytest.mark.parametrize("ratio", list(video.RATIOS))
@pytest.mark.parametrize("res", list(video.RESOLUTIONS))
def test_every_ratio_and_resolution_is_even_and_correct(ratio, res):
    w, h = video.dimensions(ratio, res)
    assert w % 2 == 0 and h % 2 == 0
    assert min(w, h) == video.RESOLUTIONS[res]["short"]
    a, b = video.RATIOS[ratio]["w"], video.RATIOS[ratio]["h"]
    assert abs(w / h - a / b) < 0.01


def test_labels_name_hd_2k_4k():
    labels = " ".join(r["label"] for r in video.RESOLUTIONS.values())
    assert "HD 720p" in labels and "Full HD 1080p" in labels and "2K" in labels and "4K" in labels


# ---------------------------------------------------------------- validation

def test_valid_project_gets_voice_and_defaults():
    p = video.validate_project(base_project())
    assert p["voice"]["voice"] == "ar-SA-HamedNeural"
    assert (p["ratio"], p["resolution"]) == ("16:9", "480")
    assert p["scenes"][0]["background"]["type"] == "theme" and p["scenes"][0]["transition"] == "fade"
    assert p["music"] is None and p["scenes"][0]["media"] is None


def test_projects_from_the_first_version_still_load():
    old = base_project(size="shorts")
    old.pop("ratio"), old.pop("resolution")
    p = video.validate_project(old)
    assert (p["ratio"], p["resolution"]) == ("9:16", "1080")
    old["quality"] = "draft"
    assert video.validate_project(old)["resolution"] == "480"


@pytest.mark.parametrize("patch,msg", [
    ({"ratio": "5:7"}, "ratio"),
    ({"resolution": "8000"}, "resolution"),
    ({"theme": "nope"}, "theme"),
    ({"scenes": []}, "scene"),
    ({"scenes": [{"layout": "weird", "title": "x"}]}, "layout"),
    ({"scenes": [{"layout": "title"}]}, "empty"),
    ({"scenes": [{"layout": "title", "title": "x", "duration": 0.5}]}, "duration"),
    ({"scenes": [{"layout": "title", "title": "x", "background": {"type": "image", "asset": "a" * 32}}]}, "image"),
    ({"scenes": [{"layout": "media", "title": "x", "media": {"asset": "a" * 32}}]}, "picture"),
    ({"music": {"asset": "a" * 32}}, "music"),
    ({"voice": {"voice": "bad-Voice"}}, "voice"),
    ({"voice": {"lang": "ar-SA", "rate": 999}}, "range"),
])
def test_invalid_projects_rejected(patch, msg, tmp_path):
    with pytest.raises(video.VideoError) as e:
        video.validate_project(base_project(**patch), video.AssetStore(tmp_path / "none"))
    assert msg in str(e.value).lower()


def test_limits_scale_with_configuration():
    scenes = [{"layout": "title", "title": "x"}] * (video.LIMITS["max_scenes"] + 1)
    with pytest.raises(video.VideoError):
        video.validate_project(base_project(scenes=scenes))
    long_scene = {"layout": "title", "title": "x", "narration": "a" * (video.LIMITS["max_narration"] + 1)}
    with pytest.raises(video.VideoError):
        video.validate_project(base_project(scenes=[long_scene]))
    ok = {"layout": "title", "title": "x", "narration": "a" * 15000}   # used to stop at 3,000 characters
    assert video.validate_project(base_project(scenes=[ok]))["scenes"][0]["narration"]


# ---------------------------------------------------------------- text helpers

def test_is_rtl():
    assert video.is_rtl("مرحبا بالعالم") and video.is_rtl("שלום")
    assert video.is_rtl("مرحبا Hello")
    assert not video.is_rtl("Hello مرحبا") and not video.is_rtl("123")


def test_split_captions_and_timing():
    text = "First sentence here. Second one is a bit longer than the first one, with a comma. Third!"
    chunks = video.split_captions(text, 40)
    assert len(chunks) >= 3 and all(len(c) <= 60 for c in chunks)
    segs = video.caption_timing(chunks, 10.0)
    assert segs[0][0] == 0 and abs(segs[-1][1] - 10.0) < 1e-6
    assert video.split_captions("") == []
    assert video.split_captions("مرحبا. كيف حالك؟ بخير.") == ["مرحبا. كيف حالك؟ بخير."]  # tiny sentences merge


def test_srt_time():
    assert video.srt_time(3661.5) == "01:01:01,500" and video.srt_time(0) == "00:00:00,000"


# ---------------------------------------------------------------- slide layout and drawing

def scene_with_media(layout="bullets", **media):
    return {"layout": layout, "title": "Lesson goals", "body": "One\nTwo", "narration": "x", "background": {"type": "theme"},
            "media": {"asset": "a" * 32, "position": "auto", "fit": "contain", **media}}


def rects_overlap(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def test_media_regions_side_by_side_on_widescreen_and_stacked_on_vertical():
    proj = {"captions": True}
    land = video.regions(proj, scene_with_media(), (1920, 1080))
    assert land["media"] and not rects_overlap(land["text"], land["media"])
    assert land["media"][0] > land["text"][0]                      # LTR text -> media on the right
    rtl = dict(scene_with_media(), title="أهداف الدرس", body="فهم\nتطبيق")
    rl = video.regions(proj, rtl, (1920, 1080))
    assert rl["media"][2] < rl["text"][2]                          # Arabic text -> media on the left
    tall = video.regions(proj, scene_with_media(), (1080, 1920))
    assert tall["media"][3] <= tall["text"][1] + 1                 # media on top, text below
    assert not rects_overlap(tall["text"], tall["media"])


def test_media_never_overlaps_the_caption_band():
    proj = {"captions": True}
    for size in [(1920, 1080), (1080, 1920), (1080, 1080), (1080, 1350)]:
        for layout in ("bullets", "media"):
            reg = video.regions(proj, scene_with_media(layout), size)
            assert reg["media"][3] <= size[1] * 0.77


def test_title_and_quote_layouts_ignore_media():
    for layout in ("title", "quote"):
        assert video.regions({"captions": True}, scene_with_media(layout), (1920, 1080))["media"] is None


@pytest.mark.parametrize("layout", video.LAYOUTS)
def test_overlay_draws_arabic_and_english_in_every_layout(layout):
    for title, body in [("أهداف الدرس", "فهم الفكرة\nتطبيق عملي"), ("Lesson goals", "Understand\nPractice")]:
        project = video.validate_project(base_project(scenes=[{"layout": layout, "title": title, "body": body}]))
        layer = video.render_overlay(project, project["scenes"][0], (640, 360), None, scrim=False)
        assert layer.size == (640, 360) and layer.getchannel("A").getbbox() is not None


def test_overlay_places_the_picture_inside_its_region(assets):
    aid = assets.save(png_bytes((600, 400), (250, 20, 20)), "p.png")["id"]
    raw = base_project(scenes=[{"layout": "bullets", "title": "T", "body": "a\nb", "narration": "n",
                                "media": {"asset": aid, "position": "right"}}])
    project = video.validate_project(raw, assets)
    scene = project["scenes"][0]
    size = (1280, 720)
    reg = video.regions(project, scene, size)
    pic = Image.new("RGB", (600, 400), (250, 20, 20))
    layer = video.render_overlay(project, scene, size, None, False, pic)
    x0, y0, x1, y1 = [int(v) for v in reg["media"]]
    r, g, b, a = layer.getpixel(((x0 + x1) // 2, (y0 + y1) // 2))
    assert a == 255 and r > 200 and g < 80                          # the red picture fills the middle of its region


def test_long_text_shrinks_to_fit_and_stays_in_bounds():
    body = " ".join(["كلمة"] * 200)
    project = video.validate_project(base_project(scenes=[{"layout": "text", "title": "عنوان", "body": body[:1400]}]))
    layer = video.render_overlay(project, project["scenes"][0], (1280, 720), None, scrim=False)
    box = layer.getchannel("A").getbbox()
    assert box and box[1] >= 0 and box[3] <= 720


def test_preview_png_has_requested_aspect():
    for ratio in video.RATIOS:
        project = video.validate_project(base_project(ratio=ratio))
        img = Image.open(io.BytesIO(video.render_preview_png(project, 0, None, max_width=480)))
        spec = video.RATIOS[ratio]
        assert abs(img.width / img.height - spec["w"] / spec["h"]) < 0.02


# ---------------------------------------------------------------- assets

def test_asset_store_accepts_image_video_audio_and_lists_them(assets, mp4_bytes, music_bytes):
    img = assets.save(png_bytes(), "my photo.png")
    vid = assets.save(mp4_bytes, "clip.mp4")
    aud = assets.save(music_bytes, "song.mp3")
    assert (img["kind"], vid["kind"], aud["kind"]) == ("image", "video", "audio")
    assert {a["name"] for a in assets.list()} == {"my photo.png", "clip.mp4", "song.mp3"}
    assert assets.thumb(img["id"]).exists() and assets.thumb(vid["id"]).exists()
    assert assets.thumb(aud["id"]) is None                          # audio has no picture
    assert assets.delete(img["id"]) and assets.path(img["id"]) is None and not assets.delete(img["id"])


def test_asset_store_rejects_bad_files_and_enforces_quota(assets, monkeypatch):
    for data, name in [(b"not an image", "x.png"), (b"not a video", "x.mp4"), (b"not audio", "x.mp3"), (b"GIF89a" + b"0" * 20, "x.gif")]:
        with pytest.raises(video.VideoError):
            assets.save(data, name)
    monkeypatch.setitem(video.LIMITS, "owner_quota_bytes", 100)
    with pytest.raises(video.VideoError) as e:
        assets.save(png_bytes((300, 300)), "big.png")
    assert "storage" in str(e.value).lower()


def test_asset_ids_cannot_escape_the_store(assets):
    for bad in ["../etc/passwd", "..", "a" * 31, "A" * 32, "x" * 32, None, "", "../../x"]:
        assert assets.path(bad) is None


def test_file_names_are_sanitised(assets):
    meta = assets.save(png_bytes(), "../../evil name<>.png")
    assert "/" not in meta["name"] and "<" not in meta["name"]


# ---------------------------------------------------------------- full renders

def streams(path):
    meta = ffprobe(path, "stream=codec_type,codec_name,width,height:format=duration")
    return meta, {s["codec_type"]: s for s in meta["streams"]}


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
    meta, by = streams(tmp_path / "o.mp4")
    assert set(by) == {"video", "audio"} and by["video"]["codec_name"] == "h264"
    assert (by["video"]["width"], by["video"]["height"]) == video.canvas_size(project)
    assert abs(float(meta["format"]["duration"]) - info["duration"]) < 0.5
    assert steps[-1] == 1.0 and steps == sorted(steps)
    assert "مرحبا بكم" in info["srt"] and info["srt"].startswith("1\n00:00:00,000 -->")


@pytest.mark.parametrize("ratio,expect_ratio", [("9:16", 9 / 16), ("1:1", 1.0), ("4:5", 0.8), ("4:3", 4 / 3), ("21:9", 21 / 9)])
def test_render_every_aspect_ratio(tmp_path, fake_tts, ratio, expect_ratio):
    project = video.validate_project(base_project(ratio=ratio))
    video.render_project(project, tmp_path / "r.mp4", None, None, fake_tts)
    v = streams(tmp_path / "r.mp4")[1]["video"]
    assert abs(v["width"] / v["height"] - expect_ratio) < 0.02


@pytest.mark.parametrize("res,size", [("720", (1280, 720)), ("1440", (2560, 1440)), ("2160", (3840, 2160))])
def test_render_hd_2k_and_4k(tmp_path, fake_tts, res, size):
    raw = base_project(resolution=res, scenes=[{"layout": "title", "title": "Resolution test", "body": res + "p", "duration": 2}])
    video.render_project(video.validate_project(raw), tmp_path / "hd.mp4", None, None, fake_tts)
    v = streams(tmp_path / "hd.mp4")[1]["video"]
    assert (v["width"], v["height"]) == size


def test_render_with_image_and_video_backgrounds(tmp_path, assets, fake_tts, mp4_bytes):
    img = assets.save(png_bytes((800, 500), (30, 90, 160)), "bg.png")["id"]
    vid = assets.save(mp4_bytes, "bg.mp4")["id"]
    raw = base_project(scenes=[
        {"layout": "title", "title": "Image scene", "narration": "Over an image.", "background": {"type": "image", "asset": img}},
        {"layout": "text", "title": "Video scene", "body": "Text over moving footage",
         "narration": "Over a video. It loops under the narration while captions appear.",
         "background": {"type": "video", "asset": vid}},
    ])
    project = video.validate_project(raw, assets)
    info = video.render_project(project, tmp_path / "bg.mp4", assets, None, fake_tts)
    assert info["duration"] > 3 and set(streams(tmp_path / "bg.mp4")[1]) == {"video", "audio"}


def test_render_with_picture_and_video_inside_scenes(tmp_path, assets, fake_tts, mp4_bytes):
    pic = assets.save(png_bytes((640, 400), (20, 160, 60)), "chart.png")["id"]
    clip = assets.save(mp4_bytes, "demo.mp4")["id"]
    bgv = assets.save(mp4_bytes, "bg.mp4")["id"]
    raw = base_project(scenes=[
        {"layout": "bullets", "title": "With picture", "body": "a\nb", "narration": "A picture sits beside the points.",
         "media": {"asset": pic, "position": "auto"}},
        {"layout": "media", "title": "With clip", "body": "Caption under the clip", "narration": "A clip plays inside the slide.",
         "media": {"asset": clip, "fit": "contain"}},
        {"layout": "text", "title": "Clip over video", "body": "both", "narration": "A clip over a video background.",
         "background": {"type": "video", "asset": bgv}, "media": {"asset": clip, "position": "left", "fit": "cover"}},
    ])
    project = video.validate_project(raw, assets)
    info = video.render_project(project, tmp_path / "m.mp4", assets, None, fake_tts)
    assert info["duration"] > 4 and set(streams(tmp_path / "m.mp4")[1]) == {"video", "audio"}


def test_a_video_clip_really_appears_inside_the_slide(tmp_path, assets, fake_tts):
    solid = tmp_path / "red.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0xff0000:s=320x240:r=15:d=2",
                    "-pix_fmt", "yuv420p", str(solid)], check=True)
    clip = assets.save(solid.read_bytes(), "red.mp4")["id"]
    raw = base_project(captions=False, scenes=[{"layout": "media", "title": "Clip", "narration": "x" * 40,
                                                "transition": "none", "media": {"asset": clip}}])
    project = video.validate_project(raw, assets)
    out = tmp_path / "clip.mp4"
    video.render_project(project, out, assets, None, fake_tts)
    frame = tmp_path / "f.png"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", "1", "-i", str(out), "-frames:v", "1", str(frame)], check=True)
    img = Image.open(frame).convert("RGB")
    reg = video.regions(project, project["scenes"][0], img.size)
    x0, y0, x1, y1 = [int(v) for v in reg["media"]]
    r, g, b = img.getpixel(((x0 + x1) // 2, (y0 + y1) // 2))
    assert r > 180 and g < 90 and b < 90                            # red clip pixels, not the blue theme


def test_background_music_is_mixed_in(tmp_path, assets, fake_tts, music_bytes):
    music = assets.save(music_bytes, "song.mp3")["id"]
    scenes = [{"layout": "title", "title": "Music", "narration": "", "duration": 4}]
    out_a, out_b = tmp_path / "plain.mp4", tmp_path / "music.mp4"
    video.render_project(video.validate_project(base_project(scenes=scenes), assets), out_a, assets, None, fake_tts)
    with_music = video.validate_project(base_project(scenes=scenes, music={"asset": music, "volume": 0.5}), assets)
    video.render_project(with_music, out_b, assets, None, fake_tts)

    def mean_volume(p):
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(p), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
        return float(r.stderr.split("mean_volume:")[1].split("dB")[0])

    assert mean_volume(out_a) < -80                                  # silent narration track
    assert mean_volume(out_b) > -40                                  # music is audible
    assert abs(float(streams(out_b)[0]["format"]["duration"]) - float(streams(out_a)[0]["format"]["duration"])) < 0.4


def test_video_longer_than_the_resolution_limit_is_refused(tmp_path, fake_tts, monkeypatch):
    monkeypatch.setitem(video.MAX_SECONDS, "480", 3.0)
    project = video.validate_project(base_project(scenes=[{"layout": "title", "title": "a", "duration": 2},
                                                          {"layout": "title", "title": "b", "duration": 2}]))
    with pytest.raises(video.VideoError) as e:
        video.render_project(project, tmp_path / "x.mp4", None, None, fake_tts)
    assert "longer than" in str(e.value)
    assert not list(tmp_path.glob("vf-render-*"))


def test_failed_speech_surfaces_as_error(tmp_path):
    def boom(*a, **k):
        raise tts.TTSUnavailable("no network")

    with pytest.raises(tts.TTSUnavailable):
        video.render_project(video.validate_project(base_project()), tmp_path / "x.mp4", None, None, boom)
    assert not list(tmp_path.glob("vf-render-*"))


# ---------------------------------------------------------------- job manager

def wait(mgr, job_id, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        job = mgr.get(job_id)
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.2)
    raise AssertionError("job timed out")


def test_job_manager_video_success_and_failure(tmp_path, fake_tts):
    mgr = video.JobManager(tmp_path)
    ok = mgr.submit(video.validate_project(base_project()), fake_tts)
    job = wait(mgr, ok)
    assert job["status"] == "done" and mgr.file(ok, "video.mp4").stat().st_size > 1000
    assert mgr.file(ok, "captions.srt").read_text(encoding="utf-8").startswith("1\n")
    assert mgr.file(ok, "../job.json") is None and mgr.file(ok, "job.json") is None

    def boom(*a, **k):
        raise tts.TTSUnavailable("Speech service unavailable: x")

    bad = wait(mgr, mgr.submit(video.validate_project(base_project()), boom))
    assert bad["status"] == "error" and "unavailable" in bad["error"].lower()


def test_long_audio_job(tmp_path):
    mgr = video.JobManager(tmp_path)
    seen = []

    def fake(text, voice, rate, pitch, progress=None):
        for i in range(4):
            seen.append(i)
            progress and progress((i + 1) / 4)
        return b"ID3-fake-mp3-bytes" * 100

    job_id = mgr.submit_tts("هذا نص طويل. " * 50, "ar-SA-HamedNeural", tts_fn=fake)
    job = wait(mgr, job_id)
    assert job["status"] == "done" and job["kind"] == "audio" and len(seen) == 4
    assert mgr.file(job_id, "speech.mp3").read_bytes().startswith(b"ID3")


def test_audio_job_validates_before_starting(tmp_path):
    mgr = video.JobManager(tmp_path)
    with pytest.raises(tts.TTSError):
        mgr.submit_tts("   ", "ar-SA-HamedNeural")
    with pytest.raises(tts.TTSError):
        mgr.submit_tts("hello", "no-such-Voice")


def test_job_state_is_visible_from_a_second_manager(tmp_path, fake_tts):
    a, b = video.JobManager(tmp_path), video.JobManager(tmp_path)  # like two gunicorn workers
    assert wait(b, a.submit(video.validate_project(base_project()), fake_tts))["status"] == "done"


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
    old = time.time() - 7200
    os.utime(d / "job.json", (old, old))
    assert mgr.get(jid)["status"] == "error"


def test_cleanup_keeps_media_used_by_saved_projects(tmp_path):
    mgr = video.JobManager(tmp_path, ttl_seconds=10)
    store = mgr.assets_for("a" * 32)
    keep = store.save(png_bytes(), "keep.png")["id"]
    drop = store.save(png_bytes((50, 50)), "drop.png")["id"]
    old = time.time() - 3600
    for aid in (keep, drop):
        os.utime(store.root / f"{aid}.json", (old, old))
    mgr.referenced_fn = lambda: {keep}
    mgr.cleanup()
    assert store.path(keep) is not None and store.path(drop) is None


def test_owners_cannot_use_each_others_files(tmp_path):
    mgr = video.JobManager(tmp_path)
    a, b = mgr.assets_for("a" * 32), mgr.assets_for("b" * 32)
    aid = a.save(png_bytes(), "mine.png")["id"]
    assert b.path(aid) is None
    with pytest.raises(video.VideoError):
        video.validate_project(base_project(scenes=[{"layout": "title", "title": "x", "background": {"type": "image", "asset": aid}}]), b)
    with pytest.raises(video.VideoError):
        mgr.assets_for("../../etc")


# ---------------------------------------------------------------- HTTP API

@pytest.fixture
def client(tmp_path, monkeypatch, fake_tts):
    mgr = video.JobManager(tmp_path)
    monkeypatch.setattr(web, "jobs", mgr)
    monkeypatch.setattr(web, "projects", web.projects_mod.ProjectStore(tmp_path / "projects"))
    mgr.referenced_fn = web.projects.referenced_assets
    monkeypatch.setattr(tts, "synthesize_mp3", fake_tts)
    web.app.config.update(TESTING=True)
    return web.app.test_client()


def upload(client, data, name):
    r = client.post("/api/video/assets", data={"file": (io.BytesIO(data), name)}, content_type="multipart/form-data")
    assert r.status_code == 200, r.data
    return r.get_json()


def wait_http(client, job_id):
    for _ in range(400):
        st = client.get(f"/api/jobs/{job_id}").get_json()
        if st["status"] in ("done", "error"):
            return st
        time.sleep(0.2)
    raise AssertionError("job timed out")


def test_video_config_lists_ratios_resolutions_themes_and_presets(client):
    d = client.get("/api/video/config").get_json()
    assert {"16:9", "9:16", "1:1", "4:5", "4:3", "21:9"} == {r["id"] for r in d["ratios"]}
    assert {"480", "720", "1080", "1440", "2160"} == {r["id"] for r in d["resolutions"]}
    assert d["dimensions"]["16:9"]["2160"] == [3840, 2160] and d["dimensions"]["16:9"]["1440"] == [2560, 1440]
    assert d["dimensions"]["9:16"]["1080"] == [1080, 1920]
    assert {"academy", "chalkboard", "clean", "bold", "midnight"} == {t["id"] for t in d["themes"]}
    assert "media" in d["layouts"] and "left" in d["media_positions"]
    lesson = next(p for p in d["presets"] if p["id"] == "lesson")
    assert lesson["scenes"]["ar"] and lesson["scenes"]["en"] and (lesson["ratio"], lesson["resolution"]) == ("16:9", "1080")
    assert d["max_seconds"]["2160"] < d["max_seconds"]["1080"]


def test_upload_library_preview_render_download_flow(client):
    asset = upload(client, png_bytes(), "bg.png")["id"]
    pic = upload(client, png_bytes((300, 300), (0, 160, 0)), "chart.png")["id"]
    assert {a["id"] for a in client.get("/api/assets").get_json()["assets"]} == {asset, pic}
    assert client.get(f"/api/assets/{asset}/thumb").mimetype == "image/jpeg"

    project = base_project(scenes=[{"layout": "bullets", "title": "مرحبا", "body": "a\nb", "narration": "مرحبا بكم.",
                                    "background": {"type": "image", "asset": asset}, "media": {"asset": pic}}])
    prev = client.post("/api/video/preview", json={"project": project, "index": 0})
    assert prev.status_code == 200 and prev.mimetype == "image/png" and Image.open(io.BytesIO(prev.data)).width > 100

    r = client.post("/api/video/render", json={"project": project})
    assert r.status_code == 202
    job_id = r.get_json()["job_id"]
    assert wait_http(client, job_id)["status"] == "done"
    mp4 = client.get(f"/api/jobs/{job_id}/video.mp4?download=1")
    assert mp4.status_code == 200 and mp4.mimetype == "video/mp4" and "attachment" in mp4.headers["Content-Disposition"]
    assert mp4.data[4:8] == b"ftyp"
    assert "مرحبا بكم" in client.get(f"/api/video/jobs/{job_id}/captions.srt").data.decode("utf-8")   # old URL still works


def test_each_browser_has_its_own_library(client):
    aid = upload(client, png_bytes(), "mine.png")["id"]
    other = web.app.test_client()                                    # a different visitor (no cookie)
    assert other.get("/api/assets").get_json()["assets"] == []
    bad = base_project(scenes=[{"layout": "title", "title": "x", "background": {"type": "image", "asset": aid}}])
    r = other.post("/api/video/render", json={"project": bad})
    assert r.status_code == 400 and "not found" in r.get_json()["error"]
    assert other.get(f"/api/assets/{aid}/thumb").status_code == 404
    assert other.delete(f"/api/assets/{aid}").status_code == 404
    assert client.delete(f"/api/assets/{aid}").status_code == 200


def test_audio_upload_and_music_in_a_render(client, music_bytes):
    music = upload(client, music_bytes, "song.mp3")
    assert music["kind"] == "audio"
    project = base_project(music={"asset": music["id"], "volume": 0.2}, scenes=[{"layout": "title", "title": "x", "duration": 2}])
    job_id = client.post("/api/video/render", json={"project": project}).get_json()["job_id"]
    assert wait_http(client, job_id)["status"] == "done"


def test_api_rejects_bad_input_and_unknown_files(client):
    assert client.post("/api/video/render", json={"project": {"scenes": []}}).status_code == 400
    assert client.post("/api/video/render", json={}).status_code == 400
    assert client.post("/api/video/assets", data={"file": (io.BytesIO(b"junk"), "x.png")}, content_type="multipart/form-data").status_code == 400
    assert client.post("/api/video/assets").status_code == 400
    assert client.get("/api/jobs/nothing").status_code == 404
    assert client.get("/api/jobs/" + "0" * 32).status_code == 404
    assert client.get("/api/jobs/" + "0" * 32 + "/video.mp4").status_code == 404
    assert client.post("/api/video/preview", json={"project": base_project(), "index": 9}).status_code == 400


def test_job_file_names_cannot_traverse(client):
    for name in ["job.json", "..%2Fjob.json", "etc"]:
        assert client.get(f"/api/jobs/{'0' * 32}/{name}").status_code in (404, 405)


def test_preview_ignores_other_unfinished_scenes_but_render_does_not(client):
    project = base_project(scenes=[{"layout": "title", "title": "Done", "narration": "ok"},
                                   {"layout": "title", "title": "", "body": "", "narration": ""}])
    for i in (0, 1):
        assert client.post("/api/video/preview", json={"project": project, "index": i}).status_code == 200
    r = client.post("/api/video/render", json={"project": project})
    assert r.status_code == 400 and "empty" in r.get_json()["error"].lower()


def test_video_endpoints_respect_login_gate(client, monkeypatch):
    monkeypatch.setattr(web, "REQUIRE_LOGIN", True)
    assert client.post("/api/video/render", json={"project": base_project()}).status_code == 401
    assert client.post("/api/video/preview", json={"project": base_project(), "index": 0}).status_code == 401
    assert client.post("/api/video/assets", data={"file": (io.BytesIO(png_bytes()), "a.png")}, content_type="multipart/form-data").status_code == 401
    assert client.post("/api/projects", json={"name": "x", "project": base_project()}).status_code == 401
    assert client.delete("/api/assets/" + "a" * 32).status_code == 401
    assert client.get("/api/video/config").status_code == 200
