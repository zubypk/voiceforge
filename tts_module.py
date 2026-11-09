"""tts_studio core: text -> MP3 with male/female neural voices in 75 languages (Arabic first).

Uses Microsoft neural voices through the `edge-tts` package (no API key; needs outbound
access to Microsoft's speech endpoint). The voice catalog ships as `voices_snapshot.json`
(regenerate with scripts/update_voices.py), so listing voices needs no network.

Library:
    from tts_module import synthesize_mp3, export_mp3, list_voices, voice_for
    mp3 = synthesize_mp3("مرحبا بالعالم", voice_for("ar-SA", "male"))
    export_mp3("Hello world", "en-US-JennyNeural", "hello.mp3")

CLI:
    python tts_module.py --list [--language ar]
    python tts_module.py "مرحبا" --voice ar-SA-ZariyahNeural --out hi.mp3
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
from dataclasses import dataclass
from pathlib import Path

import edge_tts

MAX_TEXT_CHARS = 5000      # full export limit
MAX_PREVIEW_CHARS = 300    # previews are cut to this length
RATE_RANGE = (-50, 100)    # percent
PITCH_RANGE = (-50, 50)    # Hz

SNAPSHOT = Path(__file__).with_name("voices_snapshot.json")


class TTSError(ValueError):
    """Bad input (empty text, unknown voice, out-of-range settings)."""


class TTSUnavailable(RuntimeError):
    """The speech service could not be reached or returned no audio."""


@dataclass(frozen=True)
class Voice:
    id: str        # edge-tts voice name, e.g. ar-SA-HamedNeural
    language: str  # locale code, e.g. ar-SA
    label: str     # language name shown in the UI, e.g. "Arabic (Saudi Arabia)"
    gender: str    # "male" or "female"

    @property
    def name(self) -> str:
        """Short display name, e.g. "Hamed"."""
        part = self.id.split("-", 2)[-1]
        return part.removesuffix("Neural")


# Preferred default voice per locale when several exist (used only if present in the catalog).
_PREFERRED = {
    "ar-SA": ("ar-SA-HamedNeural", "ar-SA-ZariyahNeural"),
    "ar-EG": ("ar-EG-ShakirNeural", "ar-EG-SalmaNeural"),
    "ar-AE": ("ar-AE-HamdanNeural", "ar-AE-FatimaNeural"),
    "en-US": ("en-US-GuyNeural", "en-US-JennyNeural"),
    "en-GB": ("en-GB-RyanNeural", "en-GB-SoniaNeural"),
    "fr-FR": ("fr-FR-HenriNeural", "fr-FR-DeniseNeural"),
    "de-DE": ("de-DE-ConradNeural", "de-DE-KatjaNeural"),
    "es-ES": ("es-ES-AlvaroNeural", "es-ES-ElviraNeural"),
    "it-IT": ("it-IT-DiegoNeural", "it-IT-ElsaNeural"),
    "pt-BR": ("pt-BR-AntonioNeural", "pt-BR-FranciscaNeural"),
    "ru-RU": ("ru-RU-DmitryNeural", "ru-RU-SvetlanaNeural"),
    "tr-TR": ("tr-TR-AhmetNeural", "tr-TR-EmelNeural"),
    "ur-PK": ("ur-PK-AsadNeural", "ur-PK-UzmaNeural"),
    "hi-IN": ("hi-IN-MadhurNeural", "hi-IN-SwaraNeural"),
    "zh-CN": ("zh-CN-YunxiNeural", "zh-CN-XiaoxiaoNeural"),
    "ja-JP": ("ja-JP-KeitaNeural", "ja-JP-NanamiNeural"),
    "ko-KR": ("ko-KR-InJoonNeural", "ko-KR-SunHiNeural"),
}


def _load_voices() -> list[Voice]:
    rows = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    voices = [Voice(r[0], r[2], r[3], "male" if r[1] == "M" else "female") for r in rows]

    def order(v: Voice):
        pref = _PREFERRED.get(v.language, ())
        base = v.language.split("-")[0]
        # Arabic first, English second, then alphabetical by label; preferred voice first in its group.
        group = 0 if base == "ar" else 1 if base == "en" else 2
        return (group, v.label, v.language, v.gender, v.id not in pref, v.id)

    voices.sort(key=order)
    return voices


VOICES: list[Voice] = _load_voices()
_VOICE_BY_ID = {v.id: v for v in VOICES}


def list_voices(language: str | None = None, gender: str | None = None) -> list[Voice]:
    """Return voices filtered by locale ("ar-SA") or language prefix ("ar") and gender."""
    result = VOICES
    if language:
        lang = language.lower()
        result = [v for v in result if v.language.lower() == lang or v.language.lower().startswith(lang + "-")]
    if gender:
        result = [v for v in result if v.gender == gender.lower()]
    return list(result)


def voice_for(language: str, gender: str) -> str:
    """Default voice id for a locale code (e.g. "ar-SA") and gender ("male"/"female")."""
    matches = [v for v in VOICES if v.language.lower() == language.lower() and v.gender == gender.lower()]
    if not matches:
        raise TTSError(f"No {gender} voice for language {language!r}.")
    return matches[0].id


def list_languages() -> list[tuple[str, str]]:
    """(locale code, label) pairs, Arabic first, then English, then alphabetical."""
    seen: dict[str, str] = {}
    for v in VOICES:
        seen.setdefault(v.language, v.label)
    return list(seen.items())


def _validate(text: str, voice_id: str, rate: int, pitch: int, max_chars: int) -> str:
    if not isinstance(text, str) or not text.strip():
        raise TTSError("Text is empty.")
    text = text.strip()
    if len(text) > max_chars:
        raise TTSError(f"Text is too long ({len(text)} chars; limit {max_chars}).")
    if voice_id not in _VOICE_BY_ID:
        raise TTSError(f"Unknown voice: {voice_id!r}.")
    if not (RATE_RANGE[0] <= int(rate) <= RATE_RANGE[1]):
        raise TTSError(f"Rate must be between {RATE_RANGE[0]} and {RATE_RANGE[1]} percent.")
    if not (PITCH_RANGE[0] <= int(pitch) <= PITCH_RANGE[1]):
        raise TTSError(f"Pitch must be between {PITCH_RANGE[0]} and {PITCH_RANGE[1]} Hz.")
    return text


async def _stream_mp3(text: str, voice_id: str, rate: int, pitch: int) -> bytes:
    communicate = edge_tts.Communicate(
        text,
        voice_id,
        rate=f"{int(rate):+d}%",
        pitch=f"{int(pitch):+d}Hz",
    )
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()


def synthesize_mp3(text: str, voice_id: str, rate: int = 0, pitch: int = 0, max_chars: int = MAX_TEXT_CHARS) -> bytes:
    """Synthesize `text` and return MP3 bytes."""
    text = _validate(text, voice_id, rate, pitch, max_chars)
    try:
        data = asyncio.run(_stream_mp3(text, voice_id, rate, pitch))
    except Exception as exc:  # network/proxy/service errors from edge-tts
        raise TTSUnavailable(f"Speech service unavailable: {exc}") from exc
    if not data:
        raise TTSUnavailable("Speech service returned no audio.")
    return data


def preview_mp3(text: str, voice_id: str, rate: int = 0, pitch: int = 0) -> bytes:
    """Like synthesize_mp3 but limited to MAX_PREVIEW_CHARS so previews stay fast."""
    text = _validate(text, voice_id, rate, pitch, MAX_TEXT_CHARS)
    return synthesize_mp3(text[:MAX_PREVIEW_CHARS], voice_id, rate, pitch)


def export_mp3(text: str, voice_id: str, out_path: str | Path, rate: int = 0, pitch: int = 0) -> Path:
    """Synthesize `text` and write the MP3 to `out_path`. Returns the path."""
    out = Path(out_path)
    if out.suffix.lower() != ".mp3":
        out = out.with_suffix(".mp3")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(synthesize_mp3(text, voice_id, rate, pitch))
    return out


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Text to MP3 with male/female neural voices.")
    parser.add_argument("text", nargs="?", help="Text to speak (omit with --list)")
    parser.add_argument("--voice", default="en-US-JennyNeural", help="Voice id (see --list)")
    parser.add_argument("--rate", type=int, default=0, help="Speed change in percent (-50..100)")
    parser.add_argument("--pitch", type=int, default=0, help="Pitch change in Hz (-50..50)")
    parser.add_argument("--out", default="speech.mp3", help="Output MP3 path")
    parser.add_argument("--list", action="store_true", help="List available voices and exit")
    parser.add_argument("--language", help="With --list: filter by locale or language (e.g. ar, ar-SA)")
    args = parser.parse_args(argv)

    if args.list:
        for v in list_voices(args.language):
            print(f"{v.language:8}  {v.gender:6}  {v.id:36}  {v.label}")
        return 0
    if not args.text:
        parser.error("text is required unless --list is given")
    try:
        path = export_mp3(args.text, args.voice, args.out, args.rate, args.pitch)
    except (TTSError, TTSUnavailable) as exc:
        print(f"error: {exc}")
        return 1
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
