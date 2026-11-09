"""Regenerate voices_snapshot.json from Microsoft's live voice list (needs internet).

    python scripts/update_voices.py
"""
import asyncio
import json
from pathlib import Path

import edge_tts


async def main() -> None:
    voices = await edge_tts.list_voices()
    rows = [[v["ShortName"], v["Gender"][0], v["Locale"], v["FriendlyName"].split(" - ")[-1].strip()] for v in voices]
    rows.sort(key=lambda r: (r[2], r[1], r[0]))
    out = Path(__file__).resolve().parent.parent / "voices_snapshot.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(rows)} voices, {len({r[2] for r in rows})} locales -> {out}")


asyncio.run(main())
