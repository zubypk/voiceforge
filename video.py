"""Video engine: scenes -> slides (Pillow, proper Arabic/RTL shaping) + narration (TTS) -> MP4 (ffmpeg).

A project is plain JSON:

    {
      "size": "youtube-1080",            # see SIZES
      "theme": "academy",                # see THEMES
      "captions": true,
      "quality": "final",                # "draft" renders at half size, faster
      "voice": {"lang": "ar-SA", "gender": "male", "voice": null, "rate": 0, "pitch": 0},
      "scenes": [
        {"layout": "title|bullets|text|quote", "title": "...", "body": "...", "narration": "...",
         "background": {"type": "theme|color|image|video", "color": "#112233", "asset": "<id>"},
         "duration": null,               # seconds, or null = follow the narration
         "transition": "fade|none"}
      ]
    }

All text is drawn with Pillow (never passed to ffmpeg filters), so any script is safe and shapes correctly.
"""
from __future__ import annotations

import functools
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

import tts_module as tts

# ----------------------------------------------------------------------------- presets

SIZES = {
    "youtube-1080": {"label": "YouTube · Educational 16:9 (1080p)", "w": 1920, "h": 1080, "ratio": "16:9"},
    "youtube-720": {"label": "YouTube · 16:9 (720p, small file)", "w": 1280, "h": 720, "ratio": "16:9"},
    "shorts": {"label": "Shorts · TikTok · Reels 9:16", "w": 1080, "h": 1920, "ratio": "9:16"},
    "square": {"label": "Instagram · Facebook feed 1:1", "w": 1080, "h": 1080, "ratio": "1:1"},
    "portrait": {"label": "Instagram portrait 4:5", "w": 1080, "h": 1350, "ratio": "4:5"},
    "classroom": {"label": "Classroom · Presentation 4:3", "w": 1440, "h": 1080, "ratio": "4:3"},
}

THEMES = {
    "academy": {"label": "Academy", "bg": ("#0f2a5c", "#1d4e9e"), "text": "#ffffff", "accent": "#ffc857", "muted": "#cfdcf5"},
    "chalkboard": {"label": "Chalkboard", "bg": ("#173b2e", "#245c45"), "text": "#f4f1e8", "accent": "#ffd166", "muted": "#cfe3d8"},
    "clean": {"label": "Clean light", "bg": ("#ffffff", "#e8f0ff"), "text": "#14213d", "accent": "#2f6bff", "muted": "#51607f"},
    "bold": {"label": "Bold", "bg": ("#7c3aed", "#ec4899"), "text": "#ffffff", "accent": "#fde047", "muted": "#f6dcff"},
    "midnight": {"label": "Midnight", "bg": ("#0b1020", "#1b2440"), "text": "#e8ecff", "accent": "#38bdf8", "muted": "#9aa6cf"},
}

LAYOUTS = ("title", "bullets", "text", "quote")
TRANSITIONS = ("fade", "none")
FPS = 30

LIMITS = {
    "max_scenes": 40,
    "max_title": 200,
    "max_body": 1500,
    "max_narration": 3000,          # per scene
    "max_total_narration": 20000,
    "min_scene_seconds": 2.0,
    "max_scene_seconds": 180.0,
    "default_silent_seconds": 5.0,
    "end_pad_seconds": 0.5,
    "max_total_seconds": 900.0,     # 15 minutes
    "max_image_bytes": 15 * 1024 * 1024,
    "max_video_bytes": 150 * 1024 * 1024,
}


class VideoError(ValueError):
    """Invalid project, bad asset, or a failed render."""


# ----------------------------------------------------------------------------- binaries

@functools.lru_cache(maxsize=1)
def ffmpeg_bin() -> str:
    env = os.environ.get("FFMPEG_BIN")
    if env and Path(env).exists():
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise VideoError("ffmpeg is not available (install ffmpeg or `pip install imageio-ffmpeg`).") from exc


def _run(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    nice = shutil.which("nice")
    full = ([nice, "-n", "10"] if nice else []) + cmd
    try:
        proc = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise VideoError("Rendering timed out.") from exc
    return proc


def _must(cmd: list[str], what: str, timeout: int = 900) -> None:
    proc = _run(cmd, timeout)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-6:])
        raise VideoError(f"{what} failed: {tail}")


def probe_duration(path: Path) -> float:
    proc = _run([ffmpeg_bin(), "-hide_banner", "-i", str(path)], 60)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
    if not m:
        raise VideoError("Could not read media duration.")
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


# ----------------------------------------------------------------------------- fonts

FONT_DIR = Path(os.environ.get("VF_FONT_DIR", Path(__file__).with_name("fonts")))

_SYSTEM_SANS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans{b}.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans{b}.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-{r}.ttf",
    "/usr/share/fonts/TTF/DejaVuSans{b}.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "C:/Windows/Fonts/arial{w}.ttf",
]

_SCRIPT_LANG = {
    "ARABIC": "ar", "HEBREW": "he", "CJK": "zh", "HIRAGANA": "ja", "KATAKANA": "ja", "HANGUL": "ko",
    "DEVANAGARI": "hi", "BENGALI": "bn", "THAI": "th", "TAMIL": "ta", "GUJARATI": "gu", "KANNADA": "kn",
    "MALAYALAM": "ml", "TELUGU": "te", "SINHALA": "si", "KHMER": "km", "LAO": "lo", "MYANMAR": "my",
    "GEORGIAN": "ka", "ARMENIAN": "hy", "ETHIOPIC": "am", "GURMUKHI": "pa",
}

# Optional nicer fonts dropped into ./fonts (see scripts/get_fonts.sh), checked first.
_FONT_FILES = {
    "ar": ["NotoNaskhArabic-{W}.ttf", "NotoSansArabic-{W}.ttf"],
    "he": ["NotoSansHebrew-{W}.ttf"],
    "hi": ["NotoSansDevanagari-{W}.ttf"],
    "bn": ["NotoSansBengali-{W}.ttf"],
    "th": ["NotoSansThai-{W}.ttf"],
    "ta": ["NotoSansTamil-{W}.ttf"],
    "": ["NotoSans-{W}.ttf"],
}


def _script_lang(text: str) -> str:
    for ch in text:
        if not ch.isalpha():
            continue
        word = unicodedata.name(ch, "").split(" ")[0].split("-")[0]
        if word in ("LATIN", "CYRILLIC", "GREEK"):
            continue
        if word in _SCRIPT_LANG:
            return _SCRIPT_LANG[word]
    return ""


def is_rtl(text: str) -> bool:
    for ch in text:
        d = unicodedata.bidirectional(ch)
        if d in ("R", "AL"):
            return True
        if d == "L":
            return False
    return False


@functools.lru_cache(maxsize=64)
def _font_path(lang: str, bold: bool) -> str:
    weight = "Bold" if bold else "Regular"
    for pattern in _FONT_FILES.get(lang, []) + ([] if lang else _FONT_FILES[""]):
        p = FONT_DIR / pattern.format(W=weight)
        if p.exists():
            return str(p)
    if lang:  # let fontconfig find a font that covers this script
        fc = shutil.which("fc-match")
        if fc:
            try:
                out = subprocess.run([fc, "-f", "%{file}", f":lang={lang}:weight={'bold' if bold else 'regular'}"],
                                     capture_output=True, text=True, timeout=5).stdout.strip()
                if out and Path(out).exists():
                    return out
            except Exception:
                pass
    for pattern in _SYSTEM_SANS:
        p = pattern.format(b="-Bold" if bold else "", r="Bold" if bold else "Regular", w="bd" if bold else "")
        if Path(p).exists():
            return p
    raise VideoError("No usable font found. Install fonts-dejavu-core (or put a .ttf in ./fonts).")


@functools.lru_cache(maxsize=256)
def _font(lang: str, bold: bool, size: int) -> ImageFont.FreeTypeFont:
    path = _font_path(lang, bold)
    try:
        return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)
    except Exception:
        return ImageFont.truetype(path, size)


# ----------------------------------------------------------------------------- drawing helpers

def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _valid_color(c) -> str:
    return c if isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c) else "#1d4e9e"


def gradient(size: tuple[int, int], c1: str, c2: str) -> Image.Image:
    """Diagonal gradient from c1 (top-left) to c2 (bottom-right)."""
    from PIL import ImageChops

    w, h = size
    lg = Image.linear_gradient("L")
    vertical = lg.resize((w, h), Image.BILINEAR)
    horizontal = lg.transpose(Image.Transpose.ROTATE_90).transpose(Image.Transpose.FLIP_LEFT_RIGHT).resize((w, h), Image.BILINEAR)
    mask = ImageChops.add(vertical, horizontal, scale=2.0)
    return Image.composite(Image.new("RGB", size, hex_rgb(c2)), Image.new("RGB", size, hex_rgb(c1)), mask)


def cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    w, h = size
    scale = max(w / img.width, h / img.height)
    img = img.resize((max(w, round(img.width * scale)), max(h, round(img.height * scale))), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def wrap(text: str, font: ImageFont.FreeTypeFont, max_w: float) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        cur = ""
        for word in para.split(" "):
            if font.getlength(word) > max_w:  # no spaces (CJK) or very long word: break by character
                if cur:
                    lines.append(cur)
                    cur = ""
                piece = ""
                for ch in word:
                    if font.getlength(piece + ch) > max_w and piece:
                        lines.append(piece)
                        piece = ch
                    else:
                        piece += ch
                cur = piece
                continue
            trial = f"{cur} {word}".strip()
            if font.getlength(trial) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
    return lines


class Block:
    def __init__(self, text, size, bold=False, color="text", bullet=False, align="start", gap=0.5, rule=False):
        self.text, self.size, self.bold, self.color = text, size, bold, color
        self.bullet, self.align, self.gap, self.rule = bullet, align, gap, rule


def _layout_blocks(draw, blocks, rect, theme, unit, draw_it: bool, scale: float, anchor: str):
    x0, y0, x1, y1 = rect
    width = x1 - x0
    placed = []
    total = 0.0
    for b in blocks:
        lang = _script_lang(b.text)
        font = _font(lang, b.bold, max(10, round(b.size * unit * scale)))
        indent = font.size * 1.1 if b.bullet else 0
        lines = wrap(b.text, font, width - indent)
        lh = font.size * 1.32
        h = lh * len(lines) + (font.size * 0.45 if b.rule else 0)
        placed.append((b, font, lines, lh, indent, h))
        total += h + b.gap * font.size
    if placed:
        total -= placed[-1][0].gap * placed[-1][1].size
    if not draw_it:
        return total
    y = y0 + (max(0, (y1 - y0 - total) / 2) if anchor == "center" else 0)
    for b, font, lines, lh, indent, h in placed:
        rtl = is_rtl(b.text)
        color = hex_rgb(theme[b.color])
        for line in lines:
            if b.align == "center":
                draw.text(((x0 + x1) / 2, y), line, font=font, fill=color, anchor="ma", direction="rtl" if rtl else "ltr")
            elif rtl:
                draw.text((x1 - indent, y), line, font=font, fill=color, anchor="ra", direction="rtl")
            else:
                draw.text((x0 + indent, y), line, font=font, fill=color, anchor="la", direction="ltr")
            y += lh
        if b.rule:
            rw, rt = unit * 0.14 * scale, max(3, unit * 0.008)
            ry = y + font.size * 0.12
            if is_rtl(b.text):
                draw.rounded_rectangle((x1 - rw, ry, x1, ry + rt), 4, fill=hex_rgb(theme["accent"]))
            else:
                draw.rounded_rectangle((x0, ry, x0 + rw, ry + rt), 4, fill=hex_rgb(theme["accent"]))
            y += font.size * 0.45
        if b.bullet and lines:
            r = font.size * 0.14
            cy = y - lh * len(lines) + lh * 0.52
            cx = (x1 - font.size * 0.4) if rtl else (x0 + font.size * 0.4)
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=hex_rgb(theme["accent"]))
        y += b.gap * font.size
    return total


def _fit_and_draw(draw, blocks, rect, theme, unit, anchor="center"):
    if not blocks:
        return
    scale = 1.0
    height = rect[3] - rect[1]
    while scale > 0.35 and _layout_blocks(draw, blocks, rect, theme, unit, False, scale, anchor) > height:
        scale -= 0.06
    _layout_blocks(draw, blocks, rect, theme, unit, True, scale, anchor)


def _theme_for(project: dict, dark_bg: bool) -> dict:
    t = dict(THEMES[project["theme"]])
    if dark_bg:  # image/video backgrounds always get light text over a dark scrim
        t.update(text="#ffffff", muted="#e7ebf5")
    return t


def _bullets(body: str) -> list[str]:
    out = []
    for line in body.split("\n"):
        line = re.sub(r"^\s*(?:[-*•–—]|\d+[.)])\s*", "", line).strip()
        if line:
            out.append(line)
    return out


def render_overlay(project: dict, scene: dict, size: tuple[int, int], caption: str | None, scrim: bool) -> Image.Image:
    """Transparent RGBA layer: optional scrim + slide text + optional caption pill."""
    w, h = size
    unit = min(w, h)
    bg = scene["background"]["type"]
    theme = _theme_for(project, dark_bg=bg in ("image", "video"))
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")
    if scrim:
        d.rectangle((0, 0, w, h), fill=(0, 0, 0, 105))
    elif bg == "theme":  # soft decorative circles
        d.ellipse((w * 0.62, -h * 0.35, w * 1.25, h * 0.55), fill=(*hex_rgb(theme["accent"]), 22))
        d.ellipse((-w * 0.2, h * 0.65, w * 0.3, h * 1.3), fill=(*hex_rgb(theme["text"]), 14))

    mx, my = w * 0.08, h * 0.08
    bottom = h * (0.76 if project["captions"] and caption is not None else 0.92)
    rect = (mx, my, w - mx, bottom)
    title, body, layout = scene["title"], scene["body"], scene["layout"]
    rtl_title = is_rtl(title or body)
    start_align = "start"

    if layout == "title":
        blocks = []
        if title:
            blocks.append(Block(title, 0.105, True, "text", align="center", gap=0.45))
        if body:
            blocks.append(Block(body.replace("\n", " "), 0.05, False, "muted", align="center"))
        _fit_and_draw(d, blocks, rect, theme, unit, "center")
    elif layout == "quote":
        blocks = [Block("“" if not rtl_title else "”", 0.2, True, "accent", align="center", gap=-0.05)]
        if body:
            blocks.append(Block(body.replace("\n", " "), 0.066, False, "text", align="center", gap=0.7))
        if title:
            blocks.append(Block("— " + title, 0.045, True, "accent", align="center"))
        _fit_and_draw(d, blocks, rect, theme, unit, "center")
    else:
        blocks = []
        if title:
            blocks.append(Block(title, 0.082, True, "text", align=start_align, gap=0.5, rule=True))
        if layout == "bullets":
            for item in _bullets(body):
                blocks.append(Block(item, 0.062, False, "text", bullet=True, gap=0.6))
        elif body:
            blocks.append(Block(body, 0.058, False, "text", gap=0.3))
        _fit_and_draw(d, blocks, rect, theme, unit, "top")

    if project["captions"] and caption:
        _draw_caption(d, caption, size, unit)
    return layer


def _draw_caption(d: ImageDraw.ImageDraw, text: str, size: tuple[int, int], unit: int) -> None:
    w, h = size
    portrait = h > w * 1.2
    max_w = w * (0.84 if not portrait else 0.88)
    fs = round(unit * (0.042 if not portrait else 0.04))
    lang = _script_lang(text)
    font = _font(lang, True, fs)
    lines = wrap(text, font, max_w)
    while len(lines) > 3 and fs > 14:
        fs = round(fs * 0.9)
        font = _font(lang, True, fs)
        lines = wrap(text, font, max_w)
    lh = fs * 1.3
    box_h = lh * len(lines) + fs * 0.8
    box_w = min(max_w, max(font.getlength(line) for line in lines)) + fs * 1.6
    cy_bottom = h * (1 - (0.06 if not portrait else 0.15))
    x0, y0 = (w - box_w) / 2, cy_bottom - box_h
    d.rounded_rectangle((x0, y0, x0 + box_w, y0 + box_h), fs * 0.45, fill=(0, 0, 0, 165))
    rtl = is_rtl(text)
    y = y0 + fs * 0.4
    for line in lines:
        d.text((w / 2, y), line, font=font, fill=(255, 255, 255, 255), anchor="ma", direction="rtl" if rtl else "ltr")
        y += lh


def base_frame(project: dict, scene: dict, size: tuple[int, int], assets: "AssetStore | None", video_still: Path | None = None) -> Image.Image:
    bg = scene["background"]
    theme = THEMES[project["theme"]]
    if bg["type"] == "color":
        return Image.new("RGB", size, hex_rgb(_valid_color(bg.get("color"))))
    if bg["type"] == "image":
        path = assets.path(bg["asset"]) if assets else None
        if not path:
            raise VideoError("Background image not found.")
        with Image.open(path) as im:
            return cover(im.convert("RGB"), size)
    if bg["type"] == "video":
        if video_still and video_still.exists():
            with Image.open(video_still) as im:
                return cover(im.convert("RGB"), size)
        return Image.new("RGB", size, (20, 20, 20))
    return gradient(size, *theme["bg"])


# ----------------------------------------------------------------------------- captions

def split_captions(text: str, max_chars: int = 84) -> list[str]:
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []
    sentences = [s.strip() for s in re.split(r"(?<=[.!?؟۔।。！？])\s+", text) if s.strip()]
    chunks: list[str] = []
    for s in sentences:
        if len(s) <= max_chars:
            chunks.append(s)
            continue
        cur = ""
        for word in s.split(" "):
            if len(cur) + len(word) + 1 > max_chars and cur:
                chunks.append(cur)
                cur = word
            else:
                cur = f"{cur} {word}".strip()
        if cur:
            chunks.append(cur)
    # merge tiny tails into the previous chunk
    merged: list[str] = []
    for c in chunks:
        if merged and len(c) < 12 and len(merged[-1]) + len(c) + 1 <= max_chars:
            merged[-1] += " " + c
        else:
            merged.append(c)
    return merged


def caption_timing(chunks: list[str], total: float) -> list[tuple[float, float]]:
    weights = [len(c) + 8 for c in chunks]
    s = sum(weights) or 1
    out, t = [], 0.0
    for wgt in weights:
        d = total * wgt / s
        out.append((t, t + d))
        t += d
    return out


def srt_time(t: float) -> str:
    ms = round(t * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


# ----------------------------------------------------------------------------- assets

class AssetStore:
    IMAGE_EXT = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}
    VIDEO_EXT = {".mp4": "mp4", ".mov": "mov", ".webm": "webm", ".m4v": "mp4"}

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, asset_id: str) -> Path | None:
        if not re.fullmatch(r"[0-9a-f]{32}", str(asset_id or "")):
            return None
        for p in self.root.glob(f"{asset_id}.*"):
            return p
        return None

    def kind(self, asset_id: str) -> str | None:
        p = self.path(asset_id)
        if not p:
            return None
        return "video" if p.suffix.lower().lstrip(".") in ("mp4", "mov", "webm") else "image"

    def save(self, data: bytes, filename: str) -> dict:
        ext = Path(filename or "").suffix.lower()
        asset_id = uuid.uuid4().hex
        if ext in self.VIDEO_EXT:
            if len(data) > LIMITS["max_video_bytes"]:
                raise VideoError("Video is too large (limit 150 MB).")
            dest = self.root / f"{asset_id}.{self.VIDEO_EXT[ext]}"
            dest.write_bytes(data)
            try:
                if probe_duration(dest) <= 0:
                    raise VideoError("Empty video.")
            except VideoError:
                dest.unlink(missing_ok=True)
                raise VideoError("That file is not a readable video.")
            return {"id": asset_id, "kind": "video"}
        if len(data) > LIMITS["max_image_bytes"]:
            raise VideoError("Image is too large (limit 15 MB).")
        try:
            import io

            with Image.open(io.BytesIO(data)) as im:
                fmt = im.format
                im.verify()
        except Exception:
            raise VideoError("Unsupported file. Use PNG, JPG, WEBP images or MP4/MOV/WEBM video.")
        if fmt not in self.IMAGE_EXT:
            raise VideoError("Unsupported image format. Use PNG, JPG or WEBP.")
        (self.root / f"{asset_id}.{self.IMAGE_EXT[fmt]}").write_bytes(data)
        return {"id": asset_id, "kind": "image"}

    def cleanup(self, max_age_seconds: int) -> None:
        cutoff = time.time() - max_age_seconds
        for p in self.root.iterdir():
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
            except OSError:
                pass


# ----------------------------------------------------------------------------- validation

def _text(v, limit: int, name: str) -> str:
    v = "" if v is None else str(v)
    v = v.replace("\x00", "").strip()
    if len(v) > limit:
        raise VideoError(f"{name} is too long (limit {limit} characters).")
    return v


def validate_project(raw: dict, assets: AssetStore | None = None, allow_empty: bool = False) -> dict:
    if not isinstance(raw, dict):
        raise VideoError("Invalid project.")
    size = raw.get("size", "youtube-1080")
    theme = raw.get("theme", "academy")
    if size not in SIZES:
        raise VideoError(f"Unknown size preset: {size!r}.")
    if theme not in THEMES:
        raise VideoError(f"Unknown theme: {theme!r}.")
    quality = "draft" if raw.get("quality") == "draft" else "final"
    voice = raw.get("voice") or {}
    voice_id = voice.get("voice") or None
    try:
        rate, pitch = int(voice.get("rate", 0) or 0), int(voice.get("pitch", 0) or 0)
    except (TypeError, ValueError):
        raise VideoError("Voice speed/pitch must be numbers.")
    try:
        if not voice_id:
            voice_id = tts.voice_for(voice.get("lang", "ar-SA"), voice.get("gender", "female"))
    except tts.TTSError as exc:
        raise VideoError(str(exc))
    if voice_id not in tts._VOICE_BY_ID:
        raise VideoError(f"Unknown voice: {voice_id!r}.")
    if not (tts.RATE_RANGE[0] <= rate <= tts.RATE_RANGE[1]) or not (tts.PITCH_RANGE[0] <= pitch <= tts.PITCH_RANGE[1]):
        raise VideoError("Voice speed or pitch is out of range.")

    scenes_in = raw.get("scenes")
    if not isinstance(scenes_in, list) or not scenes_in:
        raise VideoError("Add at least one scene.")
    if len(scenes_in) > LIMITS["max_scenes"]:
        raise VideoError(f"Too many scenes (limit {LIMITS['max_scenes']}).")

    scenes, total_narr = [], 0
    for i, s in enumerate(scenes_in, 1):
        if not isinstance(s, dict):
            raise VideoError(f"Scene {i} is invalid.")
        layout = s.get("layout", "title")
        if layout not in LAYOUTS:
            raise VideoError(f"Scene {i}: unknown layout {layout!r}.")
        transition = s.get("transition", "fade")
        if transition not in TRANSITIONS:
            transition = "fade"
        bg_in = s.get("background") or {}
        bg_type = bg_in.get("type", "theme")
        if bg_type not in ("theme", "color", "image", "video"):
            raise VideoError(f"Scene {i}: unknown background type.")
        bg = {"type": bg_type, "color": _valid_color(bg_in.get("color")), "asset": bg_in.get("asset")}
        if bg_type in ("image", "video"):
            if assets is None or assets.kind(bg["asset"]) != bg_type:
                raise VideoError(f"Scene {i}: the {bg_type} background was not found. Upload it again.")
        dur = s.get("duration")
        if dur in (None, "", 0):
            dur = None
        else:
            try:
                dur = float(dur)
            except (TypeError, ValueError):
                raise VideoError(f"Scene {i}: duration must be a number of seconds.")
            if not (LIMITS["min_scene_seconds"] <= dur <= LIMITS["max_scene_seconds"]):
                raise VideoError(f"Scene {i}: duration must be between {LIMITS['min_scene_seconds']:g} and {LIMITS['max_scene_seconds']:g} seconds.")
        narration = _text(s.get("narration"), LIMITS["max_narration"], f"Scene {i} narration")
        total_narr += len(narration)
        scene = {
            "layout": layout,
            "title": _text(s.get("title"), LIMITS["max_title"], f"Scene {i} title"),
            "body": _text(s.get("body"), LIMITS["max_body"], f"Scene {i} text"),
            "narration": narration,
            "background": bg,
            "duration": dur,
            "transition": transition,
        }
        if not allow_empty and not (scene["title"] or scene["body"] or narration):
            raise VideoError(f"Scene {i} is empty.")
        scenes.append(scene)
    if total_narr > LIMITS["max_total_narration"]:
        raise VideoError(f"Narration is too long overall (limit {LIMITS['max_total_narration']} characters).")
    return {"size": size, "theme": theme, "captions": bool(raw.get("captions", True)), "quality": quality,
            "voice": {"voice": voice_id, "rate": rate, "pitch": pitch}, "scenes": scenes}


def canvas_size(project: dict) -> tuple[int, int]:
    p = SIZES[project["size"]]
    f = 0.5 if project["quality"] == "draft" else 1.0
    return (round(p["w"] * f / 2) * 2, round(p["h"] * f / 2) * 2)


# ----------------------------------------------------------------------------- preview

def render_preview_png(project: dict, index: int, assets: AssetStore | None, max_width: int = 960) -> bytes:
    import io

    scene = project["scenes"][index]
    full_w, full_h = canvas_size({**project, "quality": "final"})
    f = min(1.0, max_width / full_w)
    size = (round(full_w * f / 2) * 2, round(full_h * f / 2) * 2)
    still = None
    tmpdir = None
    if scene["background"]["type"] == "video" and assets:
        vp = assets.path(scene["background"]["asset"])
        if vp:
            tmpdir = Path(tempfile.mkdtemp(prefix="vf-prev-"))
            still = tmpdir / "still.png"
            _run([ffmpeg_bin(), "-y", "-ss", "0.5", "-i", str(vp), "-frames:v", "1", str(still)], 60)
    try:
        frame = base_frame(project, scene, size, assets, still).convert("RGBA")
        cap = None
        if project["captions"] and scene["narration"]:
            cap = (split_captions(scene["narration"]) or [""])[0]
        frame.alpha_composite(render_overlay(project, scene, size, cap, scrim=scene["background"]["type"] in ("image", "video")))
        buf = io.BytesIO()
        frame.convert("RGB").save(buf, "PNG")
        return buf.getvalue()
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ----------------------------------------------------------------------------- render

ProgressFn = Callable[[float, str], None]


def render_project(project: dict, out_path: Path, assets: AssetStore | None, progress: ProgressFn | None = None,
                   tts_fn: Callable[[str, str, int, int], bytes] | None = None) -> dict:
    """Render a validated project to MP4. Returns {"duration": seconds, "srt": "<text>"}."""
    progress = progress or (lambda p, m: None)
    tts_fn = tts_fn or tts.synthesize_mp3
    out_path = Path(out_path)
    size = canvas_size(project)
    w, h = size
    draft = project["quality"] == "draft"
    voice = project["voice"]
    work = Path(tempfile.mkdtemp(prefix="vf-render-", dir=out_path.parent))
    ff = ffmpeg_bin()
    scene_files: list[Path] = []
    srt_lines: list[str] = []
    t_offset = 0.0
    n = len(project["scenes"])
    portrait = h > w * 1.2

    try:
        for i, scene in enumerate(project["scenes"]):
            progress(i / n * 0.92, f"scene {i + 1}/{n}")
            sdir = work / f"s{i}"
            sdir.mkdir()
            narration = scene["narration"]
            audio = None
            audio_len = 0.0
            if narration:
                audio = sdir / "voice.mp3"
                audio.write_bytes(tts_fn(narration, voice["voice"], voice["rate"], voice["pitch"]))
                audio_len = probe_duration(audio)
            if scene["duration"]:
                dur = float(scene["duration"])
            elif audio:
                dur = max(LIMITS["min_scene_seconds"], audio_len + LIMITS["end_pad_seconds"])
            else:
                dur = LIMITS["default_silent_seconds"]
            dur = round(dur, 2)

            chunks = split_captions(narration, 60 if portrait else 84) if (project["captions"] and narration) else []
            segs = caption_timing(chunks, dur - LIMITS["end_pad_seconds"] if audio and not scene["duration"] else dur) if chunks else []
            # stretch last caption to the end of the scene
            if segs:
                segs[-1] = (segs[-1][0], dur)
            for (a, b), text in zip(segs, chunks):
                srt_lines.append((t_offset + a, t_offset + b, text))

            bg_type = scene["background"]["type"]
            fade = scene["transition"] == "fade"
            vf_fade = f",fade=t=in:st=0:d=0.3,fade=t=out:st={max(0.0, dur - 0.3):.2f}:d=0.3" if fade else ""
            af_fade = f",afade=t=in:st=0:d=0.15,afade=t=out:st={max(0.0, dur - 0.25):.2f}:d=0.25" if fade else ""
            out_scene = sdir / "scene.mp4"
            x264 = ["-c:v", "libx264", "-preset", "ultrafast" if draft else "veryfast", "-crf", "30" if draft else "22",
                    "-pix_fmt", "yuv420p", "-threads", "2", "-r", str(FPS)]
            aud_in = ["-i", str(audio)] if audio else ["-f", "lavfi", "-t", f"{dur}", "-i", "anullsrc=r=44100:cl=stereo"]
            aud_out = ["-af", f"aresample=44100,apad=whole_dur={dur}{af_fade}", "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "44100"]

            timeline = segs if segs else [(0.0, dur)]
            captions_for = chunks if chunks else [None]

            if bg_type == "video":
                vp = assets.path(scene["background"]["asset"])
                if not vp:
                    raise VideoError(f"Scene {i + 1}: background video missing.")
                overlays = []
                for k, cap in enumerate(captions_for):
                    p = sdir / f"ov{k}.png"
                    render_overlay(project, scene, size, cap, scrim=True).save(p)
                    overlays.append(p)
                cmd = [ff, "-y", "-stream_loop", "-1", "-i", str(vp)] + aud_in
                for p in overlays:
                    cmd += ["-i", str(p)]
                chain = f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={FPS},setsar=1[b0]"
                for k, (a, b) in enumerate(timeline):
                    chain += f";[b{k}][{k + 2}:v]overlay=enable='between(t,{a:.3f},{b + 0.01:.3f})'[b{k + 1}]"
                chain += f";[b{len(timeline)}]format=yuv420p{vf_fade}[v]"
                cmd += ["-filter_complex", chain, "-map", "[v]", "-map", "1:a"] + x264 + aud_out + ["-t", f"{dur}", str(out_scene)]
            else:
                lst = sdir / "frames.txt"
                lines = []
                last = None
                base = base_frame(project, scene, size, assets).convert("RGBA")
                for k, ((a, b), cap) in enumerate(zip(timeline, captions_for)):
                    frame = base.copy()
                    frame.alpha_composite(render_overlay(project, scene, size, cap, scrim=bg_type == "image"))
                    p = sdir / f"f{k}.png"
                    frame.convert("RGB").save(p)
                    lines.append(f"file '{p.as_posix()}'\nduration {b - a:.3f}")
                    last = p
                lines.append(f"file '{last.as_posix()}'")
                lst.write_text("\n".join(lines), encoding="utf-8")
                cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst)] + aud_in
                cmd += ["-vf", f"fps={FPS},format=yuv420p{vf_fade}", "-map", "0:v", "-map", "1:a"] + x264 + aud_out + ["-t", f"{dur}", str(out_scene)]
            _must(cmd, f"Rendering scene {i + 1}")
            scene_files.append(out_scene)
            t_offset += dur
            if audio:
                audio.unlink(missing_ok=True)

        progress(0.94, "joining scenes")
        lst = work / "all.txt"
        lst.write_text("\n".join(f"file '{p.as_posix()}'" for p in scene_files), encoding="utf-8")
        _must([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(out_path)], "Joining scenes")
        progress(1.0, "done")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    srt = []
    for idx, (a, b, text) in enumerate(srt_lines, 1):
        srt.append(f"{idx}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n")
    return {"duration": round(t_offset, 2), "srt": "\n".join(srt)}


# ----------------------------------------------------------------------------- jobs

class JobManager:
    """Runs renders in background threads (one at a time per process). Job state lives on disk
    (job.json), so any gunicorn worker can answer status requests and restarts don't lose results."""

    STALE_SECONDS = 600
    MAX_ACTIVE = 4

    def __init__(self, data_dir: Path, ttl_seconds: int = 24 * 3600):
        self.root = Path(data_dir)
        self.jobs_dir = self.root / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.assets = AssetStore(self.root / "assets")
        self.ttl = ttl_seconds
        self._render_lock = threading.Semaphore(1)

    # -- state on disk
    def _write(self, job: dict) -> None:
        d = Path(job["dir"])
        tmp = d / "job.json.tmp"
        tmp.write_text(json.dumps(job), encoding="utf-8")
        os.replace(tmp, d / "job.json")

    def _read(self, d: Path) -> dict | None:
        try:
            job = json.loads((d / "job.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if job.get("status") in ("queued", "running") and time.time() - (d / "job.json").stat().st_mtime > self.STALE_SECONDS:
            job.update(status="error", error="The render was interrupted. Please try again.", message="failed")
        return job

    def active_count(self) -> int:
        n = 0
        for d in self.jobs_dir.iterdir():
            job = self._read(d) if d.is_dir() else None
            if job and job["status"] in ("queued", "running"):
                n += 1
        return n

    def cleanup(self) -> None:
        cutoff = time.time() - self.ttl
        for d in self.jobs_dir.iterdir():
            try:
                if d.stat().st_mtime < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass
        self.assets.cleanup(self.ttl)

    def submit(self, project: dict, tts_fn=None) -> str:
        self.cleanup()
        if self.active_count() >= self.MAX_ACTIVE:
            raise VideoError("The server is busy rendering other videos. Please try again in a minute.")
        job_id = uuid.uuid4().hex
        d = self.jobs_dir / job_id
        d.mkdir()
        job = {"id": job_id, "status": "queued", "progress": 0.0, "message": "queued", "error": None,
               "duration": None, "dir": str(d)}
        self._write(job)
        threading.Thread(target=self._run, args=(job, project, tts_fn), daemon=True).start()
        return job_id

    def _run(self, job: dict, project: dict, tts_fn) -> None:
        def update(**kw):
            job.update(kw)
            self._write(job)

        with self._render_lock:
            update(status="running", message="starting")
            d = Path(job["dir"])
            try:
                info = render_project(project, d / "video.mp4", self.assets,
                                      lambda p, m: update(progress=round(p, 3), message=m), tts_fn)
                (d / "captions.srt").write_text(info["srt"], encoding="utf-8")
                update(status="done", progress=1.0, message="done", duration=info["duration"])
            except (VideoError, tts.TTSError, tts.TTSUnavailable) as exc:
                update(status="error", error=str(exc), message="failed")
            except Exception as exc:  # never leave a job stuck in "running"
                update(status="error", error=f"Unexpected error: {exc}", message="failed")

    def get(self, job_id: str) -> dict | None:
        if not re.fullmatch(r"[0-9a-f]{32}", job_id or ""):
            return None
        d = self.jobs_dir / job_id
        return self._read(d) if d.is_dir() else None

    def file(self, job_id: str, name: str) -> Path | None:
        job = self.get(job_id)
        if not job or job["status"] != "done" or name not in ("video.mp4", "captions.srt"):
            return None
        p = Path(job["dir"]) / name
        return p if p.exists() else None
