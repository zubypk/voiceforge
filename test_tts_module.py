"""Tests for tts_module and app. The edge-tts network call is mocked; the MP3 bytes are real (made by ffmpeg)."""
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest

import tts_module as tts
import app as web


@pytest.fixture(scope="session")
def mp3_bytes(tmp_path_factory):
    out = tmp_path_factory.mktemp("audio") / "tone.mp3"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-codec:a", "libmp3lame", "-b:a", "48k", str(out)],
        check=True,
    )
    return out.read_bytes()


class FakeCommunicate:
    last = None

    def __init__(self, text, voice, rate, pitch):
        FakeCommunicate.last = dict(text=text, voice=voice, rate=rate, pitch=pitch)

    async def stream(self):
        yield {"type": "audio", "data": FakeCommunicate.payload}
        yield {"type": "WordBoundary", "data": None}


@pytest.fixture
def fake_service(mp3_bytes, monkeypatch):
    FakeCommunicate.payload = mp3_bytes
    FakeCommunicate.last = None
    monkeypatch.setattr(tts.edge_tts, "Communicate", FakeCommunicate)
    return FakeCommunicate


# ---------- catalog ----------

def test_catalog_is_large_and_arabic_first():
    langs = tts.list_languages()
    assert len(langs) >= 100                       # locales
    assert len({c.split("-")[0] for c, _ in langs}) >= 70   # languages
    assert langs[0][0].startswith("ar-")           # Arabic listed first
    assert any(c.startswith("en-") for c, _ in langs[:25])


@pytest.mark.parametrize("code", ["ar-SA", "ar-EG", "ar-AE", "en-US", "en-GB", "fr-FR", "de-DE", "es-ES",
                                  "it-IT", "pt-BR", "ru-RU", "tr-TR", "ur-PK", "hi-IN", "zh-CN", "ja-JP", "ko-KR"])
def test_major_locales_have_male_and_female(code):
    assert {v.gender for v in tts.list_voices(language=code)} == {"male", "female"}


def test_default_voice_for_uses_preferred():
    assert tts.voice_for("ar-SA", "male") == "ar-SA-HamedNeural"
    assert tts.voice_for("ar-SA", "female") == "ar-SA-ZariyahNeural"
    assert tts.voice_for("en-US", "female") == "en-US-JennyNeural"


def test_voice_has_friendly_name():
    v = next(v for v in tts.VOICES if v.id == "ar-SA-HamedNeural")
    assert v.name == "Hamed" and v.label == "Arabic (Saudi Arabia)"


def test_arabic_voices_present():
    ar = tts.list_voices(language="ar")
    assert ar, "Arabic voices missing"
    assert {v.gender for v in ar} == {"male", "female"}


def test_filter_by_gender_and_language():
    voices = tts.list_voices(language="ar-SA", gender="female")
    assert [v.id for v in voices] == ["ar-SA-ZariyahNeural"]


def test_voice_ids_unique():
    ids = [v.id for v in tts.VOICES]
    assert len(ids) == len(set(ids))


# ---------- validation ----------

@pytest.mark.parametrize("text", ["", "   ", None])
def test_empty_text_rejected(text, fake_service):
    with pytest.raises(tts.TTSError):
        tts.synthesize_mp3(text, "en-US-JennyNeural")


def test_unknown_voice_rejected(fake_service):
    with pytest.raises(tts.TTSError):
        tts.synthesize_mp3("hi", "not-a-voice")


def test_too_long_text_rejected(fake_service):
    with pytest.raises(tts.TTSError):
        tts.synthesize_mp3("a" * (tts.max_text_chars() + 1), "en-US-JennyNeural")


@pytest.mark.parametrize("rate,pitch", [(-51, 0), (101, 0), (0, -51), (0, 51)])
def test_out_of_range_settings_rejected(rate, pitch, fake_service):
    with pytest.raises(tts.TTSError):
        tts.synthesize_mp3("hi", "en-US-JennyNeural", rate, pitch)


# ---------- synthesis ----------

def test_synthesize_passes_arabic_text_and_settings(fake_service):
    data = tts.synthesize_mp3("  مرحبا بالعالم  ", "ar-SA-HamedNeural", rate=10, pitch=-5)
    assert data == fake_service.payload
    assert fake_service.last == {"text": "مرحبا بالعالم", "voice": "ar-SA-HamedNeural",
                                 "rate": "+10%", "pitch": "-5Hz"}


def test_rate_and_pitch_formatted_for_edge_tts(mp3_bytes, monkeypatch):
    seen = {}

    class Spy(FakeCommunicate):
        def __init__(self, text, voice, rate, pitch):
            seen.update(rate=rate, pitch=pitch)
            super().__init__(text, voice, rate, pitch)

    Spy.payload = mp3_bytes
    monkeypatch.setattr(tts.edge_tts, "Communicate", Spy)
    tts.synthesize_mp3("hi", "en-US-JennyNeural", rate=-20, pitch=7)
    assert seen == {"rate": "-20%", "pitch": "+7Hz"}


def test_preview_is_truncated(fake_service):
    tts.preview_mp3("x" * 1000, "en-US-JennyNeural")
    assert len(fake_service.last["text"]) == tts.MAX_PREVIEW_CHARS


def test_service_failure_becomes_tts_unavailable(monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            pass

        async def stream(self):
            raise OSError("proxy refused tunnel")
            yield  # pragma: no cover

    monkeypatch.setattr(tts.edge_tts, "Communicate", Boom)
    with pytest.raises(tts.TTSUnavailable):
        tts.synthesize_mp3("hi", "en-US-JennyNeural")


def test_no_audio_becomes_tts_unavailable(monkeypatch, fake_service):
    fake_service.payload = b""
    with pytest.raises(tts.TTSUnavailable):
        tts.synthesize_mp3("hi", "en-US-JennyNeural")


# ---------- export ----------

def test_export_writes_valid_mp3(fake_service, mp3_bytes, tmp_path):
    out = tts.export_mp3("hello", "ar-EG-SalmaNeural", tmp_path / "sub" / "speech.wav")
    assert out.suffix == ".mp3"
    assert out.read_bytes() == mp3_bytes
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=format_name", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    )
    assert "mp3" in probe.stdout


def test_cli_list(capsys):
    assert tts._cli(["--list"]) == 0
    out = capsys.readouterr().out
    assert "ar-SA-HamedNeural" in out and "female" in out


def test_cli_export(fake_service, tmp_path, capsys):
    out = tmp_path / "cli.mp3"
    assert tts._cli(["مرحبا", "--voice", "ar-SA-ZariyahNeural", "--out", str(out)]) == 0
    assert out.exists() and out.stat().st_size > 0


# ---------- web app ----------

@pytest.fixture
def client(fake_service):
    web.app.config.update(TESTING=True)
    return web.app.test_client()


def test_index_renders(client):
    r = client.get("/")
    assert r.status_code == 200 and b"VoiceForge" in r.data


def test_api_voices(client):
    data = client.get("/api/voices").get_json()
    assert any(v["id"] == "ar-SA-HamedNeural" and v["gender"] == "male" for v in data["voices"])
    assert data["limits"]["max_preview_chars"] == tts.MAX_PREVIEW_CHARS


def test_api_preview_returns_mp3(client, mp3_bytes):
    r = client.post("/api/preview", json={"text": "مرحبا", "voice": "ar-SA-HamedNeural"})
    assert r.status_code == 200
    assert r.mimetype == "audio/mpeg"
    assert r.data == mp3_bytes


def test_api_export_is_attachment(client, mp3_bytes):
    r = client.post("/api/export", json={"text": "hi", "voice": "en-US-GuyNeural", "rate": 5, "pitch": 0})
    assert r.status_code == 200
    assert "speech.mp3" in r.headers["Content-Disposition"]
    assert r.data == mp3_bytes


def test_api_bad_input_is_400(client):
    r = client.post("/api/preview", json={"text": "", "voice": "en-US-GuyNeural"})
    assert r.status_code == 400 and "empty" in r.get_json()["error"]


def test_api_service_down_is_502(monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            pass

        async def stream(self):
            raise OSError("403")
            yield  # pragma: no cover

    monkeypatch.setattr(tts.edge_tts, "Communicate", Boom)
    web.app.config.update(TESTING=True)
    r = web.app.test_client().post("/api/export", json={"text": "hi", "voice": "en-US-GuyNeural"})
    assert r.status_code == 502 and "unavailable" in r.get_json()["error"].lower()


def test_api_language_gender_picks_voice(client, mp3_bytes, fake_service):
    r = client.post("/api/export", json={"text": "مرحبا", "lang": "ar-SA", "gender": "male"})
    assert r.status_code == 200
    assert fake_service.last["voice"] == "ar-SA-HamedNeural"


def test_cors_only_when_configured(client, monkeypatch):
    assert "Access-Control-Allow-Origin" not in client.get("/api/voices").headers     # same-origin by default
    monkeypatch.setenv("ALLOWED_ORIGIN", "https://example.org")
    assert client.get("/api/voices").headers["Access-Control-Allow-Origin"] == "https://example.org"


def test_bad_language_gender_is_400(client, fake_service):
    r = client.post("/api/preview", json={"text": "hi", "lang": "xx-XX", "gender": "male"})
    assert r.status_code == 400


# ---------- Google sign-in (token verification is mocked) ----------

def test_config_hides_google_when_unset(client):
    data = client.get("/api/config").get_json()
    assert data["google_client_id"] is None and data["require_login"] is False


def test_google_login_503_when_not_configured(client):
    assert client.post("/api/auth/google", json={"credential": "x"}).status_code == 503


def test_google_login_flow(client, monkeypatch):
    monkeypatch.setattr(web, "GOOGLE_CLIENT_ID", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(web, "verify_google_token",
                        lambda c: {"email": "a@b.com", "name": "Ada", "picture": "http://p", "email_verified": True})
    r = client.post("/api/auth/google", json={"credential": "good"})
    assert r.status_code == 200 and r.get_json()["user"]["email"] == "a@b.com"
    assert client.get("/api/me").get_json()["user"]["name"] == "Ada"
    client.post("/api/auth/logout")
    assert client.get("/api/me").get_json()["user"] is None


def test_google_login_rejects_bad_token(client, monkeypatch):
    monkeypatch.setattr(web, "GOOGLE_CLIENT_ID", "cid")

    def boom(_):
        raise ValueError("bad signature")

    monkeypatch.setattr(web, "verify_google_token", boom)
    assert client.post("/api/auth/google", json={"credential": "bad"}).status_code == 401


def test_google_login_domain_allowlist(client, monkeypatch):
    monkeypatch.setattr(web, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(web, "ALLOWED_DOMAINS", {"corp.com"})
    monkeypatch.setattr(web, "verify_google_token", lambda c: {"email": "x@other.com", "email_verified": True})
    assert client.post("/api/auth/google", json={"credential": "t"}).status_code == 403


def test_require_login_gate(client, monkeypatch, fake_service):
    monkeypatch.setattr(web, "REQUIRE_LOGIN", True)
    r = client.post("/api/export", json={"text": "hi", "lang": "en-US", "gender": "male"})
    assert r.status_code == 401 and r.get_json()["login_required"] is True
    with client.session_transaction() as s:
        s["user"] = {"name": "Ada", "email": "a@b.com"}
    assert client.post("/api/export", json={"text": "hi", "lang": "en-US", "gender": "male"}).status_code == 200



# ---------------------------------------------------------------- long text

def test_split_text_keeps_sentences_whole_and_respects_the_limit():
    text = " ".join(f"This is sentence number {i}." for i in range(300))
    chunks = tts.split_text(text, 500)
    assert all(len(c) <= 500 for c in chunks) and len(chunks) > 10
    assert all(c.endswith(".") for c in chunks)                      # never cut mid-sentence
    assert " ".join(chunks).replace("  ", " ") == text
    assert tts.split_text("short") == ["short"] and tts.split_text("   ") == []


def test_split_text_handles_one_endless_sentence_and_arabic():
    assert all(len(c) <= 300 for c in tts.split_text("word " * 1000, 300))
    assert all(len(c) <= 300 for c in tts.split_text("x" * 2000, 300))
    chunks = tts.split_text("جملة عربية قصيرة؟ " * 200, 400)
    assert len(chunks) > 5 and all(len(c) <= 400 for c in chunks)


def test_long_text_is_synthesized_in_pieces_and_joined(fake_service):
    calls = []
    orig = fake_service.__init__

    def spy(self, text, voice, rate, pitch):
        calls.append(text)
        orig(self, text, voice, rate, pitch)

    fake_service.__init__ = spy
    text = " ".join(f"Sentence {i} is here." for i in range(1500))       # ~30,000 characters, way over the old 5,000 limit
    progress = []
    data = tts.synthesize_mp3(text, "en-US-JennyNeural", progress=progress.append)
    assert len(calls) > 8 and all(len(c) <= tts.CHUNK_CHARS for c in calls)
    assert data == fake_service.payload * len(calls)                  # one MP3 piece per chunk, in order
    assert progress[-1] == 1.0 and progress == sorted(progress)


def test_the_text_limit_is_configurable(fake_service, monkeypatch):
    monkeypatch.setenv("VF_MAX_TEXT_CHARS", "50")
    assert tts.max_text_chars() == 50
    with pytest.raises(tts.TTSError) as e:
        tts.synthesize_mp3("a" * 51, "en-US-JennyNeural")
    assert "limit is 50" in str(e.value)
    monkeypatch.setenv("VF_MAX_TEXT_CHARS", "0")                     # 0 = unlimited
    assert tts.max_text_chars() == 0
    assert tts.synthesize_mp3("word. " * 40000, "en-US-JennyNeural")
    monkeypatch.setenv("VF_MAX_TEXT_CHARS", "garbage")
    assert tts.max_text_chars() == tts.DEFAULT_MAX_TEXT_CHARS


def test_default_limit_is_far_above_the_old_5000():
    assert tts.DEFAULT_MAX_TEXT_CHARS >= 100_000


def test_no_audio_gets_a_helpful_message(monkeypatch):
    class Silent:
        def __init__(self, *a, **k):
            pass

        async def stream(self):
            raise tts.edge_tts.exceptions.NoAudioReceived("No audio was received.")
            yield  # pragma: no cover

    monkeypatch.setattr(tts.edge_tts, "Communicate", Silent)
    with pytest.raises(tts.TTSUnavailable) as e:
        tts.synthesize_mp3("مرحبا", "fr-FR-DeniseNeural")
    assert "language" in str(e.value).lower() and "voice" in str(e.value).lower()


# ---------------------------------------------------------------- languages

def test_catalog_has_dozens_of_languages_and_no_unusable_voices():
    langs = {c.split("-")[0] for c, _ in tts.list_languages()}
    assert len(langs) >= 70
    assert not any(v.language.startswith("iu") for v in tts.VOICES)          # names the library rejects
    assert not any(v.id in tts.KNOWN_BROKEN for v in tts.VOICES)
    assert all(tts._VALID_VOICE_ID.match(v.id) for v in tts.VOICES)


def test_every_language_has_a_native_sample_sentence():
    from samples import SAMPLES, sample_for

    langs = {c.split("-")[0] for c, _ in tts.list_languages()}
    missing = sorted(l for l in langs if l not in SAMPLES)
    assert missing == [] or len(missing) <= 4, missing                   # the rest fall back to English
    assert sample_for("ar-SA") == SAMPLES["ar"] and sample_for("fr-CA") == SAMPLES["fr"]
    assert sample_for("xx-XX") == SAMPLES["en"]


def test_samples_use_the_right_script():
    from samples import SAMPLES
    import unicodedata

    def first_letter_script(text):
        for ch in text:
            if ch.isalpha():
                return unicodedata.name(ch).split()[0]

    assert first_letter_script(SAMPLES["ar"]) == "ARABIC" and first_letter_script(SAMPLES["ur"]) == "ARABIC"
    assert first_letter_script(SAMPLES["hi"]) == "DEVANAGARI" and first_letter_script(SAMPLES["ru"]) == "CYRILLIC"
    assert first_letter_script(SAMPLES["el"]) == "GREEK" and first_letter_script(SAMPLES["ko"]) == "HANGUL"
    assert first_letter_script(SAMPLES["th"]) == "THAI" and first_letter_script(SAMPLES["he"]) == "HEBREW"


def test_voices_endpoint_exposes_samples_limits_and_names(client):
    d = client.get("/api/voices").get_json()
    assert d["samples"]["fr"].startswith("Bienvenue") and len(d["languages"]) >= 100
    assert d["limits"]["max_text_chars"] == tts.max_text_chars() and d["limits"]["sync_export_chars"] == web.SYNC_EXPORT_CHARS
    assert all("name" in v for v in d["voices"])


# ---------------------------------------------------------------- long exports over HTTP

def test_long_text_export_runs_as_a_job(client, fake_service, tmp_path, monkeypatch):
    import time
    import video

    monkeypatch.setattr(web, "jobs", video.JobManager(tmp_path))
    text = " ".join(f"Sentence {i} is here." for i in range(2000))            # ~40,000 characters
    assert client.post("/api/export", json={"text": text, "voice": "en-US-JennyNeural"}).status_code == 413
    r = client.post("/api/tts/jobs", json={"text": text, "lang": "en-US", "gender": "female"})
    assert r.status_code == 202
    jid = r.get_json()["job_id"]
    for _ in range(200):
        st = client.get(f"/api/jobs/{jid}").get_json()
        if st["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert st["status"] == "done" and st["kind"] == "audio", st
    mp3 = client.get(f"/api/jobs/{jid}/speech.mp3")
    assert mp3.status_code == 200 and mp3.mimetype == "audio/mpeg" and len(mp3.data) > len(fake_service.payload) * 5


def test_tts_job_rejects_bad_input(client, tmp_path, monkeypatch):
    import video

    monkeypatch.setattr(web, "jobs", video.JobManager(tmp_path))
    assert client.post("/api/tts/jobs", json={"text": "", "lang": "en-US", "gender": "male"}).status_code == 400
    assert client.post("/api/tts/jobs", json={"text": "hi", "voice": "nope"}).status_code == 400
    monkeypatch.setenv("VF_MAX_TEXT_CHARS", "10")
    assert client.post("/api/tts/jobs", json={"text": "x" * 11, "lang": "en-US", "gender": "male"}).status_code == 400


def test_tts_job_respects_login_gate(client, monkeypatch):
    monkeypatch.setattr(web, "REQUIRE_LOGIN", True)
    assert client.post("/api/tts/jobs", json={"text": "hi", "lang": "en-US", "gender": "male"}).status_code == 401


# ---- translator ----
def test_translate_chunks_and_codes():
    import translate as tr
    assert tr.api_code("zh-TW") == "zh-Hant" and tr.api_code("ar-SA") == "ar" and tr.api_code("zh-CN") == "zh-Hans"
    text = ("Hello world. " * 600) + "\n" + "x" * 7000
    parts = tr.split_chunks(text)
    assert "".join(parts) == text and all(len(p) <= 3000 for p in parts)
    out = tr.translate("Hello. Bye.", "fr-FR", backend=lambda ch, s, d: [c.upper() + d for c in ch])
    assert out == "HELLO. BYE.fr"
    assert tr.translate("same", "en-US", "en-GB", backend=lambda *a: 1 / 0) == "same"
    for bad in ("", "  "):
        try:
            tr.translate(bad, "fr-FR"); assert False
        except tr.TranslateError:
            pass


def test_translate_endpoint(monkeypatch):
    import app as appmod
    import translate as tr
    monkeypatch.setattr(tr, "_default_backend", lambda ch, s, d: ["[" + d + "]" + c for c in ch])
    c = appmod.app.test_client()
    r = c.post("/api/translate", json={"text": "Hi", "to": "ar-SA"})
    assert r.status_code == 200 and r.get_json()["text"] == "[ar]Hi"
    assert c.post("/api/translate", json={"text": "", "to": "ar-SA"}).status_code == 400
