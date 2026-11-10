"""Security helpers: per-client rate limits, client IP behind the proxy, browser security headers,
and an allow-list of media container formats (blocks HLS/concat playlists disguised as uploads, which
could make ffmpeg read local files or fetch URLs)."""
from __future__ import annotations

import os
import re
import threading
import time
from collections import deque

from flask import request

# endpoint -> (max requests, window seconds). Per client IP, per worker process.
LIMITS = {
    "api_video_render": (20, 3600), "api_tts_job": (30, 3600), "api_export": (60, 3600), "api_preview": (40, 60),
    "api_translate": (60, 600), "api_video_import": (20, 3600), "api_audio_convert": (40, 3600),
    "api_video_assets": (200, 3600), "api_library_search": (120, 600), "api_library_import": (60, 3600),
    "api_library_shape": (120, 600), "api_library_clipart": (120, 600), "api_library_sfx_add": (120, 600),
    "api_projects_import": (20, 3600), "api_timeline_render": (20, 3600), "api_timeline_from_scenes": (20, 3600), "api_auth_google": (20, 600), "api_video_preview": (120, 60),
}
if os.environ.get("VF_RATE_LIMITS", "1") == "0":
    LIMITS = {}

_hits: dict[tuple[str, str], deque] = {}
_lock = threading.Lock()
_TRUSTED_PROXIES = {"127.0.0.1", "::1"}


def client_ip() -> str:
    """Real client address. Proxy headers are only trusted when the request comes from the local proxy
    (nginx / cloudflared on the same machine), so they cannot be spoofed from outside."""
    remote = request.remote_addr or "?"
    if remote in _TRUSTED_PROXIES:
        for h in ("CF-Connecting-IP", "X-Real-IP"):
            v = (request.headers.get(h) or "").strip()
            if v:
                return v[:64]
        xff = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        if xff:
            return xff[:64]
    return remote


def check_rate_limit() -> int | None:
    """Returns seconds to wait if the client is over the limit for this endpoint, else None."""
    rule = LIMITS.get(request.endpoint or "")
    if not rule or request.method == "OPTIONS":
        return None
    n, window = rule
    key = (request.endpoint, client_ip())
    now = time.monotonic()
    with _lock:
        q = _hits.setdefault(key, deque())
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= n:
            return int(window - (now - q[0])) + 1
        q.append(now)
        if len(_hits) > 50_000:            # bound memory
            for k in list(_hits)[:10_000]:
                _hits.pop(k, None)
    return None


CSP = ("default-src 'self'; "
       "script-src 'self' https://accounts.google.com/gsi/client; "
       "style-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/style; "
       "img-src 'self' data: blob: https:; media-src 'self' blob: https:; font-src 'self' data:; "
       "connect-src 'self' https://accounts.google.com/gsi/; frame-src https://accounts.google.com/gsi/; "
       "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'")


# Google AdSense needs these extra hosts (only added when ADSENSE_CLIENT is configured)
ADS_CSP = ("default-src 'self'; "
           "script-src 'self' https://accounts.google.com/gsi/client https://pagead2.googlesyndication.com https://*.googlesyndication.com "
           "https://*.doubleclick.net https://*.google.com https://*.gstatic.com https://*.adtrafficquality.google https://fundingchoicesmessages.google.com; "
           "style-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/style; "
           "img-src 'self' data: blob: https:; media-src 'self' blob: https:; font-src 'self' data: https://fonts.gstatic.com; "
           "connect-src 'self' https://accounts.google.com/gsi/ https://*.google.com https://*.googlesyndication.com https://*.doubleclick.net "
           "https://*.adtrafficquality.google https://fundingchoicesmessages.google.com; "
           "frame-src https://accounts.google.com/gsi/ https://*.googlesyndication.com https://*.doubleclick.net https://*.google.com "
           "https://*.adtrafficquality.google https://fundingchoicesmessages.google.com; "
           "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'")


def add_headers(resp, https: bool, ads: bool = False) -> None:
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "SAMEORIGIN")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Permissions-Policy", "microphone=(self), camera=(), geolocation=(), payment=()")
    h.setdefault("Cross-Origin-Opener-Policy", "same-origin-allow-popups")
    if resp.mimetype == "text/html":
        h.setdefault("Content-Security-Policy", ADS_CSP if ads else CSP)
    if https:
        h.setdefault("Strict-Transport-Security", "max-age=31536000")


# ffmpeg demuxer names that are real media files (anything else, e.g. hls, concat, image2, ... is refused)
SAFE_DEMUXERS = {"mov,mp4,m4a,3gp,3g2,mj2", "matroska,webm", "mp3", "wav", "ogg", "flac", "aac", "avi", "mpegts"}


def media_format_ok(ffmpeg_stderr: str) -> bool:
    m = re.search(r"Input #0, ([^,\n]+(?:,[a-z0-9]+)*), from", ffmpeg_stderr)
    return bool(m) and m.group(1).strip() in SAFE_DEMUXERS
