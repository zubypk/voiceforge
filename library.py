"""Free media library for the video studio.

Built in (always available, no network):
  * shapes      - 24 vector-style shapes drawn with Pillow in any colour (transparent PNG)
  * clip art    - ~150 emoji illustrations (Noto Color Emoji, SIL OFL) grouped by topic
  * sfx         - 14 synthesized sound effects (whoosh, pop, ding, ...) made with ffmpeg

Online (Openverse, https://openverse.org - openly licensed media, no API key):
  * real photos, illustrations / clip art, music and sound effects, searchable, with licence + attribution.
  Only items marked for commercial use are returned. Downloads go through the server, which only fetches
  URLs returned by Openverse for the requested id (no arbitrary URLs from the browser).
"""
from __future__ import annotations

import io
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

import video

HERE = Path(__file__).parent
UA = {"User-Agent": "VoiceForge/1.0 (educational video editor)"}
OPENVERSE = os.environ.get("OPENVERSE_API", "https://api.openverse.org/v1")
TIMEOUT = 20
MAX_DOWNLOAD = 40 * 1024 * 1024


class LibraryError(video.VideoError):
    pass


# ----------------------------------------------------------------------------- shapes

SHAPES = ("circle", "square", "rounded", "triangle", "diamond", "hexagon", "star", "heart", "plus", "check", "cross",
          "arrow_right", "arrow_left", "arrow_up", "arrow_down", "speech", "thought", "banner", "badge", "burst",
          "lightning", "cloud", "underline", "ring")


def _poly(cx, cy, r, n, rot=-90, inner=None):
    pts = []
    for k in range(n * (2 if inner else 1)):
        rr = (inner if (inner and k % 2) else r)
        a = math.radians(rot + k * 360 / (n * (2 if inner else 1)))
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return pts


def make_shape(name: str, color: str = "#ffc857", size: int = 512) -> bytes:
    if name not in SHAPES:
        raise LibraryError("Unknown shape.")
    col = video.hex_rgb(video._valid_color(color)) + (255,)
    S = size * 2                       # draw at 2x then downsample = smooth edges
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    m, c = S * 0.06, S / 2
    lw = int(S * 0.09)
    if name == "circle":
        d.ellipse((m, m, S - m, S - m), fill=col)
    elif name == "ring":
        d.ellipse((m, m, S - m, S - m), outline=col, width=lw)
    elif name == "square":
        d.rectangle((m, m, S - m, S - m), fill=col)
    elif name == "rounded":
        d.rounded_rectangle((m, S * 0.2, S - m, S * 0.8), S * 0.12, fill=col)
    elif name == "triangle":
        d.polygon(_poly(c, c * 1.12, c * 0.95, 3), fill=col)
    elif name == "diamond":
        d.polygon(_poly(c, c, c - m, 4), fill=col)
    elif name == "hexagon":
        d.polygon(_poly(c, c, c - m, 6, rot=0), fill=col)
    elif name == "star":
        d.polygon(_poly(c, c * 1.05, c - m, 5, inner=(c - m) * 0.45), fill=col)
    elif name == "burst":
        d.polygon(_poly(c, c, c - m, 12, inner=(c - m) * 0.72), fill=col)
    elif name == "heart":
        r = S * 0.24
        d.ellipse((c - 2 * r + S * 0.02, S * 0.18, c + S * 0.02, S * 0.18 + 2 * r), fill=col)
        d.ellipse((c - S * 0.02, S * 0.18, c + 2 * r - S * 0.02, S * 0.18 + 2 * r), fill=col)
        d.polygon([(c - 2 * r + S * 0.035, S * 0.18 + r * 1.25), (c + 2 * r - S * 0.035, S * 0.18 + r * 1.25), (c, S * 0.9)], fill=col)
    elif name == "plus":
        t = S * 0.13
        d.rectangle((c - t, m, c + t, S - m), fill=col)
        d.rectangle((m, c - t, S - m, c + t), fill=col)
    elif name == "cross":
        d.line((m * 2, m * 2, S - m * 2, S - m * 2), fill=col, width=int(S * 0.16))
        d.line((S - m * 2, m * 2, m * 2, S - m * 2), fill=col, width=int(S * 0.16))
    elif name == "check":
        d.line([(S * 0.14, S * 0.52), (S * 0.4, S * 0.78), (S * 0.88, S * 0.24)], fill=col, width=int(S * 0.14), joint="curve")
    elif name.startswith("arrow_"):
        pts = [(m, c - S * 0.12), (S * 0.58, c - S * 0.12), (S * 0.58, m * 2.2), (S - m, c), (S * 0.58, S - m * 2.2),
               (S * 0.58, c + S * 0.12), (m, c + S * 0.12)]
        d.polygon(pts, fill=col)
        im = im.rotate({"arrow_right": 0, "arrow_up": 90, "arrow_left": 180, "arrow_down": 270}[name])
    elif name == "speech":
        d.rounded_rectangle((m, m * 2, S - m, S * 0.7), S * 0.14, fill=col)
        d.polygon([(S * 0.24, S * 0.66), (S * 0.46, S * 0.66), (S * 0.18, S * 0.92)], fill=col)
    elif name == "thought":
        d.ellipse((m, m * 2, S - m, S * 0.68), fill=col)
        d.ellipse((S * 0.16, S * 0.7, S * 0.3, S * 0.84), fill=col)
        d.ellipse((S * 0.06, S * 0.86, S * 0.14, S * 0.94), fill=col)
    elif name == "banner":
        d.rectangle((S * 0.12, S * 0.34, S * 0.88, S * 0.66), fill=col)
        dark = tuple(int(v * 0.7) for v in col[:3]) + (255,)
        d.polygon([(m, S * 0.42), (S * 0.12, S * 0.42), (S * 0.12, S * 0.74), (m, S * 0.74), (S * 0.09, S * 0.58)], fill=dark)
        d.polygon([(S - m, S * 0.42), (S * 0.88, S * 0.42), (S * 0.88, S * 0.74), (S - m, S * 0.74), (S * 0.91, S * 0.58)], fill=dark)
    elif name == "badge":
        d.polygon(_poly(c, c * 0.86, c * 0.72, 16, inner=c * 0.64), fill=col)
        d.polygon([(c - S * 0.2, c * 1.3), (c - S * 0.05, c * 1.3), (c - S * 0.12, S - m), (c - S * 0.2, S * 0.88)], fill=col)
        d.polygon([(c + S * 0.2, c * 1.3), (c + S * 0.05, c * 1.3), (c + S * 0.12, S - m), (c + S * 0.2, S * 0.88)], fill=col)
    elif name == "lightning":
        d.polygon([(S * 0.58, m), (S * 0.2, S * 0.56), (S * 0.46, S * 0.56), (S * 0.36, S - m), (S * 0.8, S * 0.4),
                   (S * 0.53, S * 0.4)], fill=col)
    elif name == "cloud":
        for box in ((S * 0.1, S * 0.42, S * 0.42, S * 0.74), (S * 0.26, S * 0.24, S * 0.66, S * 0.64),
                    (S * 0.52, S * 0.36, S * 0.9, S * 0.74)):
            d.ellipse(box, fill=col)
        d.rectangle((S * 0.26, S * 0.56, S * 0.74, S * 0.74), fill=col)
    elif name == "underline":
        d.rounded_rectangle((m, S * 0.44, S - m, S * 0.56), S * 0.06, fill=col)
    im = im.resize((size, size), Image.LANCZOS)
    box = im.getbbox()
    if box:
        im = im.crop(box)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


# ----------------------------------------------------------------------------- emoji clip art

CLIPART = {
    "education": "📚 📖 ✏️ 📝 🖊️ 🎓 🏫 🎒 📐 📏 🧮 🔢 🔤 🖍️ 📓 🗂️ 📌 📎 ✂️ 🧑‍🏫 👩‍🎓 👨‍🎓 🧠 💡",
    "science": "🔬 🔭 🧪 🧫 🧬 ⚗️ 🧲 ⚛️ 🌡️ 🦠 💊 🩺 🌋 🪐 🌍 🌙 ☀️ ⭐ ☄️ 🚀 🛰️ 🔋 ⚡ 💧",
    "nature": "🌱 🌳 🌲 🌴 🌵 🍀 🌸 🌻 🌷 🍁 🍂 🌊 ⛰️ 🏝️ 🌈 ❄️ 🔥 🐝 🦋 🐢 🐘 🦁 🐬 🐦",
    "business": "📈 📉 📊 💼 🤝 💰 💵 🏦 🏢 🧾 📅 ⏰ 🗓️ 📞 💻 🖥️ 📱 ✉️ 📦 🛒 🎯 🏆 🥇 🔑",
    "people": "🙂 😀 😃 🤔 😮 😎 🥳 👍 👏 🙌 👋 ✋ 🤚 👉 👈 👆 👇 🙋 💪 🧑‍💻 👩‍🔬 👨‍🔬 👩‍⚕️ 🧑‍🚀",
    "symbols": "✅ ❌ ❓ ❗ ⚠️ ⭕ 💯 ➕ ➖ ✖️ ➗ 🟰 ♻️ 🔔 🔒 🔓 🏁 🚩 💬 💭 ❤️ ⭐ ✨ 🎉",
    "food": "🍎 🍌 🍇 🍉 🥕 🥦 🍞 🧀 🥚 🍕 🍔 🥗 🍚 🥛 ☕ 🍪",
    "transport": "🚗 🚌 🚲 🚂 ✈️ 🚢 🚁 🚦 🗺️ 🧭 🏠 🏥 🕌 🏛️ 🌉 🗼",
    "flags": "🇸🇦 🇦🇪 🇪🇬 🇯🇴 🇰🇼 🇶🇦 🇧🇭 🇴🇲 🇵🇰 🇮🇳 🇬🇧 🇺🇸 🇫🇷 🇩🇪 🇪🇸 🇹🇷",
}


def _emoji_font_path() -> str | None:
    for p in (HERE / "fonts" / "NotoColorEmoji.ttf", Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf")):
        if p.exists():
            return str(p)
    return None


def clipart_catalog() -> list:
    """[[category, [emoji, ...]], ...] in display order (a list, because JSON objects get re-sorted)."""
    return [[k, v.split()] for k, v in CLIPART.items()] if _emoji_font_path() else []


def make_emoji(char: str, size: int = 384) -> bytes:
    allowed = {e for v in CLIPART.values() for e in v.split()}
    if char not in allowed:
        raise LibraryError("Unknown clip art.")
    fp = _emoji_font_path()
    if not fp:
        raise LibraryError("Clip art font is not installed on the server.")
    font = ImageFont.truetype(fp, 109)               # Noto Color Emoji only has a 109 px bitmap strike
    im = Image.new("RGBA", (220, 160), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((10, 10), char, font=font, embedded_color=True)
    box = im.getbbox()
    if not box:
        raise LibraryError("That clip art could not be drawn.")
    im = im.crop(box)
    k = size / max(im.size)
    im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


# ----------------------------------------------------------------------------- built-in sound effects

SFX = {   # name: (label, lavfi source, duration)
    "whoosh": ("Whoosh", "anoisesrc=d=0.9:c=pink:a=0.6,bandpass=f=1200:w=900,afade=t=in:d=0.35,afade=t=out:st=0.4:d=0.5", 0.9),
    "swoosh_up": ("Swoosh up", "anoisesrc=d=0.6:c=white:a=0.35,highpass=f=1500,afade=t=in:d=0.4,afade=t=out:st=0.4:d=0.2", 0.6),
    "pop": ("Pop", "sine=f=620:d=0.12,afade=t=out:st=0.02:d=0.1,volume=0.8", 0.12),
    "click": ("Click", "anoisesrc=d=0.04:c=white:a=0.8,highpass=f=2500,afade=t=out:d=0.04", 0.04),
    "ding": ("Ding", "sine=f=1318:d=1.4,afade=t=out:st=0.02:d=1.38,volume=0.6", 1.4),
    "chime": ("Success chime", "sine=f=784:d=0.18,afade=t=out:d=0.18[a];sine=f=1047:d=0.6,adelay=150|150,afade=t=out:st=0.2:d=0.55[b];[a][b]amix=inputs=2:duration=longest:normalize=0", 0.8),
    "wrong": ("Wrong answer", "sine=f=180:d=0.45,afade=t=out:st=0.3:d=0.15,volume=0.6[a];sine=f=150:d=0.45,adelay=200|200,afade=t=out:st=0.3:d=0.15,volume=0.6[b];[a][b]amix=inputs=2:duration=longest:normalize=0", 0.7),
    "tick": ("Clock tick", "sine=f=2000:d=0.02,afade=t=out:d=0.02,apad=pad_dur=0.48,aloop=loop=3:size=22050", 2.0),
    "rise": ("Rise", "aevalsrc='0.4*sin(2*PI*(300+600*t)*t)':d=1.2,afade=t=in:d=0.2,afade=t=out:st=1.0:d=0.2", 1.2),
    "fall": ("Fall", "aevalsrc='0.4*sin(2*PI*(900-500*t)*t)':d=1.0,afade=t=out:st=0.7:d=0.3", 1.0),
    "bell": ("School bell", "sine=f=880:d=1.6,tremolo=f=18:d=0.7,afade=t=out:st=1.0:d=0.6,volume=0.6", 1.6),
    "drumroll": ("Drum roll", "anoisesrc=d=2:c=brown:a=0.7,tremolo=f=24:d=0.9,lowpass=f=900,afade=t=in:d=0.3,afade=t=out:st=1.7:d=0.3", 2.0),
    "magic": ("Magic sparkle", "aevalsrc='0.25*sin(2*PI*(1500+800*sin(14*t))*t)':d=1.2,aecho=0.8:0.6:60:0.4,afade=t=out:st=0.6:d=0.6", 1.2),
    "heartbeat": ("Heartbeat", "sine=f=60:d=0.12,afade=t=out:d=0.12,volume=2,apad=pad_dur=0.12[a];sine=f=55:d=0.12,afade=t=out:d=0.12,volume=1.6,apad=pad_dur=0.6[b];[a][b]concat=n=2:v=0:a=1,aloop=loop=1:size=46000", 2.0),
}


def sfx_file(name: str, cache_dir: Path) -> Path:
    if name not in SFX:
        raise LibraryError("Unknown sound effect.")
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{name}.mp3"
    if out.exists() and out.stat().st_size > 200:
        return out
    _, src, dur = SFX[name]
    tmp = out.with_suffix(".tmp.mp3")
    graph = src if "[" in src else src + "[out]"
    if "[" in src:
        graph = src + "[m];[m]aresample=44100[out]"
    proc = subprocess.run([video.ffmpeg_bin(), "-y", "-loglevel", "error", "-filter_complex", graph, "-map", "[out]",
                           "-t", f"{dur:.2f}", "-ac", "2", "-ar", "44100", "-codec:a", "libmp3lame", "-b:a", "128k", str(tmp)],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode or not tmp.exists():
        raise LibraryError(f"Could not create sound effect ({proc.stderr.strip()[-200:]}).")
    tmp.replace(out)
    return out


# ----------------------------------------------------------------------------- Openverse (online library)

MUSIC_TOPICS = ("educational", "corporate", "inspiring", "calm", "happy", "cinematic", "kids", "technology", "ambient",
                "piano", "acoustic", "upbeat", "arabic", "lofi", "documentary", "motivational")
SFX_TOPICS = ("whoosh", "click", "pop", "ding", "applause", "bell", "notification", "typing", "success", "swoosh",
              "magic", "camera", "page turn", "crowd", "nature", "transition")
IMAGE_TOPICS = ("classroom", "students", "science", "mathematics", "nature", "city", "business", "technology",
                "space", "books", "teacher", "laboratory", "desert", "mosque", "office", "world map")
KINDS = {"audio": "audio", "image": "images"}
AUDIO_CATEGORIES = ("music", "sound_effect")
IMAGE_CATEGORIES = ("photograph", "illustration", "digitized_artwork")


def _clean_item(kind: str, r: dict) -> dict:
    creator = (r.get("creator") or "").strip() or "Unknown"
    lic = f"CC {r.get('license', '').upper()} {r.get('license_version') or ''}".strip()
    if r.get("license") in ("cc0", "pdm"):
        lic = "CC0 / public domain" if r.get("license") == "cc0" else "Public domain"
    title = (r.get("title") or "Untitled").strip()[:120]
    item = {"id": r.get("id"), "title": title, "creator": creator, "license": lic, "license_url": r.get("license_url"),
            "source": r.get("source") or r.get("provider"), "page": r.get("foreign_landing_url"),
            "attribution": f"\"{title}\" by {creator} ({lic}) via Openverse"}
    if kind == "audio":
        item.update(duration=round((r.get("duration") or 0) / 1000, 1), preview=r.get("url"),
                    category=r.get("category"), genres=r.get("genres") or [])
    else:
        item.update(thumb=f"{OPENVERSE}/images/{r.get('id')}/thumb/", width=r.get("width"), height=r.get("height"))
    return item


def search(kind: str, q: str, category: str | None = None, page: int = 1, session=None) -> dict:
    if kind not in KINDS:
        raise LibraryError("Unknown library type.")
    q = re.sub(r"\s+", " ", (q or "").strip())[:80]
    params = {"q": q or ("music" if kind == "audio" else "education"), "page": max(1, min(int(page or 1), 20)),
              "page_size": 20, "license_type": "commercial", "mature": "false"}
    cats = AUDIO_CATEGORIES if kind == "audio" else IMAGE_CATEGORIES
    if category in cats:
        params["category"] = category
    if kind == "audio":
        params["extension"] = "mp3,ogg,wav,flac"
    http = session or requests
    try:
        r = http.get(f"{OPENVERSE}/{KINDS[kind]}/", params=params, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        raise LibraryError(f"The online library is not reachable right now ({exc.__class__.__name__}).") from exc
    items = [_clean_item(kind, x) for x in data.get("results", []) if x.get("id") and x.get("url")]
    return {"items": items, "page": params["page"], "pages": min(data.get("page_count") or 1, 20),
            "total": data.get("result_count") or len(items)}


_ID = re.compile(r"^[0-9a-f-]{36}$")


def import_item(kind: str, item_id: str, assets: "video.AssetStore", session=None) -> dict:
    """Download an Openverse item (by id only) into the user's asset library, keeping its attribution."""
    if kind not in KINDS or not _ID.match(str(item_id or "")):
        raise LibraryError("Unknown library item.")
    http = session or requests
    try:
        r = http.get(f"{OPENVERSE}/{KINDS[kind]}/{item_id}/", headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        info = r.json()
        url = info.get("url") or ""
        if not url.startswith(("https://", "http://")):
            raise LibraryError("This item has no downloadable file.")
        with http.get(url, headers=UA, timeout=60, stream=True) as f:
            f.raise_for_status()
            buf = io.BytesIO()
            for chunk in f.iter_content(256 * 1024):
                buf.write(chunk)
                if buf.tell() > MAX_DOWNLOAD:
                    raise LibraryError("That file is too large.")
            ctype = (f.headers.get("Content-Type") or "").split(";")[0].strip()
    except LibraryError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise LibraryError(f"Download failed ({exc.__class__.__name__}). Try another item.") from exc
    item = _clean_item(kind, info)
    ext = (info.get("filetype") or "").lower() or Path(url.split("?")[0]).suffix.lstrip(".").lower()
    ext = {"jpeg": "jpg", "mpeg": "mp3", "audio/mpeg": "mp3"}.get(ext, ext)
    if kind == "audio" and ext not in ("mp3", "ogg", "wav", "flac", "m4a", "aac"):
        ext = {"audio/mpeg": "mp3", "audio/ogg": "ogg", "audio/wav": "wav", "audio/x-wav": "wav", "audio/flac": "flac"}.get(ctype, "mp3")
    name = re.sub(r"[^\w\- ]+", "_", item["title"])[:50] or "library"
    data = buf.getvalue()
    if kind == "image":
        data = _to_png_if_needed(data)
        ext = "png" if data[:4] == b"\x89PNG" else "jpg"
    meta = assets.save(data, f"{name}.{ext}")
    return assets.annotate(meta["id"], attribution=item["attribution"], license=item["license"],
                           license_url=item.get("license_url"), source_page=item.get("page"))


def _to_png_if_needed(data: bytes) -> bytes:
    """Openverse images can be GIF/BMP/TIFF/large; the asset store takes PNG/JPG/WEBP up to the size limit."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format in ("PNG", "JPEG", "WEBP") and len(data) <= video.LIMITS["max_image_bytes"] and max(im.size) <= 4000:
                return data
            im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
            im.thumbnail((3840, 3840))
            out = io.BytesIO()
            im.save(out, "PNG" if im.mode == "RGBA" else "JPEG", quality=90)
            return out.getvalue()
    except Exception as exc:  # noqa: BLE001
        raise LibraryError("That image could not be read.") from exc
