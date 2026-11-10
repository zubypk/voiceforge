"""Video engine: scenes -> slides (Pillow, proper Arabic/RTL shaping) + narration (TTS) -> MP4 (ffmpeg).

A project is plain JSON:

    {
      "ratio": "16:9",                   # 16:9, 9:16, 1:1, 4:5, 4:3, 21:9   (see RATIOS)
      "resolution": "1080",              # 480 (draft), 720 HD, 1080 Full HD, 1440 2K, 2160 4K   (see RESOLUTIONS)
      "theme": "academy",                # see THEMES
      "captions": true,
      "voice": {"lang": "ar-SA", "gender": "male", "voice": null, "rate": 0, "pitch": 0},
      "music": {"asset": "<id>", "volume": 0.15},          # optional background music
      "scenes": [
        {"layout": "title|bullets|text|quote|media", "title": "...", "body": "...", "narration": "...",
         "background": {"type": "theme|color|image|video", "color": "#112233", "asset": "<id>"},
         "media": {"asset": "<id>", "position": "auto|left|right|top|bottom|full", "fit": "contain|cover"},
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

RATIOS = {
    "16:9": {"label": "YouTube · Educational · Widescreen (16:9)", "w": 16, "h": 9},
    "9:16": {"label": "Shorts · TikTok · Reels · Stories (9:16)", "w": 9, "h": 16},
    "1:1": {"label": "Instagram · Facebook square (1:1)", "w": 1, "h": 1},
    "4:5": {"label": "Instagram portrait (4:5)", "w": 4, "h": 5},
    "4:3": {"label": "Classroom · Presentation (4:3)", "w": 4, "h": 3},
    "21:9": {"label": "Cinema ultrawide (21:9)", "w": 21, "h": 9},
}

# key = length of the short side in pixels (how YouTube names it: 1080p = 1920x1080 or 1080x1920)
RESOLUTIONS = {
    "480": {"label": "SD 480p (draft, fastest)", "short": 480},
    "720": {"label": "HD 720p", "short": 720},
    "1080": {"label": "Full HD 1080p", "short": 1080},
    "1440": {"label": "2K QHD 1440p", "short": 1440},
    "2160": {"label": "4K UHD 2160p", "short": 2160},
}

# Longest video allowed per resolution (seconds): big frames render much more slowly.
MAX_SECONDS = {"480": 1800.0, "720": 1800.0, "1080": 1800.0, "1440": 900.0, "2160": 600.0}

# Projects saved by the first version used these ids.
LEGACY_SIZES = {
    "youtube-1080": ("16:9", "1080"), "youtube-720": ("16:9", "720"), "shorts": ("9:16", "1080"),
    "square": ("1:1", "1080"), "portrait": ("4:5", "1080"), "classroom": ("4:3", "1080"),
}

THEMES = {
    "academy": {"label": "Academy", "bg": ("#0f2a5c", "#1d4e9e"), "text": "#ffffff", "accent": "#ffc857", "muted": "#cfdcf5"},
    "chalkboard": {"label": "Chalkboard", "bg": ("#173b2e", "#245c45"), "text": "#f4f1e8", "accent": "#ffd166", "muted": "#cfe3d8"},
    "clean": {"label": "Clean light", "bg": ("#ffffff", "#e8f0ff"), "text": "#14213d", "accent": "#2f6bff", "muted": "#51607f"},
    "bold": {"label": "Bold", "bg": ("#7c3aed", "#ec4899"), "text": "#ffffff", "accent": "#fde047", "muted": "#f6dcff"},
    "midnight": {"label": "Midnight", "bg": ("#0b1020", "#1b2440"), "text": "#e8ecff", "accent": "#38bdf8", "muted": "#9aa6cf"},
}

LAYOUTS = ("title", "bullets", "text", "quote", "media")
MEDIA_POSITIONS = ("auto", "left", "right", "top", "bottom", "full")
MEDIA_FITS = ("contain", "cover")
FPS = 30

# Transition from a scene into the next one. "fade" = dip to black inside the scene, "none" = hard cut,
# everything else is an ffmpeg xfade between the two scenes (left/right are mirrored for RTL scenes).
XFADE = {
    "crossfade": "fade", "dissolve": "dissolve", "fadeblack": "fadeblack", "fadewhite": "fadewhite",
    "wipeleft": "wipeleft", "wiperight": "wiperight", "wipeup": "wipeup", "wipedown": "wipedown",
    "slideleft": "slideleft", "slideright": "slideright", "slideup": "slideup", "slidedown": "slidedown",
    "smoothleft": "smoothleft", "smoothright": "smoothright", "coverleft": "coverleft", "revealleft": "revealleft",
    "circleopen": "circleopen", "circleclose": "circleclose", "radial": "radial", "zoomin": "zoomin",
    "pixelize": "pixelize", "diagtl": "diagtl", "hblur": "hblur", "squeezeh": "squeezeh",
    "vertopen": "vertopen", "horzopen": "horzopen", "hlslice": "hlslice", "fadegrays": "fadegrays",
}
TRANSITIONS = ("fade", "none") + tuple(XFADE)
_MIRROR = {"left": "right", "right": "left", "tl": "tr", "tr": "tl", "hl": "hr", "hr": "hl"}
XFADE_SECONDS = 0.7

MOTIONS = ("none", "zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up")
LOOKS = ("none", "grayscale", "sepia", "vintage", "warm", "cool", "vivid", "blur", "vignette", "dark")
STICKER_ANIMS = ("none", "fade", "slide", "rise", "pop", "float", "pulse", "spin")
MAX_STICKERS = 10


def _limits() -> dict:
    total = tts.max_text_chars() or 1_000_000
    return {
        "max_scenes": 60,
        "max_title": 200,
        "max_body": 1500,
        "max_narration": 20_000,           # per scene
        "max_total_narration": total,
        "min_scene_seconds": 2.0,
        "max_scene_seconds": 600.0,
        "default_silent_seconds": 5.0,
        "end_pad_seconds": 0.5,
        "max_seconds": MAX_SECONDS,
        "max_image_bytes": 25 * 1024 * 1024,
        "max_video_bytes": 300 * 1024 * 1024,
        "max_audio_bytes": 60 * 1024 * 1024,
        "owner_quota_bytes": 800 * 1024 * 1024,
    }


LIMITS = _limits()


def dimensions(ratio: str, resolution: str) -> tuple[int, int]:
    """Pixel size for an aspect ratio and a resolution key (short side), both even numbers."""
    r, short = RATIOS[ratio], RESOLUTIONS[resolution]["short"]
    if r["w"] >= r["h"]:
        h, w = short, short * r["w"] / r["h"]
    else:
        w, h = short, short * r["h"] / r["w"]
    return round(w / 2) * 2, round(h / 2) * 2


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
    "gu": ["NotoSansGujarati-{W}.ttf"],
    "te": ["NotoSansTelugu-{W}.ttf"],
    "kn": ["NotoSansKannada-{W}.ttf"],
    "ml": ["NotoSansMalayalam-{W}.ttf"],
    "si": ["NotoSansSinhala-{W}.ttf"],
    "km": ["NotoSansKhmer-{W}.ttf"],
    "lo": ["NotoSansLao-{W}.ttf"],
    "my": ["NotoSansMyanmar-{W}.ttf"],
    "ka": ["NotoSansGeorgian-{W}.ttf"],
    "am": ["NotoSansEthiopic-{W}.ttf"],
    "pa": ["NotoSansGurmukhi-{W}.ttf"],
    "zh": ["NotoSansCJKsc-{W}.otf"],     # one CJK font covers Chinese, Japanese and Korean
    "ja": ["NotoSansCJKsc-{W}.otf"],
    "ko": ["NotoSansCJKsc-{W}.otf"],
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


def regions(project: dict, scene: dict, size: tuple[int, int]) -> dict:
    """Where text and media go on a slide. Rects are (x0, y0, x1, y1) in pixels."""
    w, h = size
    mx, my = w * 0.08, h * 0.08
    bottom = h * (0.76 if (project["captions"] and scene["narration"]) else 0.92)
    area = (mx, my, w - mx, bottom)
    media = scene.get("media") or {}
    layout = scene["layout"]
    if not media.get("asset") or layout in ("title", "quote"):
        return {"text": area, "media": None}
    cw, ch = area[2] - area[0], area[3] - area[1]
    gap = w * 0.04
    if layout == "media" and media.get("position") == "full":   # whole frame (imported slides / PDF pages)
        cap = project["captions"] and scene["narration"]
        return {"text": area, "media": (0, 0, w, h * 0.80) if cap else (0, 0, w, h), "title_h": 0.0, "cap_h": 0.0}
    if layout == "media":
        title_h = h * 0.17 if scene["title"] else 0.0
        cap_h = h * 0.13 if scene["body"] else 0.0
        return {"text": area, "media": (mx, my + title_h, area[2], bottom - cap_h), "title_h": title_h, "cap_h": cap_h}
    pos = media.get("position", "auto")
    if pos == "full":
        pos = "auto"
    landscape = w >= h * 1.3
    if pos == "auto":
        pos = (("left" if is_rtl(scene["title"] or scene["body"]) else "right") if landscape else "top")
    if pos in ("left", "right"):
        text_w = cw * 0.55
        media_w = cw - text_w - gap
        if pos == "right":
            return {"text": (area[0], area[1], area[0] + text_w, area[3]), "media": (area[2] - media_w, area[1], area[2], area[3])}
        return {"text": (area[2] - text_w, area[1], area[2], area[3]), "media": (area[0], area[1], area[0] + media_w, area[3])}
    media_h = ch * 0.42
    if pos == "top":
        return {"text": (area[0], area[1] + media_h + gap * 0.6, area[2], area[3]), "media": (area[0], area[1], area[2], area[1] + media_h)}
    return {"text": (area[0], area[1], area[2], area[3] - media_h - gap * 0.6), "media": (area[0], area[3] - media_h, area[2], area[3])}


def int_rect(rect: tuple) -> tuple[int, int, int, int]:
    """(x, y, w, h) with even values, as ffmpeg likes them."""
    x0, y0, x1, y1 = rect
    x, y = int(x0) // 2 * 2, int(y0) // 2 * 2
    return x, y, max(2, (int(x1) - x) // 2 * 2), max(2, (int(y1) - y) // 2 * 2)


def paste_media(layer: Image.Image, rect: tuple, img: Image.Image, fit: str, theme: dict, unit: int, plain: bool = False) -> None:
    from PIL import ImageFilter

    x, y, rw, rh = int_rect(rect)
    img = img.convert("RGB")
    if fit == "cover":
        fitted, px, py = cover(img, (rw, rh)), x, y
    else:
        k = min(rw / img.width, rh / img.height)
        fw, fh = max(2, round(img.width * k)), max(2, round(img.height * k))
        fitted, px, py = img.resize((fw, fh), Image.LANCZOS), x + (rw - fw) // 2, y + (rh - fh) // 2
    if plain:                      # full-screen slide: no frame, shadow or rounded corners
        layer.paste(fitted, (px, py))
        return
    radius = max(6, round(unit * 0.016))
    mask = Image.new("L", fitted.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, fitted.width - 1, fitted.height - 1), radius, fill=255)
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((px + 4, py + 8, px + fitted.width + 4, py + fitted.height + 8), radius, fill=(0, 0, 0, 95))
    layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(2, unit * 0.008))))
    layer.paste(fitted, (px, py), mask)
    ImageDraw.Draw(layer).rounded_rectangle((px, py, px + fitted.width - 1, py + fitted.height - 1), radius,
                                            outline=(*hex_rgb(theme["accent"]), 255), width=max(2, round(unit * 0.004)))


def render_overlay(project: dict, scene: dict, size: tuple[int, int], caption: str | None, scrim: bool,
                   media_img: Image.Image | None = None) -> Image.Image:
    """Transparent RGBA layer: optional scrim + slide text + media picture + optional caption pill."""
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

    reg = regions(project, scene, size)
    rect = reg["text"]
    mx, my = w * 0.08, h * 0.08
    title, body, layout = scene["title"], scene["body"], scene["layout"]
    rtl_title = is_rtl(title or body)

    if layout == "media" and (scene.get("media") or {}).get("position") == "full":
        pass
    elif layout == "media":
        if title:
            _fit_and_draw(d, [Block(title, 0.082, True, "text", align="center", gap=0.3)],
                          (mx, my, w - mx, my + reg.get("title_h", h * 0.17)), theme, unit, "center")
        if body and reg.get("cap_h"):
            _fit_and_draw(d, [Block(body.replace("\n", " "), 0.05, False, "muted", align="center")],
                          (mx, rect[3] - reg["cap_h"], w - mx, rect[3]), theme, unit, "center")
    elif layout == "title":
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
            blocks.append(Block(title, 0.082, True, "text", align="start", gap=0.5, rule=True))
        if layout == "bullets":
            for item in _bullets(body):
                blocks.append(Block(item, 0.062, False, "text", bullet=True, gap=0.6))
        elif body:
            blocks.append(Block(body, 0.058, False, "text", gap=0.3))
        _fit_and_draw(d, blocks, rect, theme, unit, "top")

    if reg["media"] and media_img is not None:
        m = scene.get("media") or {}
        paste_media(layer, reg["media"], media_img, m.get("fit", "contain"), theme, unit,
                    plain=layout == "media" and m.get("position") == "full")
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


def first_frame(video_path: Path, out_png: Path) -> Path | None:
    _run([ffmpeg_bin(), "-y", "-ss", "0.4", "-i", str(video_path), "-frames:v", "1", str(out_png)], 60)
    if not out_png.exists():  # clips shorter than 0.4 s
        _run([ffmpeg_bin(), "-y", "-i", str(video_path), "-frames:v", "1", str(out_png)], 60)
    return out_png if out_png.exists() else None


def scene_media(scene: dict, assets: "AssetStore | None") -> tuple[str, Path] | None:
    m = scene.get("media") or {}
    if not m.get("asset") or scene["layout"] in ("title", "quote") or assets is None:
        return None
    p = assets.path(m["asset"])
    kind = assets.kind(m["asset"])
    return (kind, p) if p and kind in ("image", "video") else None


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
    merged: list[str] = []  # merge tiny tails into the previous chunk
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
    """One user's uploads: <root>/<id>.<ext> plus <id>.json (name, kind, size) and cached thumbnails."""

    IMAGE_EXT = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}
    VIDEO_EXT = {".mp4": "mp4", ".mov": "mov", ".webm": "webm", ".m4v": "mp4"}
    AUDIO_EXT = {".mp3": "mp3", ".wav": "wav", ".m4a": "m4a", ".aac": "aac", ".ogg": "ogg", ".flac": "flac",
                 ".weba": "weba", ".opus": "opus", ".oga": "oga"}   # .weba/.opus = browser microphone recordings

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _ok_id(asset_id) -> bool:
        return bool(re.fullmatch(r"[0-9a-f]{32}", str(asset_id or "")))

    def path(self, asset_id: str) -> Path | None:
        if not self._ok_id(asset_id):
            return None
        for p in self.root.glob(f"{asset_id}.*"):
            if p.suffix != ".json" and not p.name.endswith(".thumb.jpg"):
                return p
        return None

    def meta(self, asset_id: str) -> dict | None:
        p = self.path(asset_id)
        if not p:
            return None
        try:
            return json.loads((self.root / f"{asset_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            ext = p.suffix.lower().lstrip(".")
            kind = "video" if ext in ("mp4", "mov", "webm") else "audio" if ext in ("mp3", "wav", "m4a", "aac", "ogg", "flac", "weba", "opus", "oga") else "image"
            return {"id": asset_id, "kind": kind, "name": p.name, "bytes": p.stat().st_size, "created": p.stat().st_mtime}

    def kind(self, asset_id: str) -> str | None:
        m = self.meta(asset_id)
        return m["kind"] if m else None

    def total_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.root.iterdir() if p.is_file())

    def list(self) -> list[dict]:
        out = []
        for p in self.root.glob("*.json"):
            m = self.meta(p.stem)
            if m:
                out.append(m)
        return sorted(out, key=lambda m: m.get("created", 0), reverse=True)

    def delete(self, asset_id: str) -> bool:
        p = self.path(asset_id)
        if not p:
            return False
        for f in self.root.glob(f"{asset_id}*"):
            f.unlink(missing_ok=True)
        return True

    def save(self, data: bytes, filename: str) -> dict:
        import io

        name = re.sub(r"[^\w.\- ]+", "_", Path(filename or "upload").name)[:80] or "upload"
        ext = Path(name).suffix.lower()
        if self.total_bytes() + len(data) > LIMITS["owner_quota_bytes"]:
            raise VideoError("Your storage is full. Delete some uploads first.")
        asset_id = uuid.uuid4().hex
        nbytes = len(data)
        if ext in self.VIDEO_EXT or ext in self.AUDIO_EXT:
            is_video = ext in self.VIDEO_EXT
            if len(data) > (LIMITS["max_video_bytes"] if is_video else LIMITS["max_audio_bytes"]):
                raise VideoError("Video is too large." if is_video else "Audio file is too large.")
            dest = self.root / f"{asset_id}.{(self.VIDEO_EXT if is_video else self.AUDIO_EXT)[ext]}"
            dest.write_bytes(data)
            if not is_video and ext in (".weba", ".opus", ".oga"):
                # browser microphone recordings (WebM/Ogg Opus) have no duration header: store them as MP3
                mp3 = self.root / f"{asset_id}.mp3"
                conv = _run([ffmpeg_bin(), "-y", "-loglevel", "error", "-i", str(dest), "-vn", "-codec:a", "libmp3lame",
                             "-b:a", "160k", "-ar", "44100", str(mp3)], 300)
                dest.unlink(missing_ok=True)
                if conv.returncode or not mp3.exists():
                    mp3.unlink(missing_ok=True)
                    raise VideoError("That recording could not be read. Try recording again.")
                dest, name = mp3, Path(name).with_suffix(".mp3").name
                nbytes = mp3.stat().st_size
            proc = _run([ffmpeg_bin(), "-hide_banner", "-i", str(dest)], 60)
            has = ("Video:" if is_video else "Audio:") in proc.stderr
            if not has or not re.search(r"Duration:\s*\d", proc.stderr):
                dest.unlink(missing_ok=True)
                raise VideoError("That file is not a readable video." if is_video else "That file is not readable audio.")
            kind = "video" if is_video else "audio"
        else:
            if len(data) > LIMITS["max_image_bytes"]:
                raise VideoError("Image is too large (limit 25 MB).")
            try:
                with Image.open(io.BytesIO(data)) as im:
                    fmt = im.format
                    im.verify()
            except Exception:
                raise VideoError("Unsupported file. Use PNG/JPG/WEBP images, MP4/MOV/WEBM video or MP3/WAV/M4A audio.")
            if fmt not in self.IMAGE_EXT:
                raise VideoError("Unsupported image format. Use PNG, JPG or WEBP.")
            (self.root / f"{asset_id}.{self.IMAGE_EXT[fmt]}").write_bytes(data)
            kind = "image"
        meta = {"id": asset_id, "kind": kind, "name": name, "bytes": nbytes, "created": time.time()}
        (self.root / f"{asset_id}.json").write_text(json.dumps(meta), encoding="utf-8")
        return meta

    def annotate(self, asset_id: str, **extra) -> dict:
        """Store extra metadata (e.g. licence/attribution of library media) next to an asset."""
        meta = self.meta(asset_id)
        if not meta:
            raise VideoError("Asset not found.")
        meta.update({k: v for k, v in extra.items() if v is not None})
        (self.root / f"{asset_id}.json").write_text(json.dumps(meta), encoding="utf-8")
        return meta

    def thumb(self, asset_id: str) -> Path | None:
        p = self.path(asset_id)
        if not p:
            return None
        out = self.root / f"{asset_id}.thumb.jpg"
        if out.exists():
            return out
        kind = self.kind(asset_id)
        try:
            if kind == "image":
                with Image.open(p) as im:
                    im = im.convert("RGB")
                    im.thumbnail((360, 360))
                    im.save(out, "JPEG", quality=82)
            elif kind == "video":
                still = self.root / f"{asset_id}.still.png"
                if first_frame(p, still):
                    with Image.open(still) as im:
                        im = im.convert("RGB")
                        im.thumbnail((360, 360))
                        im.save(out, "JPEG", quality=82)
                    still.unlink(missing_ok=True)
        except Exception:
            return None
        return out if out.exists() else None

    def cleanup(self, max_age_seconds: float, keep: set[str]) -> None:
        cutoff = time.time() - max_age_seconds
        for p in self.root.glob("*.json"):
            try:
                if p.stem not in keep and p.stat().st_mtime < cutoff:
                    self.delete(p.stem)
            except OSError:
                pass


# ----------------------------------------------------------------------------- validation

def _text(v, limit: int, name: str) -> str:
    v = "" if v is None else str(v)
    v = v.replace("\x00", "").strip()
    if len(v) > limit:
        raise VideoError(f"{name} is too long (limit {limit:,} characters).")
    return v


def _num(v, default: float, lo: float, hi: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return default if f != f else min(hi, max(lo, f))


def validate_project(raw: dict, assets: AssetStore | None = None, allow_empty: bool = False) -> dict:
    if not isinstance(raw, dict):
        raise VideoError("Invalid project.")
    L = LIMITS
    ratio, resolution = raw.get("ratio"), raw.get("resolution")
    if raw.get("size") in LEGACY_SIZES and not ratio:           # projects from the first version
        ratio, resolution = LEGACY_SIZES[raw["size"]]
        if raw.get("quality") == "draft":
            resolution = "480"
    ratio, resolution = ratio or "16:9", str(resolution or "1080")
    if ratio not in RATIOS:
        raise VideoError(f"Unknown aspect ratio: {ratio!r}.")
    if resolution not in RESOLUTIONS:
        raise VideoError(f"Unknown resolution: {resolution!r}.")
    theme = raw.get("theme", "academy")
    if theme not in THEMES:
        raise VideoError(f"Unknown theme: {theme!r}.")

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

    music = None
    m_in = raw.get("music") or {}
    if m_in.get("asset"):
        if assets is None or assets.kind(m_in["asset"]) != "audio":
            raise VideoError("The background music file was not found. Upload it again.")
        try:
            vol = float(m_in.get("volume", 0.15))
        except (TypeError, ValueError):
            vol = 0.15
        music = {"asset": m_in["asset"], "volume": min(1.0, max(0.0, vol))}

    scenes_in = raw.get("scenes")
    if not isinstance(scenes_in, list) or not scenes_in:
        raise VideoError("Add at least one scene.")
    if len(scenes_in) > L["max_scenes"]:
        raise VideoError(f"Too many scenes (limit {L['max_scenes']}).")

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
        med_in = s.get("media") or {}
        media = None
        if med_in.get("asset"):
            if assets is None or assets.kind(med_in["asset"]) not in ("image", "video"):
                raise VideoError(f"Scene {i}: the picture/video was not found. Upload it again.")
            pos = med_in.get("position", "auto")
            fit = med_in.get("fit", "contain")
            media = {"asset": med_in["asset"], "position": pos if pos in MEDIA_POSITIONS else "auto",
                     "fit": fit if fit in MEDIA_FITS else "contain"}
        dur = s.get("duration")
        if dur in (None, "", 0):
            dur = None
        else:
            try:
                dur = float(dur)
            except (TypeError, ValueError):
                raise VideoError(f"Scene {i}: duration must be a number of seconds.")
            if not (L["min_scene_seconds"] <= dur <= L["max_scene_seconds"]):
                raise VideoError(f"Scene {i}: duration must be between {L['min_scene_seconds']:g} and {L['max_scene_seconds']:g} seconds.")
        narration = _text(s.get("narration"), L["max_narration"], f"Scene {i} narration")
        total_narr += len(narration)
        motion = s.get("motion", "none") if s.get("motion") in MOTIONS else "none"
        look = s.get("look", "none") if s.get("look") in LOOKS else "none"
        vo = None
        if (s.get("voiceover") or {}).get("asset"):
            if assets is None or assets.kind(s["voiceover"]["asset"]) != "audio":
                raise VideoError(f"Scene {i}: the recorded voice-over was not found. Record it again.")
            vo = {"asset": s["voiceover"]["asset"]}
        sfx = None
        if (s.get("sfx") or {}).get("asset"):
            if assets is None or assets.kind(s["sfx"]["asset"]) != "audio":
                raise VideoError(f"Scene {i}: the sound effect was not found.")
            sfx = {"asset": s["sfx"]["asset"], "at": _num(s["sfx"].get("at"), 0.0, 0.0, 600.0),
                   "volume": _num(s["sfx"].get("volume"), 0.8, 0.0, 2.0)}
        stickers = []
        for k in (s.get("stickers") or [])[:MAX_STICKERS]:
            if not isinstance(k, dict) or not k.get("asset"):
                continue
            if assets is None or assets.kind(k["asset"]) != "image":
                raise VideoError(f"Scene {i}: a sticker/clip-art image was not found.")
            stickers.append({"asset": k["asset"], "x": _num(k.get("x"), 0.5, 0.0, 1.0), "y": _num(k.get("y"), 0.5, 0.0, 1.0),
                             "w": _num(k.get("w"), 0.2, 0.02, 1.0), "start": _num(k.get("start"), 0.0, 0.0, 600.0),
                             "anim": k.get("anim") if k.get("anim") in STICKER_ANIMS else "pop"})
        scene = {"layout": layout, "title": _text(s.get("title"), L["max_title"], f"Scene {i} title"),
                 "body": _text(s.get("body"), L["max_body"], f"Scene {i} text"), "narration": narration,
                 "background": bg, "media": media, "duration": dur, "transition": transition,
                 "motion": motion, "look": look, "voiceover": vo, "sfx": sfx, "stickers": stickers}
        if not allow_empty and not (scene["title"] or scene["body"] or narration or media or vo or stickers
                                    or bg_type in ("image", "video")):
            raise VideoError(f"Scene {i} is empty.")
        scenes.append(scene)
    if total_narr > L["max_total_narration"]:
        raise VideoError(f"Narration is too long overall (limit {L['max_total_narration']:,} characters).")
    return {"ratio": ratio, "resolution": resolution, "theme": theme, "captions": bool(raw.get("captions", True)),
            "voice": {"voice": voice_id, "rate": rate, "pitch": pitch}, "music": music, "scenes": scenes}


def canvas_size(project: dict) -> tuple[int, int]:
    return dimensions(project["ratio"], project["resolution"])


# ----------------------------------------------------------------------------- preview

def render_preview_png(project: dict, index: int, assets: AssetStore | None, max_width: int = 960,
                       stickers: bool = True) -> bytes:
    import io

    scene = project["scenes"][index]
    full_w, full_h = dimensions(project["ratio"], "1080")  # preview is drawn as the 1080p layout, scaled down
    f = min(1.0, max_width / full_w)
    size = (round(full_w * f / 2) * 2, round(full_h * f / 2) * 2)
    tmpdir = Path(tempfile.mkdtemp(prefix="vf-prev-"))
    try:
        bg_still = media_img = None
        if scene["background"]["type"] == "video" and assets:
            vp = assets.path(scene["background"]["asset"])
            bg_still = first_frame(vp, tmpdir / "bg.png") if vp else None
        sm = scene_media(scene, assets)
        if sm:
            kind, path = sm
            if kind == "video":
                path = first_frame(path, tmpdir / "media.png")
            if path:
                with Image.open(path) as im:
                    media_img = im.convert("RGB")
        frame = look_pil(base_frame(project, scene, size, assets, bg_still), scene.get("look", "none")).convert("RGBA")
        cap = None
        if project["captions"] and scene["narration"]:
            cap = (split_captions(scene["narration"]) or [""])[0]
        frame.alpha_composite(render_overlay(project, scene, size, cap, scene["background"]["type"] in ("image", "video"), media_img))
        if stickers:
            for st in scene.get("stickers") or []:
                img = sticker_image(assets, st, size[0])
                if img is not None:
                    frame.paste(img, sticker_box(st, img, size), img)
        buf = io.BytesIO()
        frame.convert("RGB").save(buf, "PNG")
        return buf.getvalue()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ----------------------------------------------------------------------------- render

ProgressFn = Callable[[float, str], None]


def _video_overlay_filter(rect: tuple, fit: str, in_label: str, base_label: str, out_label: str, src_idx: int) -> str:
    x, y, rw, rh = int_rect(rect)
    if fit == "cover":
        scale = f"scale={rw}:{rh}:force_original_aspect_ratio=increase,crop={rw}:{rh}"
    else:
        scale = f"scale={rw}:{rh}:force_original_aspect_ratio=decrease"
    return (f"[{src_idx}:v]fps={FPS},{scale},setsar=1[mv{src_idx}];"
            f"[{base_label}][mv{src_idx}]overlay=x={x}+({rw}-overlay_w)/2:y={y}+({rh}-overlay_h)/2[{out_label}]")


def _motion_filter(motion: str, w: int, h: int, dur: float) -> str:
    d = max(dur, 0.1)
    if motion == "zoom_in":
        return f"scale=w='trunc({w}*(1+0.12*t/{d:.3f})/2)*2':h=-2:eval=frame,crop={w}:{h}"
    if motion == "zoom_out":
        return f"scale=w='trunc({w}*(1.12-0.12*t/{d:.3f})/2)*2':h=-2:eval=frame,crop={w}:{h}"
    big_w, big_h = (int(w * 1.18) // 2) * 2, (int(h * 1.18) // 2) * 2
    if motion == "pan_left":
        return f"scale={big_w}:{big_h},crop={w}:{h}:x='(iw-ow)*(1-t/{d:.3f})':y='(ih-oh)/2'"
    if motion == "pan_right":
        return f"scale={big_w}:{big_h},crop={w}:{h}:x='(iw-ow)*t/{d:.3f}':y='(ih-oh)/2'"
    if motion == "pan_up":
        return f"scale={big_w}:{big_h},crop={w}:{h}:x='(iw-ow)/2':y='(ih-oh)*(1-t/{d:.3f})'"
    return ""


_LOOK_FILTERS = {
    "grayscale": "hue=s=0",
    "sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131",
    "vintage": "curves=preset=vintage",
    "warm": "colorbalance=rs=.10:gs=.03:bs=-.10:rm=.06:bm=-.06",
    "cool": "colorbalance=rs=-.08:bs=.10:rm=-.04:bm=.08",
    "vivid": "eq=saturation=1.4:contrast=1.06",
    "blur": "gblur=sigma=12",
    "vignette": "vignette=angle=PI/4",
    "dark": "eq=brightness=-0.12:saturation=0.9",
}


def _look_filter(look: str) -> str:
    return _LOOK_FILTERS.get(look, "")


def look_pil(img: Image.Image, look: str) -> Image.Image:
    """Approximate the ffmpeg look for the still preview."""
    from PIL import ImageEnhance, ImageFilter, ImageOps

    img = img.convert("RGB")
    if look == "grayscale":
        return ImageOps.grayscale(img).convert("RGB")
    if look in ("sepia", "vintage"):
        g = ImageOps.grayscale(img)
        out = ImageOps.colorize(g, "#2e1f0f", "#f3e2c0")
        return Image.blend(img, out, 0.85 if look == "sepia" else 0.55)
    if look == "vivid":
        return ImageEnhance.Contrast(ImageEnhance.Color(img).enhance(1.4)).enhance(1.06)
    if look == "blur":
        return img.filter(ImageFilter.GaussianBlur(max(2, img.width / 160)))
    if look == "dark":
        return ImageEnhance.Brightness(img).enhance(0.8)
    if look in ("warm", "cool"):
        r, g, b = img.split()
        k = 1.1 if look == "warm" else 0.92
        r = r.point(lambda v: min(255, int(v * k)))
        b = b.point(lambda v: min(255, int(v / k)))
        return Image.merge("RGB", (r, g, b))
    if look == "vignette":
        w, h = img.size
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).ellipse((-w * 0.25, -h * 0.25, w * 1.25, h * 1.25), fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(min(w, h) / 6))
        return Image.composite(img, Image.new("RGB", (w, h), (0, 0, 0)), mask)
    return img


def scene_is_rtl(scene: dict) -> bool:
    return is_rtl(scene.get("title") or scene.get("body") or scene.get("narration") or "")


def xfade_name(transition: str, rtl: bool) -> str | None:
    name = XFADE.get(transition)
    if not name or not rtl:
        return name
    for a, b in _MIRROR.items():
        if name.endswith(a):
            return name[: -len(a)] + b
    return name


def sticker_image(assets: "AssetStore", sticker: dict, frame_w: int) -> Image.Image | None:
    p = assets.path(sticker["asset"]) if assets else None
    if not p:
        return None
    with Image.open(p) as im:
        im = im.convert("RGBA")
        sw = max(2, round(sticker["w"] * frame_w / 2) * 2)
        sh = max(2, round(im.height * sw / im.width / 2) * 2)
        return im.resize((sw, sh), Image.LANCZOS)


def sticker_box(sticker: dict, img: Image.Image, size: tuple[int, int]) -> tuple[int, int]:
    w, h = size
    return round(sticker["x"] * w - img.width / 2), round(sticker["y"] * h - img.height / 2)


def _sticker_filter(idx: int, st: dict, sw: int, sh: int, x: int, y: int, size: tuple[int, int], rtl: bool,
                    base: str, out: str) -> str:
    w, h = size
    S = f"{st['start']:.3f}"
    p = f"min(1,max(0,(t-{S})/0.6))"
    ease = f"(1-pow(1-{p},3))"
    src = f"[{idx}:v]format=rgba"
    xs, ys = str(x), str(y)
    anim = st["anim"]
    if anim == "fade":
        src += f",fade=t=in:st={S}:d=0.5:alpha=1"
    elif anim == "slide":
        off = int(w * 0.3) * (1 if rtl else -1)
        src += f",fade=t=in:st={S}:d=0.4:alpha=1"
        xs = f"'{x}+({off})*(1-{ease})'"
    elif anim == "rise":
        src += f",fade=t=in:st={S}:d=0.4:alpha=1"
        ys = f"'{y}+{int(h * 0.15)}*(1-{ease})'"
    elif anim == "pop":
        q = f"min(1,max(0.02,(t-{S})/0.4))"
        src += f",scale=w='max(2,trunc({sw}*{q}*(1+0.18*sin(PI*{q}))/2)*2)':h=-2:eval=frame"
        xs, ys = f"'{x}+({sw}-overlay_w)/2'", f"'{y}+({sh}-overlay_h)/2'"
    elif anim == "float":
        ys = f"'{y}+{max(2, int(h * 0.012))}*sin(2*PI*t/2.4)'"
    elif anim == "pulse":
        src += f",scale=w='trunc({sw}*(1+0.06*sin(2*PI*t/1.2))/2)*2':h=-2:eval=frame"
        xs, ys = f"'{x}+({sw}-overlay_w)/2'", f"'{y}+({sh}-overlay_h)/2'"
    elif anim == "spin":
        src += f",rotate='2*PI*t/6*{-1 if rtl else 1}':c=none:ow='hypot(iw,ih)':oh='hypot(iw,ih)'"
        xs, ys = f"'{x}+({sw}-overlay_w)/2'", f"'{y}+({sh}-overlay_h)/2'"
    return (f"{src}[sk{idx}];[{base}][sk{idx}]overlay=x={xs}:y={ys}:enable='gte(t,{S})':eval=frame[{out}]")


def render_project(project: dict, out_path: Path, assets: AssetStore | None, progress: ProgressFn | None = None,
                   tts_fn: Callable[[str, str, int, int], bytes] | None = None) -> dict:
    """Render a validated project to MP4. Returns {"duration": seconds, "srt": "<text>"}.

    Each scene is rendered on its own: background (with motion/look effect) -> slide overlay (text, picture,
    captions) -> media video -> animated stickers; audio = TTS or recorded voice-over (+ sound effect).
    Scenes are then joined with a stream copy, or with xfade/acrossfade when a scene uses a transition.
    """
    progress = progress or (lambda p, m: None)
    tts_fn = tts_fn or tts.synthesize_mp3
    out_path = Path(out_path)
    size = canvas_size(project)
    w, h = size
    resolution = project["resolution"]
    heavy = RESOLUTIONS[resolution]["short"] >= 1440
    draft = resolution == "480"
    voice = project["voice"]
    work = Path(tempfile.mkdtemp(prefix="vf-render-", dir=out_path.parent))
    ff = ffmpeg_bin()
    scene_files: list[Path] = []
    durations: list[float] = []
    scene_caps: list[list] = []
    n = len(project["scenes"])
    portrait = h > w * 1.2
    max_total = MAX_SECONDS[resolution]
    x264 = ["-c:v", "libx264", "-preset", "ultrafast" if draft else "veryfast",
            "-crf", "30" if draft else ("20" if heavy else "22"), "-pix_fmt", "yuv420p",
            "-threads", "3" if heavy else "2", "-r", str(FPS)]
    aac = ["-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "44100"]
    timeout = 3600 if heavy else 1800

    try:
        total = 0.0
        for i, scene in enumerate(project["scenes"]):
            progress(i / n * 0.88, f"scene {i + 1}/{n}")
            sdir = work / f"s{i}"
            sdir.mkdir()
            narration = scene["narration"]
            rtl = scene_is_rtl(scene)
            audio, audio_len = None, 0.0
            vo = scene.get("voiceover")
            if vo and assets and assets.path(vo["asset"]):
                audio = assets.path(vo["asset"])
                audio_len = probe_duration(audio)
            elif narration:
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
            if total + dur > max_total:
                raise VideoError(f"The video is longer than {max_total / 60:g} minutes, the limit for "
                                 f"{RESOLUTIONS[resolution]['label']}. Choose a lower resolution or split it into parts.")
            total += dur

            chunks = split_captions(narration, 60 if portrait else 84) if (project["captions"] and narration) else []
            speak = (audio_len if audio else dur)
            segs = caption_timing(chunks, min(dur, speak) if audio and not scene["duration"] else dur) if chunks else []
            if segs:
                segs[-1] = (segs[-1][0], dur)
            scene_caps.append(list(zip(segs, chunks)))

            bg_type = scene["background"]["type"]
            fade = scene["transition"] == "fade"
            timeline = segs if segs else [(0.0, dur)]
            captions_for = chunks if chunks else [None]

            media_video = media_img = None
            sm = scene_media(scene, assets)
            if sm:
                kind, path = sm
                if kind == "video":
                    media_video = path
                else:
                    with Image.open(path) as im:
                        media_img = im.convert("RGB")
            reg = regions(project, scene, size)

            cmd = [ff, "-y"]
            # input 0: background
            if bg_type == "video":
                vp = assets.path(scene["background"]["asset"]) if assets else None
                if not vp:
                    raise VideoError(f"Scene {i + 1}: background video missing.")
                cmd += ["-stream_loop", "-1", "-i", str(vp)]
                filt = f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={FPS},setsar=1"
            else:
                bp = sdir / "bg.png"
                base_frame(project, scene, size, assets).convert("RGB").save(bp)
                cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur}", "-i", str(bp)]
                filt = f"[0:v]fps={FPS},setsar=1"
            for extra in (_motion_filter(scene.get("motion", "none"), w, h, dur), _look_filter(scene.get("look", "none"))):
                if extra:
                    filt += "," + extra
            filt += "[b0]"
            # input 1: audio
            cmd += ["-i", str(audio)] if audio else ["-f", "lavfi", "-t", f"{dur}", "-i", "anullsrc=r=44100:cl=stereo"]
            # input 2: slide overlay (text, picture, captions) as a timed RGBA image sequence
            lst = sdir / "ov.txt"
            lines, last = [], None
            for k, ((a, b), cap) in enumerate(zip(timeline, captions_for)):
                p = sdir / f"ov{k}.png"
                render_overlay(project, scene, size, cap, bg_type in ("image", "video"), media_img).save(p)
                lines.append(f"file '{p.as_posix()}'\nduration {max(0.04, b - a):.3f}")
                last = p
            lines.append(f"file '{last.as_posix()}'")
            lst.write_text("\n".join(lines), encoding="utf-8")
            cmd += ["-f", "concat", "-safe", "0", "-i", str(lst)]
            filt += f";[2:v]format=rgba[ovs];[b0][ovs]overlay=format=auto:eof_action=repeat[b1]"
            cur, nxt = "b1", 3
            if media_video is not None and reg["media"]:
                cmd += ["-stream_loop", "-1", "-i", str(media_video)]
                filt += ";" + _video_overlay_filter(reg["media"], (scene.get("media") or {}).get("fit", "contain"),
                                                     "", cur, "bm", nxt)
                cur, nxt = "bm", nxt + 1
            for k, st in enumerate(scene.get("stickers") or []):
                img = sticker_image(assets, st, w)
                if img is None:
                    continue
                sp = sdir / f"st{k}.png"
                img.save(sp)
                x, y = sticker_box(st, img, size)
                cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur}", "-i", str(sp)]
                filt += ";" + _sticker_filter(nxt, st, img.width, img.height, x, y, size, rtl, cur, f"bs{k}")
                cur, nxt = f"bs{k}", nxt + 1
            vf_fade = f",fade=t=in:st=0:d=0.3,fade=t=out:st={max(0.0, dur - 0.3):.2f}:d=0.3" if fade else ""
            filt += f";[{cur}]format=yuv420p{vf_fade}[v]"
            # audio: voice (+ sound effect)
            af_fade = f",afade=t=in:st=0:d=0.15,afade=t=out:st={max(0.0, dur - 0.25):.2f}:d=0.25" if fade else ""
            filt += f";[1:a]aresample=44100,aformat=channel_layouts=stereo,apad=whole_dur={dur}[va]"
            alab = "va"
            sfx = scene.get("sfx")
            sp = assets.path(sfx["asset"]) if (sfx and assets) else None
            if sp:
                cmd += ["-i", str(sp)]
                ms = int(sfx["at"] * 1000)
                filt += (f";[{nxt}:a]aresample=44100,aformat=channel_layouts=stereo,volume={sfx['volume']:.2f},"
                         f"adelay={ms}|{ms}[sx];[va][sx]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[vm]")
                alab, nxt = "vm", nxt + 1
            filt += f";[{alab}]atrim=0:{dur}{af_fade}[a]"
            out_scene = sdir / "scene.mp4"
            cmd += ["-filter_complex", filt, "-map", "[v]", "-map", "[a]"] + x264 + aac + ["-t", f"{dur}", str(out_scene)]
            _must(cmd, f"Rendering scene {i + 1}", timeout=timeout)
            scene_files.append(out_scene)
            durations.append(dur)
            if audio and audio.parent == sdir:
                audio.unlink(missing_ok=True)
            for p in sdir.glob("*.png"):
                p.unlink(missing_ok=True)

        # ---- join
        progress(0.9, "joining scenes")
        trans = []
        for i in range(n - 1):
            name = xfade_name(project["scenes"][i]["transition"], scene_is_rtl(project["scenes"][i]))
            d = min(XFADE_SECONDS, durations[i] / 3, durations[i + 1] / 3) if name else 0.0
            trans.append((name, round(d, 3)))
        starts, t = [], 0.0
        for i in range(n):
            starts.append(t)
            t += durations[i] - (trans[i][1] if i < n - 1 else 0.0)
        total = round(t, 3)
        joined = work / "joined.mp4"
        if not any(name for name, _ in trans):
            lst = work / "all.txt"
            lst.write_text("\n".join(f"file '{p.as_posix()}'" for p in scene_files), encoding="utf-8")
            _must([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(joined)],
                  "Joining scenes")
        else:
            cmd = [ff, "-y"]
            for p in scene_files:
                cmd += ["-i", str(p)]
            filt = ";".join(f"[{i}:v]settb=AVTB,fps={FPS},format=yuv420p[v{i}];[{i}:a]aresample=44100[a{i}]" for i in range(n))
            vcur, acur, length = "v0", "a0", durations[0]
            for i in range(1, n):
                name, d = trans[i - 1]
                vo_, ao_ = f"vx{i}", f"ax{i}"
                if name:
                    filt += (f";[{vcur}][v{i}]xfade=transition={name}:duration={d}:offset={max(0.0, length - d):.3f}[{vo_}]"
                             f";[{acur}][a{i}]acrossfade=d={d}:c1=tri:c2=tri[{ao_}]")
                    length += durations[i] - d
                else:
                    filt += f";[{vcur}][{acur}][v{i}][a{i}]concat=n=2:v=1:a=1[{vo_}][{ao_}]"
                    length += durations[i]
                vcur, acur = vo_, ao_
            cmd += ["-filter_complex", filt, "-map", f"[{vcur}]", "-map", f"[{acur}]"] + x264 + aac + \
                   ["-movflags", "+faststart", str(joined)]
            _must(cmd, "Joining scenes with transitions", timeout=timeout)

        music = project.get("music")
        mpath = assets.path(music["asset"]) if (music and assets) else None
        if mpath:
            progress(0.96, "mixing music")
            fade_start = max(0.0, total - 2.0)
            _must([ff, "-y", "-i", str(joined), "-stream_loop", "-1", "-i", str(mpath), "-filter_complex",
                   f"[1:a]volume={music['volume']:.3f},afade=t=in:st=0:d=1.5,afade=t=out:st={fade_start:.2f}:d=2[m];"
                   f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]",
                   "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.2f}",
                   "-movflags", "+faststart", str(out_path)], "Mixing music")
        else:
            shutil.move(str(joined), str(out_path))
        progress(1.0, "done")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    srt_lines = []
    for i, caps in enumerate(scene_caps):
        for (a, b), text in caps:
            srt_lines.append((starts[i] + a, min(starts[i] + b, total), text))
    srt = [f"{idx}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n" for idx, (a, b, text) in enumerate(srt_lines, 1)]
    return {"duration": round(total, 2), "srt": "\n".join(srt)}



# ----------------------------------------------------------------------------- jobs

class JobManager:
    """Runs renders and long audio exports in background threads (one heavy job at a time per process).
    Job state lives on disk (job.json), so any gunicorn worker can answer status requests and restarts
    don't lose results. Each user (owner) has their own asset folder."""

    STALE_SECONDS = 900
    MAX_ACTIVE = 4
    FILES = ("video.mp4", "captions.srt", "speech.mp3")

    def __init__(self, data_dir: Path, ttl_seconds: int = 24 * 3600):
        self.root = Path(data_dir)
        self.jobs_dir = self.root / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.assets_root = self.root / "assets"
        self.assets_root.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl_seconds
        self.referenced_fn: Callable[[], set[str]] = lambda: set()   # asset ids that saved projects still use
        self._render_lock = threading.Semaphore(1)

    def assets_for(self, owner: str) -> AssetStore:
        if not re.fullmatch(r"[a-z0-9]{8,64}", str(owner or "")):
            raise VideoError("Unknown user.")
        return AssetStore(self.assets_root / owner)

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
            job.update(status="error", error="The job was interrupted. Please try again.", message="failed")
        return job

    def active_count(self) -> int:
        n = 0
        for d in self.jobs_dir.iterdir():
            job = self._read(d) if d.is_dir() else None
            if job and job["status"] in ("queued", "running"):
                n += 1
        return n

    def cleanup(self, referenced: set[str] | None = None) -> None:
        cutoff = time.time() - self.ttl
        for d in self.jobs_dir.iterdir():
            try:
                if d.stat().st_mtime < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass
        keep = referenced if referenced is not None else self.referenced_fn()
        for owner_dir in self.assets_root.iterdir():
            if owner_dir.is_dir():
                AssetStore(owner_dir).cleanup(self.ttl, keep)

    def _new_job(self, kind: str) -> dict:
        self.cleanup()
        if self.active_count() >= self.MAX_ACTIVE:
            raise VideoError("The server is busy with other jobs. Please try again in a minute.")
        job_id = uuid.uuid4().hex
        d = self.jobs_dir / job_id
        d.mkdir()
        job = {"id": job_id, "kind": kind, "status": "queued", "progress": 0.0, "message": "queued",
               "error": None, "duration": None, "dir": str(d)}
        self._write(job)
        return job

    def submit(self, project: dict, tts_fn=None, owner: str = "anonymous0") -> str:
        """Start rendering a validated project. (`owner` selects whose uploads the project may use.)"""
        job = self._new_job("video")
        assets = self.assets_for(owner)

        def work(d: Path, update):
            info = render_project(project, d / "video.mp4", assets, lambda p, m: update(progress=round(p, 3), message=m), tts_fn)
            (d / "captions.srt").write_text(info["srt"], encoding="utf-8")
            return {"duration": info["duration"]}

        threading.Thread(target=self._run, args=(job, work), daemon=True).start()
        return job["id"]

    def submit_tts(self, text: str, voice_id: str, rate: int = 0, pitch: int = 0, tts_fn=None) -> str:
        """Start a long text-to-MP3 export."""
        tts._validate(text, voice_id, rate, pitch, tts.max_text_chars())
        job = self._new_job("audio")
        fn = tts_fn or tts.synthesize_mp3

        def work(d: Path, update):
            data = fn(text, voice_id, rate, pitch, progress=lambda p: update(progress=round(p * 0.98, 3), message="speaking"))
            (d / "speech.mp3").write_bytes(data)
            return {}

        threading.Thread(target=self._run, args=(job, work), daemon=True).start()
        return job["id"]

    def _run(self, job: dict, work) -> None:
        def update(**kw):
            job.update(kw)
            self._write(job)

        with self._render_lock:
            update(status="running", message="starting")
            try:
                extra = work(Path(job["dir"]), update)
                update(status="done", progress=1.0, message="done", **extra)
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
        if not job or job["status"] != "done" or name not in self.FILES:
            return None
        p = Path(job["dir"]) / name
        return p if p.exists() else None
