# Voxa

Live: https://voxa.lusona.org  ·  (repository name `voiceforge` is the original project name)

Text-to-speech, speech-to-text, an audio editor and an educational video studio in one web app (English and Arabic UI, five colour themes).

Natural text-to-speech in **75 languages (Arabic first)** plus a **video studio** that turns scenes into a narrated MP4 with burned-in captions. One small Python package: a library, a CLI and a web app.

- **Voice** — 322 Microsoft neural voices (male/female) via [`edge-tts`](https://github.com/rany2/edge-tts). Preview with a waveform, export MP3.
- **Video** — scenes → slides (Pillow, correct Arabic/RTL shaping) + narration + captions → H.264/AAC MP4 (ffmpeg). Six aspect ratios (**16:9, 9:16, 1:1, 4:5, 4:3, 21:9**) × five resolutions (**480p, 720p HD, 1080p Full HD, 1440p 2K, 2160p 4K**); five content presets (lesson, explainer, short, course intro, quiz) in English and Arabic; insert images, videos and background music; SRT export.
- **Translator** — translate pasted text into any supported language (Microsoft Edge translator, Google as fallback; no key), the voice switches automatically, with Undo.
- **Speech to text** — live typing while you speak (browser speech recognition: Chrome, Edge, Safari), live waveform, editable transcript, TXT/SRT export, translate, send to text-to-speech. The Voice tab also has 🎤 dictation.
- **Audio editor** — import/record, zoomable waveform, select + cut/copy/paste/delete/trim/silence, fades, normalize, gain, reverse, effects (voice enhance, hiss reduction, compressor, echo, reverb, radio, bass/treble, speed, pitch, robot), mix-in, undo/redo, export WAV/MP3, save to library.
- **Video extras** — record your own voice-over per scene (with live captions), motion (Ken Burns zoom/pan) and looks (sepia, B&W, vintage, warm, cool, vivid, blur, vignette), 28 transitions (mirrored for right-to-left scenes), animated layers (pop, fade, slide, rise, float, pulse, spin), per-scene sound effects.
- **Free media library** — 24 shapes in any colour, ~200 clip-art illustrations, 14 built-in sound effects, plus searchable real photos, illustrations, music and sound effects from Openverse (openly licensed, commercial use; attribution is stored with each file).
- **Import PDF / PowerPoint / Word / Excel** — every page or slide becomes a scene on the timeline (full-screen, sharp up to 1440p); speaker notes or page text can become the narration. PowerPoint is converted pixel-exactly with LibreOffice when installed; otherwise `.pptx` becomes editable title/bullets/picture scenes.
- **Projects** — save, open, duplicate, delete, "new project", autosave, and export/import a project as a zip bundle (with its media).
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
| `ADSENSE_CLIENT` | Google AdSense publisher id (`ca-pub-…`). Enables ads in three fixed spots (never inside the editors) and serves `/ads.txt` |
| `ADSENSE_SLOTS` | Optional ad unit ids: `top=…,middle=…,footer=…` (without it, AdSense Auto ads are used) |
| `VF_RATE_LIMITS=0` | Disable the per-client rate limits (on by default) |
| `OPENVERSE_API` | Online library endpoint (default `https://api.openverse.org/v1`) |
| `VF_MAX_TEXT_CHARS` | Max characters per MP3 (default `100000`; `0` = unlimited). Long texts are chunked and run as background jobs |

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
| `POST /api/video/import` | Import a PDF/PPTX/PPT/ODP as scenes (multipart `file`, `narration=notes\|text\|none`, `background=black\|theme`) → `{scenes, assets}` |
| `POST /api/translate` | `{text, to}` → `{text}` |
| `POST /api/video/render` | Start a render → `{job_id}`; poll `GET /api/video/jobs/<id>`; download `…/video.mp4` and `…/captions.srt` |

Scene layouts: `title`, `bullets`, `text`, `quote`, `media`. Limits (env-tunable in `video.py`): 60 scenes, 25 MB images, 300 MB clips, 60 MB audio, 800 MB storage per user; max duration shrinks as resolution grows (4K is slow and CPU-heavy).

## Languages not working?

The voice must match the language of the text. Arabic text with a French voice, for example, returns no audio. The Voice tab warns about a mismatch and offers to switch. Three voices Microsoft no longer serves are excluded. Slide text in Hindi, Thai, Chinese etc. needs a matching font (`scripts/get_fonts.sh`, or the Docker image).

## Fonts for slides

Arabic, Latin, Cyrillic and Greek work with DejaVu Sans. Other scripts need a matching system font (the Docker image installs Noto fonts; build with `--build-arg INSTALL_CJK=1` for Chinese/Japanese/Korean). Narration works for every language regardless.

## Docker on the server

1. Once, with sudo: `sudo bash deploy/docker-setup.sh` (adds the docker compose plugin and gives your user Docker access).
2. Then, and for every update: `bash deploy/docker-deploy.sh`. It builds the image, keeps `data/` and your secret key, serves on 127.0.0.1:5057 for nginx, restarts automatically, and rolls back to the non-Docker setup if the container is not healthy.
The container runs as your user with a read-only filesystem, no Linux capabilities and memory/CPU limits. Settings live in `.env.docker` (not in git or the image).

## Security

- Per-client rate limits on every expensive endpoint (render, TTS, translate, import, uploads, library); proxy headers are trusted only from the local proxy.
- Security headers: Content-Security-Policy, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy (microphone only for this site), HSTS over HTTPS.
- Same-origin API by default (set `ALLOWED_ORIGIN` to allow another site).
- Uploads: size limits, strict IDs (no path traversal), image re-validation, and a media-container allow-list so playlists disguised as video/audio can't make ffmpeg read local files or URLs. Online media is fetched by Openverse id only (no arbitrary URLs).
- Cookies are HttpOnly, SameSite=Lax, Secure over HTTPS.

## Build number

Run `python scripts/stamp_build.py` on each deploy; it writes `build.json` (commit count, commit, Riyadh time) which the footer shows.

## Deploying on a server (no root)

`bash deploy/update.sh` pulls the latest code, installs packages, stamps the build, restarts the app, starts a Cloudflare quick tunnel and installs a crontab watchdog (`deploy/watchdog.sh`, every 5 minutes and after reboot) that restarts the app and tunnel if they stop. The current public link is kept in `PUBLIC_URL.txt`. Add `WITH_OFFICE=1` once to install a portable LibreOffice for Word/Excel/PowerPoint import.

## Tests

```bash
pip install pytest && python -m pytest -q      # needs ffmpeg + ffprobe on PATH
```

Speech is faked in the tests; everything else (Pillow, ffmpeg, Flask) is real.

## Notes

- `edge-tts` uses an unofficial Microsoft endpoint: it can change or be rate-limited. Check Microsoft's terms before commercial use, and make sure you own the rights to uploaded media.
- `voices_snapshot.json` is the voice catalog; refresh it with `python scripts/update_voices.py`.
- Deployment examples: `deploy/nginx.conf`, `deploy/voiceforge.service`.
