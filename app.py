"""Voxa (formerly VoiceForge): natural neural voices (edge-tts) + video studio, with optional Google sign-in.

Environment:
  GOOGLE_CLIENT_ID       OAuth client id. Sign-in is hidden if unset.
  REQUIRE_LOGIN          "1" = voice/video endpoints need a signed-in user. Default: sign-in is optional.
  ALLOWED_EMAIL_DOMAINS  optional comma list (e.g. "example.com") limiting who may sign in.
  SECRET_KEY             cookie signing key (set it, or sessions reset on every restart).
  COOKIE_SECURE          "1" when served over HTTPS (recommended).
  VF_DATA                folder for renders, uploads and saved projects (default ./data).
  VF_MAX_TEXT_CHARS      longest text per MP3 export (default 100000; 0 = unlimited).
"""
from __future__ import annotations

import hashlib
import json
import io
import os
import secrets
import uuid
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request, send_file, session

import doc_import
import library
import projects as projects_mod
import security
import timeline as timeline_mod
import translate as translate_mod
import tts_module as tts
import video
import video_presets
from samples import SAMPLES

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",
    MAX_CONTENT_LENGTH=460 * 1024 * 1024,  # video uploads and project bundles
)
DATA_DIR = Path(os.environ.get("VF_DATA", Path(__file__).with_name("data")))
jobs = video.JobManager(DATA_DIR)
projects = projects_mod.ProjectStore(DATA_DIR / "projects")
jobs.referenced_fn = projects.referenced_assets   # saved projects keep their media

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()


def _adsense():
    """ADSENSE_CLIENT=ca-pub-XXXXXXXXXXXXXXXX enables Google AdSense. Optional ADSENSE_SLOTS="top=123,middle=456,footer=789"
    uses fixed ad units; without slots, AdSense Auto ads decide placement."""
    import re as _re
    client = os.environ.get("ADSENSE_CLIENT", "").strip()
    if not _re.fullmatch(r"ca-pub-\d{10,20}", client):
        return "", {}
    slots = {}
    for part in os.environ.get("ADSENSE_SLOTS", "").split(","):
        k, _, v = part.partition("=")
        if k.strip() in ("top", "middle", "footer") and _re.fullmatch(r"\d{6,20}", v.strip()):
            slots[k.strip()] = v.strip()
    return client, slots


ADSENSE_CLIENT, ADSENSE_SLOTS = _adsense()
REQUIRE_LOGIN = os.environ.get("REQUIRE_LOGIN") == "1"
ALLOWED_DOMAINS = {d.strip().lower() for d in os.environ.get("ALLOWED_EMAIL_DOMAINS", "").split(",") if d.strip()}
SYNC_EXPORT_CHARS = 12_000   # longer exports run as background jobs (proxies cut long requests)


# ----------------------------------------------------------------------------- identity

def owner_id() -> str:
    """Who owns uploads and saved projects: the Google account if signed in, else a browser cookie."""
    user = session.get("user")
    if user and user.get("email"):
        return "g" + hashlib.sha256(user["email"].lower().encode()).hexdigest()[:30]
    uid = request.cookies.get("vf_uid", "")
    if not (len(uid) == 32 and all(c in "0123456789abcdef" for c in uid)):
        uid = uuid.uuid4().hex
        g.new_uid = uid
    return "a" + uid


@app.after_request
def after(resp):
    uid = getattr(g, "new_uid", None)
    if uid:
        resp.set_cookie("vf_uid", uid, max_age=2 * 365 * 86400, httponly=True, samesite="Lax",
                        secure=os.environ.get("COOKIE_SECURE") == "1")
    origin = os.environ.get("ALLOWED_ORIGIN", "").strip()      # same-origin only unless configured
    if origin:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    security.add_headers(resp, https=os.environ.get("COOKIE_SECURE") == "1", ads=bool(ADSENSE_CLIENT))
    return resp


@app.before_request
def rate_limit():
    wait = security.check_rate_limit()
    if wait:
        resp = jsonify(error=f"Too many requests. Please wait {wait} seconds and try again.")
        resp.status_code = 429
        resp.headers["Retry-After"] = str(wait)
        return resp
    return None


def verify_google_token(credential: str) -> dict:
    """Validate a Google ID token and return its claims. Raises ValueError if invalid."""
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token

    claims = id_token.verify_oauth2_token(credential, g_requests.Request(), GOOGLE_CLIENT_ID)
    if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise ValueError("Wrong token issuer.")
    if not claims.get("email_verified"):
        raise ValueError("Google email is not verified.")
    return claims


def _login_gate():
    if REQUIRE_LOGIN and not session.get("user"):
        return jsonify(error="Please sign in with Google first.", login_required=True), 401
    return None


# ----------------------------------------------------------------------------- pages and auth

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/healthz")
def healthz():
    return jsonify(ok=True)


def _build_info() -> dict:
    """build.json is written at deploy time by scripts/stamp_build.py (build number + Riyadh time)."""
    try:
        return json.loads(Path(__file__).with_name("build.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        import datetime as dt
        now = dt.datetime.now(dt.timezone(dt.timedelta(hours=3)))
        return {"build": "dev", "commit": None, "time": now.isoformat(timespec="minutes"), "display": now.strftime("%d %b %Y, %H:%M")}


BUILD = _build_info()


@app.get("/api/config")
def api_config():
    return jsonify(google_client_id=GOOGLE_CLIENT_ID or None, require_login=REQUIRE_LOGIN, build=BUILD,
                   ads={"client": ADSENSE_CLIENT, "slots": ADSENSE_SLOTS} if ADSENSE_CLIENT else None)


@app.get("/ads.txt")
def ads_txt():
    """Required by AdSense: authorises Google to sell ads on this site."""
    if not ADSENSE_CLIENT:
        return "", 404
    return (f"google.com, {ADSENSE_CLIENT.replace('ca-', '')}, DIRECT, f08c47fec0942fa0\n", 200, {"Content-Type": "text/plain"})


@app.get("/api/me")
def api_me():
    return jsonify(user=session.get("user"))


@app.post("/api/auth/google")
def api_auth_google():
    if not GOOGLE_CLIENT_ID:
        return jsonify(error="Google sign-in is not configured."), 503
    credential = (request.get_json(silent=True) or {}).get("credential", "")
    try:
        claims = verify_google_token(credential)
    except Exception as exc:  # invalid signature, expired, wrong audience, network
        return jsonify(error=f"Sign-in failed: {exc}"), 401
    email = claims.get("email", "")
    if ALLOWED_DOMAINS and email.split("@")[-1].lower() not in ALLOWED_DOMAINS:
        return jsonify(error="This account is not allowed."), 403
    session["user"] = {"name": claims.get("name") or email, "email": email, "picture": claims.get("picture")}
    return jsonify(user=session["user"])


@app.post("/api/auth/logout")
def api_logout():
    session.pop("user", None)
    return jsonify(ok=True)


@app.route("/api/<path:_>", methods=["OPTIONS"])
def preflight(_):
    return ("", 204)


# ----------------------------------------------------------------------------- voices and MP3

@app.get("/api/voices")
def api_voices():
    return jsonify(
        languages=[{"code": c, "label": l} for c, l in tts.list_languages()],
        voices=[{"id": v.id, "name": v.name, "language": v.language, "label": v.label, "gender": v.gender} for v in tts.VOICES],
        samples=SAMPLES,
        limits={"max_text_chars": tts.max_text_chars(), "max_preview_chars": tts.MAX_PREVIEW_CHARS,
                "sync_export_chars": SYNC_EXPORT_CHARS, "rate": tts.RATE_RANGE, "pitch": tts.PITCH_RANGE},
    )


def _payload():
    data = request.get_json(silent=True) or {}
    voice = data.get("voice") or tts.voice_for(data.get("lang", "ar-SA"), data.get("gender", "female"))
    return (data.get("text", ""), voice, int(data.get("rate", 0) or 0), int(data.get("pitch", 0) or 0))


def _error(exc: Exception):
    return jsonify(error=str(exc)), (400 if isinstance(exc, (tts.TTSError, video.VideoError, projects_mod.ProjectError)) else 502)


@app.post("/api/translate")
def api_translate():
    """{text, to, from?} -> {text}. `to`/`from` are voice locale codes (e.g. ar-SA) or bare language codes."""
    if (gate := _login_gate()):
        return gate
    data = request.get_json(silent=True) or {}
    try:
        out = translate_mod.translate(str(data.get("text", "")), str(data.get("to", "")), data.get("from") or None)
    except translate_mod.TranslateError as exc:
        return jsonify(error=str(exc)), (503 if "unavailable" in str(exc) else 400)   # 502 gets replaced by Cloudflare
    return jsonify(text=out)


@app.post("/api/preview")
def api_preview():
    if (gate := _login_gate()):
        return gate
    try:
        mp3 = tts.preview_mp3(*_payload())
    except (tts.TTSError, tts.TTSUnavailable, ValueError) as exc:
        return _error(exc)
    return send_file(io.BytesIO(mp3), mimetype="audio/mpeg", download_name="preview.mp3")


@app.post("/api/export")
def api_export():
    """Short texts: returns the MP3 directly. Longer texts: use POST /api/tts/jobs."""
    if (gate := _login_gate()):
        return gate
    try:
        text, voice, rate, pitch = _payload()
        if len(text) > SYNC_EXPORT_CHARS:
            return jsonify(error=f"Text over {SYNC_EXPORT_CHARS:,} characters must use POST /api/tts/jobs (a background job)."), 413
        mp3 = tts.synthesize_mp3(text, voice, rate, pitch)
    except (tts.TTSError, tts.TTSUnavailable, ValueError) as exc:
        return _error(exc)
    return send_file(io.BytesIO(mp3), mimetype="audio/mpeg", as_attachment=True, download_name="speech.mp3")


@app.post("/api/audio/convert")
def api_audio_convert():
    """Audio editor export: uploaded WAV/any audio -> MP3 (or WAV). multipart: file, format=mp3|wav."""
    if (gate := _login_gate()):
        return gate
    f = request.files.get("file")
    fmt = request.form.get("format", "mp3")
    if not f or fmt not in ("mp3", "wav"):
        return jsonify(error="Send an audio file and format=mp3 or wav."), 400
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory(dir=DATA_DIR) as td:
        src, out = Path(td) / "in", Path(td) / f"out.{fmt}"
        f.save(src)
        if src.stat().st_size > 200 * 1024 * 1024:
            return jsonify(error="Audio is too large (limit 200 MB)."), 413
        probe = subprocess.run([video.ffmpeg_bin(), "-hide_banner", "-i", str(src)], capture_output=True, text=True, timeout=60)
        if not security.media_format_ok(probe.stderr):
            return jsonify(error="That file is not a supported audio file."), 400
        codec = ["-codec:a", "libmp3lame", "-b:a", "192k"] if fmt == "mp3" else ["-codec:a", "pcm_s16le"]
        proc = subprocess.run([video.ffmpeg_bin(), "-y", "-loglevel", "error", "-i", str(src), "-vn", *codec, str(out)],
                              capture_output=True, text=True, timeout=600)
        if proc.returncode or not out.exists():
            return jsonify(error="That audio could not be converted."), 400
        data = out.read_bytes()
    return send_file(io.BytesIO(data), mimetype="audio/mpeg" if fmt == "mp3" else "audio/wav",
                     as_attachment=True, download_name=f"audio.{fmt}")


@app.post("/api/tts/jobs")
def api_tts_job():
    """Start a text-to-MP3 job of any length; poll /api/jobs/<id>, then download speech.mp3."""
    if (gate := _login_gate()):
        return gate
    try:
        text, voice, rate, pitch = _payload()
        job_id = jobs.submit_tts(text, voice, rate, pitch, owner=owner_id())
    except (tts.TTSError, video.VideoError, ValueError) as exc:
        return _error(exc)
    return jsonify(job_id=job_id), 202


@app.get("/api/jobs/<job_id>")
@app.get("/api/video/jobs/<job_id>")
def api_job(job_id):
    job = jobs.get(job_id, owner_id())          # private: only the browser/account that started it
    if not job:
        return jsonify(error="Job not found (it may have expired)."), 404
    return jsonify({k: job.get(k) for k in ("id", "kind", "status", "progress", "message", "error", "duration")})


@app.get("/api/jobs/<job_id>/<name>")
@app.get("/api/video/jobs/<job_id>/<name>")
def api_job_file(job_id, name):
    path = jobs.file(job_id, name, owner_id())
    if not path:
        return jsonify(error="File not available."), 404
    if name == "video.mp4":
        return send_file(path, mimetype="video/mp4", conditional=True,
                         as_attachment=request.args.get("download") == "1", download_name="video.mp4")
    if name == "speech.mp3":
        return send_file(path, mimetype="audio/mpeg", conditional=True, as_attachment=True, download_name="speech.mp3")
    return send_file(path, mimetype="application/x-subrip", as_attachment=True, download_name="captions.srt")


# ----------------------------------------------------------------------------- video studio

@app.get("/api/video/config")
def api_video_config():
    dims = {r: {res: list(video.dimensions(r, res)) for res in video.RESOLUTIONS} for r in video.RATIOS}
    return jsonify(
        ratios=[{"id": k, "label": v["label"]} for k, v in video.RATIOS.items()],
        resolutions=[{"id": k, "label": v["label"]} for k, v in video.RESOLUTIONS.items()],
        dimensions=dims,
        max_seconds=video.MAX_SECONDS,
        themes=[{"id": k, "label": v["label"], "bg": v["bg"], "text": v["text"], "accent": v["accent"]} for k, v in video.THEMES.items()],
        layouts=list(video.LAYOUTS),
        media_positions=list(video.MEDIA_POSITIONS), import_formats=doc_import.SUPPORTED,
        limits={k: v for k, v in video.LIMITS.items() if k != "max_seconds"},
        presets=[{"id": k, "label": v["label"], "desc": v["desc"], "ratio": v["ratio"], "resolution": v["resolution"],
                  "theme": v["theme"], "scenes": v["scenes"]} for k, v in video_presets.PRESETS.items()],
    )


def _assets():
    return jobs.assets_for(owner_id())


@app.post("/api/video/assets")
def api_video_assets():
    """Upload an image, video clip or audio file to the user's library."""
    if (gate := _login_gate()):
        return gate
    f = request.files.get("file")
    if not f:
        return jsonify(error="No file uploaded."), 400
    try:
        return jsonify(_assets().save(f.read(), f.filename or ""))
    except video.VideoError as exc:
        return _error(exc)


_import_lock = __import__("threading").BoundedSemaphore(2)


@app.post("/api/video/import")
def api_video_import():
    """Import a PDF / PowerPoint as scenes. multipart: file, narration=notes|text|none, max_pages, background=black|theme."""
    if (gate := _login_gate()):
        return gate
    f = request.files.get("file")
    if not f:
        return jsonify(error="No file uploaded."), 400
    try:
        max_pages = int(request.form.get("max_pages") or 0) or None
    except ValueError:
        max_pages = None
    if not _import_lock.acquire(timeout=120):
        return jsonify(error="The server is busy converting other files. Try again in a minute."), 503
    try:
        return jsonify(doc_import.import_document(f.read(), f.filename or "", _assets(),
                                                  narration=request.form.get("narration", "notes"), max_pages=max_pages,
                                                  keep_layout=request.form.get("background", "black") != "theme"))
    except video.VideoError as exc:
        return _error(exc)
    finally:
        _import_lock.release()


# ---------------------------------------------------------------- media library

@app.get("/api/library")
def api_library():
    return jsonify(shapes=list(library.SHAPES), clipart=library.clipart_catalog(),
                   sfx=[{"name": k, "label": v[0], "seconds": v[2]} for k, v in library.SFX.items()],
                   music_topics=library.MUSIC_TOPICS, sfx_topics=library.SFX_TOPICS, image_topics=library.IMAGE_TOPICS)


@app.get("/api/library/shape/<name>.png")
def api_library_shape_preview(name):
    try:
        png = library.make_shape(name, request.args.get("color", "#ffc857"), size=160)
    except video.VideoError as exc:
        return _error(exc)
    return send_file(io.BytesIO(png), mimetype="image/png", max_age=3600)


@app.post("/api/library/shape")
def api_library_shape():
    if (gate := _login_gate()):
        return gate
    data = request.get_json(silent=True) or {}
    try:
        png = library.make_shape(str(data.get("name", "")), str(data.get("color", "#ffc857")))
        return jsonify(_assets().save(png, f"shape-{data.get('name')}.png"))
    except video.VideoError as exc:
        return _error(exc)


@app.post("/api/library/clipart")
def api_library_clipart():
    if (gate := _login_gate()):
        return gate
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(_assets().save(library.make_emoji(str(data.get("char", ""))), "clipart.png"))
    except video.VideoError as exc:
        return _error(exc)


@app.get("/api/library/sfx/<name>.mp3")
def api_library_sfx_file(name):
    try:
        return send_file(library.sfx_file(name, DATA_DIR / "library" / "sfx"), mimetype="audio/mpeg", max_age=86400)
    except video.VideoError as exc:
        return _error(exc)


@app.post("/api/library/sfx/<name>")
def api_library_sfx_add(name):
    if (gate := _login_gate()):
        return gate
    try:
        path = library.sfx_file(name, DATA_DIR / "library" / "sfx")
        meta = _assets().save(path.read_bytes(), f"sfx-{name}.mp3")
        return jsonify(_assets().annotate(meta["id"], name=library.SFX[name][0] + ".mp3"))
    except video.VideoError as exc:
        return _error(exc)


@app.get("/api/library/search")
def api_library_search():
    try:
        return jsonify(library.search(request.args.get("kind", "audio"), request.args.get("q", ""),
                                      request.args.get("category"), int(request.args.get("page", 1) or 1)))
    except (video.VideoError, ValueError) as exc:
        return _error(exc)


@app.post("/api/library/import")
def api_library_import():
    if (gate := _login_gate()):
        return gate
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(library.import_item(str(data.get("kind", "")), str(data.get("id", "")), _assets()))
    except video.VideoError as exc:
        return _error(exc)


@app.get("/api/assets")
def api_assets_list():
    store = _assets()
    return jsonify(assets=store.list(), used_bytes=store.total_bytes(), quota_bytes=video.LIMITS["owner_quota_bytes"])


@app.get("/api/assets/<asset_id>/thumb")
def api_asset_thumb(asset_id):
    path = _assets().thumb(asset_id)
    if not path:
        return jsonify(error="No preview."), 404
    return send_file(path, mimetype="image/jpeg", max_age=3600)


@app.get("/api/assets/<asset_id>/file")
def api_asset_file(asset_id):
    store = _assets()
    path, meta = store.path(asset_id), store.meta(asset_id)
    if not path or not meta:
        return jsonify(error="Not found."), 404
    mime = {"video": "video/mp4", "audio": "audio/mpeg"}.get(meta["kind"], "image/png")
    return send_file(path, mimetype=mime, conditional=True)


@app.delete("/api/assets/<asset_id>")
def api_asset_delete(asset_id):
    if (gate := _login_gate()):
        return gate
    if not _assets().delete(asset_id):
        return jsonify(error="Not found."), 404
    return jsonify(ok=True)


def _project_from_request():
    data = request.get_json(silent=True) or {}
    return video.validate_project(data.get("project"), _assets()), data


@app.post("/api/video/preview")
def api_video_preview():
    if (gate := _login_gate()):
        return gate
    try:
        data = request.get_json(silent=True) or {}
        raw = data.get("project")
        scenes = raw.get("scenes") if isinstance(raw, dict) else None
        index = int(data.get("index", 0))
        if not isinstance(scenes, list) or not (0 <= index < len(scenes)):
            raise video.VideoError("Scene not found.")
        # Only the selected scene is validated, so other unfinished scenes never block the preview.
        assets = _assets()
        project = video.validate_project({**raw, "scenes": [scenes[index]]}, assets, allow_empty=True)
        png = video.render_preview_png(project, 0, assets, stickers=data.get("stickers", True) is not False)
    except (video.VideoError, ValueError) as exc:
        return _error(exc)
    return send_file(io.BytesIO(png), mimetype="image/png")


@app.post("/api/timeline/render")
def api_timeline_render():
    """Render a multi-track timeline: {timeline} -> {job_id}; poll /api/jobs/<id>, download video.mp4."""
    if (gate := _login_gate()):
        return gate
    data = request.get_json(silent=True) or {}
    try:
        tl = timeline_mod.validate_timeline(data.get("timeline"), _assets())
        return jsonify(job_id=jobs.submit_timeline(tl, owner=owner_id()))
    except video.VideoError as exc:
        return _error(exc)


@app.post("/api/timeline/from-scenes")
def api_timeline_from_scenes():
    """Video Studio project -> timeline clips (slide images + narration audio)."""
    if (gate := _login_gate()):
        return gate
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(timeline_mod.scenes_to_clips(data.get("project") or {}, _assets()))
    except (video.VideoError, tts.TTSError, tts.TTSUnavailable) as exc:
        return _error(exc)


@app.post("/api/video/render")
def api_video_render():
    if (gate := _login_gate()):
        return gate
    try:
        project, _ = _project_from_request()
        job_id = jobs.submit(project, owner=owner_id())
    except video.VideoError as exc:
        return _error(exc)
    return jsonify(job_id=job_id), 202


# ----------------------------------------------------------------------------- saved projects

@app.get("/api/projects")
def api_projects_list():
    return jsonify(projects=projects.list(owner_id()))


@app.post("/api/projects")
def api_projects_save():
    """Create (no id) or update (id) a saved project: {id?, name, project}."""
    if (gate := _login_gate()):
        return gate
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(projects.save(owner_id(), data.get("name"), data.get("project"), data.get("id")))
    except projects_mod.ProjectError as exc:
        return _error(exc)


@app.post("/api/projects/import")
def api_projects_import():
    """Import a .voxa.zip / .voiceforge.zip bundle (with media) or a plain project .json."""
    if (gate := _login_gate()):
        return gate
    f = request.files.get("file")
    if not f:
        return jsonify(error="No file uploaded."), 400
    owner = owner_id()
    try:
        return jsonify(projects.import_bundle(owner, f.read(), jobs.assets_for(owner)))
    except (projects_mod.ProjectError, video.VideoError) as exc:
        return _error(exc)


@app.get("/api/projects/<pid>")
def api_projects_get(pid):
    try:
        return jsonify(projects.get(owner_id(), pid))
    except projects_mod.ProjectError as exc:
        return jsonify(error=str(exc)), 404


@app.delete("/api/projects/<pid>")
def api_projects_delete(pid):
    try:
        projects.delete(owner_id(), pid)
    except projects_mod.ProjectError as exc:
        return jsonify(error=str(exc)), 404
    return jsonify(ok=True)


@app.post("/api/projects/<pid>/duplicate")
def api_projects_duplicate(pid):
    try:
        return jsonify(projects.duplicate(owner_id(), pid, (request.get_json(silent=True) or {}).get("name")))
    except projects_mod.ProjectError as exc:
        return jsonify(error=str(exc)), 404


@app.get("/api/projects/<pid>/bundle")
def api_projects_bundle(pid):
    owner = owner_id()
    try:
        data = projects.export_bundle(owner, pid, jobs.assets_for(owner))
        name = projects.get(owner, pid)["name"]
    except projects_mod.ProjectError as exc:
        return jsonify(error=str(exc)), 404
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip() or "project"
    return send_file(io.BytesIO(data), mimetype="application/zip", as_attachment=True, download_name=f"{safe}.voxa.zip")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5057)), debug=False)
