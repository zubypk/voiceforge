"""Multi-track timeline editor engine: validate a timeline and render it to MP4 with ffmpeg.

A timeline is plain JSON (tracks listed bottom -> top):

    {"ratio": "16:9", "resolution": "1080", "background": "#000000",
     "tracks": [
       {"kind": "video",   "muted": false, "hidden": false, "volume": 1,
        "clips": [{"type": "video|image|color", "asset": "<id>", "color": "#123456",
                   "start": 0, "dur": 5, "in": 0, "fit": "cover|contain", "volume": 1,
                   "fade_in": 0.5, "fade_out": 0.5, "opacity": 1}]},
       {"kind": "overlay", "clips": [{"type": "image|video|text", "asset": "<id>", "start": 1, "dur": 3,
                   "x": 0.5, "y": 0.5, "w": 0.3, "anim": "pop", "text": "...", "size": 0.08, "color": "#fff",
                   "box": "#00000099", "bold": true, "align": "center"}]},
       {"kind": "audio",   "clips": [{"type": "audio", "asset": "<id>", "start": 0, "dur": 12, "in": 0, "volume": 0.3}]}
     ]}

Visual clips are composited in track order; audio comes from audio clips and from the sound of video clips.
Text is drawn with Pillow (correct Arabic/RTL shaping) - never passed to ffmpeg's text filters.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

import video
from video import VideoError, _num

TRACK_KINDS = ("video", "overlay", "audio")
ALLOWED = {"video": ("video", "image", "color"), "overlay": ("video", "image", "text"), "audio": ("audio",)}
ANIMS = ("none", "fade", "slide", "rise", "pop")
MAX_TRACKS, MAX_CLIPS, MAX_TEXT = 12, 300, 600
FPS = video.FPS


def _color(c, default):
    return c if isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", c) else default


def validate_timeline(raw: dict, assets: "video.AssetStore | None") -> dict:
    if not isinstance(raw, dict):
        raise VideoError("Invalid timeline.")
    ratio = raw.get("ratio", "16:9")
    resolution = str(raw.get("resolution", "1080"))
    if ratio not in video.RATIOS:
        raise VideoError("Unknown screen ratio.")
    if resolution not in video.RESOLUTIONS:
        raise VideoError("Unknown resolution.")
    tracks_in = raw.get("tracks")
    if not isinstance(tracks_in, list) or not tracks_in:
        raise VideoError("The timeline is empty.")
    if len(tracks_in) > MAX_TRACKS:
        raise VideoError(f"Too many tracks (limit {MAX_TRACKS}).")
    tracks, n_clips, end = [], 0, 0.0
    for ti, t in enumerate(tracks_in, 1):
        if not isinstance(t, dict) or t.get("kind") not in TRACK_KINDS:
            raise VideoError(f"Track {ti} is invalid.")
        kind = t["kind"]
        clips = []
        for ci, c in enumerate(t.get("clips") or [], 1):
            n_clips += 1
            if n_clips > MAX_CLIPS:
                raise VideoError(f"Too many clips (limit {MAX_CLIPS}).")
            if not isinstance(c, dict) or c.get("type") not in ALLOWED[kind]:
                raise VideoError(f"Track {ti}, clip {ci}: this type of clip can't go on a {kind} track.")
            typ = c["type"]
            clip = {"type": typ, "start": round(_num(c.get("start"), 0, 0, 7200), 3),
                    "dur": round(_num(c.get("dur"), 3, 0.1, 3600), 3), "in": round(_num(c.get("in"), 0, 0, 7200), 3),
                    "volume": _num(c.get("volume"), 1, 0, 2), "opacity": _num(c.get("opacity"), 1, 0, 1)}
            half = clip["dur"] / 2
            clip["fade_in"] = _num(c.get("fade_in"), 0, 0, half)
            clip["fade_out"] = _num(c.get("fade_out"), 0, 0, half)
            if typ in ("video", "image", "audio"):
                a = c.get("asset")
                k = assets.kind(a) if (assets and a) else None
                ok = k == typ or (typ == "audio" and k == "video")      # audio clips may use a video's sound
                if not ok:
                    raise VideoError(f"Track {ti}, clip {ci}: the media file was not found. Upload it again.")
                clip["asset"] = a
            if typ == "color":
                clip["color"] = _color(c.get("color"), "#000000")[:7]
            if kind == "video":
                clip["fit"] = c.get("fit") if c.get("fit") in ("cover", "contain") else "cover"
            if kind == "overlay":
                clip.update(x=_num(c.get("x"), 0.5, -0.5, 1.5), y=_num(c.get("y"), 0.5, -0.5, 1.5),
                            w=_num(c.get("w"), 0.4, 0.02, 2), anim=c.get("anim") if c.get("anim") in ANIMS else "fade")
            if typ == "text":
                text = str(c.get("text") or "").strip()
                if not text:
                    raise VideoError(f"Track {ti}, clip {ci}: the text is empty.")
                if len(text) > MAX_TEXT:
                    raise VideoError(f"Track {ti}, clip {ci}: text is too long (limit {MAX_TEXT}).")
                clip.update(text=text, size=_num(c.get("size"), 0.07, 0.02, 0.3), color=_color(c.get("color"), "#ffffff")[:7],
                            box=_color(c.get("box"), "") if c.get("box") else "", bold=bool(c.get("bold", True)),
                            align=c.get("align") if c.get("align") in ("start", "center", "end") else "center")
            clips.append(clip)
            if not t.get("hidden") and not (kind == "audio" and t.get("muted")):
                end = max(end, clip["start"] + clip["dur"])
        tracks.append({"kind": kind, "muted": bool(t.get("muted")), "hidden": bool(t.get("hidden")),
                       "volume": _num(t.get("volume"), 1, 0, 2), "clips": clips})
    if end <= 0:
        raise VideoError("Add at least one clip to the timeline.")
    limit = video.MAX_SECONDS[resolution]
    if end > limit:
        raise VideoError(f"The timeline is longer than {limit / 60:g} minutes, the limit for "
                         f"{video.RESOLUTIONS[resolution]['label']}. Choose a lower resolution.")
    return {"ratio": ratio, "resolution": resolution, "background": _color(raw.get("background"), "#000000")[:7],
            "tracks": tracks, "duration": round(end, 3)}


# ----------------------------------------------------------------------------- text layers

def text_layer(clip: dict, size: tuple[int, int]) -> Image.Image:
    """Full-frame transparent PNG with the text block centred at (x, y)."""
    w, h = size
    unit = min(w, h)
    fs = max(10, round(clip["size"] * h if h <= w else clip["size"] * w * 0.9))
    text = clip["text"]
    lang = video._script_lang(text)
    font = video._font(lang, clip["bold"], fs)
    rtl = video.is_rtl(text)
    max_w = max(fs * 2, clip["w"] * w)
    lines = []
    for para in text.split("\n"):
        lines += video.wrap(para, font, max_w) or [""]
    lh = fs * 1.25
    widths = [font.getlength(line) for line in lines]
    bw, bh = max(widths + [1]), lh * len(lines)
    pad = fs * 0.45 if clip["box"] else 0
    cx, cy = clip["x"] * w, clip["y"] * h
    x0, y0 = cx - bw / 2, cy - bh / 2
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if clip["box"]:
        box = clip["box"]
        rgba = video.hex_rgb(box[:7]) + ((int(box[7:9], 16),) if len(box) == 9 else (190,))
        d.rounded_rectangle((x0 - pad, y0 - pad * 0.7, x0 + bw + pad, y0 + bh + pad * 0.5), radius=fs * 0.35, fill=rgba)
    fill = video.hex_rgb(clip["color"]) + (255,)
    align = clip["align"]
    for i, (line, lw) in enumerate(zip(lines, widths)):
        if align == "center":
            lx = cx - lw / 2
        elif (align == "start") != rtl:
            lx = x0
        else:
            lx = x0 + bw - lw
        if not clip["box"]:   # soft shadow keeps text readable on any background
            d.text((lx + max(1, unit // 400), y0 + i * lh + max(1, unit // 400)), line, font=font, fill=(0, 0, 0, 150),
                   direction="rtl" if rtl else "ltr")
        d.text((lx, y0 + i * lh), line, font=font, fill=fill, direction="rtl" if rtl else "ltr")
    return layer


# ----------------------------------------------------------------------------- render

_audio_cache: dict[str, bool] = {}


def has_audio(path: Path) -> bool:
    key = f"{path}:{path.stat().st_mtime}"
    if key not in _audio_cache:
        proc = subprocess.run([video.ffmpeg_bin(), "-hide_banner", "-i", str(path)], capture_output=True, text=True, timeout=60)
        _audio_cache[key] = "Audio:" in proc.stderr
    return _audio_cache[key]


def _anim_xy(clip, x: str, y: str, w: int, h: int, rtl: bool = False):
    S = f"{clip['start']:.3f}"
    p = f"min(1,max(0,(t-{S})/0.5))"
    ease = f"(1-pow(1-{p},3))"
    if clip["anim"] == "slide":
        x = f"({x})+{int(w * 0.25) * (1 if rtl else -1)}*(1-{ease})"
    elif clip["anim"] == "rise":
        y = f"({y})+{int(h * 0.12)}*(1-{ease})"
    return x, y


def render_timeline(tl: dict, out_path: Path, assets: "video.AssetStore | None", progress=None) -> dict:
    progress = progress or (lambda p, m: None)
    out_path = Path(out_path)
    w, h = video.dimensions(tl["ratio"], tl["resolution"])
    total = tl["duration"]
    heavy = video.RESOLUTIONS[tl["resolution"]]["short"] >= 1440
    work = Path(tempfile.mkdtemp(prefix="vf-tl-", dir=out_path.parent))
    try:
        cmd = [video.ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error",
               "-f", "lavfi", "-i", f"color=c={tl['background']}:s={w}x{h}:r={FPS}:d={total}",
               "-f", "lavfi", "-t", f"{total}", "-i", "anullsrc=r=44100:cl=stereo"]
        filt, cur, idx, audio_labels = [f"[0:v]setsar=1,format=yuva420p[base]"], "base", 2, []
        progress(0.02, "preparing")
        for ti, track in enumerate(tl["tracks"]):
            for ci, clip in enumerate(track["clips"]):
                typ, S, D = clip["type"], clip["start"], clip["dur"]
                lab = f"t{ti}c{ci}"
                path = assets.path(clip["asset"]) if clip.get("asset") and assets else None
                # ---- audio
                if track["kind"] == "audio":
                    if track["muted"] or not path:
                        continue
                    cmd += ["-ss", f"{clip['in']}", "-t", f"{D}", "-i", str(path)]
                    audio_labels.append(_audio_chain(filt, idx, clip, track["volume"], lab))
                    idx += 1
                    continue
                if track["hidden"]:
                    continue
                # ---- visuals
                if typ == "image":
                    cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{D}", "-i", str(path)]
                elif typ == "video":
                    cmd += ["-ss", f"{clip['in']}", "-t", f"{D}", "-i", str(path)]
                elif typ == "color":
                    cmd += ["-f", "lavfi", "-i", f"color=c={clip['color']}:s={w}x{h}:r={FPS}:d={D}"]
                else:   # text
                    png = work / f"{lab}.png"
                    text_layer(clip, (w, h)).save(png)
                    cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{D}", "-i", str(png)]
                chain = f"[{idx}:v]fps={FPS},setsar=1"
                if track["kind"] == "video":
                    if clip["fit"] == "cover":
                        chain += f",scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
                    else:
                        chain += f",scale={w}:{h}:force_original_aspect_ratio=decrease"
                    x, y = "(W-w)/2", "(H-h)/2"
                elif typ == "text":
                    x, y = "0", "0"
                else:
                    pw = max(2, int(clip["w"] * w) // 2 * 2)
                    chain += f",scale={pw}:-2"
                    x, y = f"{clip['x'] * w:.1f}-w/2", f"{clip['y'] * h:.1f}-h/2"
                chain += ",format=rgba"
                if track["kind"] == "overlay" and clip["anim"] == "pop" and typ != "text":
                    q = f"min(1,max(0.05,(t)/0.35))"
                    chain += f",scale=w='max(2,trunc(iw*{q}*(1+0.15*sin(PI*{q}))/2)*2)':h=-2:eval=frame"
                if clip["opacity"] < 1:
                    chain += f",colorchannelmixer=aa={clip['opacity']:.3f}"
                fi = clip["fade_in"] or (0.35 if track["kind"] == "overlay" and clip["anim"] in ("fade", "slide", "rise") else 0)
                if fi:
                    chain += f",fade=t=in:st=0:d={fi:.3f}:alpha=1"
                if clip["fade_out"]:
                    chain += f",fade=t=out:st={max(0, D - clip['fade_out']):.3f}:d={clip['fade_out']:.3f}:alpha=1"
                chain += f",setpts=PTS-STARTPTS+{S:.3f}/TB[{lab}]"
                if track["kind"] == "overlay":
                    rtl = typ == "text" and video.is_rtl(clip.get("text", ""))
                    x, y = _anim_xy(clip, x, y, w, h, rtl)
                filt.append(chain)
                filt.append(f"[{cur}][{lab}]overlay=x='{x}':y='{y}':eval=frame:eof_action=pass:"
                            f"enable='between(t,{S:.3f},{S + D:.3f})'[o{lab}]")
                cur = f"o{lab}"
                if typ == "video" and path and not track["muted"] and clip["volume"] > 0 and has_audio(path):
                    audio_labels.append(_audio_chain(filt, idx, clip, track["volume"], f"a{lab}"))
                idx += 1
        filt.append(f"[{cur}]format=yuv420p[vout]")
        if audio_labels:
            ins = "".join(f"[{a}]" for a in ["1:a"] + audio_labels)
            filt.append(f"{ins}amix=inputs={len(audio_labels) + 1}:duration=first:dropout_transition=0:normalize=0,"
                        f"alimiter=limit=0.95[aout]")
        else:
            filt.append("[1:a]anull[aout]")
        # inline graph: -filter_complex_script was removed in newer ffmpeg builds (the Docker image uses ffmpeg 7.x)
        cmd += ["-filter_complex", ";".join(filt), "-map", "[vout]", "-map", "[aout]",
                "-c:v", "libx264", "-preset", "ultrafast" if tl["resolution"] == "480" else "veryfast",
                "-crf", "20" if heavy else "22", "-pix_fmt", "yuv420p", "-r", str(FPS),
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                "-t", f"{total}", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(out_path)]
        progress(0.05, "rendering")
        _run_with_progress(cmd, total, progress, timeout=3600 if heavy else 1800)
        progress(1.0, "done")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"duration": total}


def _audio_chain(filt: list, idx: int, clip: dict, track_volume: float, lab: str) -> str:
    ms = int(clip["start"] * 1000)
    chain = f"[{idx}:a]aresample=44100,aformat=channel_layouts=stereo,volume={clip['volume'] * track_volume:.3f}"
    if clip["fade_in"]:
        chain += f",afade=t=in:st=0:d={clip['fade_in']:.3f}"
    if clip["fade_out"]:
        chain += f",afade=t=out:st={max(0, clip['dur'] - clip['fade_out']):.3f}:d={clip['fade_out']:.3f}"
    chain += f",adelay={ms}|{ms}[{lab}]"
    filt.append(chain)
    return lab


def _run_with_progress(cmd: list, total: float, progress, timeout: int) -> None:
    import time
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for line in proc.stdout:
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    sec = int(line.split("=")[1]) / 1_000_000
                    progress(min(0.98, 0.05 + 0.93 * sec / max(total, 0.1)), "rendering")
                except ValueError:
                    pass
            if time.time() - t0 > timeout:
                proc.kill()
                raise VideoError("Rendering took too long.")
        err = proc.stderr.read()
        if proc.wait() != 0:
            raise VideoError(f"Rendering the timeline failed: {err.strip()[-300:]}")
    finally:
        if proc.poll() is None:
            proc.kill()


# ----------------------------------------------------------------------------- scenes -> timeline

def scenes_to_clips(raw_project: dict, assets: "video.AssetStore", tts_fn=None, max_scenes: int = 40) -> dict:
    """Turn Video Studio scenes into timeline clips: one slide image (video track) + its narration (audio track)."""
    tts_fn = tts_fn or video.tts.synthesize_mp3
    project = video.validate_project(raw_project, assets)
    scenes = project["scenes"][:max_scenes]
    size = video.canvas_size(project)
    voice = project["voice"]
    t, vclips, aclips = 0.0, [], []
    for i, scene in enumerate(scenes):
        media_img = None
        sm = video.scene_media(scene, assets)
        tmp = Path(tempfile.mkdtemp(prefix="vf-s2t-"))
        try:
            if sm:
                kind, path = sm
                if kind == "video":
                    path = video.first_frame(path, tmp / "m.png")
                if path:
                    with Image.open(path) as im:
                        media_img = im.convert("RGB")
            still = None
            if scene["background"]["type"] == "video":
                vp = assets.path(scene["background"]["asset"])
                still = video.first_frame(vp, tmp / "bg.png") if vp else None
            frame = video.look_pil(video.base_frame(project, scene, size, assets, still), scene.get("look", "none")).convert("RGBA")
            frame.alpha_composite(video.render_overlay(project, scene, size, None, scene["background"]["type"] in ("image", "video"), media_img))
            for st in scene.get("stickers") or []:
                img = video.sticker_image(assets, st, size[0])
                if img is not None:
                    frame.paste(img, video.sticker_box(st, img, size), img)
            png = tmp / "slide.png"
            frame.convert("RGB").save(png, optimize=True)
            slide = assets.save(png.read_bytes(), f"slide-{i + 1:02d}.png")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        audio_meta, alen = None, 0.0
        vo = scene.get("voiceover")
        if vo:
            audio_meta = assets.meta(vo["asset"])
            alen = video.probe_duration(assets.path(vo["asset"]))
        elif scene["narration"]:
            mp3 = tts_fn(scene["narration"], voice["voice"], voice["rate"], voice["pitch"])
            audio_meta = assets.save(mp3, f"narration-{i + 1:02d}.mp3")
            alen = video.probe_duration(assets.path(audio_meta["id"]))
        dur = float(scene["duration"]) if scene["duration"] else (max(2.0, alen + 0.5) if alen else 5.0)
        vclips.append({"type": "image", "asset": slide["id"], "name": slide["name"], "start": round(t, 3), "dur": round(dur, 3),
                       "in": 0, "fit": "contain", "fade_in": 0.3 if i else 0, "fade_out": 0.3})
        if audio_meta:
            aclips.append({"type": "audio", "asset": audio_meta["id"], "name": audio_meta["name"], "start": round(t, 3),
                           "dur": round(min(alen, dur), 3), "in": 0, "volume": 1})
        t += dur
    music = project.get("music")
    mclips = []
    if music and assets.path(music["asset"]):
        mclips.append({"type": "audio", "asset": music["asset"], "name": (assets.meta(music["asset"]) or {}).get("name", "music"),
                       "start": 0, "dur": round(t, 3), "in": 0, "volume": music["volume"], "fade_in": 1.0, "fade_out": 2.0})
    return {"ratio": project["ratio"], "resolution": project["resolution"], "duration": round(t, 3),
            "video": vclips, "voice": aclips, "music": mclips}
