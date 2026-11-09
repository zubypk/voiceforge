# VoiceForge

Natural text-to-speech in **75 languages (Arabic first)** plus a **video studio** that turns scenes into a narrated MP4 with burned-in captions. One small Python package: a library, a CLI and a web app.

- **Voice** — 322 Microsoft neural voices (male/female) via [`edge-tts`](https://github.com/rany2/edge-tts). Preview with a waveform, export MP3.
- **Video** — scenes → slides (Pillow, correct Arabic/RTL shaping) + narration + captions → H.264/AAC MP4 (ffmpeg). Presets for **YouTube 16:9**, **Shorts/TikTok/Reels 9:16**, **Instagram 1:1 and 4:5**, **classroom 4:3**; five content presets (lesson, explainer, short, course intro, quiz) in English and Arabic; upload images or clips as backgrounds; SRT export.
- **UI** in English and Arabic (RTL), optional **Sign in with Google**.

## Run it

```bash
python -m venv venv && . venv/bin/activate
pip install -r requirements.txt
python app.py                 # http://localhost:5057
```

Docker:

```bash
docker compose up --build     # http://localhost:8080
# or, once the GitHub Action has run:
docker run -p 8080:8080 -v vf-data:/data ghcr.io/<owner>/<repo>:latest
```

The server needs outbound HTTPS access to Microsoft's speech service. `imageio-ffmpeg` bundles an ffmpeg binary; a system `ffmpeg` is used if present (or set `FFMPEG_BIN`).

## Configuration (environment variables)

| Variable | Purpose |
|---|---|
| `VF_DATA` | Folder for renders and uploads (default `./data`; files are deleted after 24 h) |
| `GOOGLE_CLIENT_ID` | Enables "Sign in with Google" (create an OAuth Web client; add your site as an authorised JavaScript origin) |
| `REQUIRE_LOGIN=1` | Require sign-in for voice/video endpoints (default: optional) |
| `ALLOWED_EMAIL_DOMAINS` | Comma list, e.g. `example.com` |
| `SECRET_KEY` | Cookie signing key (set it, or sessions reset on restart) |
| `COOKIE_SECURE=1` | Set when serving over HTTPS |
| `ALLOWED_ORIGIN` | CORS origin for the API (default `*`) |
| `VF_FONT_DIR` | Extra fonts for slides (see below) |

## Library and CLI

```python
from tts_module import export_mp3, voice_for
export_mp3("مرحبا بكم", voice_for("ar-SA", "male"), "hello.mp3")

import video
project = video.validate_project({
    "size": "youtube-1080", "theme": "academy", "captions": True,
    "voice": {"lang": "ar-SA", "gender": "female"},
    "scenes": [{"layout": "title", "title": "درس جديد", "narration": "أهلاً بكم في هذا الدرس."}],
})
video.render_project(project, "lesson.mp4", assets=None)
```

```bash
python tts_module.py --list --language ar
python tts_module.py "Hello" --voice en-US-JennyNeural --out hello.mp3
```

## HTTP API

| Endpoint | |
|---|---|
| `GET /api/voices` | Languages and voices |
| `POST /api/preview`, `POST /api/export` | MP3 from `{text, lang, gender}` or `{text, voice}`, plus `rate`, `pitch` |
| `GET /api/video/config` | Sizes, themes, presets, limits |
| `POST /api/video/assets` | Upload a background image/clip (multipart `file`) |
| `POST /api/video/preview` | PNG preview of one scene: `{project, index}` |
| `POST /api/video/render` | Start a render → `{job_id}`; poll `GET /api/video/jobs/<id>`; download `…/video.mp4` and `…/captions.srt` |

Scene layouts: `title`, `bullets`, `text`, `quote`. Backgrounds: theme gradient, solid colour, image, video. Limits: 40 scenes / ~15 min per video, 5,000 characters per MP3, images 15 MB, clips 150 MB.

## Fonts for slides

Arabic, Latin, Cyrillic and Greek work with DejaVu Sans. Other scripts need a matching system font (the Docker image installs Noto fonts; build with `--build-arg INSTALL_CJK=1` for Chinese/Japanese/Korean). Narration works for every language regardless.

## Tests

```bash
pip install pytest && python -m pytest -q      # needs ffmpeg + ffprobe on PATH
```

Speech is faked in the tests; everything else (Pillow, ffmpeg, Flask) is real.

## Notes

- `edge-tts` uses an unofficial Microsoft endpoint: it can change or be rate-limited. Check Microsoft's terms before commercial use, and make sure you own the rights to uploaded media.
- `voices_snapshot.json` is the voice catalog; refresh it with `python scripts/update_voices.py`.
- Deployment examples: `deploy/nginx.conf`, `deploy/voiceforge.service`.
