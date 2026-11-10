"""Write build.json: build number (git commit count), short commit and the build time in Riyadh (UTC+3).

Run on every deploy:  python scripts/stamp_build.py
"""
import datetime as dt
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RIYADH = dt.timezone(dt.timedelta(hours=3), "AST")   # Saudi Arabia has no daylight saving time


def git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
    except OSError:
        return ""


def stamp(path: Path = ROOT / "build.json") -> dict:
    now = dt.datetime.now(RIYADH)
    info = {"build": int(git("rev-list", "--count", "HEAD") or 0) or None, "commit": git("rev-parse", "--short", "HEAD") or None,
            "time": now.isoformat(timespec="minutes"), "display": now.strftime("%d %b %Y, %H:%M")}
    path.write_text(json.dumps(info), encoding="utf-8")
    return info


if __name__ == "__main__":
    print(stamp())
