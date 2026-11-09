"""TTS Studio: natural neural voices (edge-tts) with optional Google sign-in.

Environment:
  GOOGLE_CLIENT_ID  OAuth client id (Google Cloud > APIs & Services > Credentials). Sign-in is hidden if unset.
  REQUIRE_LOGIN     "1" = preview/export need a signed-in user. Default: sign-in is optional.
  ALLOWED_EMAIL_DOMAINS  optional comma list (e.g. "example.com") limiting who may sign in.
  SECRET_KEY        cookie signing key (set it, or sessions reset on every restart).
  COOKIE_SECURE     "1" when served over HTTPS (recommended).
"""
from __future__ import annotations

import io
import os
import secrets
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file, session

import tts_module as tts
import video
import video_presets

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 160 * 1024 * 1024  # video uploads
DATA_DIR = Path(os.environ.get("VF_DATA", Path(__file__).with_name("data")))
jobs = video.JobManager(DATA_DIR)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",
)

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
REQUIRE_LOGIN = os.environ.get("REQUIRE_LOGIN") == "1"
ALLOWED_DOMAINS = {d.strip().lower() for d in os.environ.get("ALLOWED_EMAIL_DOMAINS", "").split(",") if d.strip()}


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


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/healthz")
def healthz():
    return jsonify(ok=True)


@app.get("/api/config")
def api_config():
    return jsonify(google_client_id=GOOGLE_CLIENT_ID or None, require_login=REQUIRE_LOGIN)


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


@app.after_request
def cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = os.environ.get("ALLOWED_ORIGIN", "*")
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


@app.route("/api/<path:_>", methods=["OPTIONS"])
def preflight(_):
    return ("", 204)


@app.get("/api/voices")
def api_voices():
    return jsonify(
        languages=[{"code": c, "label": l} for c, l in tts.list_languages()],
        voices=[{"id": v.id, "name": v.name, "language": v.language, "label": v.label, "gender": v.gender} for v in tts.VOICES],
        limits={"max_text_chars": tts.MAX_TEXT_CHARS, "max_preview_chars": tts.MAX_PREVIEW_CHARS,
                "rate": tts.RATE_RANGE, "pitch": tts.PITCH_RANGE},
    )


def _payload():
    data = request.get_json(silent=True) or {}
    voice = data.get("voice") or tts.voice_for(data.get("lang", "ar-SA"), data.get("gender", "female"))
    return (data.get("text", ""), voice, int(data.get("rate", 0) or 0), int(data.get("pitch", 0) or 0))


def _error(exc: Exception):
    return jsonify(error=str(exc)), (400 if isinstance(exc, tts.TTSError) else 502)


def _login_gate():
    if REQUIRE_LOGIN and not session.get("user"):
        return jsonify(error="Please sign in with Google first.", login_required=True), 401
    return None


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
    if (gate := _login_gate()):
        return gate
    try:
        mp3 = tts.synthesize_mp3(*_payload())
    except (tts.TTSError, tts.TTSUnavailable, ValueError) as exc:
        return _error(exc)
    return send_file(io.BytesIO(mp3), mimetype="audio/mpeg", as_attachment=True, download_name="speech.mp3")


# ----------------------------------------------------------------------------- video studio

def _video_error(exc: Exception):
    code = 400 if isinstance(exc, (video.VideoError, tts.TTSError)) else 502
    return jsonify(error=str(exc)), code


@app.get("/api/video/config")
def api_video_config():
    return jsonify(
        sizes=[{"id": k, **v} for k, v in video.SIZES.items()],
        themes=[{"id": k, "label": v["label"], "bg": v["bg"], "text": v["text"], "accent": v["accent"]}
                for k, v in video.THEMES.items()],
        layouts=list(video.LAYOUTS),
        limits=video.LIMITS,
        presets=[{"id": k, "label": v["label"], "desc": v["desc"], "size": v["size"], "theme": v["theme"],
                  "scenes": v["scenes"]} for k, v in video_presets.PRESETS.items()],
    )


@app.post("/api/video/assets")
def api_video_assets():
    if (gate := _login_gate()):
        return gate
    f = request.files.get("file")
    if not f:
        return jsonify(error="No file uploaded."), 400
    try:
        return jsonify(jobs.assets.save(f.read(), f.filename or ""))
    except video.VideoError as exc:
        return _video_error(exc)


def _project_from_request():
    data = request.get_json(silent=True) or {}
    return video.validate_project(data.get("project"), jobs.assets), data


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
        project = video.validate_project({**raw, "scenes": [scenes[index]]}, jobs.assets, allow_empty=True)
        png = video.render_preview_png(project, 0, jobs.assets)
    except (video.VideoError, ValueError) as exc:
        return _video_error(exc)
    return send_file(io.BytesIO(png), mimetype="image/png")


@app.post("/api/video/render")
def api_video_render():
    if (gate := _login_gate()):
        return gate
    try:
        project, _ = _project_from_request()
        job_id = jobs.submit(project)
    except video.VideoError as exc:
        return _video_error(exc)
    return jsonify(job_id=job_id), 202


@app.get("/api/video/jobs/<job_id>")
def api_video_job(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify(error="Job not found (it may have expired)."), 404
    return jsonify({k: job[k] for k in ("id", "status", "progress", "message", "error", "duration")})


@app.get("/api/video/jobs/<job_id>/<name>")
def api_video_file(job_id, name):
    path = jobs.file(job_id, name)
    if not path:
        return jsonify(error="File not available."), 404
    if name == "video.mp4":
        return send_file(path, mimetype="video/mp4", conditional=True,
                         as_attachment=request.args.get("download") == "1", download_name="video.mp4")
    return send_file(path, mimetype="application/x-subrip", as_attachment=True, download_name="captions.srt")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5057)), debug=False)
