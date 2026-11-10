/* Audio editor: waveform with zoom/selection, cut/copy/paste/delete/trim/silence, fades, normalize, gain, reverse,
   effects (echo, reverb, radio, EQ, voice enhance, compressor, speed, pitch, robot), mix-in, undo/redo,
   import (file, library, microphone, TTS output), export WAV (in browser) / MP3 (server), save to library. */
(() => {
"use strict";
const VF = window.VF, $ = VF.$, t = VF.t, tf = VF.tf;
const AC = window.AudioContext || window.webkitAudioContext, OAC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
let ac = null;
const ctx = () => (ac = ac || new AC());
let A = null;               // { sr, ch: Float32Array[] }
let name = "sound", sel = null, cursor = 0, view = { a: 0, b: 0 }, undo = [], redo = [], clip = null;
let src = null, playStart = 0, playFrom = 0, playTo = 0, raf = 0;
const len = () => (A ? A.ch[0].length : 0);
const secs = (n) => (n / (A ? A.sr : 44100));
const fmt = (n) => { const s = secs(n); return `${Math.floor(s / 60)}:${(s % 60).toFixed(2).padStart(5, "0")}`; };

/* ---------- load ---------- */
async function openBlob(blob, nm) {
  stop(); setBusy(true);
  try {
    const buf = await ctx().decodeAudioData(await blob.arrayBuffer());
    A = { sr: buf.sampleRate, ch: [...Array(Math.min(2, buf.numberOfChannels)).keys()].map((i) => buf.getChannelData(i).slice()) };
    name = (nm || "sound").replace(/\.[^.]+$/, ""); undo = []; redo = []; sel = null; cursor = 0; view = { a: 0, b: len() };
    $("aeEmpty").style.display = "none"; $("aeMain").style.display = "block"; $("aeName").textContent = name; refresh();
  } catch (e) { VF.toast(t("ae_decode_fail"), true); }
  finally { setBusy(false); }
}
async function openAsset(id, nm) { const r = await VF.api(`/api/assets/${id}/file`); await openBlob(await r.blob(), nm); }
async function decodeOther(blob) { const b = await ctx().decodeAudioData(await blob.arrayBuffer()); return resample(b, A.sr); }
function resample(buf, sr) {
  const n = Math.round(buf.length * sr / buf.sampleRate), out = [];
  for (let c = 0; c < A.ch.length; c++) {
    const inp = buf.getChannelData(Math.min(c, buf.numberOfChannels - 1)), o = new Float32Array(n), k = buf.sampleRate / sr;
    for (let i = 0; i < n; i++) { const x = i * k, j = Math.floor(x), f = x - j; o[i] = (inp[j] || 0) * (1 - f) + (inp[j + 1] || 0) * f; }
    out.push(o);
  }
  return out;
}

/* ---------- history ---------- */
function snapshot() { undo.push({ ch: A.ch.map((c) => c.slice()), sel, cursor }); if (undo.length > 15) undo.shift(); redo = []; }
function restore(from, to) { if (!from.length) return; to.push({ ch: A.ch.map((c) => c.slice()), sel, cursor }); const s = from.pop(); A.ch = s.ch; sel = s.sel; cursor = Math.min(s.cursor, len()); fitView(); refresh(); }
function fitView() { if (view.b > len() || view.a >= view.b) view = { a: 0, b: len() }; }

/* ---------- region helpers ---------- */
const region = () => (sel && sel[1] - sel[0] > 10 ? [sel[0], sel[1]] : [0, len()]);
function replaceRegion(a, b, chans) {
  A.ch = A.ch.map((c, i) => { const ins = chans[i] || chans[0], o = new Float32Array(c.length - (b - a) + ins.length); o.set(c.subarray(0, a)); o.set(ins, a); o.set(c.subarray(b), a + ins.length); return o; });
}
function edit(fn) { if (!A) return; stop(); snapshot(); fn(); fitView(); refresh(); }

const ops = {
  cut: () => { if (!sel) return; const [a, b] = sel; clip = A.ch.map((c) => c.slice(a, b)); edit(() => { replaceRegion(a, b, A.ch.map(() => new Float32Array(0))); cursor = a; sel = null; }); },
  copy: () => { if (!sel) return; clip = A.ch.map((c) => c.slice(sel[0], sel[1])); VF.toast(t("stt_copied")); },
  paste: () => { if (!clip) return VF.toast(t("ae_clip_empty"), true); const [a, b] = sel || [cursor, cursor]; edit(() => { replaceRegion(a, b, clip); sel = [a, a + clip[0].length]; }); },
  delete: () => { if (!sel) return; const [a, b] = sel; edit(() => { replaceRegion(a, b, A.ch.map(() => new Float32Array(0))); cursor = a; sel = null; }); },
  trim: () => { if (!sel) return; const [a, b] = sel; edit(() => { A.ch = A.ch.map((c) => c.slice(a, b)); sel = null; cursor = 0; view = { a: 0, b: b - a }; }); },
  silence: () => { const [a, b] = region(); edit(() => A.ch.forEach((c) => c.fill(0, a, b))); },
  insert_sil: () => { const n = A.sr; edit(() => replaceRegion(cursor, cursor, A.ch.map(() => new Float32Array(n)))); },
  fadein: () => { const [a, b] = region(); edit(() => A.ch.forEach((c) => { for (let i = a; i < b; i++) c[i] *= (i - a) / (b - a); })); },
  fadeout: () => { const [a, b] = region(); edit(() => A.ch.forEach((c) => { for (let i = a; i < b; i++) c[i] *= (b - i) / (b - a); })); },
  normalize: () => { const [a, b] = region(); edit(() => normalize(a, b)); },
  louder: () => gain(1.4125), quieter: () => gain(0.7079),
  reverse: () => { const [a, b] = region(); edit(() => A.ch.forEach((c) => c.subarray(a, b).reverse())); },
};
function gain(g) { const [a, b] = region(); edit(() => A.ch.forEach((c) => { for (let i = a; i < b; i++) c[i] = Math.max(-1, Math.min(1, c[i] * g)); })); }
function normalize(a, b, target = 0.891) {
  let peak = 0; A.ch.forEach((c) => { for (let i = a; i < b; i++) peak = Math.max(peak, Math.abs(c[i])); });
  if (peak > 1e-4) { const g = target / peak; A.ch.forEach((c) => { for (let i = a; i < b; i++) c[i] *= g; }); }
}

/* ---------- effects ---------- */
function impulse(o, seconds = 2.4, decay = 3) {
  const n = Math.floor(o.sampleRate * seconds), ir = o.createBuffer(2, n, o.sampleRate);
  for (let c = 0; c < 2; c++) { const d = ir.getChannelData(c); for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / n, decay); }
  return ir;
}
async function offline(a, b, build, rate = 1) {
  const n = b - a, outLen = Math.max(1, Math.round(n / rate)), o = new OAC(A.ch.length, outLen, A.sr);
  const buf = o.createBuffer(A.ch.length, n, A.sr); A.ch.forEach((c, i) => buf.copyToChannel(c.slice(a, b), i));
  const s = o.createBufferSource(); s.buffer = buf; s.playbackRate.value = rate;
  build(o, s, o.destination); s.start(); const r = await o.startRendering();
  return A.ch.map((_, i) => r.getChannelData(i).slice());
}
const FX = {
  echo: (o, s, out) => { const d = o.createDelay(2); d.delayTime.value = 0.28; const fb = o.createGain(); fb.gain.value = 0.38; const wet = o.createGain(); wet.gain.value = 0.5;
    s.connect(out); s.connect(d); d.connect(fb); fb.connect(d); d.connect(wet); wet.connect(out); },
  reverb: (o, s, out) => { const cv = o.createConvolver(); cv.buffer = impulse(o); const wet = o.createGain(); wet.gain.value = 0.35; const dry = o.createGain(); dry.gain.value = 0.85;
    s.connect(dry); dry.connect(out); s.connect(cv); cv.connect(wet); wet.connect(out); },
  radio: (o, s, out) => { const hp = o.createBiquadFilter(); hp.type = "highpass"; hp.frequency.value = 450; const lp = o.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 3200;
    const ws = o.createWaveShaper(); const curve = new Float32Array(1024); for (let i = 0; i < 1024; i++) { const x = i / 512 - 1; curve[i] = Math.tanh(2.2 * x); } ws.curve = curve;
    s.connect(hp); hp.connect(lp); lp.connect(ws); ws.connect(out); },
  bass: (o, s, out) => { const f = o.createBiquadFilter(); f.type = "lowshelf"; f.frequency.value = 200; f.gain.value = 8; s.connect(f); f.connect(out); },
  treble: (o, s, out) => { const f = o.createBiquadFilter(); f.type = "highshelf"; f.frequency.value = 3500; f.gain.value = 6; s.connect(f); f.connect(out); },
  enhance: (o, s, out) => { const hp = o.createBiquadFilter(); hp.type = "highpass"; hp.frequency.value = 85; const pr = o.createBiquadFilter(); pr.type = "peaking"; pr.frequency.value = 3000; pr.Q.value = 0.9; pr.gain.value = 3.5;
    const mud = o.createBiquadFilter(); mud.type = "peaking"; mud.frequency.value = 300; mud.Q.value = 1; mud.gain.value = -2.5;
    const cp = o.createDynamicsCompressor(); cp.threshold.value = -22; cp.ratio.value = 3.5; cp.attack.value = 0.005; cp.release.value = 0.2;
    s.connect(hp); hp.connect(mud); mud.connect(pr); pr.connect(cp); cp.connect(out); },
  denoise: (o, s, out) => { const lp = o.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 7500; const hp = o.createBiquadFilter(); hp.type = "highpass"; hp.frequency.value = 70;
    s.connect(hp); hp.connect(lp); lp.connect(out); },
  compress: (o, s, out) => { const cp = o.createDynamicsCompressor(); cp.threshold.value = -26; cp.ratio.value = 4; cp.knee.value = 10; s.connect(cp); cp.connect(out); },
};
function pitchShift(x, factor) {        // overlap-add pitch shift (keeps length)
  const N = 2048, H = N / 4, out = new Float32Array(x.length), norm = new Float32Array(x.length), w = new Float32Array(N);
  for (let i = 0; i < N; i++) w[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / N);
  for (let pos = 0; pos + N < x.length; pos += H) {
    for (let i = 0; i < N; i++) { const s = pos + i * factor, j = Math.floor(s), f = s - j; const v = j + 1 < x.length ? x[j] * (1 - f) + x[j + 1] * f : 0;
      out[pos + i] += v * w[i]; norm[pos + i] += w[i] * w[i]; }
  }
  for (let i = 0; i < x.length; i++) if (norm[i] > 1e-3) out[i] /= norm[i];
  return out;
}
async function applyFx(kind) {
  if (!A) return; const [a, b] = region(); stop(); setBusy(true);
  try {
    snapshot(); let res;
    if (kind === "speedup" || kind === "slow") res = await offline(a, b, (o, s, out) => s.connect(out), kind === "speedup" ? 1.1 : 0.9);
    else if (kind === "pitchup" || kind === "pitchdown") res = A.ch.map((c) => pitchShift(c.slice(a, b), kind === "pitchup" ? 1.26 : 0.8));
    else if (kind === "robot") res = A.ch.map((c) => { const o = c.slice(a, b); for (let i = 0; i < o.length; i++) o[i] *= Math.sin((2 * Math.PI * 55 * i) / A.sr) * 1.6; return o; });
    else res = await offline(a, b, FX[kind]);
    replaceRegion(a, b, res);
    if (sel) sel = [a, a + res[0].length];
    if (kind === "enhance" || kind === "compress") normalize(a, a + res[0].length);
    A.ch.forEach((c) => { for (let i = 0; i < c.length; i++) if (c[i] > 1) c[i] = 1; else if (c[i] < -1) c[i] = -1; });
    fitView(); refresh();
  } catch (e) { VF.toast(e.message, true); } finally { setBusy(false); }
}
async function mixIn(blob) {
  setBusy(true);
  try { const other = await decodeOther(blob); edit(() => {
    const need = cursor + other[0].length;
    if (need > len()) A.ch = A.ch.map((c) => { const o = new Float32Array(need); o.set(c); return o; });
    A.ch.forEach((c, i) => { const s = other[i] || other[0]; for (let k = 0; k < s.length; k++) c[cursor + k] = Math.max(-1, Math.min(1, c[cursor + k] + s[k] * 0.7)); });
    sel = [cursor, cursor + other[0].length]; }); }
  catch (_) { VF.toast(t("ae_decode_fail"), true); } finally { setBusy(false); }
}

/* ---------- waveform drawing & interaction ---------- */
const cv = $("aeWave");
function draw(play) {
  if (!A) return; const dpr = devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
  if (cv.width !== Math.round(W * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
  const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
  const css = getComputedStyle(document.documentElement), acc = css.getPropertyValue("--accent").trim() || "#7c5cff", acc2 = css.getPropertyValue("--accent2").trim() || "#3ea6ff";
  const span = view.b - view.a, x2s = (x) => view.a + (x / W) * span, s2x = (s) => ((s - view.a) / span) * W;
  if (sel) { g.fillStyle = "rgba(124,92,255,.22)"; g.fillRect(s2x(sel[0]), 0, s2x(sel[1]) - s2x(sel[0]), H); }
  const nch = A.ch.length, lane = H / nch;
  for (let c = 0; c < nch; c++) {
    const d = A.ch[c], mid = lane * c + lane / 2; const grad = g.createLinearGradient(0, 0, W, 0); grad.addColorStop(0, acc); grad.addColorStop(1, acc2); g.fillStyle = grad;
    for (let x = 0; x < W; x++) {
      const i0 = Math.floor(x2s(x)), i1 = Math.max(i0 + 1, Math.floor(x2s(x + 1))); let mn = 0, mx = 0;
      const step = Math.max(1, Math.floor((i1 - i0) / 200));
      for (let i = i0; i < i1 && i < d.length; i += step) { const v = d[i]; if (v < mn) mn = v; if (v > mx) mx = v; }
      g.fillRect(x, mid - mx * lane * 0.46, 1, Math.max(1, (mx - mn) * lane * 0.46));
    }
    g.fillStyle = "rgba(255,255,255,.08)"; g.fillRect(0, mid, W, 1);
  }
  g.fillStyle = "#ffc857"; g.fillRect(s2x(cursor), 0, 2, H);
  if (play != null) { g.fillStyle = "#fff"; g.fillRect(s2x(play), 0, 2, H); }
  $("aeTime").textContent = `${fmt(play != null ? play : cursor)} / ${fmt(len())}`;
  $("aeSel").textContent = sel ? tf("ae_sel", fmt(sel[0]), fmt(sel[1])) : t("ae_nosel");
  const scr = $("aeScroll"); scr.max = Math.max(0, len() - span); scr.value = view.a; scr.disabled = span >= len();
}
function refresh() { draw(); ["cut", "copy", "delete", "trim"].forEach((k) => ($("ae_" + k).disabled = !sel)); $("aeUndo").disabled = !undo.length; $("aeRedo").disabled = !redo.length; }
cv.addEventListener("pointerdown", (e) => {
  if (!A) return; const r = cv.getBoundingClientRect(), toS = (cx) => Math.round(view.a + Math.min(1, Math.max(0, (cx - r.left) / r.width)) * (view.b - view.a));
  const s0 = toS(e.clientX); cursor = s0; sel = null; cv.setPointerCapture(e.pointerId); draw();
  cv.onpointermove = (m) => { const s1 = toS(m.clientX); sel = Math.abs(s1 - s0) > 50 ? [Math.min(s0, s1), Math.max(s0, s1)] : null; draw(); };
  cv.onpointerup = () => { cv.onpointermove = null; if (sel) cursor = sel[0]; refresh(); };
});
function zoom(f) {
  if (!A) return; const span = view.b - view.a, ns = Math.max(Math.min(len(), 2000), Math.min(len(), Math.round(span / f))), center = sel ? (sel[0] + sel[1]) / 2 : cursor;
  let a = Math.round(center - ns / 2); a = Math.max(0, Math.min(len() - ns, a)); view = { a, b: a + ns }; draw();
}
cv.addEventListener("wheel", (e) => { if (!A) return; e.preventDefault(); if (e.ctrlKey || e.metaKey) zoom(e.deltaY < 0 ? 1.25 : 0.8);
  else { const span = view.b - view.a, d = Math.round(span * 0.1 * Math.sign(e.deltaY || e.deltaX)); const a = Math.max(0, Math.min(len() - span, view.a + d)); view = { a, b: a + span }; draw(); } }, { passive: false });
$("aeScroll").oninput = (e) => { const span = view.b - view.a, a = +e.target.value; view = { a, b: a + span }; draw(); };
$("aeZin").onclick = () => zoom(2); $("aeZout").onclick = () => zoom(0.5); $("aeZfit").onclick = () => { view = { a: 0, b: len() }; draw(); };
addEventListener("resize", () => draw());

/* ---------- playback ---------- */
function toBuffer(a = 0, b = len()) { const buf = ctx().createBuffer(A.ch.length, Math.max(1, b - a), A.sr); A.ch.forEach((c, i) => buf.copyToChannel(c.slice(a, b), i)); return buf; }
function play(onlySel) {
  if (!A) return; stop(); ctx().resume();
  const [a, b] = onlySel && sel ? sel : [cursor >= len() - 10 ? 0 : cursor, len()];
  src = ctx().createBufferSource(); src.buffer = toBuffer(a, b); src.connect(ctx().destination); src.start();
  playStart = ctx().currentTime; playFrom = a; playTo = b; $("aePlay").textContent = t("ae_pause");
  src.onended = () => { if (src) stop(); };
  const tick = () => { if (!src) return; const pos = playFrom + Math.round((ctx().currentTime - playStart) * A.sr); draw(Math.min(pos, playTo)); raf = requestAnimationFrame(tick); }; tick();
}
function stop() { if (src) { const s = src; src = null; try { s.onended = null; s.stop(); } catch (_) {} } cancelAnimationFrame(raf); $("aePlay").textContent = t("ae_play"); draw(); }
$("aePlay").onclick = () => (src ? stop() : play(false)); $("aePlaySel").onclick = () => play(true);

/* ---------- export / save ---------- */
function wavBlob() {
  const n = len(), nc = A.ch.length, data = new DataView(new ArrayBuffer(44 + n * nc * 2));
  const w = (o, s) => [...s].forEach((c, i) => data.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF"); data.setUint32(4, 36 + n * nc * 2, true); w(8, "WAVE"); w(12, "fmt "); data.setUint32(16, 16, true); data.setUint16(20, 1, true);
  data.setUint16(22, nc, true); data.setUint32(24, A.sr, true); data.setUint32(28, A.sr * nc * 2, true); data.setUint16(32, nc * 2, true); data.setUint16(34, 16, true);
  w(36, "data"); data.setUint32(40, n * nc * 2, true);
  let o = 44; for (let i = 0; i < n; i++) for (let c = 0; c < nc; c++) { const v = Math.max(-1, Math.min(1, A.ch[c][i])); data.setInt16(o, v < 0 ? v * 0x8000 : v * 0x7fff, true); o += 2; }
  return new Blob([data], { type: "audio/wav" });
}
async function mp3Blob() {
  const fd = new FormData(); fd.append("file", wavBlob(), "edit.wav"); fd.append("format", "mp3");
  return await (await VF.api("/api/audio/convert", { method: "POST", body: fd })).blob();
}
const save = (blob, ext) => { const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `${name}-edited.${ext}`; a.click(); };
$("aeWav").onclick = () => A && save(wavBlob(), "wav");
$("aeMp3").onclick = async () => { if (!A) return; setBusy(true); try { save(await mp3Blob(), "mp3"); } catch (e) { VF.toast(e.message, true); } finally { setBusy(false); } };
$("aeSave").onclick = async () => { if (!A) return; setBusy(true);
  try { const b = await mp3Blob(); const [m] = await VF.uploadFiles([new File([b], `${name}-edited.mp3`, { type: "audio/mpeg" })]); if (m) VF.toast(t("ae_saved")); }
  catch (e) { VF.toast(e.message, true); } finally { setBusy(false); } };

/* ---------- inputs ---------- */
$("aeFile").onchange = (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) openBlob(f, f.name); };
$("aeLib").onclick = async () => { const a = await VF.pickAsset(["audio"]); if (a) openAsset(a.id, a.name); };
$("aeMix").onclick = async () => { if (!A) return; const a = await VF.pickAsset(["audio"]); if (a) mixIn(await (await VF.api(`/api/assets/${a.id}/file`)).blob()); };
let arec = null;
$("aeRec").onclick = async () => {
  if (arec) { const r = await arec.stop(); arec = null; $("aeRec").textContent = t("ae_record"); $("aeRec").classList.remove("on"); $("aeRecWave").style.display = "none"; openBlob(r.blob, "recording"); return; }
  try { $("aeRecWave").style.display = "block"; arec = await VFMic.record({ canvas: $("aeRecWave"), onTick: (s) => ($("aeRec").textContent = `■ ${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`) }); $("aeRec").classList.add("on"); }
  catch (e) { $("aeRecWave").style.display = "none"; VF.toast(e.message === "NO_MIC" ? t("mic_unsupported") : t("mic_denied"), true); }
};
Object.keys(ops).forEach((k) => { const b = $("ae_" + k); if (b) b.onclick = ops[k]; });
$("aeUndo").onclick = () => restore(undo, redo); $("aeRedo").onclick = () => restore(redo, undo);
$("aeFxApply").onclick = () => applyFx($("aeFx").value);
function setBusy(on) { $("aeBusy").style.display = on ? "inline-block" : "none"; document.querySelectorAll("#viewAudio button").forEach((b) => (b.disabled = on || b.dataset.off === "1")); if (!on && A) refresh(); }
addEventListener("keydown", (e) => {
  if (!$("viewAudio").classList.contains("on") || !A || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
  const k = e.key.toLowerCase(), mod = e.ctrlKey || e.metaKey;
  if (k === " ") { e.preventDefault(); src ? stop() : play(false); }
  else if (mod && k === "z") { e.preventDefault(); e.shiftKey ? restore(redo, undo) : restore(undo, redo); }
  else if (mod && k === "y") { e.preventDefault(); restore(redo, undo); }
  else if (mod && k === "x") { e.preventDefault(); ops.cut(); } else if (mod && k === "c") { e.preventDefault(); ops.copy(); } else if (mod && k === "v") { e.preventDefault(); ops.paste(); }
  else if (k === "delete" || k === "backspace") { e.preventDefault(); ops.delete(); }
});
// "Edit in audio editor" from the Text-to-Speech tab
$("editAudioBtn").onclick = async () => { const a = $("audio"); if (!a.src) return VF.toast(t("ae_empty"), true); await openBlob(await (await fetch(a.src)).blob(), "speech"); VF.showView("audio"); };

function fillFx() { const s = $("aeFx"), cur = s.value; s.innerHTML = ""; ["enhance", "denoise", "compress", "echo", "reverb", "radio", "bass", "treble", "speedup", "slow", "pitchup", "pitchdown", "robot"]
  .forEach((k) => { const o = document.createElement("option"); o.value = k; o.textContent = t("ae_fx_" + k); s.appendChild(o); }); if (cur) s.value = cur; }
VF.on("ready", fillFx); VF.on("ui", () => { fillFx(); if (A) refresh(); $("aePlay").textContent = t(src ? "ae_pause" : "ae_play"); });
VF.on("view", (v) => { if (v === "audio") setTimeout(() => draw(), 30); else stop(); });
window.VFAudio = { openBlob, openAsset, _state: () => A, _ops: ops, _applyFx: applyFx, _wav: wavBlob };
})();
