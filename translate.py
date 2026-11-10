"""Text translation for the Voice tab (no API key needed).

Backends, tried in order (all free, no key, unofficial - they can change or rate-limit):
  1. Google's Chrome dictionary endpoint (clients5) - auto-detects the source language
  2. MyMemory (api.mymemory.translated.net) - free tier, ~5,000 characters/day per server IP
  3. Google's web endpoint (translate_a/single)
(The old Microsoft Edge endpoint was shut down in 2026.)
`translate(text, to_locale, from_locale=None, backend=None)` accepts an injectable
backend for tests: backend(chunks, src, dst) -> list[str].
"""
from __future__ import annotations

import re

import requests

MAX_CHARS = 50_000
_CHUNK = 3000
_TIMEOUT = 20


class TranslateError(Exception):
    pass


def api_code(locale: str | None) -> str | None:
    """Voice locale (ar-SA, zh-CN) -> translator language code."""
    if not locale:
        return None
    loc = locale.strip()
    low = loc.lower()
    if low in ("zh-cn", "zh-sg", "zh"):
        return "zh-Hans"
    if low in ("zh-tw", "zh-hk"):
        return "zh-Hant"
    base = low.split("-")[0]
    return {"nb": "nb", "fil": "fil", "he": "he", "iw": "he"}.get(base, base)


def split_chunks(text: str, size: int = _CHUNK) -> list[str]:
    """Split on line breaks, then sentence ends, keeping chunks <= size. Joined with "" restores text."""
    parts = re.split(r"(?<=[\n.!?؟。！？])", text)
    out, cur = [], ""
    for p in parts:
        while len(p) > size:                       # no punctuation at all: hard split
            if cur:
                out.append(cur); cur = ""
            out.append(p[:size]); p = p[size:]
        if len(cur) + len(p) > size and cur:
            out.append(cur); cur = ""
        cur += p
    if cur:
        out.append(cur)
    return out


def _google(chunks: list[str], src: str | None, dst: str) -> list[str]:
    out = []
    for c in chunks:
        r = requests.get("https://translate.googleapis.com/translate_a/single",
                         params={"client": "gtx", "sl": src or "auto", "tl": dst, "dt": "t", "q": c}, timeout=_TIMEOUT)
        r.raise_for_status()
        out.append("".join(seg[0] for seg in r.json()[0] if seg and seg[0]))
    return out


def _clients5(chunks: list[str], src: str | None, dst: str) -> list[str]:
    out = []
    for c in chunks:
        r = requests.get("https://clients5.google.com/translate_a/t",
                         params={"client": "dict-chrome-ex", "sl": src or "auto", "tl": dst, "q": c}, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        item = data[0] if isinstance(data, list) and data else data
        text = item[0] if isinstance(item, list) else item
        if not isinstance(text, str):
            raise ValueError("unexpected response")
        out.append(text + (" " if c.endswith(" ") and not text.endswith(" ") else ""))
    return out


def _mymemory(chunks: list[str], src: str | None, dst: str) -> list[str]:
    out = []
    for c in chunks:
        pieces = split_chunks(c, 480) if len(c) > 480 else [c]   # MyMemory accepts ~500 characters per request
        res = []
        for p in pieces:
            if not p.strip():
                res.append(p)
                continue
            r = requests.get("https://api.mymemory.translated.net/get",
                             params={"q": p, "langpair": f"{src or 'autodetect'}|{dst}"}, timeout=_TIMEOUT)
            r.raise_for_status()
            j = r.json()
            if int(j.get("responseStatus") or 200) != 200:
                raise ValueError(j.get("responseDetails") or "quota")
            res.append(j["responseData"]["translatedText"])
        out.append(" ".join(x.strip() for x in res))
    return out


def _default_backend(chunks, src, dst):
    last = None
    for fn in (_clients5, _mymemory, _google):
        try:
            return fn(chunks, src, dst)
        except Exception as exc:  # noqa: BLE001 - try the next backend
            last = exc
    raise TranslateError(f"Translation service unavailable ({last.__class__.__name__}). Try again shortly.")


def translate(text: str, to_locale: str, from_locale: str | None = None, backend=None) -> str:
    text = text or ""
    if not text.strip():
        raise TranslateError("Enter some text to translate.")
    if len(text) > MAX_CHARS:
        raise TranslateError(f"Text is too long to translate ({len(text):,} > {MAX_CHARS:,} characters).")
    dst = api_code(to_locale)
    if not dst:
        raise TranslateError("Choose a target language.")
    src = api_code(from_locale)
    if src == dst:
        return text
    chunks = split_chunks(text)
    res = (backend or _default_backend)(chunks, src, dst)
    if len(res) != len(chunks):
        raise TranslateError("Unexpected translator response.")
    return "".join(res)
