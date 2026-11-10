"""Timeline editor engine: validation, real ffmpeg render, scenes -> clips, nested asset references."""
import io
import json
import subprocess

import pytest
from PIL import Image

import projects
import timeline
import video


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@pytest.fixture
def store(tmp_path):
    return video.AssetStore(tmp_path / "a")


@pytest.fixture
def media(tmp_path, store):
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=4",
                    "-f", "lavfi", "-i", "sine=frequency=500:duration=4", "-shortest", "-pix_fmt", "yuv420p", str(clip)], check=True)
    song = tmp_path / "s.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=6", str(song)], check=True)
    buf = io.BytesIO()
    Image.new("RGBA", (200, 120), (255, 200, 0, 255)).save(buf, "PNG")
    return {"video": store.save(clip.read_bytes(), "c.mp4")["id"], "audio": store.save(song.read_bytes(), "s.mp3")["id"],
            "image": store.save(buf.getvalue(), "logo.png")["id"]}


def make(media, **over):
    tl = {"ratio": "16:9", "resolution": "480", "tracks": [
        {"kind": "video", "clips": [
            {"type": "video", "asset": media["video"], "start": 0, "dur": 3, "in": 0.5, "fade_out": 0.4},
            {"type": "color", "color": "#2f6bff", "start": 3, "dur": 2, "fade_in": 0.3}]},
        {"kind": "overlay", "clips": [
            {"type": "image", "asset": media["image"], "start": 0.5, "dur": 2, "x": 0.8, "y": 0.2, "w": 0.2, "anim": "pop"},
            {"type": "text", "text": "مرحبا بكم\nWelcome", "start": 1, "dur": 3.5, "x": 0.5, "y": 0.75, "w": 0.8,
             "size": 0.08, "box": "#000000aa", "anim": "slide"}]},
        {"kind": "audio", "clips": [{"type": "audio", "asset": media["audio"], "start": 0.5, "dur": 4, "volume": 0.4,
                                     "fade_in": 0.5, "fade_out": 1}]}]}
    tl.update(over)
    return tl


def test_validate_and_duration(store, media):
    tl = timeline.validate_timeline(make(media), store)
    assert tl["duration"] == 5.0 and len(tl["tracks"]) == 3
    assert tl["tracks"][1]["clips"][1]["anim"] == "slide"


@pytest.mark.parametrize("bad,msg", [
    (lambda t: t["tracks"][0]["clips"].append({"type": "text", "text": "x"}), "can't go on a video track"),
    (lambda t: t["tracks"][2]["clips"][0].update(asset="0" * 32), "not found"),
    (lambda t: t.update(tracks=[]), "empty"),
    (lambda t: t.update(ratio="7:3"), "ratio"),
    (lambda t: t["tracks"][1]["clips"][1].update(text="  "), "text is empty"),
    (lambda t: t.update(tracks=[{"kind": "video", "clips": []}]), "at least one clip"),
])
def test_invalid_timelines(store, media, bad, msg):
    tl = make(media)
    bad(tl)
    with pytest.raises(video.VideoError, match=msg):
        timeline.validate_timeline(tl, store)


def test_render_mixes_everything(tmp_path, store, media):
    tl = timeline.validate_timeline(make(media), store)
    out = tmp_path / "tl.mp4"
    seen = []
    timeline.render_timeline(tl, out, store, lambda p, m: seen.append(p))
    info = probe(out)
    assert abs(float(info["format"]["duration"]) - 5.0) < 0.15
    assert {s["codec_type"] for s in info["streams"]} == {"video", "audio"}
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == video.dimensions("16:9", "480")
    assert seen[-1] == 1.0 and len(seen) > 2
    # frame at 2 s: video track visible (not the blue colour clip), at 4 s: the blue colour clip
    def px(t):
        f = tmp_path / f"f{t}.png"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(t), "-i", str(out), "-frames:v", "1", str(f)], check=True)
        return Image.open(f).convert("RGB").getpixel((5, 5))
    r, g, b = px(4.2)
    assert b > 200 and r < 90          # #2f6bff colour clip
    # hidden tracks and muted audio are skipped; still renders
    t2 = make(media)
    t2["tracks"][1]["hidden"] = True
    t2["tracks"][2]["muted"] = True
    timeline.render_timeline(timeline.validate_timeline(t2, store), tmp_path / "t2.mp4", store)


def test_text_layer_rtl_and_box(media):
    clip = {"text": "مرحبا", "size": 0.1, "color": "#ffffff", "box": "#000000aa", "bold": True, "align": "center", "x": 0.5, "y": 0.5, "w": 0.6}
    im = timeline.text_layer(clip, (640, 360))
    assert im.mode == "RGBA" and im.getbbox() is not None and im.getpixel((0, 0))[3] == 0


def test_scenes_to_clips(store, tmp_path):
    def fake_tts(text, voice, rate, pitch, **_):
        p = tmp_path / "t.mp3"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=duration=2", str(p)], check=True)
        return p.read_bytes()
    raw = {"ratio": "9:16", "resolution": "720", "voice": {"lang": "ar-SA", "gender": "male"},
           "scenes": [{"layout": "title", "title": "مرحبا", "narration": "مرحبا بكم"}, {"layout": "title", "title": "Bye", "duration": 3}]}
    res = timeline.scenes_to_clips(raw, store, tts_fn=fake_tts)
    d0 = res["video"][0]["dur"]
    assert 2.4 < d0 < 2.7 and res["video"][1]["dur"] == 3.0 and res["video"][1]["start"] == d0
    assert len(res["voice"]) == 1 and store.kind(res["video"][0]["asset"]) == "image"
    tl = {"ratio": res["ratio"], "resolution": "480", "tracks": [{"kind": "video", "clips": res["video"]},
                                                              {"kind": "audio", "clips": res["voice"]}]}
    timeline.render_timeline(timeline.validate_timeline(tl, store), tmp_path / "s.mp4", store)


def test_nested_asset_ids_and_remap():
    p = {"scenes": [{"voiceover": {"asset": "a" * 32}, "stickers": [{"asset": "b" * 32}], "sfx": {"asset": "c" * 32}}],
         "timeline": {"tracks": [{"clips": [{"asset": "d" * 32}, {"asset": "e" * 32}]}]}, "music": {"asset": "f" * 32}}
    assert set(projects.asset_ids(p)) == {x * 32 for x in "abcdef"}
    out = projects.remap_assets(p, {"a" * 32: "1" * 32, "d" * 32: "2" * 32})
    assert out["scenes"][0]["voiceover"]["asset"] == "1" * 32 and out["scenes"][0]["stickers"] == []
    assert out["timeline"]["tracks"][0]["clips"] == [{"asset": "2" * 32}] and out["music"] is None


def test_timeline_endpoints(media, monkeypatch, tmp_path):
    import time
    import app as appmod
    c = appmod.app.test_client()
    # put the fixture media into this client's asset store
    c.get("/")
    owner_store = None
    r = c.post("/api/timeline/render", json={"timeline": {"tracks": []}})
    assert r.status_code == 400
    png = io.BytesIO()
    Image.new("RGB", (64, 64), (0, 200, 0)).save(png, "PNG")
    m = c.post("/api/video/assets", data={"file": (io.BytesIO(png.getvalue()), "g.png")}, content_type="multipart/form-data").get_json()
    tl = {"ratio": "1:1", "resolution": "480", "tracks": [{"kind": "video", "clips": [{"type": "image", "asset": m["id"], "start": 0, "dur": 2}]},
                                                       {"kind": "overlay", "clips": [{"type": "text", "text": "Hi", "start": 0, "dur": 2}]}]}
    job = c.post("/api/timeline/render", json={"timeline": tl}).get_json()["job_id"]
    for _ in range(120):
        j = c.get(f"/api/jobs/{job}").get_json()
        if j["status"] in ("done", "error"):
            break
        time.sleep(0.25)
    assert j["status"] == "done", j
    assert c.get(f"/api/jobs/{job}/video.mp4").status_code == 200
