"""Saved video projects: one JSON file per project, per user (owner). Plus portable zip bundles.

Layout:  <root>/<owner>/<project_id>.json   ->  {"id", "name", "updated", "project": {...}}
"""
from __future__ import annotations

import io
import json
import os
import re
import time
import uuid
import zipfile
from pathlib import Path

MAX_PROJECT_BYTES = 2 * 1024 * 1024
MAX_PROJECTS_PER_OWNER = 200
MAX_BUNDLE_BYTES = 450 * 1024 * 1024
HEX32 = re.compile(r"[0-9a-f]{32}")


class ProjectError(ValueError):
    """Bad project data, unknown project, or a limit was hit."""


def clean_name(name) -> str:
    name = re.sub(r"\s+", " ", str(name or "")).strip()[:80]
    return name or "Untitled project"


_HEX32 = re.compile(r"[0-9a-f]{32}")


def _walk_assets(obj, fn, parent=None, key=None):
    """Visit every {"asset": "<id>"} object anywhere in a project (scenes, music, voice-overs, sound effects,
    layers, timeline clips...). fn(holder_dict) may return False to have the holder removed."""
    if isinstance(obj, dict):
        if isinstance(obj.get("asset"), str) and _HEX32.fullmatch(obj["asset"]):
            if fn(obj) is False:
                return False
        for k in list(obj):
            if _walk_assets(obj[k], fn, obj, k) is False:
                obj[k] = None
    elif isinstance(obj, list):
        keep = [x for x in obj if _walk_assets(x, fn, obj) is not False]
        obj[:] = keep
    return True


def asset_ids(project: dict) -> list[str]:
    """Every asset id a project refers to, wherever it is used."""
    ids = []
    _walk_assets(json.loads(json.dumps(project)) if isinstance(project, (dict, list)) else {}, lambda o: ids.append(o["asset"]))
    return list(dict.fromkeys(ids))


def remap_assets(project: dict, mapping: dict[str, str | None]) -> dict:
    """Return a copy of the project with asset ids replaced via `mapping` (None drops the media)."""
    p = json.loads(json.dumps(project))
    for s in p.get("scenes", []) if isinstance(p, dict) else []:     # scene backgrounds fall back to the theme
        bg = (s or {}).get("background") or {}
        if bg.get("asset") and mapping.get(bg["asset"]) is None:
            s["background"] = {"type": "theme", "color": bg.get("color", "#1d4e9e"), "asset": None}

    def swap(o):
        new = mapping.get(o["asset"])
        if new is None:
            return False          # drop media / layer / clip / music whose file is gone
        o["asset"] = new
        return True

    _walk_assets(p, swap)
    return p


class ProjectStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, owner: str) -> Path:
        if not re.fullmatch(r"[a-z0-9]{8,64}", str(owner or "")):
            raise ProjectError("Unknown user.")
        d = self.root / owner
        d.mkdir(exist_ok=True)
        return d

    @staticmethod
    def _ok_id(pid) -> bool:
        return bool(re.fullmatch(r"[0-9a-f]{16}", str(pid or "")))

    def _path(self, owner: str, pid: str) -> Path:
        if not self._ok_id(pid):
            raise ProjectError("Project not found.")
        return self._dir(owner) / f"{pid}.json"

    def list(self, owner: str) -> list[dict]:
        out = []
        for p in self._dir(owner).glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                proj = d.get("project") or {}
                out.append({"id": d["id"], "name": d["name"], "updated": d["updated"],
                            "scenes": len(proj.get("scenes", [])), "ratio": proj.get("ratio"),
                            "resolution": proj.get("resolution")})
            except (OSError, ValueError, KeyError):
                continue
        return sorted(out, key=lambda x: x["updated"], reverse=True)

    def get(self, owner: str, pid: str) -> dict:
        p = self._path(owner, pid)
        if not p.exists():
            raise ProjectError("Project not found.")
        return json.loads(p.read_text(encoding="utf-8"))

    def save(self, owner: str, name: str, project: dict, pid: str | None = None) -> dict:
        if not isinstance(project, dict) or not isinstance(project.get("scenes"), list):
            raise ProjectError("Invalid project.")
        raw = json.dumps(project, ensure_ascii=False)
        if len(raw.encode("utf-8")) > MAX_PROJECT_BYTES:
            raise ProjectError("Project is too large to save.")
        d = self._dir(owner)
        if pid is None:
            if len(list(d.glob("*.json"))) >= MAX_PROJECTS_PER_OWNER:
                raise ProjectError("Too many saved projects. Delete some first.")
            pid = uuid.uuid4().hex[:16]
        elif not self._path(owner, pid).exists():
            raise ProjectError("Project not found.")
        record = {"id": pid, "name": clean_name(name), "updated": time.time(), "project": project}
        tmp = d / f"{pid}.json.tmp"
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, d / f"{pid}.json")
        return {"id": pid, "name": record["name"], "updated": record["updated"]}

    def delete(self, owner: str, pid: str) -> None:
        p = self._path(owner, pid)
        if not p.exists():
            raise ProjectError("Project not found.")
        p.unlink()

    def duplicate(self, owner: str, pid: str, name: str | None = None) -> dict:
        rec = self.get(owner, pid)
        return self.save(owner, name or f"{rec['name']} (copy)", rec["project"])

    def referenced_assets(self) -> set[str]:
        """Asset ids used by any saved project (so cleanup keeps them)."""
        keep: set[str] = set()
        for f in self.root.glob("*/*.json"):
            try:
                keep.update(HEX32.findall(f.read_text(encoding="utf-8")))
            except OSError:
                pass
        return keep

    def cleanup(self, max_age_days: int = 180) -> None:
        cutoff = time.time() - max_age_days * 86400
        for f in self.root.glob("*/*.json"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------------ bundles (project + media in one zip)
    def export_bundle(self, owner: str, pid: str, assets) -> bytes:
        rec = self.get(owner, pid)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("project.json", json.dumps({"format": "voiceforge-project", "version": 2, "name": rec["name"],
                                                    "project": rec["project"]}, ensure_ascii=False))
            for aid in asset_ids(rec["project"]):
                path, meta = assets.path(aid), assets.meta(aid)
                if path and meta:
                    z.write(path, f"assets/{aid}{path.suffix}")
                    z.writestr(f"assets/{aid}.meta.json", json.dumps({"name": meta.get("name"), "kind": meta.get("kind")}))
        return buf.getvalue()

    def import_bundle(self, owner: str, data: bytes, assets) -> dict:
        """Import a .zip bundle or a plain project .json. Media in a bundle is stored under new ids."""
        if len(data) > MAX_BUNDLE_BYTES:
            raise ProjectError("File is too large.")
        if data[:2] == b"PK":
            try:
                z = zipfile.ZipFile(io.BytesIO(data))
            except zipfile.BadZipFile:
                raise ProjectError("That file is not a valid project bundle.")
            if sum(i.file_size for i in z.infolist()) > MAX_BUNDLE_BYTES or len(z.infolist()) > 500:
                raise ProjectError("The bundle is too large.")
            try:
                doc = json.loads(z.read("project.json").decode("utf-8"))
            except (KeyError, ValueError):
                raise ProjectError("The bundle has no project.json.")
            mapping: dict[str, str | None] = {}
            for info in z.infolist():
                m = re.fullmatch(r"assets/([0-9a-f]{32})(\.[A-Za-z0-9]{1,5})", info.filename)
                if not m:
                    continue
                old = m.group(1)
                try:
                    meta = json.loads(z.read(f"assets/{old}.meta.json").decode("utf-8"))
                except (KeyError, ValueError):
                    meta = {}
                try:
                    mapping[old] = assets.save(z.read(info), meta.get("name") or f"{old}{m.group(2)}")["id"]
                except ValueError:
                    mapping[old] = None
        else:
            try:
                doc = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise ProjectError("That file is not a Voxa project.")
            mapping = {}
        project = doc.get("project") if isinstance(doc, dict) and "project" in doc else doc
        if not isinstance(project, dict) or not isinstance(project.get("scenes"), list):
            raise ProjectError("That file is not a Voxa project.")
        for aid in asset_ids(project):          # references to files we do not have are dropped
            if aid not in mapping:
                mapping[aid] = aid if assets.path(aid) else None
        project = remap_assets(project, mapping)
        return self.save(owner, (doc.get("name") if isinstance(doc, dict) else None) or "Imported project", project)
