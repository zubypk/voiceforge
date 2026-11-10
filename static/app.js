(() => {
"use strict";
const $ = (id) => document.getElementById(id);
const I18N = window.I18N;
let ui = "en", catalog = { languages: [], voices: [], samples: {}, limits: {} }, cfg = null, config = {};
const t = (k) => (I18N[ui][k] !== undefined ? I18N[ui][k] : I18N.en[k] !== undefined ? I18N.en[k] : k);
const tf = (k, ...a) => { const v = t(k); return typeof v === "function" ? v(...a) : v; };
const RTL_LANGS = /^(ar|ur|fa|he|ps|sd|ug)/;
const isRtlLang = (c) => RTL_LANGS.test(c || "");
const LEGACY = { "youtube-1080": ["16:9", "1080"], "youtube-720": ["16:9", "720"], shorts: ["9:16", "1080"], square: ["1:1", "1080"], portrait: ["4:5", "1080"], classroom: ["4:3", "1080"] };

/* ================= small helpers ================= */
const fmtTime = (s) => (isFinite(s) ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}` : "0:00");
const fmtBytes = (n) => (n >= 1048576 ? (n / 1048576).toFixed(n >= 10485760 ? 0 : 1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB");
const clone = (o) => JSON.parse(JSON.stringify(o));
let toastTimer;
function toast(msg, isErr = false) {
  const el = $("toast"); el.textContent = msg; el.className = "toast on" + (isErr ? " err" : "");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (el.className = "toast"), isErr ? 6000 : 2600);
}
async function errOf(res) {
  let d = {}; try { d = await res.json(); } catch (_) {}
  return d.login_required ? t("login_needed") : d.error || `Request failed (${res.status})`;
}
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(await errOf(res));
  return res;
}
const postJson = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

let modalResolve = null;
function openModal(title, node, onClose) {
  $("mTitle").textContent = title; const b = $("mBody"); b.innerHTML = ""; b.appendChild(node);
  $("modal").classList.add("on"); $("modal")._onClose = onClose || null;
}
function closeModal() { const m = $("modal"); m.classList.remove("on"); const f = m._onClose; m._onClose = null; if (f) f(); }
$("mClose").onclick = closeModal;
$("modal").addEventListener("mousedown", (e) => { if (e.target === $("modal")) closeModal(); });
addEventListener("keydown", (e) => { if (e.key === "Escape" && $("modal").classList.contains("on")) closeModal(); });

/* ================= language / script helpers ================= */
const familyOf = (label) => label.split(" (")[0];
const regionOf = (label) => { const m = label.match(/\((.*)\)/); return m ? m[1] : label; };
const langLabel = (code) => { const l = catalog.languages.find((x) => x.code === code); return l ? familyOf(l.label) : code; };
const sampleFor = (code) => catalog.samples[(code || "en").split("-")[0]] || catalog.samples.en || "";

function fillLanguages(sel, selected) {
  sel.innerHTML = ""; const groups = {};
  catalog.languages.forEach((l) => (groups[familyOf(l.label)] = groups[familyOf(l.label)] || []).push(l));
  Object.entries(groups).forEach(([fam, list]) => {
    const parent = list.length > 1 ? Object.assign(document.createElement("optgroup"), { label: fam }) : sel;
    list.forEach((l) => { const o = document.createElement("option"); o.value = l.code; o.textContent = list.length > 1 ? regionOf(l.label) : l.label; parent.appendChild(o); });
    if (parent !== sel) sel.appendChild(parent);
  });
  sel.value = selected;
}
function fillVoices(sel, lang, gender, selected) {
  const list = catalog.voices.filter((v) => v.language === lang && v.gender === gender);
  const use = list.length ? list : catalog.voices.filter((v) => v.language === lang);
  sel.innerHTML = "";
  use.forEach((v) => { const o = document.createElement("option"); o.value = v.id; o.textContent = v.name + (list.length ? "" : ` (${v.gender})`); sel.appendChild(o); });
  if (selected && use.some((v) => v.id === selected)) sel.value = selected;
  return use;
}
function genderBtns(root, onPick) { root.querySelectorAll("button").forEach((b) => (b.onclick = () => { setGenderUI(root, b.dataset.g); onPick(b.dataset.g); })); }
function setGenderUI(root, g) { root.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x.dataset.g === g)); }

const SCRIPTS = {
  arabic: /[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]/g, hebrew: /[֐-׿]/g, devanagari: /[ऀ-ॿ]/g,
  bengali: /[ঀ-৿]/g, gujarati: /[઀-૿]/g, tamil: /[஀-௿]/g, telugu: /[ఀ-౿]/g, kannada: /[ಀ-೿]/g,
  malayalam: /[ഀ-ൿ]/g, sinhala: /[඀-෿]/g, thai: /[฀-๿]/g, lao: /[຀-໿]/g, myanmar: /[က-႟]/g,
  khmer: /[ក-៿]/g, georgian: /[Ⴀ-ჿ]/g, ethiopic: /[ሀ-፿]/g, hangul: /[가-힯ᄀ-ᇿ]/g,
  kana: /[぀-ヿ]/g, han: /[一-鿿]/g, cyrillic: /[Ѐ-ӿ]/g, greek: /[Ͱ-Ͽ]/g, latin: /[A-Za-zÀ-ɏ]/g,
};
const LANG_SCRIPT = { ar: "arabic", ur: "arabic", fa: "arabic", ps: "arabic", he: "hebrew", hi: "devanagari", mr: "devanagari", ne: "devanagari", bn: "bengali",
  gu: "gujarati", ta: "tamil", te: "telugu", kn: "kannada", ml: "malayalam", si: "sinhala", th: "thai", lo: "lao", my: "myanmar", km: "khmer", ka: "georgian",
  am: "ethiopic", ko: "hangul", ja: "kana|han", zh: "han", ru: "cyrillic", uk: "cyrillic", bg: "cyrillic", mk: "cyrillic", sr: "cyrillic|latin", kk: "cyrillic|latin",
  mn: "cyrillic", el: "greek", uz: "latin|cyrillic", az: "latin|cyrillic" };
const SCRIPT_LOCALE = { hebrew: "he-IL", devanagari: "hi-IN", bengali: "bn-IN", gujarati: "gu-IN", tamil: "ta-IN", telugu: "te-IN", kannada: "kn-IN", malayalam: "ml-IN",
  sinhala: "si-LK", thai: "th-TH", lao: "lo-LA", myanmar: "my-MM", khmer: "km-KH", georgian: "ka-GE", ethiopic: "am-ET", hangul: "ko-KR", kana: "ja-JP", han: "zh-CN", greek: "el-GR" };
function dominantScript(text) {
  let best = null, bestN = 0, total = 0;
  for (const [name, re] of Object.entries(SCRIPTS)) { const n = (text.match(re) || []).length; total += n; if (n > bestN) { best = name; bestN = n; } }
  return total >= 3 && bestN / total >= 0.5 ? best : null;   // need a few letters, mostly one script
}
function mismatch(text, localeCode) {
  const found = dominantScript(text || ""); if (!found || found === "latin") return null;   // Latin text is read by any voice
  const expected = (LANG_SCRIPT[(localeCode || "").split("-")[0]] || "latin").split("|");
  return expected.includes(found) ? null : { found };
}
function hasLocale(code) { return catalog.languages.some((l) => l.code === code); }
function suggestLocale(text, current) {
  const found = dominantScript(text || ""); if (!found) return null;
  let code = null;
  if (found === "arabic") code = /[ٹڈڑںے]/.test(text) ? "ur-PK" : (current || "").startsWith("ar-") ? current : "ar-SA";
  else if (found === "cyrillic") code = /[іїєґ]/i.test(text) ? "uk-UA" : "ru-RU";
  else if (found === "latin") { const exp = (LANG_SCRIPT[(current || "").split("-")[0]] || "latin"); code = exp === "latin" ? current : "en-US"; }
  else code = SCRIPT_LOCALE[found];
  return code && hasLocale(code) ? code : null;
}
const scriptName = (s) => (t("scripts") || {})[s] || s;

/* ================= VOICE TAB ================= */
const els = { language: $("language"), voice: $("voice"), text: $("text"), rate: $("rate"), pitch: $("pitch"), rateVal: $("rateVal"), pitchVal: $("pitchVal"),
  preview: $("previewBtn"), exp: $("exportBtn"), play: $("playBtn"), status: $("status"), count: $("count"), time: $("time"), audio: $("audio"), wave: $("wave") };
let gender = "female", peaks = null, audioUrl = null, busy = false, statusKey = null;
function setStatus(msg, cls = "") { els.status.textContent = msg; els.status.className = "status " + cls; }
function refreshVoice() { fillVoices(els.voice, els.language.value, gender, els.voice.value); }
function updateCount() {
  const n = els.text.value.length, lim = catalog.limits.max_text_chars;
  els.count.textContent = tf("chars", n, lim) + " · " + tf("mins", n / 900);
}
function updateTextWarn() {
  const m = mismatch(els.text.value, els.language.value), box = $("textWarn");
  box.style.display = m ? "block" : "none";
  if (m) $("textWarnMsg").textContent = tf("mismatch_body", scriptName(m.found), langLabel(els.language.value));
}
const isSample = (txt) => !txt.trim() || Object.values(catalog.samples).includes(txt.trim());
function onLanguageChange() {
  refreshVoice();
  if (isSample(els.text.value)) els.text.value = sampleFor(els.language.value);
  els.text.dir = "auto"; updateCount(); updateTextWarn();
}
els.language.onchange = onLanguageChange;
genderBtns($("gender"), (g) => { gender = g; refreshVoice(); });
$("fixVoice").onclick = () => {
  const code = suggestLocale(els.text.value, els.language.value);
  if (code) { els.language.value = code; refreshVoice(); toast(tf("detected", langLabel(code))); updateTextWarn(); } else toast(t("nothing_detected"), true);
};
$("fixText").onclick = () => { els.text.value = sampleFor(els.language.value); updateCount(); updateTextWarn(); };
$("detectBtn").onclick = () => {
  const code = suggestLocale(els.text.value, els.language.value);
  if (!code) return toast(t("nothing_detected"), true);
  els.language.value = code; refreshVoice(); toast(tf("detected", langLabel(code))); updateTextWarn();
};
$("sampleBtn").onclick = () => { els.text.value = sampleFor(els.language.value); updateCount(); updateTextWarn(); };
els.text.oninput = () => { updateCount(); updateTextWarn(); };
// ---- translator ----
let trBackup = null;
(function initTr() {
  const sel = $("trLang"); sel.innerHTML = "";
  catalog.languages.forEach((l) => { const o = document.createElement("option"); o.value = l.code; o.textContent = l.label; sel.appendChild(o); });
  sel.value = els.language.value;
})();
$("trBtn").onclick = async () => {
  const text = els.text.value; if (!text.trim()) return toast(t("tr_empty"), true);
  const to = $("trLang").value, btn = $("trBtn"); btn.disabled = true; setStatus(t("tr_working"));
  try {
    const r = await (await postJson("/api/translate", { text, to })).json();
    trBackup = { text, lang: els.language.value }; els.text.value = r.text;
    els.language.value = to; refreshVoice(); updateCount(); updateTextWarn();
    $("trUndo").style.display = ""; setStatus(""); toast(tf("tr_done", langLabel(to)));
  } catch (e) { setStatus(""); toast(e.message, true); } finally { btn.disabled = false; }
};
$("trUndo").onclick = () => {
  if (!trBackup) return; els.text.value = trBackup.text; els.language.value = trBackup.lang; refreshVoice();
  updateCount(); updateTextWarn(); trBackup = null; $("trUndo").style.display = "none";
};
els.rate.oninput = () => (els.rateVal.textContent = `${+els.rate.value > 0 ? "+" : ""}${els.rate.value}%`);
els.pitch.oninput = () => (els.pitchVal.textContent = `${+els.pitch.value > 0 ? "+" : ""}${els.pitch.value} Hz`);

function drawWave(p = 0) {
  const c = els.wave, dpr = devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight; if (!w) return;
  if (c.width !== Math.round(w * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); }
  const g = c.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
  if (!peaks) { g.fillStyle = "#6b7490"; g.font = "14px system-ui"; g.textAlign = "center"; g.fillText(t("wave"), w / 2, h / 2 + 5); return; }
  const n = peaks.length, bar = w / n, mid = h / 2, px = p * w, grad = g.createLinearGradient(0, 0, w, 0);
  grad.addColorStop(0, "#7c5cff"); grad.addColorStop(1, "#3ea6ff");
  for (let i = 0; i < n; i++) { const x = i * bar, a = Math.max(1, peaks[i] * h * 0.46); g.fillStyle = x < px ? grad : "rgba(255,255,255,.22)"; g.fillRect(x, mid - a, Math.max(1, bar * 0.7), a * 2); }
  g.fillStyle = "#fff"; g.fillRect(px, 0, 1.5, h);
}
const audioProgress = () => { const d = els.audio.duration; return isFinite(d) && d > 0 ? els.audio.currentTime / d : 0; };
els.audio.ontimeupdate = () => { els.time.textContent = `${fmtTime(els.audio.currentTime)} / ${fmtTime(els.audio.duration)}`; drawWave(audioProgress()); };
els.audio.onplay = () => (els.play.textContent = t("pause")); els.audio.onpause = els.audio.onended = () => (els.play.textContent = t("play"));
els.play.onclick = () => { if (els.audio.src) els.audio.paused ? els.audio.play() : els.audio.pause(); };
els.wave.onclick = (e) => { if (!els.audio.duration) return; const r = els.wave.getBoundingClientRect(); els.audio.currentTime = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * els.audio.duration; drawWave(audioProgress()); };
addEventListener("resize", () => drawWave(audioProgress()));
async function computePeaks(buf, bins = 900) {
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  try {
    const a = await ctx.decodeAudioData(buf), d = a.getChannelData(0), step = Math.max(1, Math.floor(d.length / bins)), out = new Float32Array(bins);
    for (let i = 0; i < bins; i++) { let m = 0; for (let j = i * step, e = Math.min(d.length, j + step); j < e; j++) { const v = Math.abs(d[j]); if (v > m) m = v; } out[i] = m; }
    return out;
  } finally { ctx.close(); }
}
const voicePayload = () => ({ text: els.text.value, voice: els.voice.value, rate: +els.rate.value, pitch: +els.pitch.value });
function setBusy(b) { busy = b; els.preview.disabled = els.exp.disabled = b; }
function saveBlob(blob, name) { const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 10000); }
els.preview.onclick = async () => {
  if (busy) return; if (!els.text.value.trim()) return setStatus(t("empty"), "err");
  setBusy(true); statusKey = "working_prev"; setStatus(t(statusKey));
  try {
    const blob = await (await postJson("/api/preview", voicePayload())).blob();
    peaks = await computePeaks(await blob.arrayBuffer());
    if (audioUrl) URL.revokeObjectURL(audioUrl); audioUrl = URL.createObjectURL(blob);
    els.audio.src = audioUrl; els.play.disabled = false; drawWave(0);
    statusKey = "prev_ok"; setStatus(t(statusKey), "ok"); els.audio.play().catch(() => {});
  } catch (e) { statusKey = null; setStatus(e.message, "err"); } finally { setBusy(false); }
};
els.exp.onclick = async () => {
  if (busy) return; if (!els.text.value.trim()) return setStatus(t("empty"), "err");
  setBusy(true); statusKey = "working_exp"; setStatus(t(statusKey));
  try {
    const long = els.text.value.length > (catalog.limits.sync_export_chars || 12000);
    if (!long) {
      const blob = await (await postJson("/api/export", voicePayload())).blob();
      saveBlob(blob, `speech-${els.language.value}-${gender}.mp3`);
      statusKey = null; setStatus(`${t("exp_ok")} · ${fmtBytes(blob.size)}`, "ok");
    } else {
      $("expBar").style.display = "block"; $("expFill").style.width = "2%"; setStatus(t("long_hint"));
      const { job_id } = await (await postJson("/api/tts/jobs", voicePayload())).json();
      for (;;) {
        await new Promise((r) => setTimeout(r, 1200));
        const j = await (await api(`/api/jobs/${job_id}`)).json();
        $("expFill").style.width = Math.max(3, Math.round(j.progress * 100)) + "%";
        if (j.status === "queued") setStatus(t("queued")); else if (j.status === "running") setStatus(`${t("speaking")}… ${Math.round(j.progress * 100)}%`);
        if (j.status === "error") throw new Error(j.error);
        if (j.status === "done") break;
      }
      const blob = await (await api(`/api/jobs/${job_id}/speech.mp3`)).blob();
      saveBlob(blob, `speech-${els.language.value}-${gender}.mp3`);
      statusKey = null; setStatus(`${t("exp_ok")} · ${fmtBytes(blob.size)}`, "ok");
    }
  } catch (e) { statusKey = null; setStatus(e.message, "err"); } finally { setBusy(false); $("expBar").style.display = "none"; }
};

/* ================= VIDEO STUDIO: state ================= */
const V = { project: null, name: "", serverId: null, dirty: false, savedAt: null, sel: 0, assets: {}, quota: 0, used: 0, status: null,
  timers: { local: null, server: null, prev: null, job: null }, prevUrl: null, prevSeq: 0, saving: false };

const newScene = (o = {}) => ({ layout: "title", title: "", body: "", narration: "", background: { type: "theme", color: "#1d4e9e", asset: null, assetName: "" },
  media: null, duration: null, transition: "fade", motion: "none", look: "none", voiceover: null, sfx: null, stickers: [], ...o });
const defaultProject = () => ({ ratio: "16:9", resolution: "1080", theme: "academy", captions: true,
  voice: { lang: "ar-SA", gender: "female", voice: "", rate: 0, pitch: 0 }, music: null, scenes: [newScene()] });

function migrate(p) {   // accepts projects saved by older versions
  const out = Object.assign(defaultProject(), clone(p));
  if (p.size && !p.ratio && LEGACY[p.size]) { [out.ratio, out.resolution] = LEGACY[p.size]; if (p.quality === "draft") out.resolution = "480"; }
  delete out.size; delete out.quality;
  out.resolution = String(out.resolution);
  out.voice = Object.assign({ lang: "ar-SA", gender: "female", voice: "", rate: 0, pitch: 0 }, out.voice || {});
  out.scenes = (out.scenes && out.scenes.length ? out.scenes : [newScene()]).map((s) => {
    const sc = newScene(s); sc.background = Object.assign({ type: "theme", color: "#1d4e9e", asset: null, assetName: "" }, s.background || {});
    sc.media = s.media && s.media.asset ? Object.assign({ asset: null, position: "auto", fit: "contain", assetName: "" }, s.media) : null; return sc;
  });
  return out;
}
const sceneAt = () => V.project.scenes[V.sel];

function projectPayload() {
  const p = V.project;
  return { ratio: p.ratio, resolution: p.resolution, theme: p.theme, captions: p.captions,
    voice: { voice: p.voice.voice || null, lang: p.voice.lang, gender: p.voice.gender, rate: p.voice.rate, pitch: p.voice.pitch },
    music: p.music && p.music.asset ? { asset: p.music.asset, volume: p.music.volume } : null,
    scenes: p.scenes.map((s) => ({ layout: s.layout, title: s.title, body: s.body, narration: s.narration,
      background: { type: s.background.type, color: s.background.color, asset: s.background.asset },
      media: s.media && s.media.asset ? { asset: s.media.asset, position: s.media.position, fit: s.media.fit } : null,
      duration: s.duration, transition: s.transition, motion: s.motion || "none", look: s.look || "none",
      voiceover: s.voiceover && s.voiceover.asset ? { asset: s.voiceover.asset } : null,
      sfx: s.sfx && s.sfx.asset ? { asset: s.sfx.asset, at: s.sfx.at || 0, volume: s.sfx.volume == null ? 0.8 : s.sfx.volume } : null,
      stickers: (s.stickers || []).map((k) => ({ asset: k.asset, x: k.x, y: k.y, w: k.w, anim: k.anim, start: k.start || 0 })) })) };
}

/* ---- saving: local draft always, server copy when the project has been saved ---- */
function saveLocal() { try { localStorage.setItem("vf-draft2", JSON.stringify({ name: V.name, serverId: V.serverId, project: V.project })); } catch (_) {} }
function loadLocal() { try { const d = JSON.parse(localStorage.getItem("vf-draft2") || "null"); if (d && d.project && Array.isArray(d.project.scenes)) return d; } catch (_) {} return null; }
function markDirty() {
  V.dirty = true; updateProjStatus();
  clearTimeout(V.timers.local); V.timers.local = setTimeout(saveLocal, 400);
  clearTimeout(V.timers.server);
  if (V.serverId) V.timers.server = setTimeout(() => saveProject({ silent: true }), 6000);   // autosave saved projects
}
function updateProjStatus() {
  const pill = $("pStatus");
  if (V.saving) { pill.textContent = t("p_saving"); pill.className = "pill"; }
  else if (V.dirty) { pill.textContent = V.serverId ? t("p_unsaved") : t("p_local"); pill.className = "pill warn"; }
  else if (V.savedAt) { pill.textContent = tf("p_saved", V.savedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })); pill.className = "pill ok"; }
  else { pill.textContent = ""; pill.className = "pill"; }
  $("pDelete").disabled = !V.serverId;
}
async function saveProject({ asNew = false, name = null, silent = false } = {}) {
  if (V.saving) return;
  V.saving = true; updateProjStatus();
  try {
    const body = { name: name || V.name || t("p_new_name"), project: clone(V.project) };
    if (!asNew && V.serverId) body.id = V.serverId;
    const r = await (await postJson("/api/projects", body)).json();
    V.serverId = r.id; V.name = r.name; $("pName").value = V.name; V.dirty = false; V.savedAt = new Date(r.updated * 1000); saveLocal();
    if (!silent) toast(tf("p_saved", V.savedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })));
  } catch (e) { toast(e.message, true); } finally { V.saving = false; updateProjStatus(); }
}
function loadProjectInto(project, name, serverId, savedAt = null) {
  V.project = migrate(project); V.name = name || ""; V.serverId = serverId || null; V.dirty = false; V.savedAt = savedAt; V.sel = 0;
  $("pName").value = V.name; $("result").style.display = "none"; setVStatus("", ""); refreshVideoUI(); saveLocal(); updateProjStatus(); fire("project");
}
function newProject() {
  if (V.dirty && V.project.scenes.some((s) => s.title || s.body || s.narration) && !confirm(t("p_new_confirm"))) return;
  const p = defaultProject(); p.voice = clone(V.project.voice); p.ratio = V.project.ratio; p.resolution = V.project.resolution; p.theme = V.project.theme;
  loadProjectInto(p, "", null);
}
$("pName").oninput = (e) => { V.name = e.target.value; markDirty(); };
$("pNew").onclick = newProject;
$("pSave").onclick = () => saveProject();
$("pSaveAs").onclick = () => { const n = prompt(t("p_saveas_prompt"), (V.name || t("p_new_name")) + " (copy)"); if (n) saveProject({ asNew: true, name: n }); };
$("pDup").onclick = () => saveProject({ asNew: true, name: (V.name || t("p_new_name")) + " (copy)" });
$("pDelete").onclick = async () => {
  if (!V.serverId || !confirm(t("p_delete_confirm"))) return;
  try { await api(`/api/projects/${V.serverId}`, { method: "DELETE" }); const p = defaultProject(); loadProjectInto(p, "", null); } catch (e) { toast(e.message, true); }
};
$("pExportJson").onclick = () => saveBlob(new Blob([JSON.stringify({ format: "voiceforge-project", version: 2, name: V.name, project: V.project }, null, 1)], { type: "application/json" }), `${(V.name || "project").replace(/[^\w\- ]+/g, "_")}.voxa.json`);
$("pExportZip").onclick = async () => {
  await saveProject({ silent: true }); if (!V.serverId) return toast(t("p_save_first"), true);
  location.href = `/api/projects/${V.serverId}/bundle`;
};
$("pImportFile").onchange = async (e) => {
  const f = e.target.files[0]; e.target.value = ""; if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  try { const r = await (await api("/api/projects/import", { method: "POST", body: fd })).json(); await openProjectById(r.id); await loadAssets(); toast(t("p_import_ok")); }
  catch (err) { toast(err.message, true); }
};
async function openProjectById(id) {
  const rec = await (await api(`/api/projects/${id}`)).json();
  await loadAssets(); loadProjectInto(rec.project, rec.name, rec.id, new Date(rec.updated * 1000)); toast(t("p_loaded"));
}
$("pOpen").onclick = async () => {
  let list = [];
  try { list = (await (await api("/api/projects")).json()).projects; } catch (e) { return toast(e.message, true); }
  const box = document.createElement("div");
  if (!list.length) { box.innerHTML = `<p class="hint"></p>`; box.firstChild.textContent = t("p_none"); }
  const wrap = document.createElement("div"); wrap.className = "plist";
  list.forEach((p) => {
    const row = document.createElement("div"); row.className = "prow";
    row.innerHTML = `<b></b><span></span><button class="btn sm primary"></button><button class="btn sm danger"></button>`;
    row.children[0].textContent = p.name;
    row.children[1].textContent = `${tf("p_scenes", p.scenes)} · ${p.ratio || ""} ${p.resolution || ""}p · ${new Date(p.updated * 1000).toLocaleString()}`;
    row.children[2].textContent = t("p_open_btn"); row.children[3].textContent = t("p_delete");
    row.children[2].onclick = async () => { try { closeModal(); await openProjectById(p.id); } catch (e) { toast(e.message, true); } };
    row.children[3].onclick = async () => { if (!confirm(t("p_delete_confirm"))) return; try { await api(`/api/projects/${p.id}`, { method: "DELETE" }); row.remove(); if (V.serverId === p.id) { V.serverId = null; updateProjStatus(); } } catch (e) { toast(e.message, true); } };
    wrap.appendChild(row);
  });
  box.appendChild(wrap); openModal(t("p_open_title"), box);
};

/* ================= VIDEO STUDIO: media library ================= */
async function loadAssets() {
  try { const d = await (await api("/api/assets")).json(); V.assets = {}; d.assets.forEach((a) => (V.assets[a.id] = a)); V.quota = d.quota_bytes; V.used = d.used_bytes; } catch (_) {}
}
const assetName = (id) => (V.assets[id] ? V.assets[id].name : "");
async function uploadFiles(files) {
  const out = [];
  for (const f of files) {
    const fd = new FormData(); fd.append("file", f);
    try { const m = await (await api("/api/video/assets", { method: "POST", body: fd })).json(); V.assets[m.id] = m; out.push(m); }
    catch (e) { toast(`${f.name}: ${e.message}`, true); }
  }
  await loadAssets(); return out;
}
// Opens the library; resolves with the chosen asset (or null). `kinds` limits what can be chosen.
function pickAsset(kinds) {
  return new Promise(async (resolve) => {
    await loadAssets(); let chosen = null, filter = "all";
    const box = document.createElement("div");
    const top = document.createElement("div"); top.className = "row"; top.style.marginTop = "0";
    const up = document.createElement("label"); up.className = "btn primary sm"; up.style.cssText = "margin:0;text-transform:none;letter-spacing:0";
    const upText = document.createElement("span"); upText.textContent = t("lib_upload");
    const input = document.createElement("input"); input.type = "file"; input.multiple = true; input.hidden = true;
    const accept = { image: "image/png,image/jpeg,image/webp", video: "video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm", audio: "audio/*,.mp3,.wav,.m4a,.aac,.ogg,.flac" };
    input.accept = kinds.map((k) => accept[k]).join(","); up.append(upText, input); top.appendChild(up);
    const chips = document.createElement("div"); chips.className = "chips"; chips.style.marginInlineStart = "8px";
    if (kinds.length > 1) ["all", ...kinds].forEach((k) => { const c = document.createElement("button"); c.className = "rchip"; c.style.padding = "4px 10px";
      c.textContent = k === "all" ? t("lib_all") : t(k === "image" ? "lib_images" : k === "video" ? "lib_videos" : "lib_audio"); c.onclick = () => { filter = k; draw(); }; chips.appendChild(c); });
    top.appendChild(chips);
    const info = document.createElement("div"); info.className = "hint"; info.style.marginTop = "8px"; info.textContent = t("lib_formats");
    const grid = document.createElement("div"); grid.className = "lib"; const quota = document.createElement("div"); quota.className = "hint"; quota.style.marginTop = "10px";
    box.append(top, info, grid, quota);
    function draw() {
      grid.innerHTML = ""; const list = Object.values(V.assets).filter((a) => kinds.includes(a.kind) && (filter === "all" || a.kind === filter)).sort((a, b) => b.created - a.created);
      if (!list.length) { const p = document.createElement("p"); p.className = "hint"; p.textContent = t("lib_empty"); grid.appendChild(p); }
      list.forEach((a) => {
        const card = document.createElement("div"); card.className = "asset";
        const thumb = a.kind === "audio" ? Object.assign(document.createElement("div"), { className: "ph", textContent: "♪" }) : Object.assign(document.createElement("img"), { src: `/api/assets/${a.id}/thumb`, alt: "" });
        const cap = document.createElement("div"); cap.textContent = `${a.name} · ${fmtBytes(a.bytes)}`; cap.title = a.name;
        const x = document.createElement("button"); x.className = "x"; x.textContent = "✕"; x.title = t("lib_delete");
        x.onclick = async (ev) => { ev.stopPropagation(); if (!confirm(t("lib_delete_confirm"))) return; try { await api(`/api/assets/${a.id}`, { method: "DELETE" }); delete V.assets[a.id]; draw(); } catch (e) { toast(e.message, true); } };
        card.onclick = () => { chosen = a; closeModal(); }; card.append(thumb, cap, x); grid.appendChild(card);
      });
      quota.textContent = tf("lib_used", fmtBytes(V.used), fmtBytes(V.quota));
    }
    input.onchange = async () => {
      const files = [...input.files]; input.value = ""; if (!files.length) return; upText.textContent = t("lib_uploading");
      const metas = await uploadFiles(files); upText.textContent = t("lib_upload");
      const ok = metas.filter((m) => kinds.includes(m.kind));
      if (ok.length === 1 && metas.length === 1) { chosen = ok[0]; closeModal(); } else draw();
    };
    draw(); openModal(t("lib_title"), box, () => resolve(chosen));
  });
}

/* ================= VIDEO STUDIO: format, theme, voice, music ================= */
function ratioDims(ratio, res) { return (cfg.dimensions[ratio] || {})[res] || [0, 0]; }
function renderPresetCards() {
  const box = $("presetCards"); box.innerHTML = "";
  cfg.presets.forEach((p) => { const b = document.createElement("button"); b.className = "pcard"; b.innerHTML = "<b></b><span></span>"; b.firstChild.textContent = p.label[ui]; b.lastChild.textContent = p.desc[ui]; b.onclick = () => applyPreset(p.id); box.appendChild(b); });
  const blank = document.createElement("button"); blank.className = "pcard"; blank.innerHTML = "<b></b><span></span>";
  blank.firstChild.textContent = ui === "ar" ? "مشروع فارغ" : "Blank project"; blank.lastChild.textContent = ui === "ar" ? "ابدأ من الصفر بمشهد واحد." : "Start from scratch with one scene.";
  blank.onclick = () => { V.project.scenes = [newScene()]; V.sel = 0; refreshVideoUI(); markDirty(); }; box.appendChild(blank);
}
function applyPreset(id) {
  const p = cfg.presets.find((x) => x.id === id); if (!p) return;
  const keepRes = V.project.resolution;
  V.project.ratio = p.ratio; V.project.theme = p.theme; V.project.resolution = keepRes;   // the preset sets the shape; your resolution choice stays
  V.project.scenes = p.scenes[ui].map((s) => newScene(s));
  const v = V.project.voice;
  if (ui === "ar" && !isRtlLang(v.lang)) { v.lang = "ar-SA"; v.voice = ""; } else if (ui !== "ar" && isRtlLang(v.lang)) { v.lang = "en-US"; v.voice = ""; }
  V.sel = 0; refreshVideoUI(); markDirty(); setVKey("loaded_preset", "ok");
}
function renderRatios() {
  const box = $("ratioCards"); box.innerHTML = "";
  cfg.ratios.forEach((r) => {
    const [a, b] = r.id.split(":").map(Number), k = 28 / Math.max(a, b);
    const el = document.createElement("button"); el.className = "pcard size" + (V.project.ratio === r.id ? " on" : "");
    el.innerHTML = `<div class="ar" style="width:${Math.round(a * k * 1.5)}px;height:${Math.round(b * k * 1.5)}px"></div><div><b></b><span></span></div>`;
    el.querySelector("b").textContent = r.id; el.querySelector("span").textContent = r.label.replace(/ \(.*\)$/, "");
    el.onclick = () => { V.project.ratio = r.id; renderRatios(); renderResolutions(); markDirty(); schedulePreview(); }; box.appendChild(el);
  });
}
function renderResolutions() {
  const box = $("resChips"); box.innerHTML = "";
  cfg.resolutions.forEach((r) => {
    const [w, h] = ratioDims(V.project.ratio, r.id), el = document.createElement("button"); el.className = "rchip" + (V.project.resolution === r.id ? " on" : "");
    el.innerHTML = "<span></span><small></small>"; el.firstChild.textContent = r.label; el.lastChild.textContent = `${w}×${h}`;
    el.onclick = () => { V.project.resolution = r.id; renderResolutions(); markDirty(); }; box.appendChild(el);
  });
  const res = V.project.resolution, [w, h] = ratioDims(V.project.ratio, res), lab = (cfg.resolutions.find((r) => r.id === res) || {}).label || res;
  $("outInfo").textContent = tf("v_out", w, h, lab);
  $("resNote").textContent = tf("v_res_note", Math.round(cfg.max_seconds[res] / 60)) + (res === "2160" ? " · " + t("v_res_4k") : "");
}
function renderThemes() {
  const box = $("themeSw"); box.innerHTML = "";
  cfg.themes.forEach((th) => { const b = document.createElement("button"); b.className = "sw" + (V.project.theme === th.id ? " on" : ""); b.innerHTML = `<i style="background:linear-gradient(135deg,${th.bg[0]},${th.bg[1]})"></i><span></span>`; b.querySelector("span").textContent = th.label; b.onclick = () => { V.project.theme = th.id; renderThemes(); markDirty(); schedulePreview(); }; box.appendChild(b); });
}
const vv = () => V.project.voice;
function refreshVVoice() { const list = fillVoices($("vVoice"), vv().lang, vv().gender, vv().voice); vv().voice = $("vVoice").value || (list[0] && list[0].id) || ""; }
$("vLanguage").onchange = (e) => { vv().lang = e.target.value; vv().voice = ""; refreshVVoice(); markDirty(); updateNarrWarnings(); };
$("vVoice").onchange = (e) => { vv().voice = e.target.value; markDirty(); };
genderBtns($("vGender"), (g) => { vv().gender = g; vv().voice = ""; refreshVVoice(); markDirty(); });
$("vRate").oninput = (e) => { vv().rate = +e.target.value; $("vRateVal").textContent = `${vv().rate > 0 ? "+" : ""}${vv().rate}%`; markDirty(); };
$("vPitch").oninput = (e) => { vv().pitch = +e.target.value; $("vPitchVal").textContent = `${vv().pitch > 0 ? "+" : ""}${vv().pitch} Hz`; markDirty(); };
$("vCaptions").onchange = (e) => { V.project.captions = e.target.checked; markDirty(); schedulePreview(); };

function renderMusic() {
  const m = V.project.music, has = m && m.asset;
  $("musicName").textContent = has ? (assetName(m.asset) || m.assetName || "♪") : t("v_music_none"); $("musicClear").style.display = has ? "" : "none";
  $("musicBox").style.display = has ? "block" : "none";
  if (has) { $("musicVol").value = Math.round(m.volume * 100); $("musicVolVal").textContent = Math.round(m.volume * 100) + "%"; if ($("musicAudio").dataset.id !== m.asset) { $("musicAudio").src = `/api/assets/${m.asset}/file`; $("musicAudio").dataset.id = m.asset; } }
}
$("musicPick").onclick = async () => { const a = await pickAsset(["audio"]); if (a) { V.project.music = { asset: a.id, volume: (V.project.music && V.project.music.volume) || 0.15, assetName: a.name }; renderMusic(); markDirty(); } };
$("musicClear").onclick = () => { V.project.music = null; $("musicAudio").removeAttribute("src"); $("musicAudio").dataset.id = ""; renderMusic(); markDirty(); };
$("musicVol").oninput = (e) => { V.project.music.volume = +e.target.value / 100; $("musicVolVal").textContent = e.target.value + "%"; markDirty(); };

/* ================= VIDEO STUDIO: scenes ================= */
const sceneLabel = (s) => s.title || (s.body || "").split("\n")[0] || s.label || (s.narration || "").slice(0, 40) || t("untitled");
function renderSceneList() {
  const box = $("sceneList"); box.innerHTML = "";
  V.project.scenes.forEach((s, i) => { const b = document.createElement("button"); b.className = "sitem" + (i === V.sel ? " on" : ""); b.innerHTML = "<em></em><span></span>"; b.firstChild.textContent = i + 1; b.lastChild.textContent = sceneLabel(s);
    if (s.media && s.media.asset) { const im = document.createElement("img"); im.className = "sthumb"; im.loading = "lazy"; im.alt = ""; im.src = `/api/assets/${s.media.asset}/thumb`; b.insertBefore(im, b.lastChild); }
    b.onclick = () => { V.sel = i; renderSceneList(); loadSceneFields(); schedulePreview(); }; box.appendChild(b); });
  updateEstimate();
}
function updateSceneItem() { const b = $("sceneList").children[V.sel]; if (b) b.lastChild.textContent = sceneLabel(sceneAt()); updateEstimate(); }
const MEDIA_LAYOUTS = ["bullets", "text", "media"];
function loadSceneFields() {
  const s = sceneAt(); $("sceneTitleHead").textContent = `${t("scene")} ${V.sel + 1}`;
  $("sLayout").value = s.layout; $("sTitle").value = s.title; $("sBody").value = s.body; $("sNarr").value = s.narration;
  $("sBgType").value = s.background.type; $("sDur").value = s.duration == null ? "" : s.duration; $("sTrans").value = s.transition;
  $("narrCount").textContent = tf("narr_chars", s.narration.length);
  $("sUp").disabled = V.sel === 0; $("sDown").disabled = V.sel === V.project.scenes.length - 1; $("sDel").disabled = V.project.scenes.length === 1;
  renderMediaBox(); renderBgExtra(); updateNarrWarnings(); fire("scene");
}
function renderMediaBox() {
  const s = sceneAt(), show = MEDIA_LAYOUTS.includes(s.layout); $("mediaBox").style.display = show ? "block" : "none"; if (!show) return;
  const m = s.media, has = m && m.asset;
  $("mediaName").textContent = has ? assetName(m.asset) || m.assetName || "" : t("v_media_none"); $("mediaClear").style.display = has ? "" : "none"; $("mediaOpts").style.display = has ? "" : "none";
  const th = $("mediaThumb"); th.style.display = has ? "" : "none"; $("mediaEmpty").style.display = has ? "none" : "";
  if (has) { th.src = `/api/assets/${m.asset}/thumb`; $("mediaPos").value = m.position; $("mediaFit").value = m.fit; $("mediaPos").disabled = false; }
}
$("mediaPick").onclick = async () => {
  const a = await pickAsset(["image", "video"]); if (!a) return; const s = sceneAt();
  s.media = Object.assign({ position: "auto", fit: "contain" }, s.media || {}, { asset: a.id, assetName: a.name }); renderMediaBox(); markDirty(); schedulePreview();
};
$("mediaClear").onclick = () => { sceneAt().media = null; renderMediaBox(); markDirty(); schedulePreview(); };
$("mediaPos").onchange = (e) => { sceneAt().media.position = e.target.value; markDirty(); schedulePreview(); };
$("mediaFit").onchange = (e) => { sceneAt().media.fit = e.target.value; markDirty(); schedulePreview(); };

function renderBgExtra() {
  const s = sceneAt(), box = $("bgExtra"), type = s.background.type; box.innerHTML = "";
  if (type === "color") {
    box.innerHTML = `<label></label><input type="color" id="bgColor" style="width:100%;height:42px;border-radius:10px;border:1px solid var(--line);background:none">`; box.firstChild.textContent = t("colour");
    $("bgColor").value = s.background.color || "#1d4e9e"; $("bgColor").oninput = (e) => { s.background.color = e.target.value; markDirty(); schedulePreview(); };
  } else if (type === "image" || type === "video") {
    box.innerHTML = `<label></label><button class="btn" style="width:100%"></button><span class="hint"></span>`;
    box.querySelector("label").textContent = type === "image" ? t("b_image") : t("b_video"); box.querySelector("button").textContent = t("v_media_pick");
    box.querySelector(".hint").textContent = s.background.asset ? assetName(s.background.asset) || s.background.assetName || "" : "";
    box.querySelector("button").onclick = async () => { const a = await pickAsset([type]); if (!a) return; s.background.asset = a.id; s.background.assetName = a.name; renderBgExtra(); markDirty(); schedulePreview(); };
  }
}
function bindField(id, fn) { $(id).addEventListener("input", (e) => { fn(sceneAt(), e.target.value); markDirty(); schedulePreview(); updateSceneItem(); }); }
bindField("sTitle", (s, v) => (s.title = v)); bindField("sBody", (s, v) => (s.body = v));
$("sNarr").addEventListener("input", (e) => { sceneAt().narration = e.target.value; $("narrCount").textContent = tf("narr_chars", e.target.value.length); markDirty(); updateSceneItem(); updateNarrWarnings(); });
$("sLayout").onchange = (e) => { sceneAt().layout = e.target.value; renderMediaBox(); markDirty(); schedulePreview(); };
$("sTrans").onchange = (e) => { sceneAt().transition = e.target.value; markDirty(); };
$("sDur").oninput = (e) => { const v = parseFloat(e.target.value); sceneAt().duration = isFinite(v) && v > 0 ? v : null; markDirty(); updateEstimate(); };
$("sBgType").onchange = (e) => { sceneAt().background.type = e.target.value; renderBgExtra(); markDirty(); schedulePreview(); };
$("importDoc").onclick = () => {
  const box = document.createElement("div");
  box.innerHTML = `<p class="hint" data-r="intro"></p>
    <input type="file" data-r="file" accept=".pdf,.pptx,.ppsx,.ppt,.odp,.docx,.doc,.odt,.rtf,.txt,.xlsx,.xls,.ods,.csv" style="width:100%;margin:8px 0">
    <div class="grid2" style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
      <div><label data-r="l_narr"></label><select data-r="narr"><option value="notes"></option><option value="text"></option><option value="none"></option></select></div>
      <div><label data-r="l_where"></label><select data-r="where"><option value="after"></option><option value="end"></option><option value="replace"></option></select></div>
      <div><label data-r="l_bg"></label><select data-r="bg"><option value="black"></option><option value="theme"></option></select></div>
    </div>
    <div class="row" style="margin-top:12px"><button class="btn primary" data-r="go"></button><span class="status" data-r="st"></span></div>`;
  const r = (k) => box.querySelector(`[data-r="${k}"]`);
  r("intro").textContent = t("imp_intro"); r("l_narr").textContent = t("imp_narr"); r("l_where").textContent = t("imp_where"); r("l_bg").textContent = t("imp_bg");
  ["imp_n_notes", "imp_n_text", "imp_n_none"].forEach((k, i) => (r("narr").options[i].textContent = t(k)));
  ["imp_w_after", "imp_w_end", "imp_w_replace"].forEach((k, i) => (r("where").options[i].textContent = t(k)));
  ["imp_bg_black", "imp_bg_theme"].forEach((k, i) => (r("bg").options[i].textContent = t(k)));
  r("go").textContent = t("imp_go");
  r("go").onclick = async () => {
    const f = r("file").files[0]; if (!f) return toast(t("imp_pick"), true);
    const fd = new FormData(); fd.append("file", f); fd.append("narration", r("narr").value); fd.append("background", r("bg").value);
    const where = r("where").value, room = cfg.limits.max_scenes - (where === "replace" ? 0 : V.project.scenes.length);
    if (room < 1) return toast(t("imp_full"), true);
    fd.append("max_pages", room);
    r("go").disabled = true; r("st").textContent = t("imp_working");
    try {
      const res = await (await api("/api/video/import", { method: "POST", body: fd })).json();
      const names = {}; res.assets.forEach((a) => (names[a.id] = a.name));
      const sc = res.scenes.map((s) => { const n = newScene(s); n.background = Object.assign({ type: "theme", color: "#1d4e9e", asset: null, assetName: "" }, s.background || {});
        n.media = s.media ? Object.assign({ assetName: names[s.media.asset] || "" }, s.media) : null; return n; });
      const a = V.project.scenes, onlyBlank = a.length === 1 && !a[0].title && !a[0].body && !a[0].narration && !a[0].media;
      if (where === "replace" || onlyBlank) { V.project.scenes = sc; V.sel = 0; }
      else if (where === "end") { V.sel = a.length; a.push(...sc); }
      else { a.splice(V.sel + 1, 0, ...sc); V.sel = V.sel + 1; }
      closeModal(); refreshVideoUI(); markDirty();
      toast(res.imported < res.pages ? tf("imp_partial", res.imported, res.pages) : tf("imp_done", res.imported));
    } catch (e) { r("st").textContent = ""; toast(e.message, true); r("go").disabled = false; }
  };
  openModal(t("imp_title"), box);
};
$("addScene").onclick = () => { V.project.scenes.push(newScene()); V.sel = V.project.scenes.length - 1; refreshVideoUI(); markDirty(); };
$("sDup").onclick = () => { V.project.scenes.splice(V.sel + 1, 0, clone(sceneAt())); V.sel++; refreshVideoUI(); markDirty(); };
$("sDel").onclick = () => { V.project.scenes.splice(V.sel, 1); V.sel = Math.max(0, V.sel - 1); refreshVideoUI(); markDirty(); };
$("sUp").onclick = () => moveScene(-1); $("sDown").onclick = () => moveScene(1);
function moveScene(d) { const a = V.project.scenes, i = V.sel, j = i + d; if (j < 0 || j >= a.length) return; [a[i], a[j]] = [a[j], a[i]]; V.sel = j; refreshVideoUI(); markDirty(); }

function narrationProblems() {
  const out = [];
  V.project.scenes.forEach((s, i) => { const m = mismatch(s.narration, vv().lang); if (m) out.push({ i, found: m.found, text: s.narration }); });
  return out;
}
function updateNarrWarnings() {
  const probs = narrationProblems(), here = probs.find((p) => p.i === V.sel), nb = $("narrWarn");
  nb.style.display = here ? "block" : "none"; if (here) nb.textContent = tf("narr_mismatch", here.i + 1, scriptName(here.found), langLabel(vv().lang));
  const rb = $("renderWarn"); rb.style.display = probs.length ? "block" : "none"; rb.innerHTML = "";
  if (probs.length) {
    probs.slice(0, 4).forEach((p) => { const d = document.createElement("div"); d.textContent = tf("narr_mismatch", p.i + 1, scriptName(p.found), langLabel(vv().lang)); rb.appendChild(d); });
    const btn = document.createElement("button"); btn.className = "btn sm"; btn.style.marginTop = "8px"; btn.textContent = t("mismatch_fix_voice");
    btn.onclick = () => { const code = suggestLocale(probs[0].text, vv().lang); if (code) { vv().lang = code; vv().voice = ""; $("vLanguage").value = code; refreshVVoice(); markDirty(); updateNarrWarnings(); toast(tf("detected", langLabel(code))); } };
    rb.appendChild(btn);
  }
}

/* ---- live slide preview ---- */
function schedulePreview() { clearTimeout(V.timers.prev); V.timers.prev = setTimeout(refreshPreview, 600); }
async function refreshPreview() {
  if (!$("viewVideo").classList.contains("on") || !cfg) return; const s = sceneAt();
  if (["image", "video"].includes(s.background.type) && !s.background.asset) { $("prevNote").textContent = t("need_upload"); return; }
  const seq = ++V.prevSeq; $("prevNote").textContent = t("prev_loading");
  try {
    const blob = await (await postJson("/api/video/preview", { project: projectPayload(), index: V.sel, stickers: false })).blob(); if (seq !== V.prevSeq) return;
    if (V.prevUrl) URL.revokeObjectURL(V.prevUrl); V.prevUrl = URL.createObjectURL(blob); $("scenePreview").src = V.prevUrl; $("prevNote").textContent = "";
  } catch (e) { if (seq === V.prevSeq) $("prevNote").textContent = t("prev_fail") + e.message; }
}
const estimateSeconds = () => V.project.scenes.reduce((a, s) => a + (s.duration || (s.narration ? Math.max(2, s.narration.length / 14 + 0.5) : 5)), 0);
function updateEstimate() { const sec = Math.round(estimateSeconds()); $("estimate").textContent = `${t("est")}: ~${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`; }

/* ---- render ---- */
function setVStatus(msg, cls = "") { const e = $("vStatus"); e.textContent = msg; e.className = "status " + cls; }
function setVKey(key, cls = "") { V.status = { key, cls }; setVStatus(t(key), cls); }
$("renderBtn").onclick = async () => {
  const btn = $("renderBtn"); btn.disabled = true; $("result").style.display = "none"; clearInterval(V.timers.job);
  $("bar").style.display = "block"; $("barFill").style.width = "2%"; setVKey("queued");
  try {
    const { job_id } = await (await postJson("/api/video/render", { project: projectPayload() })).json();
    V.timers.job = setInterval(() => pollJob(job_id), 1000); pollJob(job_id);
  } catch (e) { V.status = null; setVStatus(t("render_fail") + e.message, "err"); $("bar").style.display = "none"; btn.disabled = false; }
};
async function pollJob(id) {
  try {
    const j = await (await api(`/api/jobs/${id}`)).json(); $("barFill").style.width = Math.max(3, Math.round(j.progress * 100)) + "%";
    if (j.status === "queued") setVKey("queued"); else if (j.status === "running") { V.status = null; setVStatus(`${t("rendering")}… ${Math.round(j.progress * 100)}% (${j.message})`); }
    if (j.status === "done") {
      clearInterval(V.timers.job); $("renderBtn").disabled = false; $("barFill").style.width = "100%"; setVKey("render_done", "ok");
      const base = `/api/jobs/${id}/video.mp4`; $("outVideo").src = base; $("dlMp4").href = base + "?download=1"; $("dlSrt").href = `/api/jobs/${id}/captions.srt`;
      $("resInfo").textContent = `${Math.floor(j.duration / 60)}:${String(Math.round(j.duration % 60)).padStart(2, "0")} · ${$("outInfo").textContent}`; $("result").style.display = "block"; $("result").scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
    if (j.status === "error") { clearInterval(V.timers.job); $("renderBtn").disabled = false; $("bar").style.display = "none"; V.status = null; setVStatus(t("render_fail") + j.error, "err"); }
  } catch (e) { clearInterval(V.timers.job); $("renderBtn").disabled = false; V.status = null; setVStatus(t("render_fail") + e.message, "err"); }
}

function refreshVideoUI() {
  const p = V.project; if (V.sel >= p.scenes.length) V.sel = p.scenes.length - 1;
  renderPresetCards(); renderRatios(); renderResolutions(); renderThemes(); renderMusic(); renderSceneList(); loadSceneFields();
  $("vCaptions").checked = p.captions; fillLanguages($("vLanguage"), p.voice.lang); setGenderUI($("vGender"), p.voice.gender); refreshVVoice();
  $("vRate").value = p.voice.rate; $("vPitch").value = p.voice.pitch;
  $("vRateVal").textContent = `${p.voice.rate > 0 ? "+" : ""}${p.voice.rate}%`; $("vPitchVal").textContent = `${p.voice.pitch > 0 ? "+" : ""}${p.voice.pitch} Hz`;
  updateProjStatus(); schedulePreview();
}

/* ================= tabs, language, auth, init ================= */
function applyUI(lang) {
  ui = lang; document.documentElement.lang = lang; document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  document.querySelectorAll("[data-i]").forEach((el) => { const v = I18N[lang][el.dataset.i]; if (typeof v === "string") el.textContent = v; });
  document.querySelectorAll("[data-iph]").forEach((el) => { const v = I18N[lang][el.dataset.iph]; if (typeof v === "string") el.placeholder = v; });
  $("langBtn").textContent = lang === "ar" ? "English" : "العربية"; $("sDur").placeholder = lang === "ar" ? "تلقائي" : "auto";
  if (catalog.languages.length) updateCount();
  if (statusKey) setStatus(t(statusKey), statusKey === "prev_ok" ? "ok" : "");
  drawWave(audioProgress());
  if (cfg && V.project) { renderPresetCards(); renderRatios(); renderResolutions(); renderThemes(); renderMusic(); renderSceneList(); loadSceneFields(); updateProjStatus(); if (V.status) setVStatus(t(V.status.key), V.status.cls); }
  updateTextWarn(); fire("ui");
}
const VIEWS = ["voice", "video", "timeline", "stt", "audio"];
const cap1 = (v) => v[0].toUpperCase() + v.slice(1);
function showView(v) {
  if (!VIEWS.includes(v)) v = "voice";
  VIEWS.forEach((k) => { const view = $("view" + cap1(k)), tab = $("tab" + cap1(k)); if (view) view.classList.toggle("on", k === v); if (tab) tab.classList.toggle("on", k === v); });
  if (v === "video") refreshPreview(); else if (v === "voice") drawWave(audioProgress());
  try { history.replaceState(null, "", "#" + v); } catch (_) {}
  fire("view", v);
}
VIEWS.forEach((k) => { const tab = $("tab" + cap1(k)); if (tab) tab.onclick = () => showView(k); });
document.querySelectorAll("[data-go]").forEach((a) => a.addEventListener("click", () => showView(a.dataset.go)));
$("langBtn").onclick = () => applyUI(ui === "en" ? "ar" : "en");

async function initAuth() {
  const me = await (await fetch("/api/me")).json().catch(() => ({})); showUser(me.user);
  if (!config.google_client_id) return;
  const s = document.createElement("script"); s.src = "https://accounts.google.com/gsi/client"; s.async = true;
  s.onload = () => {
    google.accounts.id.initialize({ client_id: config.google_client_id, callback: async (r) => {
      const res = await fetch("/api/auth/google", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ credential: r.credential }) });
      const data = await res.json(); if (res.ok) { showUser(data.user); await loadAssets(); toast(data.user.name); } else setStatus(data.error, "err"); } });
    google.accounts.id.renderButton($("gsi"), { theme: "filled_black", size: "medium", shape: "pill", text: "signin_with" });
  };
  document.head.appendChild(s);
}
function showUser(u) { $("user").style.display = u ? "flex" : "none"; $("gsi").style.display = u ? "none" : "block"; if (u) { $("uname").textContent = u.name; if (u.picture) $("uimg").src = u.picture; else $("uimg").style.display = "none"; } }
$("signout").onclick = async () => { await fetch("/api/auth/logout", { method: "POST" }); showUser(null); };

async function init() {
  [catalog, cfg, config] = await Promise.all([fetch("/api/voices").then((r) => r.json()), fetch("/api/video/config").then((r) => r.json()), fetch("/api/config").then((r) => r.json()).catch(() => ({}))]);
  const fam = new Set(catalog.languages.map((l) => l.code.split("-")[0]));
  $("sLang").textContent = fam.size; $("sVoice").textContent = catalog.voices.length; $("sFmt").textContent = cfg.ratios.length;
  $("kFormats").textContent = cfg.ratios.map((r) => r.id).join(" · ");
  $("kRes").textContent = cfg.resolutions.map((r) => r.label.replace(/ \(.*\)/, "")).join(" · ");
  document.querySelectorAll(".origin").forEach((e) => (e.textContent = location.origin));
  fillLanguages(els.language, "ar-SA"); refreshVoice(); els.text.value = sampleFor("ar-SA"); updateCount(); updateTextWarn();
  const rows = {}; catalog.voices.forEach((v) => { (rows[v.language] = rows[v.language] || { label: v.label, male: [], female: [] })[v.gender].push(v.name); });
  $("voiceTable").innerHTML = Object.values(rows).map((r) => `<tr><td>${r.label}</td><td>${r.male.join(", ") || "—"}</td><td>${r.female.join(", ") || "—"}</td></tr>`).join("");
  await loadAssets();
  const draft = loadLocal(); if (draft) { V.project = migrate(draft.project); V.name = draft.name || ""; V.serverId = draft.serverId || null; } else V.project = defaultProject();
  $("pName").value = V.name; refreshVideoUI(); applyUI("en"); initAuth(); showView((location.hash || "#voice").slice(1)); fire("ready");
}
const hooks = {};
function fire(name, arg) { (hooks[name] || []).forEach((fn) => { try { fn(arg); } catch (e) { console.error(e); } }); }
window.VF = {
  $, t, tf, api, postJson, toast, openModal, closeModal, pickAsset, loadAssets, uploadFiles, sceneAt, markDirty, schedulePreview,
  refreshVideoUI, renderMusic, loadSceneFields, showView, projectPayload, saveBlob, langLabel, fillLanguages, sampleFor, fmtBytes, renderSceneList,
  get V() { return V; }, get cfg() { return cfg; }, get catalog() { return catalog; }, get ui() { return ui; },
  get voiceLang() { return els.language.value; }, voiceText: (v) => { if (v === undefined) return els.text.value; els.text.value = v; els.text.dispatchEvent(new Event("input")); },
  setVoiceLang: (code) => { els.language.value = code; els.language.dispatchEvent(new Event("change")); },
  on: (name, fn) => (hooks[name] = hooks[name] || []).push(fn),
};
init().catch((e) => setStatus("Could not load: " + e.message, "err"));
})();
