/* App shell: menu bar (File / Edit / View / Help), module tab bar, context ribbon with icons,
   Web / Desktop workspaces, status bar, Video Studio sub-tabs and global shortcuts.
   Ribbon buttons trigger the existing controls, so every feature keeps one implementation. */
(() => {
"use strict";
const VF = window.VF, $ = VF.$, t = VF.t;

/* ---------------- icons (24px line icons) ---------------- */
const P = {
  new: "M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M12 12v6M9 15h6",
  open: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v1H7.5a2 2 0 0 0-1.9 1.4L3 19zM3 19l2.6-7.6A2 2 0 0 1 7.5 10H22l-2.7 7.9a2 2 0 0 1-1.9 1.1z",
  save: "M5 3h11l5 5v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM7 3v6h9V3M7 21v-7h10v7",
  saveas: "M5 3h11l5 5v4M7 3v6h9V3M3 5v14a2 2 0 0 0 2 2h6M18 15l3 3-5 5h-3v-3z",
  download: "M12 3v12M7 10l5 5 5-5M4 21h16",
  upload: "M12 21V9M7 14l5-5 5 5M4 3h16",
  play: "M7 4l13 8-13 8z", pause: "M7 4h4v16H7zM13 4h4v16h-4z", stop: "M6 6h12v12H6z",
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3",
  globe: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18",
  wand: "M15 4V2M15 10V8M11 6h2M17 6h2M5 21l11-11-2-2L3 19zM19 13l1 1M8 3l1 1",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5",
  scissors: "M6 4a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM6 14a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM20 4L8.5 15.5M14.5 12.5L20 20M8.5 8.5L12 12",
  copy: "M9 9h11v11H9zM5 15H4V4h11v1", paste: "M9 4h6v3H9zM8 5H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
  undo: "M9 14L4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3", redo: "M15 14l5-5-5-5M20 9H9a5 5 0 0 0 0 10h3",
  plus: "M12 5v14M5 12h14", image: "M4 5h16v14H4zM4 16l5-5 4 4 3-3 4 4M15 9h.01",
  music: "M9 18V5l11-2v13M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM20 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z",
  volume: "M4 9h4l5-4v14l-5-4H4zM16 9a4 4 0 0 1 0 6M19 6a8 8 0 0 1 0 12",
  text: "M5 6V4h14v2M12 4v16M9 20h6", square: "M5 5h14v14H5z",
  film: "M4 4h16v16H4zM8 4v16M16 4v16M4 8h4M4 12h4M4 16h4M16 8h4M16 12h4M16 16h4",
  layers: "M12 3l9 5-9 5-9-5zM3 13l9 5 9-5M3 17l9 5 9-5", export: "M14 3h7v7M21 3l-9 9M19 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5",
  file: "M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M8 13h8M8 17h5", captions: "M3 6h18v12H3zM7 11h3M7 14h6M13 11h4",
  up: "M12 19V5M6 11l6-6 6 6", down: "M12 5v14M6 13l6 6 6-6", dup: "M8 8h12v12H8zM4 16V4h12",
  sliders: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4",
  monitor: "M3 4h18v12H3zM8 20h8M12 16v4", grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  fadein: "M3 20L21 4M3 20h18", fadeout: "M3 4l18 16M3 20h18", bars: "M5 20V10M10 20V4M15 20v-8M20 20v-5",
  crop: "M6 2v14a2 2 0 0 0 2 2h14M2 6h14a2 2 0 0 1 2 2v14", wave: "M2 12h2l2-6 3 12 3-15 3 18 3-9h4",
  help: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17h.01",
  sun: "M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  doc: "M7 3h8l4 4v14H7zM15 3v4h4", eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
  keyboard: "M3 6h18v12H3zM7 10h.01M11 10h.01M15 10h.01M7 14h10", home: "M3 11l9-8 9 8M5 9v11h5v-6h4v6h5V9",
  maximize: "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5", minimize: "M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5", logo: "M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z",
};
const icon = (n) => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${P[n] || P.plus}"/></svg>`;
const click = (id) => () => { const e = $(id); if (!e) return; if (e.tagName === "INPUT" && e.type === "file") e.click(); else e.click(); };
const view = () => (location.hash || "#voice").slice(1);
let lastVtab = "scenes";
const initialHash = (location.hash || "#home").slice(1);     // read before app.js rewrites the hash

/* ---------------- ribbon definitions ---------------- */
const FILE = [{ i: "new", k: "rb_new", a: click("pNew") }, { i: "open", k: "rb_open", a: click("pOpen") }, { i: "save", k: "rb_save", a: click("pSave"), primary: true },
  { i: "download", k: "rb_download", a: click("pExportZip") }];
const RIBBON = {
  voice: [
    { g: "rg_speech", items: [{ i: "scissors", k: "rb_edit_audio", a: click("editAudioBtn") }] },
    { g: "rg_text", items: [{ i: "globe", k: "rb_translate", a: () => { const d = $("trBox"); d.open = true; $("trLang").focus(); } }, { i: "mic", k: "rb_dictate", a: () => { $("trBox").open = true; $("trMic").click(); } },
      { i: "wand", k: "rb_sample", a: click("sampleBtn") }, { i: "search", k: "rb_detect", a: click("detectBtn") }] },
  ],
  video: [
    { g: "rg_scenes", items: [{ i: "plus", k: "rb_add_scene", a: () => { vtab("scenes"); $("addScene").click(); } }, { i: "dup", k: "rb_duplicate", a: () => { vtab("scenes"); $("sDup").click(); } },
      { i: "trash", k: "rb_delete", a: () => { vtab("scenes"); $("sDel").click(); } }, { i: "up", k: "rb_up", a: click("sUp") }, { i: "down", k: "rb_down", a: click("sDown") }] },
    { g: "rg_insert", items: [{ i: "doc", k: "rb_import_doc", a: click("importDoc") }, { i: "layers", k: "rb_layer", a: () => { vtab("scenes"); $("layerBox").open = true; $("addLayer").click(); } },
      { i: "music", k: "rb_music", a: click("musicLib") }, { i: "mic", k: "rb_voiceover", a: () => { vtab("scenes"); $("voBox").open = true; $("voBox").scrollIntoView({ block: "center" }); } }] },
    { g: "rg_output", items: [{ i: "export", k: "rb_to_timeline", a: () => { VF.showView("timeline"); setTimeout(() => window.VFTimeline && VFTimeline.fromScenes(), 50); } }] },
  ],
  timeline: [
    { g: "rg_edit", items: [{ i: "play", k: "rb_play", a: () => VFTimeline.play(), primary: true }, { i: "scissors", k: "tl_split", a: () => VFTimeline.split() }, { i: "dup", k: "rb_duplicate", a: () => VFTimeline.dup() },
      { i: "trash", k: "rb_delete", a: () => VFTimeline.del() }, { i: "undo", k: "rb_undo", a: () => VFTimeline.undo() }, { i: "redo", k: "rb_redo", a: () => VFTimeline.redo() }] },
    { g: "rg_insert", items: [{ i: "film", k: "rb_media", a: click("tlAddMedia") }, { i: "image", k: "lt_photos", a: click("tlAddPhoto") }, { i: "layers", k: "rb_layer", a: click("tlAddOverlay") },
      { i: "text", k: "tl_text", a: click("tlAddText") }, { i: "square", k: "tl_color", a: click("tlAddColor") }, { i: "music", k: "rb_music", a: click("tlAddMusic") },
      { i: "volume", k: "rb_sfx", a: click("tlAddSfx") }, { i: "mic", k: "rb_record", a: click("tlRec") }, { i: "upload", k: "rb_from_scenes", a: click("tlFromScenes") }] },
  ],
  stt: [
    { g: "rg_listen", items: [{ i: "trash", k: "rb_clear", a: click("sttClear") }] },
    { g: "rg_text", items: [{ i: "copy", k: "rb_copy", a: click("sttCopy") }, { i: "file", k: "rb_txt", a: click("sttTxt") }, { i: "captions", k: "rb_srt", a: click("sttSrt") },
      { i: "globe", k: "rb_translate", a: click("sttTrBtn") }, { i: "volume", k: "rb_to_tts", a: click("sttToTts") }] },
    { g: "rg_recording", items: [{ i: "scissors", k: "rb_edit_audio", a: click("sttEdit") }, { i: "save", k: "rb_save_lib", a: click("sttSave") }] },
  ],
  audio: [
    { g: "rg_file", items: [{ i: "grid", k: "rb_from_lib", a: click("aeLib") }, { i: "mic", k: "rb_record", a: click("aeRec") }] },
    { g: "rg_play", items: [{ i: "play", k: "rb_play", a: click("aePlay"), primary: true }, { i: "undo", k: "rb_undo", a: click("aeUndo") }, { i: "redo", k: "rb_redo", a: click("aeRedo") }] },
    { g: "rg_edit", items: [{ i: "scissors", k: "rb_cut", a: click("ae_cut") }, { i: "copy", k: "rb_copy", a: click("ae_copy") }, { i: "paste", k: "rb_paste", a: click("ae_paste") },
      { i: "trash", k: "rb_delete", a: click("ae_delete") }, { i: "crop", k: "rb_trim", a: click("ae_trim") }] },
    { g: "rg_effects", items: [{ i: "fadein", k: "ae_fadein", a: click("ae_fadein") }, { i: "fadeout", k: "ae_fadeout", a: click("ae_fadeout") }, { i: "bars", k: "ae_normalize", a: click("ae_normalize") },
      { i: "wand", k: "rb_fx", a: () => { $("aeFx").focus(); $("aeFx").scrollIntoView({ block: "center" }); } }] },
    { g: "rg_output", items: [{ i: "download", k: "rb_export_wav", a: click("aeWav") }, { i: "save", k: "rb_save_lib", a: click("aeSave") }] },
  ],
};
function drawRibbon() {
  const r = $("ribbon"); r.innerHTML = "";
  (RIBBON[view()] || []).forEach((grp) => {
    const g = document.createElement("div"); g.className = "rgroup";
    const items = document.createDocumentFragment();
    grp.items.forEach((it) => { const b = document.createElement("button"); b.className = "rbtn" + (it.primary ? " primary" : ""); b.type = "button";
      b.innerHTML = icon(it.i) + "<span></span>"; b.lastChild.textContent = t(it.k); b.title = t(it.k);
      b.onclick = () => { try { it.a(); } catch (e) { console.error(e); } }; items.appendChild(b); });
    g.title = t(grp.g); g.appendChild(items); r.appendChild(g);
  });
}

/* ---------------- menus ---------------- */
const THEMES = ["daylight", "paper", "mint", "sky", "midnight", "ocean", "sunset", "forest"];
function primaryExport() { return { voice: "exportBtn", video: "renderBtn", timeline: "tlExport", stt: "sttTxt", audio: "aeMp3" }[view()]; }
const MENUS = {
  file: () => [["new", "rb_new", click("pNew")], ["open", "rb_open", click("pOpen")], ["save", "rb_save_k", click("pSave")], ["saveas", "rb_saveas", click("pSaveAs")],
    ["dup", "rb_duplicate_project", click("pDup")], "-", ["download", "rb_download_zip", click("pExportZip")], ["file", "rb_download_json", click("pExportJson")],
    ["upload", "rb_import_project", click("pImportFile")], "-", ["export", "rb_export_current", () => { if (view() === "video") vtab("export"); click(primaryExport())(); }], "-",
    ["trash", "rb_delete_project", click("pDelete")]],
  edit: () => view() === "timeline" ? [["undo", "rb_undo", () => VFTimeline.undo()], ["redo", "rb_redo", () => VFTimeline.redo()], "-", ["scissors", "tl_split", () => VFTimeline.split()],
      ["dup", "rb_duplicate", () => VFTimeline.dup()], ["trash", "rb_delete", () => VFTimeline.del()]]
    : view() === "audio" ? [["undo", "rb_undo", click("aeUndo")], ["redo", "rb_redo", click("aeRedo")], "-", ["scissors", "rb_cut", click("ae_cut")], ["copy", "rb_copy", click("ae_copy")],
      ["paste", "rb_paste", click("ae_paste")], ["trash", "rb_delete", click("ae_delete")]]
    : view() === "video" ? [["plus", "rb_add_scene", click("addScene")], ["dup", "rb_duplicate", click("sDup")], ["trash", "rb_delete", click("sDel")]]
    : [["copy", "rb_copy", () => document.execCommand("copy")], ["paste", "rb_paste", () => navigator.clipboard && navigator.clipboard.readText().then((x) => document.execCommand("insertText", false, x))]],
  view: () => [["maximize", "rb_maximize", () => toggleFull(), isFull()], ["home", "sn_home", () => setRoute("home")], "-",
    ...THEMES.map((k) => ["sun", "th_" + k, () => document.querySelector(`.tdot[data-t=${k}]`).click(), document.documentElement.dataset.theme === k]), "-",
    ["globe", "rb_language", click("langBtn")]],
  help: () => [["keyboard", "rb_shortcuts", shortcuts], ["help", "rb_guide", () => { setRoute("home"); setTimeout(() => $("guide").scrollIntoView({ behavior: "smooth" }), 80); }],
    ["doc", "rb_about", () => { setRoute("home"); setTimeout(() => $("about").scrollIntoView({ behavior: "smooth" }), 80); }]],
};
function openMenu(name, btn) {
  closeMenus(); const drop = document.createElement("div"); drop.className = "mdrop"; drop.id = "mdrop";
  MENUS[name]().forEach((it) => {
    if (it === "-") { drop.appendChild(Object.assign(document.createElement("hr"))); return; }
    const [ic, key, fn, checked] = it; const b = document.createElement("button"); b.type = "button"; b.innerHTML = icon(ic) + "<span></span>" + (checked ? "<em>✓</em>" : "");
    b.children[1].textContent = t(key); b.onclick = () => { closeMenus(); fn(); }; drop.appendChild(b);
  });
  const r = btn.getBoundingClientRect(); drop.style.top = r.bottom + 4 + "px";
  if (document.documentElement.dir === "rtl") drop.style.right = (innerWidth - r.right) + "px"; else drop.style.left = r.left + "px";
  document.body.appendChild(drop); btn.classList.add("on");
}
function closeMenus() { const d = $("mdrop"); if (d) d.remove(); document.querySelectorAll(".mbtn.on").forEach((b) => b.classList.remove("on")); }
document.querySelectorAll(".mbtn[data-menu]").forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); const open = b.classList.contains("on"); closeMenus(); if (!open) openMenu(b.dataset.menu, b); }));
document.addEventListener("click", (e) => { if (!e.target.closest("#mdrop")) closeMenus(); });
addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenus(); });

function shortcuts() {
  const rows = [["Ctrl+S", "rb_save"], ["Space", "rb_play"], ["S", "tl_split"], ["Delete", "rb_delete"], ["Ctrl+Z / Ctrl+Y", "rb_undo"], ["Ctrl+D", "rb_duplicate"],
    ["Ctrl+X / C / V", "rb_cut"], ["← →", "rb_seek"], ["Ctrl + scroll", "rb_zoom"]];
  const box = document.createElement("table"); rows.forEach(([k, l]) => { const tr = document.createElement("tr"); tr.innerHTML = "<td><kbd></kbd></td><td></td>"; tr.querySelector("kbd").textContent = k; tr.children[1].textContent = t(l); box.appendChild(tr); });
  VF.openModal(t("rb_shortcuts"), box);
}

/* ---------------- home page vs. app, full screen ---------------- */
const APP_VIEWS = ["voice", "video", "timeline", "stt", "audio"];
function setRoute(route) {
  document.documentElement.dataset.route = route;
  if (route === "home") { try { history.replaceState(null, "", "#home"); } catch (_) {} document.title = "Voxa — " + t("home_title"); window.scrollTo(0, 0); }
  else document.title = "Voxa — " + t("home_title");
  setTimeout(() => dispatchEvent(new Event("resize")), 50);
}
function openApp(v) { setRoute("app"); VF.showView(v || "voice"); }
$("goHome").onclick = (e) => { e.preventDefault(); setRoute("home"); };
$("navHome").onclick = () => setRoute("home");
document.querySelectorAll("[data-open]").forEach((b) => (b.onclick = () => openApp(b.dataset.open)));
$("openApp").onclick = () => openApp(view() === "home" ? "voice" : view());
document.querySelectorAll(".feat[data-go], nav [data-go]").forEach((el) => el.addEventListener("click", (e) => { e.preventDefault(); e.stopImmediatePropagation(); openApp(el.dataset.go); }, true));
addEventListener("hashchange", () => { const h = view(); if (APP_VIEWS.includes(h)) { if (document.documentElement.dataset.route !== "app") setRoute("app"); } else if (h === "home" || h === "") setRoute("home"); });
function isFull() { return !!(document.fullscreenElement || document.webkitFullscreenElement); }
function toggleFull(el) {
  if (isFull()) return (document.exitFullscreen || document.webkitExitFullscreen).call(document);
  const target = el || $("studio"); const req = target.requestFullscreen || target.webkitRequestFullscreen;
  if (req) req.call(target).catch(() => VF.toast(t("full_fail"), true)); else VF.toast(t("full_fail"), true);
}
$("maxBtn").onclick = () => toggleFull();
$("appLang").onclick = () => $("langBtn").click();
document.addEventListener("fullscreenchange", () => { $("maxBtn").innerHTML = icon(isFull() ? "minimize" : "maximize"); $("maxBtn").title = t(isFull() ? "rb_restore" : "rb_maximize"); dispatchEvent(new Event("resize")); });
// full-screen buttons on every preview area
function addMax(host) { if (!host || host.querySelector(":scope > .pmax")) return; const b = document.createElement("button"); b.className = "pmax"; b.type = "button";
  b.innerHTML = icon("maximize"); b.title = t("rb_maximize"); b.onclick = (e) => { e.stopPropagation(); toggleFull(host); }; host.style.position = host.style.position || "relative"; host.appendChild(b); }
window.VFShell = { addMax, toggleFull, openApp, setRoute };

/* ---------------- Video Studio sub-tabs ---------------- */
function vtab(name) {
  if (name === "timeline") { if (view() !== "timeline") VF.showView("timeline"); markTabs("timeline"); return; }
  lastVtab = name;
  if (view() !== "video") VF.showView("video");
  markTabs(name);
  document.querySelectorAll("#viewVideo [data-vtab]").forEach((c) => (c.style.display = c.dataset.vtab === name ? "" : "none"));
  if (name === "scenes") VF.schedulePreview();
}
function markTabs(name) { document.querySelectorAll("#vTabs .stab").forEach((b) => b.classList.toggle("on", b.dataset.vt === name)); }
document.querySelectorAll("#vTabs .stab").forEach((b) => (b.onclick = () => { if (b.dataset.vt !== "timeline") lastVtab = b.dataset.vt; vtab(b.dataset.vt); }));
Object.assign(window.VFShell, { vtab });

/* ---------------- document title + status ---------------- */
function syncTitle() { $("docTitle").value = $("pName").value; $("docStatus").textContent = $("pStatus").textContent;
  $("sbProject").textContent = ($("pName").value || t("untitled")) + " · " + $("pStatus").textContent; }
$("docTitle").addEventListener("input", (e) => { $("pName").value = e.target.value; $("pName").dispatchEvent(new Event("input")); });
new MutationObserver(syncTitle).observe($("pStatus"), { childList: true, characterData: true, subtree: true, attributes: true });

/* ---------------- shortcuts ---------------- */
addEventListener("keydown", (e) => {
  const mod = e.ctrlKey || e.metaKey, k = e.key.toLowerCase();
  if (mod && k === "s") { e.preventDefault(); $("pSave").click(); }
  else if (mod && k === "o") { e.preventDefault(); $("pOpen").click(); }
});

const HEAD = {   // [icon, label, action, primary]
  voice: [["play", "rb_preview", click("previewBtn")], ["download", "rb_export_mp3", click("exportBtn"), true]],
  video: [["new", "rb_new", click("pNew")], ["open", "rb_open", click("pOpen")], ["save", "rb_save", click("pSave")], ["play", "rb_play_preview", click("vPlayAll")],
    ["film", "rb_export_video", () => { vtab("export"); $("renderBtn").scrollIntoView({ block: "center" }); }, true]],
  timeline: [["new", "rb_new", click("pNew")], ["open", "rb_open", click("pOpen")], ["save", "rb_save", click("pSave")], ["film", "rb_export_mp4", click("tlExport"), true]],
  stt: [["mic", "rb_listen", click("sttBtn"), true], ["file", "rb_txt", click("sttTxt")]],
  audio: [["open", "rb_import_sound", click("aeFile")], ["download", "rb_export_mp3", click("aeMp3"), true]],
};
function drawHead() {
  const box = $("hactions"); box.innerHTML = "";
  (HEAD[view()] || []).forEach(([ic, k, fn, primary]) => { const b = document.createElement("button"); b.className = "hbtn" + (primary ? " primary" : ""); b.type = "button";
    b.innerHTML = icon(ic) + "<span></span>"; b.lastChild.textContent = t(k); b.title = t(k); b.onclick = () => fn(); box.appendChild(b); });
  $("maxBtn").innerHTML = icon(isFull() ? "minimize" : "maximize"); $("maxBtn").title = t(isFull() ? "rb_restore" : "rb_maximize");
  document.querySelectorAll(".snav .si[data-ic]").forEach((e) => { if (!e.firstChild) e.innerHTML = icon(e.dataset.ic); });
  const mod = view() === "timeline" ? "video" : view();
  document.documentElement.dataset.module = mod;
  $("tabVideo").classList.toggle("on", mod === "video");
  if (view() === "timeline") markTabs("timeline"); else if (view() === "video") markTabs(lastVtab);
}
function refresh() { $("appLang").textContent = VF.ui === "ar" ? "EN" : "ع"; drawRibbon(); drawHead(); syncTitle(); $("sbBuild").textContent = $("buildInfo").textContent; }
VF.on("view", () => { drawRibbon(); drawHead(); });
VF.on("ui", () => { refresh(); });
VF.on("ready", () => {
  if (APP_VIEWS.includes(initialHash)) { setRoute("app"); VF.showView(initialHash); } else setRoute("home");
  vtab_init(); refresh(); setTimeout(refresh, 800);
  addMax($("pWrap")); addMax($("tlStageWrap"));
});
function vtab_init() { document.querySelectorAll("#viewVideo [data-vtab]").forEach((c) => (c.style.display = c.dataset.vtab === "scenes" ? "" : "none")); }
VF.on("project", syncTitle);
})();
