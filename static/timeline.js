/* Timeline editor: multi-track editing (video, overlays/text, audio) with a live preview that plays in the browser,
   drag / trim / split / snap, undo, inspector, and MP4 export through /api/timeline/render.
   The timeline is stored in the Video Studio project (V.project.timeline), so New / Save / Open include it. */
(() => {
"use strict";
const VF = window.VF, $ = VF.$, t = VF.t, tf = VF.tf;
const KIND_OF = { video: ["video", "image", "color"], overlay: ["video", "image", "text"], audio: ["audio"] };
const uid = () => Math.random().toString(36).slice(2, 10);
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const fmt = (s) => { s = Math.max(0, s); const m = Math.floor(s / 60); return `${m}:${(s % 60).toFixed(1).padStart(4, "0")}`; };
let T = null, sel = null, pps = 60, playhead = 0, playing = false, snap = true, undo = [], redo = [], raf = 0, t0 = 0, p0 = 0;
const els = new Map();   // clip id -> preview element

/* ---------------- model ---------------- */
function defaults() {
  const p = VF.V.project || {};
  return { ratio: p.ratio || "16:9", resolution: p.resolution || "1080", background: "#000000", tracks: [
    { id: uid(), kind: "video", name: t("tl_tr_video"), clips: [] },
    { id: uid(), kind: "overlay", name: t("tl_tr_overlay"), clips: [] },
    { id: uid(), kind: "overlay", name: t("tl_tr_text"), clips: [] },
    { id: uid(), kind: "audio", name: t("tl_tr_voice"), clips: [] },
    { id: uid(), kind: "audio", name: t("tl_tr_music"), clips: [] },
    { id: uid(), kind: "audio", name: t("tl_tr_sfx"), clips: [] }] };
}
function load() {
  const p = VF.V.project; if (!p) return;
  if (!p.timeline || !Array.isArray(p.timeline.tracks)) p.timeline = defaults();
  T = p.timeline; T.tracks.forEach((tr) => { tr.id = tr.id || uid(); tr.clips.forEach((c) => (c.id = c.id || uid())); });
  sel = null; undo = []; redo = []; playhead = Math.min(playhead, duration());
}
const duration = () => T ? Math.max(0, ...T.tracks.flatMap((tr) => tr.clips.map((c) => c.start + c.dur))) : 0;
const findClip = (id) => { for (const tr of T.tracks) { const c = tr.clips.find((x) => x.id === id); if (c) return [tr, c]; } return [null, null]; };
function snapshot() { undo.push(JSON.stringify(T.tracks)); if (undo.length > 60) undo.shift(); redo = []; }
function restore(from, to) { if (!from.length) return; to.push(JSON.stringify(T.tracks)); T.tracks = JSON.parse(from.pop()); if (sel && !findClip(sel)[1]) sel = null; changed(); }
function changed(soft) { VF.markDirty(); render(); if (!soft) inspector(); preview(); }
function serialize() {
  return { ratio: T.ratio, resolution: T.resolution, background: T.background, tracks: T.tracks.map((tr) => ({ kind: tr.kind, muted: !!tr.muted, hidden: !!tr.hidden,
    volume: tr.volume == null ? 1 : tr.volume, clips: tr.clips.map(({ id, name, srcDur, ...c }) => c) })) };
}

/* ---------------- adding clips ---------------- */
function mediaDuration(asset, kind) {
  if (kind === "image") return Promise.resolve(null);
  return new Promise((res) => { const m = document.createElement(kind === "audio" ? "audio" : "video"); m.preload = "metadata";
    m.onloadedmetadata = () => res(isFinite(m.duration) ? m.duration : null); m.onerror = () => res(null); m.src = `/api/assets/${asset}/file`; setTimeout(() => res(null), 8000); });
}
function trackFor(kind, prefer) {
  if (prefer) { const tr = T.tracks.find((x) => x.name === prefer && x.kind === kind); if (tr) return tr; }
  const selTr = sel && findClip(sel)[0]; if (selTr && selTr.kind === kind) return selTr;
  return T.tracks.find((x) => x.kind === kind);
}
function freeStart(tr, at, dur) {   // first position >= at without overlapping existing clips on the track
  let s = at; const sorted = tr.clips.slice().sort((a, b) => a.start - b.start);
  for (const c of sorted) if (s < c.start + c.dur && s + dur > c.start) s = c.start + c.dur;
  return +s.toFixed(3);
}
async function addAsset(a, opts = {}) {
  const kind = a.kind, srcDur = await mediaDuration(a.id, kind);
  const trackKind = opts.track || (kind === "audio" ? "audio" : "video");
  const tr = trackFor(trackKind, opts.prefer); if (!tr) return;
  const dur = opts.dur || (srcDur ? Math.min(srcDur, 600) : (kind === "image" ? 5 : 5));
  snapshot();
  const c = { id: uid(), type: kind, asset: a.id, name: a.name, srcDur, start: freeStart(tr, opts.at != null ? opts.at : playhead, dur), dur: +dur.toFixed(3), in: 0,
    volume: opts.volume != null ? opts.volume : 1, fade_in: 0, fade_out: 0, opacity: 1 };
  if (tr.kind === "video") c.fit = "cover";
  if (tr.kind === "overlay") Object.assign(c, { x: 0.78, y: 0.25, w: 0.3, anim: "pop" });
  tr.clips.push(c); sel = c.id; changed();
  if (a.attribution) VF.toast(t("lib_credit") + " " + a.attribution);
}
function addText() {
  const tr = trackFor("overlay", t("tl_tr_text")); snapshot();
  const c = { id: uid(), type: "text", name: t("tl_text"), text: t("tl_text_default"), start: freeStart(tr, playhead, 4), dur: 4, x: 0.5, y: 0.82, w: 0.8,
    size: 0.07, color: "#ffffff", box: "#000000aa", bold: true, align: "center", anim: "rise", fade_in: 0, fade_out: 0.3, opacity: 1, in: 0, volume: 1 };
  tr.clips.push(c); sel = c.id; changed();
}
function addColor() {
  const tr = trackFor("video"); snapshot();
  const c = { id: uid(), type: "color", name: t("tl_color"), color: "#1d4e9e", start: freeStart(tr, playhead, 3), dur: 3, in: 0, fit: "cover", fade_in: 0, fade_out: 0, opacity: 1, volume: 1 };
  tr.clips.push(c); sel = c.id; changed();
}
async function fromScenes() {
  if (T.tracks.some((tr) => tr.clips.length) && !confirm(t("tl_from_scenes_confirm"))) return;
  const btn = $("tlFromScenes"); btn.disabled = true; setStatus(t("tl_from_scenes_working"));
  try {
    const r = await (await VF.postJson("/api/timeline/from-scenes", { project: VF.projectPayload() })).json();
    snapshot();
    const set = (name, kind, clips) => { const tr = trackFor(kind, name) || T.tracks.find((x) => x.kind === kind); tr.clips = clips.map((c) => ({ id: uid(), opacity: 1, fade_in: 0, fade_out: 0, volume: 1, ...c, srcDur: c.type === "image" ? null : c.dur })); };
    set(t("tl_tr_video"), "video", r.video); set(t("tl_tr_voice"), "audio", r.voice); set(t("tl_tr_music"), "audio", r.music);
    T.ratio = r.ratio; T.resolution = r.resolution; playhead = 0; sel = null; changed(); setStatus(tf("tl_from_scenes_done", r.video.length));
  } catch (e) { setStatus(""); VF.toast(e.message, true); } finally { btn.disabled = false; }
}
let rec = null;
async function recordVoice() {
  const b = $("tlRec");
  if (rec) { const r = await rec.stop(); rec = null; b.classList.remove("on"); b.title = t("tl_rec");
    const [m] = await VF.uploadFiles([new File([r.blob], `voice-${Date.now()}.${r.ext}`, { type: r.blob.type })]); if (m) addAsset(m, { prefer: t("tl_tr_voice"), at: recAt }); return; }
  try { recAt = playhead; rec = await VFMic.record({ onTick: (s) => setStatus(`● ${fmt(s)}`) }); b.classList.add("on"); b.title = t("tl_rec_stop"); }
  catch (e) { rec = null; VF.toast(e.message === "NO_MIC" ? t("mic_unsupported") : t("mic_denied"), true); }
}
let recAt = 0;

/* ---------------- editing ---------------- */
function split() {
  const targets = sel ? [findClip(sel)] : T.tracks.flatMap((tr) => tr.clips.filter((c) => playhead > c.start && playhead < c.start + c.dur).map((c) => [tr, c]));
  const valid = targets.filter(([, c]) => c && playhead > c.start + 0.05 && playhead < c.start + c.dur - 0.05);
  if (!valid.length) return VF.toast(t("tl_split_none"), true);
  snapshot();
  valid.forEach(([tr, c]) => { const cut = playhead - c.start; const b = { ...JSON.parse(JSON.stringify(c)), id: uid(), start: +playhead.toFixed(3), dur: +(c.dur - cut).toFixed(3), in: +((c.in || 0) + cut).toFixed(3), fade_in: 0 };
    c.dur = +cut.toFixed(3); c.fade_out = 0; tr.clips.push(b); });
  changed();
}
function del() { if (!sel) return; const [tr, c] = findClip(sel); if (!c) return; snapshot(); tr.clips = tr.clips.filter((x) => x !== c); sel = null; changed(); }
function dup() { if (!sel) return; const [tr, c] = findClip(sel); if (!c) return; snapshot(); const n = { ...JSON.parse(JSON.stringify(c)), id: uid() }; n.start = freeStart(tr, c.start + c.dur, c.dur); tr.clips.push(n); sel = n.id; changed(); }
function addTrack(kind) { snapshot(); T.tracks.push({ id: uid(), kind, name: t("tl_tr_" + (kind === "overlay" ? "overlay" : kind)) + " " + (T.tracks.filter((x) => x.kind === kind).length + 1), clips: [] }); changed(); }

/* ---------------- timeline rendering ---------------- */
function render() {
  if (!T) return;
  const total = Math.max(duration() + 10, 30), width = total * pps;
  const ruler = $("tlRuler"), lanes = $("tlLanes"), heads = $("tlHeads");
  ruler.style.width = lanes.style.width = width + "px"; ruler.innerHTML = ""; lanes.innerHTML = ""; heads.innerHTML = "";
  const step = pps > 120 ? 1 : pps > 40 ? 5 : pps > 15 ? 10 : 30;
  for (let s = 0; s <= total; s += step) { const m = document.createElement("span"); m.style.left = s * pps + "px"; m.textContent = fmt(s).replace(/\.0$/, ""); ruler.appendChild(m); }
  // display order like other editors: picture tracks with the top layer first, then audio tracks
  const order = [...T.tracks.map((tr, ti) => [tr, ti]).filter(([tr]) => tr.kind !== "audio").reverse(), ...T.tracks.map((tr, ti) => [tr, ti]).filter(([tr]) => tr.kind === "audio")];
  order.forEach(([tr, ti]) => {
    const h = document.createElement("div"); h.className = "tl-head k-" + tr.kind;
    h.innerHTML = `<i></i><b></b><button class="tl-ic" data-a="mute"></button><button class="tl-ic" data-a="hide"></button><button class="tl-ic" data-a="up">↑</button>`;
    h.querySelector("i").textContent = tr.kind === "audio" ? "♪" : tr.kind === "video" ? "▣" : "T";
    const name = h.querySelector("b"); name.textContent = tr.name; name.title = t("tl_rename"); name.ondblclick = () => { const v = prompt(t("tl_rename"), tr.name); if (v) { tr.name = v.slice(0, 30); changed(true); } };
    const mute = h.querySelector('[data-a="mute"]'); mute.textContent = tr.muted ? "🔇" : "🔊"; mute.title = t("tl_mute"); mute.style.visibility = tr.kind === "overlay" ? "hidden" : "";
    mute.onclick = () => { tr.muted = !tr.muted; changed(true); };
    const hide = h.querySelector('[data-a="hide"]'); hide.textContent = tr.hidden ? "🙈" : "👁"; hide.title = t("tl_hide"); hide.style.visibility = tr.kind === "audio" ? "hidden" : "";
    hide.onclick = () => { tr.hidden = !tr.hidden; changed(true); };
    const up = h.querySelector('[data-a="up"]'); up.title = t("tl_track_up"); up.disabled = ti === T.tracks.length - 1;
    up.onclick = () => { snapshot(); [T.tracks[ti], T.tracks[ti + 1]] = [T.tracks[ti + 1], T.tracks[ti]]; changed(true); };
    heads.appendChild(h);
    const lane = document.createElement("div"); lane.className = "tl-lane k-" + tr.kind + (tr.hidden || tr.muted ? " off" : ""); lane.dataset.track = tr.id;
    tr.clips.forEach((c) => lane.appendChild(clipEl(tr, c)));
    lane.onpointerdown = (e) => { if (e.target === lane) { sel = null; seek((e.offsetX) / pps); render(); inspector(); } };
    lanes.appendChild(lane);
  });
  $("tlPlayhead").style.left = playhead * pps + "px";
  $("tlTime").textContent = `${fmt(playhead)} / ${fmt(duration())}`;
  $("tlEmpty").style.display = T.tracks.some((tr) => tr.clips.length) ? "none" : "block";
}
function clipEl(tr, c) {
  const e = document.createElement("div"); e.className = "tl-clip t-" + c.type + (c.id === sel ? " on" : ""); e.dataset.id = c.id;
  e.style.left = c.start * pps + "px"; e.style.width = Math.max(6, c.dur * pps) + "px";
  if ((c.type === "image" || c.type === "video") && c.asset) e.style.backgroundImage = `url(/api/assets/${c.asset}/thumb)`;
  if (c.type === "color") e.style.background = c.color;
  const lab = document.createElement("span"); lab.textContent = c.type === "text" ? c.text.split("\n")[0] : (c.name || c.type); e.appendChild(lab);
  ["l", "r"].forEach((side) => { const hnd = document.createElement("i"); hnd.className = "h " + side; hnd.onpointerdown = (ev) => startDrag(ev, tr, c, side); e.appendChild(hnd); });
  e.onpointerdown = (ev) => startDrag(ev, tr, c, "move");
  return e;
}
function snapTo(v, exclude) {
  if (!snap) return v;
  const pts = [0, playhead]; T.tracks.forEach((tr) => tr.clips.forEach((c) => { if (c.id !== exclude) pts.push(c.start, c.start + c.dur); }));
  let best = v, dist = 8 / pps; pts.forEach((p) => { if (Math.abs(p - v) < dist) { dist = Math.abs(p - v); best = p; } });
  return best;
}
function startDrag(ev, tr, c, mode) {
  ev.stopPropagation(); ev.preventDefault(); sel = c.id;
  const el = ev.currentTarget.closest(".tl-clip"), x0 = ev.clientX, start0 = c.start, dur0 = c.dur, in0 = c.in || 0;
  let moved = false, overLane = null;
  document.querySelectorAll(".tl-clip.on").forEach((x) => x.classList.remove("on")); el.classList.add("on");
  const maxLen = (c.type === "video" || c.type === "audio") && c.srcDur ? c.srcDur : Infinity;
  const mv = (m) => {
    const dx = (m.clientX - x0) / pps; if (!moved && Math.abs(m.clientX - x0) < 3 && Math.abs(m.clientY - ev.clientY) < 3) return;
    if (!moved) { moved = true; snapshot(); el.classList.add("drag"); }
    if (mode === "move") {
      let s = Math.max(0, start0 + dx); const sStart = snapTo(s, c.id), sEnd = snapTo(s + c.dur, c.id) - c.dur;
      s = sStart !== s ? sStart : sEnd !== s ? sEnd : s; c.start = +Math.max(0, s).toFixed(3);
      const over = document.elementFromPoint(m.clientX, m.clientY); overLane = over && over.closest(".tl-lane");
      document.querySelectorAll(".tl-lane.drop").forEach((l) => l.classList.remove("drop"));
      if (overLane && overLane.dataset.track !== tr.id) overLane.classList.add("drop");
    } else if (mode === "r") {
      c.dur = +clamp(snapTo(start0 + dur0 + dx, c.id) - start0, 0.1, maxLen - in0).toFixed(3);
    } else {
      const ns = clamp(snapTo(start0 + dx, c.id), Math.max(0, start0 - (c.type === "video" || c.type === "audio" ? in0 : Infinity)), start0 + dur0 - 0.1);
      const d = ns - start0; c.start = +ns.toFixed(3); c.dur = +(dur0 - d).toFixed(3); c.in = +Math.max(0, in0 + d).toFixed(3);
    }
    el.style.left = c.start * pps + "px"; el.style.width = Math.max(6, c.dur * pps) + "px";
    $("tlTime").textContent = `${fmt(playhead)} / ${fmt(duration())}`; preview();
  };
  const up = () => {
    removeEventListener("pointermove", mv); removeEventListener("pointerup", up);
    document.querySelectorAll(".tl-lane.drop").forEach((l) => l.classList.remove("drop"));
    if (moved && mode === "move" && overLane && overLane.dataset.track !== tr.id) {     // dropped on another track
      const nt = T.tracks.find((x) => x.id === overLane.dataset.track);
      if (nt && KIND_OF[nt.kind].includes(c.type)) {
        tr.clips = tr.clips.filter((x) => x !== c); nt.clips.push(c);
        if (nt.kind === "overlay" && c.x == null) Object.assign(c, { x: 0.5, y: 0.5, w: 0.5, anim: "fade" });
        if (nt.kind === "video" && !c.fit) c.fit = "cover";
      } else VF.toast(t("tl_wrong_track"), true);
    }
    if (moved) VF.markDirty();
    render(); inspector(); preview();
  };
  addEventListener("pointermove", mv); addEventListener("pointerup", up);
}

/* ---------------- preview (plays in the browser, no export needed) ---------------- */
function stageSize() { const [a, b] = T.ratio.split(":").map(Number); const st = $("tlStage"), wrap = $("tlStageWrap");
  const maxW = wrap.clientWidth, maxH = Math.max(160, wrap.clientHeight || 360); let w = maxW, h = w * b / a; if (h > maxH) { h = maxH; w = h * a / b; }
  st.style.width = w + "px"; st.style.height = h + "px"; return [w, h]; }
function preview() {
  if (!T || !$("viewTimeline").classList.contains("on")) return;
  const [W, H] = stageSize(), st = $("tlStage"); st.style.background = T.background;
  const live = new Set();
  T.tracks.forEach((tr, ti) => tr.clips.forEach((c) => {
    const active = playhead >= c.start && playhead < c.start + c.dur;
    if (!active || (tr.hidden && tr.kind !== "audio")) return;
    live.add(c.id); let el = els.get(c.id);
    if (!el || el.dataset.type !== c.type || el.dataset.asset !== (c.asset || "")) {
      if (el) el.remove();
      el = c.type === "video" ? document.createElement("video") : c.type === "audio" ? document.createElement("audio") : c.type === "image" ? document.createElement("img") : document.createElement("div");
      el.dataset.type = c.type; el.dataset.asset = c.asset || ""; el.className = "tl-el";
      if (c.asset) { el.src = `/api/assets/${c.asset}/file`; if (el.tagName !== "IMG") { el.preload = "auto"; el.playsInline = true; } }
      st.appendChild(el); els.set(c.id, el);
    }
    const local = playhead - c.start;
    let op = c.opacity == null ? 1 : c.opacity;
    if (c.fade_in && local < c.fade_in) op *= local / c.fade_in; if (c.fade_out && local > c.dur - c.fade_out) op *= (c.dur - local) / c.fade_out;
    if (tr.kind === "overlay" && ["fade", "slide", "rise"].includes(c.anim) && !c.fade_in && local < 0.35) op *= local / 0.35;
    el.style.opacity = clamp(op, 0, 1); el.style.zIndex = ti + 1;
    if (tr.kind === "video") { Object.assign(el.style, { left: 0, top: 0, width: "100%", height: "100%", transform: "none", objectFit: c.fit || "cover" }); if (c.type === "color") el.style.background = c.color; }
    else if (tr.kind === "overlay") {
      const e = 1 - Math.pow(1 - clamp(local / 0.5, 0, 1), 3);
      let dx = 0, dy = 0, sc = 1; if (c.anim === "slide") dx = -0.25 * W * (1 - e); if (c.anim === "rise") dy = 0.12 * H * (1 - e);
      if (c.anim === "pop") { const q = clamp(local / 0.35, 0.05, 1); sc = q * (1 + 0.15 * Math.sin(Math.PI * q)); }
      Object.assign(el.style, { left: c.x * 100 + "%", top: c.y * 100 + "%", width: c.type === "text" ? c.w * 100 + "%" : c.w * 100 + "%", height: "auto",
        transform: `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) scale(${sc})` });
      if (c.type === "text") { el.textContent = c.text; el.dir = "auto"; Object.assign(el.style, { fontSize: c.size * H + "px", color: c.color, fontWeight: c.bold ? 700 : 400,
        textAlign: c.align === "center" ? "center" : c.align === "end" ? "end" : "start", background: c.box ? hexA(c.box) : "transparent", padding: c.box ? `${c.size * H * 0.3}px ${c.size * H * 0.45}px` : 0,
        borderRadius: c.size * H * 0.35 + "px", textShadow: c.box ? "none" : "0 2px 6px rgba(0,0,0,.6)", width: "auto", maxWidth: c.w * 100 + "%", whiteSpace: "pre-wrap", lineHeight: 1.25 }); }
    } else { el.style.display = "none"; }
    if (el.tagName === "VIDEO" || el.tagName === "AUDIO") {
      const want = (c.in || 0) + local; el.volume = clamp((c.volume == null ? 1 : c.volume) * (tr.volume == null ? 1 : tr.volume), 0, 1); el.muted = !!tr.muted;
      if (playing) { if (Math.abs(el.currentTime - want) > 0.3) el.currentTime = want; if (el.paused) el.play().catch(() => {}); }
      else { el.pause(); if (Math.abs(el.currentTime - want) > 0.05) el.currentTime = want; }
    }
  }));
  els.forEach((el, id) => { if (!live.has(id)) { if (el.pause) el.pause(); el.remove(); els.delete(id); } });
  $("tlPlayhead").style.left = playhead * pps + "px"; $("tlTime").textContent = `${fmt(playhead)} / ${fmt(duration())}`;
  const sc = $("tlScrub"); if (sc && document.activeElement !== sc) { sc.max = Math.max(0.1, duration()).toFixed(2); sc.value = playhead.toFixed(2); }
}
function hexA(h) { if (h.length === 9) { const a = parseInt(h.slice(7), 16) / 255; return `rgba(${parseInt(h.slice(1, 3), 16)},${parseInt(h.slice(3, 5), 16)},${parseInt(h.slice(5, 7), 16)},${a.toFixed(2)})`; } return h; }
function seek(s) { playhead = clamp(s, 0, Math.max(duration(), 0)); if (playing) { t0 = performance.now(); p0 = playhead; } preview(); }
function play() {
  if (playing) return stop();
  if (playhead >= duration() - 0.05) playhead = 0;
  playing = true; t0 = performance.now(); p0 = playhead; $("tlPlay").textContent = "❚❚";
  const tick = () => { if (!playing) return; playhead = p0 + (performance.now() - t0) / 1000;
    if (playhead >= duration()) { playhead = duration(); stop(); preview(); return; }
    preview(); const lanes = $("tlScroll"), x = playhead * pps; if (x > lanes.scrollLeft + lanes.clientWidth - 80) lanes.scrollLeft = x - 120;
    raf = requestAnimationFrame(tick); };
  tick();
}
function stop() { playing = false; cancelAnimationFrame(raf); $("tlPlay").textContent = "▶"; els.forEach((el) => el.pause && el.pause()); }

/* ---------------- inspector ---------------- */
function field(label, input) { const w = document.createElement("label"); w.className = "tl-f"; const s = document.createElement("span"); s.textContent = label; w.append(s, input); return w; }
function num(val, step, min, max, on) { const i = document.createElement("input"); i.type = "number"; i.step = step; if (min != null) i.min = min; if (max != null) i.max = max; i.value = +(+val).toFixed(3);
  i.onchange = () => { const v = parseFloat(i.value); if (isFinite(v)) { snapshot(); on(v); changed(true); } }; return i; }
function sel_(opts, val, on) { const s = document.createElement("select"); opts.forEach(([v, l]) => { const o = document.createElement("option"); o.value = v; o.textContent = l; s.appendChild(o); }); s.value = val; s.onchange = () => { snapshot(); on(s.value); changed(true); }; return s; }
function range(val, min, max, on) { const r = document.createElement("input"); r.type = "range"; r.min = min; r.max = max; r.value = val; let snapped = false; r.oninput = () => { if (!snapped) { snapshot(); snapped = true; } on(+r.value); VF.markDirty(); preview(); render(); }; r.onchange = () => (snapped = false); return r; }
function inspector() {
  const box = $("tlInspector"); box.innerHTML = "";
  const h = document.createElement("h4"); box.appendChild(h);
  const [tr, c] = sel ? findClip(sel) : [null, null];
  if (!c) {
    h.textContent = t("tl_project");
    box.append(field(t("v_ratio_short"), sel_(VF.cfg.ratios.map((r) => [r.id, r.id]), T.ratio, (v) => (T.ratio = v))),
      field(t("v_res_short"), sel_(VF.cfg.resolutions.map((r) => [r.id, r.label.replace(/ \(.*\)/, "")]), T.resolution, (v) => (T.resolution = v))));
    const bg = document.createElement("input"); bg.type = "color"; bg.value = T.background; bg.oninput = () => { T.background = bg.value; VF.markDirty(); preview(); };
    box.append(field(t("tl_bg"), bg));
    const p = document.createElement("p"); p.className = "hint"; p.textContent = t("tl_hint"); box.appendChild(p);
    return;
  }
  h.textContent = c.type === "text" ? t("tl_text") : c.name || c.type;
  const g = document.createElement("div"); g.className = "tl-grid"; box.appendChild(g);
  g.append(field(t("tl_start"), num(c.start, 0.1, 0, null, (v) => (c.start = Math.max(0, v)))), field(t("tl_dur"), num(c.dur, 0.1, 0.1, null, (v) => (c.dur = Math.max(0.1, v)))));
  if (c.type === "video" || c.type === "audio") g.append(field(t("tl_in"), num(c.in || 0, 0.1, 0, null, (v) => (c.in = Math.max(0, v)))));
  g.append(field(t("tl_fade_in"), num(c.fade_in || 0, 0.1, 0, c.dur / 2, (v) => (c.fade_in = clamp(v, 0, c.dur / 2)))), field(t("tl_fade_out"), num(c.fade_out || 0, 0.1, 0, c.dur / 2, (v) => (c.fade_out = clamp(v, 0, c.dur / 2)))));
  if (c.type === "video" || c.type === "audio") g.append(field(t("tl_volume") + ` ${Math.round((c.volume == null ? 1 : c.volume) * 100)}%`, range(Math.round((c.volume == null ? 1 : c.volume) * 100), 0, 200, (v) => (c.volume = v / 100))));
  if (tr.kind !== "audio") g.append(field(t("tl_opacity"), range(Math.round((c.opacity == null ? 1 : c.opacity) * 100), 0, 100, (v) => (c.opacity = v / 100))));
  if (tr.kind === "video") g.append(field(t("v_media_fit"), sel_([["cover", t("fit_cover")], ["contain", t("fit_contain")]], c.fit || "cover", (v) => (c.fit = v))));
  if (c.type === "color") { const ci = document.createElement("input"); ci.type = "color"; ci.value = c.color; ci.oninput = () => { c.color = ci.value; VF.markDirty(); preview(); render(); }; g.append(field(t("colour"), ci)); }
  if (tr.kind === "overlay") {
    g.append(field(t("tl_anim"), sel_(["none", "fade", "slide", "rise", "pop"].map((a) => [a, t("an_" + a)]), c.anim || "fade", (v) => (c.anim = v))),
      field("X", range(Math.round(c.x * 100), -20, 120, (v) => (c.x = v / 100))), field("Y", range(Math.round(c.y * 100), -20, 120, (v) => (c.y = v / 100))),
      field(t("ly_size"), range(Math.round(c.w * 100), 3, 150, (v) => (c.w = v / 100))));
  }
  if (c.type === "text") {
    const ta = document.createElement("textarea"); ta.value = c.text; ta.dir = "auto"; ta.rows = 3; let s1 = false;
    ta.oninput = () => { if (!s1) { snapshot(); s1 = true; } c.text = ta.value.slice(0, 600); VF.markDirty(); preview(); render(); };
    const col = document.createElement("input"); col.type = "color"; col.value = c.color; col.oninput = () => { c.color = col.value; VF.markDirty(); preview(); };
    const boxOn = document.createElement("input"); boxOn.type = "checkbox"; boxOn.checked = !!c.box; boxOn.onchange = () => { snapshot(); c.box = boxOn.checked ? "#000000aa" : ""; changed(true); };
    box.append(field(t("tl_text"), ta));
    g.append(field(t("tl_size"), range(Math.round(c.size * 1000), 20, 300, (v) => (c.size = v / 1000))), field(t("colour"), col), field(t("tl_box"), boxOn),
      field(t("tl_bold"), Object.assign(document.createElement("input"), { type: "checkbox", checked: c.bold, onchange: (e) => { snapshot(); c.bold = e.target.checked; changed(true); } })),
      field(t("tl_align"), sel_([["start", t("tl_al_start")], ["center", t("tl_al_center")], ["end", t("tl_al_end")]], c.align || "center", (v) => (c.align = v))));
  }
  const row = document.createElement("div"); row.className = "row";
  const d1 = Object.assign(document.createElement("button"), { className: "btn sm", textContent: t("tl_split"), onclick: split });
  const d2 = Object.assign(document.createElement("button"), { className: "btn sm", textContent: t("v_dup"), onclick: dup });
  const d3 = Object.assign(document.createElement("button"), { className: "btn sm danger", textContent: t("v_del"), onclick: del });
  row.append(d1, d2, d3); box.appendChild(row);
}

/* ---------------- export ---------------- */
function setStatus(m, cls = "") { const e = $("tlStatus"); e.textContent = m; e.className = "hint " + cls; }
async function exportMp4() {
  if (!duration()) return VF.toast(t("tl_empty_export"), true);
  stop(); const b = $("tlExport"); b.disabled = true; $("tlBar").style.display = "block"; $("tlBarFill").style.width = "2%"; setStatus(t("queued"));
  try {
    const { job_id } = await (await VF.postJson("/api/timeline/render", { timeline: serialize() })).json();
    const poll = async () => {
      const j = await (await VF.api(`/api/jobs/${job_id}`)).json(); $("tlBarFill").style.width = Math.max(3, Math.round(j.progress * 100)) + "%";
      if (j.status === "done") { b.disabled = false; setStatus(t("render_done"), "ok"); showResult(job_id, j.duration); return; }
      if (j.status === "error") { b.disabled = false; $("tlBar").style.display = "none"; setStatus(t("render_fail") + j.error, "err"); return; }
      setStatus(`${t("rendering")}… ${Math.round(j.progress * 100)}%`); setTimeout(poll, 1000);
    };
    poll();
  } catch (e) { b.disabled = false; $("tlBar").style.display = "none"; setStatus(t("render_fail") + e.message, "err"); }
}
function showResult(id, dur) {
  const box = document.createElement("div"); const v = document.createElement("video"); v.controls = true; v.playsInline = true; v.src = `/api/jobs/${id}/video.mp4`;
  const row = document.createElement("div"); row.className = "row";
  const dl = Object.assign(document.createElement("a"), { className: "btn primary", href: `/api/jobs/${id}/video.mp4?download=1`, textContent: t("v_dl") });
  const info = Object.assign(document.createElement("span"), { className: "hint", textContent: `${fmt(dur)} · ${T.ratio} · ${T.resolution}p` });
  row.append(dl, info); box.append(v, row); VF.openModal(t("render_done"), box);
}

/* ---------------- wiring ---------------- */
const on = (id, fn) => { const e = $(id); if (e) e.onclick = fn; };
on("tlPlay", play); on("tlStart", () => seek(0)); on("tlEnd", () => seek(duration()));
on("tlSplit", split); on("tlDelete", del); on("tlDup", dup); on("tlUndo", () => restore(undo, redo)); on("tlRedo", () => restore(redo, undo));
on("tlAddMedia", async () => { const a = await VF.pickAsset(["video", "image", "audio"]); if (a) addAsset(a); });
on("tlAddOverlay", async () => { const a = await VFLibrary.open("layer"); if (a) addAsset(a, { track: "overlay", dur: 4 }); });
on("tlAddPhoto", async () => { const a = await VFLibrary.open("background"); if (a) addAsset(a, { track: "video" }); });
on("tlAddText", addText); on("tlAddColor", addColor);
on("tlAddMusic", async () => { const a = await VFLibrary.open("music"); if (a) addAsset(a, { prefer: t("tl_tr_music"), volume: 0.3, at: 0 }); });
on("tlAddSfx", async () => { const a = await VFLibrary.open("sfx"); if (a) addAsset(a, { prefer: t("tl_tr_sfx") }); });
on("tlRec", recordVoice); on("tlFromScenes", fromScenes); on("tlExport", exportMp4);
on("tlAddTrackV", () => addTrack("video")); on("tlAddTrackO", () => addTrack("overlay")); on("tlAddTrackA", () => addTrack("audio"));
$("tlZoom").oninput = (e) => { pps = +e.target.value; render(); };
$("tlScrub").oninput = (e) => seek(+e.target.value);
$("tlSnap").onchange = (e) => (snap = e.target.checked);
$("tlRuler").onpointerdown = (e) => { const r = $("tlRuler").getBoundingClientRect(); const go = (x) => seek((x - r.left) / pps);
  go(e.clientX); const mv = (m) => go(m.clientX); const up = () => { removeEventListener("pointermove", mv); removeEventListener("pointerup", up); };
  addEventListener("pointermove", mv); addEventListener("pointerup", up); };
$("tlScroll").addEventListener("wheel", (e) => { if (e.ctrlKey || e.metaKey) { e.preventDefault(); pps = clamp(pps * (e.deltaY < 0 ? 1.15 : 0.87), 8, 300); $("tlZoom").value = pps; render(); } }, { passive: false });
addEventListener("keydown", (e) => {
  if (!$("viewTimeline").classList.contains("on") || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) || $("modal").classList.contains("on")) return;
  const k = e.key.toLowerCase(), mod = e.ctrlKey || e.metaKey;
  if (k === " ") { e.preventDefault(); play(); }
  else if (k === "s" && !mod) { e.preventDefault(); split(); }
  else if (k === "delete" || k === "backspace") { e.preventDefault(); del(); }
  else if (mod && k === "z") { e.preventDefault(); e.shiftKey ? restore(redo, undo) : restore(undo, redo); }
  else if (mod && k === "y") { e.preventDefault(); restore(redo, undo); }
  else if (mod && k === "d") { e.preventDefault(); dup(); }
  else if (k === "arrowleft") { e.preventDefault(); seek(playhead - (e.shiftKey ? 1 : 1 / 30)); }
  else if (k === "arrowright") { e.preventDefault(); seek(playhead + (e.shiftKey ? 1 : 1 / 30)); }
  else if (k === "home") seek(0); else if (k === "end") seek(duration());
});
addEventListener("resize", () => preview());
function refresh() { titles(); load(); render(); inspector(); preview(); }
VF.on("ready", refresh);
VF.on("view", (v) => { if (v === "timeline") { if (!T || VF.V.project.timeline !== T) load(); render(); inspector(); setTimeout(preview, 30); } else stop(); });
function titles() { document.querySelectorAll("[data-it]").forEach((e) => (e.title = t(e.dataset.it))); }
VF.on("ui", () => { titles(); if (T) { render(); inspector(); } });
VF.on("project", refresh);
window.VFTimeline = { play, stop, split, del, dup, undo: () => restore(undo, redo), redo: () => restore(redo, undo), exportMp4, addText, addColor, fromScenes,
  addMedia: () => $("tlAddMedia").click(), serialize, get state() { return T; }, seek };
})();
