"""Text translation for the Voice tab (no API key needed).

Primary: the Microsoft Edge translator endpoint (same vendor as the voices).
Fallback: the public Google web endpoint. Both are unofficial and may change.
`translate(text, to_locale, from_locale=None, backend=None)` accepts an injectable
backend for tests: backend(chunks, src, dst) -> list[str].
"""
from __future__ import annotations

import re
import threading
import time

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


_tok = {"v": None, "t": 0.0}
_lock = threading.Lock()


def _edge_token() -> str:
    with _lock:
        if _tok["v"] and time.time() - _tok["t"] < 480:
            return _tok["v"]
        r = requests.get("https://edge.microsoft.com/translate/auth", timeout=_TIMEOUT)
        r.raise_for_status()
        _tok["v"], _tok["t"] = r.text.strip(), time.time()
        return _tok["v"]


def _edge(chunks: list[str], src: str | None, dst: str) -> list[str]:
    params = {"to": dst, "api-version": "3.0", "includeSentenceLength": "true"}
    if src:
        params["from"] = src
    r = requests.post("https://api-edge.cognitive.microsofttranslator.com/translate", params=params,
                      headers={"Authorization": "Bearer " + _edge_token(), "Content-Type": "application/json"},
                      json=[{"Text": c} for c in chunks], timeout=_TIMEOUT)
    if r.status_code == 401:
        _tok["v"] = None
    r.raise_for_status()
    return [item["translations"][0]["text"] for item in r.json()]


def _google(chunks: list[str], src: str | None, dst: str) -> list[str]:
    out = []
    for c in chunks:
        r = requests.get("https://translate.googleapis.com/translate_a/single",
                         params={"client": "gtx", "sl": src or "auto", "tl": dst, "dt": "t", "q": c}, timeout=_TIMEOUT)
        r.raise_for_status()
        out.append("".join(seg[0] for seg in r.json()[0] if seg and seg[0]))
    return out


def _default_backend(chunks, src, dst):
    last = None
    for fn in (_edge, _google):
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
