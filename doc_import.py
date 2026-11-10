"""Import a PDF or PowerPoint deck as video scenes (one page/slide -> one scene).

- PDF: each page is rendered to an image (pypdfium2, else poppler's pdftoppm); page text can become narration.
- PPTX/PPT/ODP: converted to PDF with LibreOffice when it is installed (exact look), and speaker
  notes become narration. Without LibreOffice, .pptx falls back to python-pptx: slide title,
  bullet text and the largest picture are turned into an editable scene.

import_document(data, filename, assets, narration="notes|text|none", max_pages=N) -> {"scenes", "assets", "pages", "method"}
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

import video

MAX_DOC_BYTES = 100 * 1024 * 1024
RENDER_LONG_SIDE = 2560          # sharp enough for 1440p; 4K upscales a little
DEFAULT_SECONDS = 5.0
NARRATION_MODES = ("notes", "text", "none")
PDF_EXT = {".pdf"}
DECK_EXT = {".pptx", ".ppt", ".odp", ".key", ".pps", ".ppsx"}
WORD_EXT = {".docx", ".doc", ".odt", ".rtf", ".txt"}
SHEET_EXT = {".xlsx", ".xls", ".ods", ".csv"}
OFFICE_EXT = DECK_EXT | WORD_EXT | SHEET_EXT          # converted to PDF pages with LibreOffice
SUPPORTED = sorted(PDF_EXT | OFFICE_EXT)


class ImportError_(video.VideoError):
    pass


def _clean(text: str, limit: int) -> str:
    text = re.sub(r"[ \t ]+", " ", (text or "").replace("\r", "\n"))
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    text = re.sub(r"-\n(?=\w)", "", text)
    if len(text) > limit:
        cut = text[:limit]
        text = cut[: max(cut.rfind(". "), cut.rfind("\n"), limit // 2) + 1].strip()
    return text


def _soffice() -> str | None:
    env = os.environ.get("VF_SOFFICE")                 # e.g. a portable LibreOffice installed without root
    if env and Path(env).exists():
        return env
    return shutil.which("soffice") or shutil.which("libreoffice")


def _png(img: Image.Image) -> bytes:
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    w, h = img.size
    s = RENDER_LONG_SIDE / max(w, h)
    if s < 1:
        img = img.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ---------------- PDF ----------------
def pdf_pages(pdf: bytes, max_pages: int) -> tuple[list[bytes], list[str], int]:
    """-> (png per page, text per page, total page count)."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        pdfium = None
    if pdfium is not None:
        try:
            doc = pdfium.PdfDocument(pdf)
        except Exception as exc:  # noqa: BLE001
            raise ImportError_("That PDF could not be opened (damaged or password-protected).") from exc
        total = len(doc)
        imgs, texts = [], []
        for i in range(min(total, max_pages)):
            page = doc[i]
            w, h = page.get_size()
            scale = RENDER_LONG_SIDE / max(w, h, 1)
            imgs.append(_png(page.render(scale=scale).to_pil()))
            try:
                texts.append(page.get_textpage().get_text_range())
            except Exception:  # noqa: BLE001
                texts.append("")
        doc.close()
        return imgs, texts, total
    if not shutil.which("pdftoppm"):
        raise ImportError_("PDF import needs the 'pypdfium2' package (pip install pypdfium2).")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in.pdf"
        src.write_bytes(pdf)
        info = subprocess.run(["pdfinfo", str(src)], capture_output=True, text=True, timeout=60) if shutil.which("pdfinfo") else None
        m = re.search(r"Pages:\s+(\d+)", info.stdout) if info else None
        total = int(m.group(1)) if m else max_pages
        n = min(total, max_pages)
        r = subprocess.run(["pdftoppm", "-png", "-scale-to", str(RENDER_LONG_SIDE), "-f", "1", "-l", str(n), str(src), str(Path(td) / "p")],
                           capture_output=True, timeout=600)
        files = sorted(Path(td).glob("p-*.png"), key=lambda p: int(re.findall(r"(\d+)\.png$", p.name)[0]))
        if r.returncode or not files:
            raise ImportError_("That PDF could not be rendered.")
        imgs = [_png(Image.open(f)) for f in files]
        texts = []
        for i in range(1, len(files) + 1):
            t = subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), str(src), "-"], capture_output=True, text=True, timeout=60) \
                if shutil.which("pdftotext") else None
            texts.append(t.stdout if t and t.returncode == 0 else "")
        return imgs, texts, total


# ---------------- PowerPoint ----------------
def pptx_notes_titles(data: bytes) -> tuple[list[str], list[str]]:
    try:
        from pptx import Presentation
        prs = Presentation(io.BytesIO(data))
    except Exception:  # noqa: BLE001
        return [], []
    notes, titles = [], []
    for slide in prs.slides:
        n = ""
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            n = slide.notes_slide.notes_text_frame.text
        notes.append(n)
        t = slide.shapes.title.text if slide.shapes.title is not None and slide.shapes.title.has_text_frame else ""
        titles.append(t)
    return notes, titles


def deck_to_pdf(data: bytes, ext: str) -> bytes:
    exe = _soffice()
    if not exe:
        raise ImportError_("Converting this file needs LibreOffice on the server.")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"deck{ext}"
        src.write_bytes(data)
        prof = Path(td) / "profile"
        try:
            subprocess.run([exe, f"-env:UserInstallation=file://{prof}", "--headless", "--convert-to", "pdf", "--outdir", td, str(src)],
                           capture_output=True, timeout=300)
        except subprocess.TimeoutExpired as exc:
            raise ImportError_("Converting the presentation took too long.") from exc
        out = Path(td) / "deck.pdf"
        if not out.exists():
            raise ImportError_("The presentation could not be converted. Try exporting it as PDF first.")
        return out.read_bytes()


def pptx_editable(data: bytes, max_pages: int):
    """Fallback without LibreOffice: -> list of (title, body, notes, picture_bytes|None), total slides."""
    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        prs = Presentation(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ImportError_("That PowerPoint file could not be opened.") from exc
    slides = list(prs.slides)
    out = []
    for slide in slides[:max_pages]:
        title_shape = slide.shapes.title
        title = title_shape.text if title_shape is not None and title_shape.has_text_frame else ""
        lines, best, best_area = [], None, 0
        title_id = title_shape.shape_id if title_shape is not None else None
        for sh in slide.shapes:
            if sh.shape_id == title_id:
                continue
            if sh.has_text_frame:
                for p in sh.text_frame.paragraphs:
                    t = "".join(r.text for r in p.runs).strip()
                    if t:
                        lines.append(t)
            if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                area = int(sh.width or 0) * int(sh.height or 0)
                if area > best_area:
                    try:
                        best, best_area = sh.image.blob, area
                    except Exception:  # noqa: BLE001
                        pass
        notes = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None else ""
        out.append((title, "\n".join(lines), notes, best))
    return out, len(slides)


# ---------------- main entry ----------------
def import_document(data: bytes, filename: str, assets: "video.AssetStore", narration: str = "notes",
                    max_pages: int | None = None, keep_layout: bool = True) -> dict:
    ext = Path(filename or "").suffix.lower()
    if ext not in PDF_EXT | OFFICE_EXT:
        raise ImportError_("Unsupported file. Import a PDF, PowerPoint, Word or Excel file.")
    if not data:
        raise ImportError_("The file is empty.")
    if len(data) > MAX_DOC_BYTES:
        raise ImportError_(f"File is too large (limit {MAX_DOC_BYTES // 1024 // 1024} MB).")
    if narration not in NARRATION_MODES:
        narration = "notes"
    L = video.LIMITS
    max_pages = max(1, min(max_pages or L["max_scenes"], L["max_scenes"]))
    max_narr, max_title = L["max_narration"], L["max_title"]
    stem = re.sub(r"[^\w\- ]+", "_", Path(filename).stem)[:40] or "slides"

    notes, titles, method = [], [], "pdf"
    if ext in OFFICE_EXT:
        if ext in (".pptx", ".ppsx"):
            notes, titles = pptx_notes_titles(data)
        if _soffice():
            pdf, method = deck_to_pdf(data, ext), "libreoffice"
        elif ext in (".pptx", ".ppsx"):
            return _editable_import(data, stem, assets, narration, max_pages, max_narr, max_title)
        elif ext in (".docx", ".txt"):
            return _text_import(data, ext, stem, narration, max_pages, max_narr, max_title)
        else:
            raise ImportError_("This file type needs LibreOffice on the server. Save it as PDF (or .pptx / .docx) and try again.")
    else:
        pdf = data

    imgs, texts, total = pdf_pages(pdf, max_pages)
    if not imgs:
        raise ImportError_("No pages found in that document.")
    scenes, saved = [], []
    try:
        for i, png in enumerate(imgs):
            meta = assets.save(png, f"{stem}-{i + 1:02d}.png")
            saved.append(meta)
            if narration == "notes":
                narr = notes[i] if i < len(notes) else ""
                if not narr.strip() and not notes:      # PDFs have no notes: fall back to page text
                    narr = texts[i] if i < len(texts) else ""
            elif narration == "text":
                narr = texts[i] if i < len(texts) else ""
            else:
                narr = ""
            narr = _clean(narr, max_narr)
            scenes.append({"layout": "media", "title": "", "body": "", "narration": narr,
                           "background": {"type": "color", "color": "#000000"} if keep_layout else {"type": "theme"},
                           "media": {"asset": meta["id"], "position": "full", "fit": "contain"},
                           "duration": None if narr else DEFAULT_SECONDS, "transition": "fade",
                           "label": _clean(titles[i] if i < len(titles) else "", max_title) or f"{stem} {i + 1}"})
    except video.VideoError:
        for m in saved:
            assets.delete(m["id"])
        raise
    return {"scenes": scenes, "assets": saved, "pages": total, "imported": len(scenes), "method": method}


def _editable_import(data, stem, assets, narration, max_pages, max_narr, max_title):
    slides, total = pptx_editable(data, max_pages)
    scenes, saved = [], []
    try:
        for i, (title, body, notes, pic) in enumerate(slides):
            media = None
            if pic:
                try:
                    with Image.open(io.BytesIO(pic)) as im:
                        im.load()
                        meta = assets.save(_png(im), f"{stem}-{i + 1:02d}.png")
                    saved.append(meta)
                    media = {"asset": meta["id"], "position": "auto", "fit": "contain"}
                except (OSError, video.VideoError):
                    media = None
            narr = notes if narration == "notes" else (f"{title}. {body}" if narration == "text" else "")
            if narration == "notes" and not notes.strip():
                narr = ""
            narr = _clean(narr, max_narr)
            body_c = _clean(body, video.LIMITS["max_body"])
            layout = "media" if media else ("bullets" if body_c.count("\n") >= 1 else ("text" if body_c else "title"))
            scene = {"layout": layout, "title": _clean(title, max_title), "body": body_c, "narration": narr,
                     "background": {"type": "theme"}, "media": media,
                     "duration": None if narr else DEFAULT_SECONDS, "transition": "fade",
                     "label": _clean(title, max_title) or f"{stem} {i + 1}"}
            if media and body_c and layout == "media":
                scene["layout"] = "bullets" if body_c.count("\n") >= 1 else "text"
            if not (scene["title"] or scene["body"] or media or narr):
                scene["title"] = f"{stem} {i + 1}"
            scenes.append(scene)
    except video.VideoError:
        for m in saved:
            assets.delete(m["id"])
        raise
    return {"scenes": scenes, "assets": saved, "pages": total, "imported": len(scenes), "method": "editable"}


def docx_blocks(data: bytes) -> list[tuple[str, str]]:
    """Minimal .docx reader (no LibreOffice): -> [(style, text)] for each paragraph."""
    import zipfile
    from xml.etree import ElementTree as ET
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            root = ET.fromstring(z.read("word/document.xml"))
    except Exception as exc:  # noqa: BLE001
        raise ImportError_("That Word file could not be opened.") from exc
    out = []
    for p in root.iter(W + "p"):
        style = p.find(f"{W}pPr/{W}pStyle")
        st = (style.get(W + "val") if style is not None else "") or ""
        text = "".join(t.text or "" for t in p.iter(W + "t")).strip()
        if text:
            out.append((st, text))
    return out


def _text_import(data, ext, stem, narration, max_pages, max_narr, max_title):
    """Word/text without LibreOffice: every heading starts a new scene; paragraphs become bullets + narration."""
    if ext == ".txt":
        text = data.decode("utf-8", "replace")
        blocks = []
        for para in re.split(r"\n\s*\n", text):
            lines = [x.strip() for x in para.strip().splitlines() if x.strip()]
            if lines:
                blocks.append(("Heading1" if len(lines) == 1 and len(lines[0]) < 80 else "", lines[0]))
                blocks += [("", x) for x in lines[1:]]
    else:
        blocks = docx_blocks(data)
    if not blocks:
        raise ImportError_("No text found in that document.")
    groups, cur = [], None
    for st, text in blocks:
        heading = bool(re.match(r"(?i)(heading|title|\u0639\u0646\u0648\u0627\u0646)", st))
        if heading or cur is None:
            cur = {"title": text if heading else "", "lines": [] if heading else [text]}
            groups.append(cur)
        else:
            cur["lines"].append(text)
    scenes = []
    for g in groups[:max_pages]:
        body = _clean("\n".join(g["lines"][:8]), video.LIMITS["max_body"])
        narr = _clean(" ".join([g["title"]] + g["lines"]) if narration != "none" else "", max_narr)
        layout = "bullets" if len(g["lines"]) > 1 and all(len(x) < 140 for x in g["lines"][:8]) else ("text" if body else "title")
        scenes.append({"layout": layout, "title": _clean(g["title"], max_title), "body": body if layout != "title" else "",
                       "narration": narr, "background": {"type": "theme"}, "media": None,
                       "duration": None if narr else DEFAULT_SECONDS, "transition": "fade",
                       "label": _clean(g["title"], max_title) or f"{stem} {len(scenes) + 1}"})
    return {"scenes": scenes, "assets": [], "pages": len(groups), "imported": len(scenes), "method": "text"}
