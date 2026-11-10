"""Try one voice per locale with a native sample sentence; also test mismatched text. Needs internet.

    python scripts/lang_test.py            # all locales
    python scripts/lang_test.py ar fr hi   # only these language prefixes
"""
import asyncio, io, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import edge_tts
import tts_module as tts
from samples import SAMPLES, sample_for


async def speak(voice, text):
    buf = io.BytesIO()
    async for ch in edge_tts.Communicate(text, voice).stream():
        if ch["type"] == "audio":
            buf.write(ch["data"])
    return buf.getvalue()


async def one(sem, voice, text, tag):
    async with sem:
        t = time.time()
        try:
            data = await asyncio.wait_for(speak(voice.id, text), 40)
            return tag, voice, len(data), None, time.time() - t
        except Exception as exc:
            return tag, voice, 0, f"{type(exc).__name__}: {str(exc)[:80]}", time.time() - t


async def main():
    only = set(sys.argv[1:])
    sem = asyncio.Semaphore(4)
    jobs = []
    for code, label in tts.list_languages():
        base = code.split("-")[0]
        if only and base not in only:
            continue
        for g in ("female", "male"):
            vs = tts.list_voices(code, g)
            if vs:
                jobs.append(one(sem, vs[0], sample_for(code), "native" if base in SAMPLES else "english-fallback"))
                break
    results = await asyncio.gather(*jobs)
    bad = [r for r in results if r[3] or r[2] == 0]
    print(f"{len(results) - len(bad)}/{len(results)} locales produced audio")
    for tag, v, n, err, dt in sorted(bad, key=lambda r: r[1].language):
        print(f"  FAIL {v.language:7} {v.id:34} [{tag}] {err or 'no audio returned'}")
    falls = [r for r in results if r[0] == "english-fallback" and not r[3] and r[2] > 0]
    print(f"english-text fallback worked for {len(falls)} locales without a native sample")

    print("--- mismatch tests (text in a different script than the voice) ---")
    tests = [("fr-FR-DeniseNeural", SAMPLES["ar"], "French voice + Arabic text"),
             ("ar-SA-HamedNeural", SAMPLES["en"], "Arabic voice + English text"),
             ("hi-IN-SwaraNeural", SAMPLES["ar"], "Hindi voice + Arabic text"),
             ("en-US-AvaMultilingualNeural", SAMPLES["ar"], "Multilingual EN voice + Arabic text"),
             ("en-US-AvaMultilingualNeural", SAMPLES["fr"], "Multilingual EN voice + French text")]
    for vid, text, label in tests:
        v = next((x for x in tts.VOICES if x.id == vid), None)
        if not v:
            print(f"  {label}: voice not in catalog"); continue
        tag, _, n, err, dt = await one(sem, v, text, "")
        print(f"  {label}: {'AUDIO ' + str(n) + ' bytes' if n else 'NO AUDIO'} {err or ''}")

asyncio.run(main())
