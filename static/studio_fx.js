/* Video studio extras: effects & transitions, recorded voice-over, animated layers (clip art / shapes / photos),
   sound effects, and the free media library (built-in + Openverse). Plugs into app.js through window.VF. */
(() => {
"use strict";
const VF = window.VF, $ = VF.$, t = VF.t, tf = VF.tf;
let LIB = null;
const S = () => VF.sceneAt();
const changed = (prev = true) => { VF.markDirty(); if (prev) VF.schedulePreview(); };

/* ---------------- effects & transitions ---------------- */
const MOTIONS = ["none", "zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up"];
const LOOKS = ["none", "grayscale", "sepia", "vintage", "warm", "cool", "vivid", "blur", "vignette", "dark"];
const TRANS_GROUPS = [
  ["tg_basic", ["fade", "none", "crossfade", "dissolve", "fadeblack", "fadewhite", "fadegrays"]],
  ["tg_wipe", ["wipeleft", "wiperight", "wipeup", "wipedown", "diagtl"]],
  ["tg_slide", ["slideleft", "slideright", "slideup", "slidedown", "smoothleft", "smoothright", "coverleft", "revealleft"]],
  ["tg_shape", ["circleopen", "circleclose", "radial", "vertopen", "horzopen", "squeezeh", "hlslice"]],
  ["tg_fx", ["zoomin", "pixelize", "hblur"]],
];
function fillFx() {
  const opt = (sel, list, pre) => { sel.innerHTML = ""; list.forEach((k) => { const o = document.createElement("option"); o.value = k; o.textContent = t(pre + k); sel.appendChild(o); }); };
  opt($("sMotion"), MOTIONS, "mo_"); opt($("sLook"), LOOKS, "lk_");
  const tr = $("sTrans"); tr.innerHTML = "";
  TRANS_GROUPS.forEach(([g, list]) => { const og = document.createElement("optgroup"); og.label = t(g);
    list.forEach((k) => { const o = document.createElement("option"); o.value = k; o.textContent = t("tn_" + k); og.appendChild(o); }); tr.appendChild(og); });
}
$("sMotion").onchange = (e) => { S().motion = e.target.value; changed(false); };
$("sLook").onchange = (e) => { S().look = e.target.value; changed(); };
$("sTrans").onchange = (e) => { S().transition = e.target.value; changed(false); };

/* ---------------- voice-over (microphone) ---------------- */
let rec = null, recog = null;
const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
function renderVo() {
  const vo = S().voiceover, has = vo && vo.asset, a = $("voAudio");
  $("voHas").style.display = has ? "" : "none";
  if (has && a.dataset.id !== vo.asset) { a.src = `/api/assets/${vo.asset}/file`; a.dataset.id = vo.asset; }
  if (!has) { a.removeAttribute("src"); a.dataset.id = ""; }
  if (!VFMic.supported.record) { $("voRec").disabled = true; $("voRec").title = t("mic_unsupported"); }
  $("voType").parentElement.style.display = VFMic.supported.speech ? "" : "none";
}
$("voRec").onclick = async () => {
  const btn = $("voRec");
  if (rec) {           // stop
    btn.disabled = true; const r = await rec.stop(); rec = null;
    const said = recog ? recog.stop().text : ""; recog = null;
    btn.textContent = t("vo_rec"); btn.classList.remove("on");
    if (r.seconds < 0.6) { btn.disabled = false; return VF.toast(t("vo_short"), true); }
    try {
      const f = new File([r.blob], `voice-scene-${VF.V.sel + 1}.${r.ext}`, { type: r.blob.type });
      const [meta] = await VF.uploadFiles([f]);
      if (meta) { const s = S(); s.voiceover = { asset: meta.id, assetName: meta.name };
        if (said && $("voType").checked && !s.narration.trim()) { s.narration = said; $("sNarr").value = said; $("sNarr").dispatchEvent(new Event("input")); }
        renderVo(); changed(); VF.toast(t("vo_saved")); }
    } finally { btn.disabled = false; }
    return;
  }
  try {
    rec = await VFMic.record({ canvas: $("voWave"), onTick: (s) => ($("voTime").textContent = fmt(s)) });
  } catch (e) { rec = null; return VF.toast(e.message === "NO_MIC" ? t("mic_unsupported") : t("mic_denied"), true); }
  btn.textContent = t("vo_stop"); btn.classList.add("on");
  if ($("voType").checked && VFMic.supported.speech) {
    const lang = VF.V.project.voice.lang || "ar-SA";
    recog = VFMic.recognizer(lang, (fin, interim) => { $("voTime").title = fin + " " + interim; $("prevNote").textContent = (fin + " " + interim).slice(-120); });
  }
};
$("voDel").onclick = () => { S().voiceover = null; renderVo(); changed(false); };
$("voPick").onclick = async () => { const a = await VF.pickAsset(["audio"]); if (a) { S().voiceover = { asset: a.id, assetName: a.name }; renderVo(); changed(false); } };
$("voEdit").onclick = () => { const vo = S().voiceover; if (vo && window.VFAudio) { VFAudio.openAsset(vo.asset, vo.assetName || "voice"); VF.showView("audio"); } };

/* ---------------- sound effect ---------------- */
function renderSfx() {
  const x = S().sfx, has = x && x.asset;
  $("sfxName").textContent = has ? x.assetName || "♪" : t("sx_none");
  $("sfxOpts").style.display = has ? "" : "none"; $("sfxDelRow").style.display = has ? "" : "none";
  if (has) { $("sfxAt").value = x.at || 0; const v = Math.round((x.volume == null ? 0.8 : x.volume) * 100); $("sfxVol").value = v; $("sfxVolVal").textContent = v + "%"; }
}
$("sfxPick").onclick = async () => { const a = await openLibrary("sfx"); if (a) { S().sfx = { asset: a.id, assetName: a.name, at: 0, volume: 0.8 }; renderSfx(); changed(false); } };
$("sfxDel").onclick = () => { S().sfx = null; renderSfx(); changed(false); };
$("sfxAt").oninput = (e) => { S().sfx.at = Math.max(0, +e.target.value || 0); changed(false); };
$("sfxVol").oninput = (e) => { S().sfx.volume = +e.target.value / 100; $("sfxVolVal").textContent = e.target.value + "%"; changed(false); };

/* ---------------- layers (stickers) ---------------- */
const ANIMS = ["pop", "fade", "slide", "rise", "float", "pulse", "spin", "none"];
function renderLayers() {
  const s = S(); s.stickers = s.stickers || [];
  const list = $("layerList"); list.innerHTML = "";
  s.stickers.forEach((k, i) => {
    const row = document.createElement("div"); row.className = "prow layer-row";
    row.innerHTML = `<img alt=""><select></select><label class="mini-l"><span></span><input type="range" min="3" max="100"></label><label class="mini-l"><span></span><input type="number" min="0" max="600" step="0.1" style="width:72px"></label><button class="btn sm danger">✕</button>`;
    row.querySelector("img").src = `/api/assets/${k.asset}/thumb`;
    const sel = row.querySelector("select"); ANIMS.forEach((a) => { const o = document.createElement("option"); o.value = a; o.textContent = t("an_" + a); sel.appendChild(o); }); sel.value = k.anim || "pop";
    sel.onchange = () => { k.anim = sel.value; changed(false); };
    const [szL, stL] = row.querySelectorAll(".mini-l"); szL.firstChild.textContent = t("ly_size"); stL.firstChild.textContent = t("ly_start");
    const sz = szL.querySelector("input"); sz.value = Math.round(k.w * 100); sz.oninput = () => { k.w = +sz.value / 100; placeLayers(); changed(false); };
    const st = stL.querySelector("input"); st.value = k.start || 0; st.oninput = () => { k.start = Math.max(0, +st.value || 0); changed(false); };
    row.querySelector("button").onclick = () => { s.stickers.splice(i, 1); renderLayers(); changed(false); };
    list.appendChild(row);
  });
  $("addLayer").disabled = s.stickers.length >= 10;
  placeLayers();
}
function placeLayers() {
  const host = $("layerHost"), img = $("scenePreview"); host.innerHTML = "";
  const s = S(); if (!s || !img.naturalWidth) return;
  const W = img.clientWidth, H = img.clientHeight;
  host.style.width = W + "px"; host.style.height = H + "px";
  (s.stickers || []).forEach((k) => {
    const el = document.createElement("img"); el.className = "layer"; el.src = `/api/assets/${k.asset}/file`; el.draggable = false;
    el.style.width = k.w * W + "px"; el.style.left = k.x * W + "px"; el.style.top = k.y * H + "px";
    el.onpointerdown = (e) => {
      e.preventDefault(); el.setPointerCapture(e.pointerId); el.classList.add("drag");
      const r = host.getBoundingClientRect();
      el.onpointermove = (m) => { k.x = Math.min(1, Math.max(0, (m.clientX - r.left) / r.width)); k.y = Math.min(1, Math.max(0, (m.clientY - r.top) / r.height));
        el.style.left = k.x * W + "px"; el.style.top = k.y * H + "px"; };
      el.onpointerup = () => { el.onpointermove = null; el.classList.remove("drag"); VF.markDirty(); };
    };
    el.onwheel = (e) => { e.preventDefault(); k.w = Math.min(1, Math.max(0.03, k.w * (e.deltaY < 0 ? 1.08 : 0.92))); placeLayers(); renderLayersSizes(); VF.markDirty(); };
    host.appendChild(el);
  });
}
function renderLayersSizes() { const s = S(); document.querySelectorAll("#layerList .layer-row").forEach((row, i) => { const k = s.stickers[i]; if (k) row.querySelector("input[type=range]").value = Math.round(k.w * 100); }); }
$("scenePreview").addEventListener("load", placeLayers);
addEventListener("resize", placeLayers);
$("addLayer").onclick = async () => {
  const a = await openLibrary("layer"); if (!a) return; const s = S(); s.stickers = s.stickers || [];
  const n = s.stickers.length; s.stickers.push({ asset: a.id, x: 0.78 - (n % 3) * 0.12, y: 0.3 + Math.floor(n / 3) * 0.2, w: a.wide ? 0.4 : 0.18, anim: "pop", start: 0 });
  renderLayers(); changed(false);
};

/* ---------------- free media library ---------------- */
async function lib() { if (!LIB) LIB = await (await VF.api("/api/library")).json(); return LIB; }
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
let player = null;
function play(url, btn) {
  if (player && player.dataset.url === url && !player.paused) { player.pause(); btn.textContent = "▶"; return; }
  if (player) { player.pause(); document.querySelectorAll(".libplay.on").forEach((b) => { b.classList.remove("on"); b.textContent = "▶"; }); }
  player = new Audio(url); player.dataset.url = url; player.play().catch(() => VF.toast(t("lib_preview_fail"), true));
  btn.textContent = "❚❚"; btn.classList.add("on"); player.onended = () => { btn.textContent = "▶"; btn.classList.remove("on"); };
}
// mode: "layer" | "music" | "sfx" | "background"
function openLibrary(mode) {
  return new Promise(async (resolve) => {
    let chosen = null, delegate = null; const L = await lib();
    const tabsDef = {
      layer: ["shapes", "clipart", "photos", "illus", "mine_img"],
      background: ["photos", "illus", "mine_img"],
      music: ["music", "mine_audio"],
      sfx: ["sfx_builtin", "sfx_online", "mine_audio"],
    }[mode];
    const box = el("div"); const tabs = el("div", "chips libtabs"); const body = el("div", "libbody");
    box.append(tabs, body);
    const done = (a) => { chosen = a; if (player) player.pause(); VF.closeModal(); };
    const busy = (b, on) => { b.disabled = on; if (on) b.dataset.t = b.textContent, b.textContent = "…"; else if (b.dataset.t) b.textContent = b.dataset.t; };
    function show(tab) {
      tabs.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.k === tab)); body.innerHTML = "";
      ({ shapes, clipart, photos: () => online("image", "photograph", L.image_topics), illus: () => online("image", "illustration", ["clipart", "icon", "cartoon", "diagram", "infographic", "school", "science", "map"]),
         music: () => online("audio", "music", L.music_topics), sfx_online: () => online("audio", "sound_effect", L.sfx_topics), sfx_builtin: builtinSfx,
         mine_img: () => mine(["image"]), mine_audio: () => mine(["audio"]) })[tab]();
    }
    tabsDef.forEach((k, i) => { const b = el("button", "rchip", t("lt_" + k)); b.dataset.k = k; b.onclick = () => show(k); tabs.appendChild(b); });

    function shapes() {
      const row = el("div", "row"); row.style.marginTop = "0"; const lab = el("span", "hint", t("lib_colour"));
      const col = el("input"); col.type = "color"; col.value = "#ffc857"; row.append(lab, col);
      ["#ffc857", "#ff6b81", "#3ea6ff", "#3ddc97", "#7c5cff", "#ffffff", "#14213d"].forEach((c) => { const sw = el("button", "dot"); sw.style.background = c; sw.onclick = () => { col.value = c; draw(); }; row.appendChild(sw); });
      const grid = el("div", "lib small"); body.append(row, grid);
      function draw() { grid.innerHTML = ""; L.shapes.forEach((n) => { const c = el("button", "asset shape"); c.title = t("sh_" + n);
        const im = el("img"); im.loading = "lazy"; im.alt = ""; im.src = `/api/library/shape/${n}.png?color=${encodeURIComponent(col.value)}`; c.append(im, el("div", "", t("sh_" + n)));
        c.onclick = async () => { busy(c, true); try { done(await (await VF.postJson("/api/library/shape", { name: n, color: col.value })).json()); } catch (e) { VF.toast(e.message, true); busy(c, false); } }; grid.appendChild(c); }); }
      col.onchange = draw; draw();
    }
    function clipart() {
      const CA = Object.fromEntries(L.clipart || []), cats = (L.clipart || []).map((x) => x[0]); if (!cats.length) { body.appendChild(el("p", "hint", t("lib_no_clipart"))); return; }
      const chips = el("div", "chips"); const grid = el("div", "emoji-grid"); body.append(chips, grid);
      const draw = (cat) => { chips.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.c === cat)); grid.innerHTML = "";
        CA[cat].forEach((ch) => { const b = el("button", "emo", ch); b.onclick = async () => { busy(b, true); try { done(await (await VF.postJson("/api/library/clipart", { char: ch })).json()); } catch (e) { VF.toast(e.message, true); busy(b, false); } }; grid.appendChild(b); }); };
      cats.forEach((c) => { const b = el("button", "rchip", t("cc_" + c)); b.dataset.c = c; b.onclick = () => draw(c); chips.appendChild(b); }); draw(cats[0]);
    }
    function builtinSfx() {
      const list = el("div", "plist"); body.appendChild(list);
      L.sfx.forEach((x) => { const row = el("div", "prow"); const p = el("button", "btn sm libplay", "▶"); p.onclick = () => play(`/api/library/sfx/${x.name}.mp3`, p);
        const name = el("b", "", x.label); const d = el("span", "", x.seconds.toFixed(1) + " s"); const use = el("button", "btn sm primary", t("lib_use"));
        use.onclick = async () => { busy(use, true); try { done(await (await VF.postJson(`/api/library/sfx/${x.name}`, {})).json()); } catch (e) { VF.toast(e.message, true); busy(use, false); } };
        row.append(p, name, d, use); list.appendChild(row); });
    }
    function mine(kinds) { delegate = kinds; if (player) player.pause(); VF.closeModal(); }
    function online(kind, category, topics) {
      const bar = el("div", "row"); bar.style.marginTop = "0";
      const q = el("input"); q.type = "text"; q.placeholder = t("lib_search_ph"); q.style.flex = "1"; const go = el("button", "btn sm primary", t("lib_search"));
      bar.append(q, go); const chips = el("div", "chips"); chips.style.marginTop = "8px";
      topics.forEach((tp) => { const b = el("button", "rchip", t("tp_" + tp.replace(/ /g, "_")) === "tp_" + tp.replace(/ /g, "_") ? tp : t("tp_" + tp.replace(/ /g, "_"))); b.onclick = () => { q.value = tp; run(1); }; chips.appendChild(b); });
      const res = el("div", kind === "image" ? "lib" : "plist"); const more = el("div", "row"); const note = el("p", "hint", t("lib_ov_note"));
      body.append(bar, chips, res, more, note);
      async function run(page) {
        res.innerHTML = ""; more.innerHTML = ""; res.appendChild(el("p", "hint", t("lib_loading")));
        try {
          const d = await (await VF.api(`/api/library/search?kind=${kind}&category=${category}&page=${page}&q=${encodeURIComponent(q.value)}`)).json();
          res.innerHTML = ""; if (!d.items.length) res.appendChild(el("p", "hint", t("lib_none")));
          d.items.forEach((it) => kind === "image" ? res.appendChild(imageCard(it)) : res.appendChild(audioRow(it, kind)));
          if (d.pages > 1) { const info = el("span", "hint", `${page} / ${d.pages}`);
            const prev = el("button", "btn sm", "‹"); prev.disabled = page <= 1; prev.onclick = () => run(page - 1);
            const next = el("button", "btn sm", "›"); next.disabled = page >= d.pages; next.onclick = () => run(page + 1); more.append(prev, info, next); }
        } catch (e) { res.innerHTML = ""; res.appendChild(el("p", "hint", e.message)); }
      }
      function imageCard(it) {
        const c = el("div", "asset"); const im = el("img"); im.loading = "lazy"; im.src = it.thumb; im.alt = it.title;
        const cap = el("div", "", it.title); cap.title = it.attribution; c.append(im, cap);
        c.onclick = async () => { c.style.opacity = ".5"; try { const m = await (await VF.postJson("/api/library/import", { kind: "image", id: it.id })).json();
          m.wide = (it.width || 1) > (it.height || 1) * 1.2 && category === "photograph"; done(m); } catch (e) { VF.toast(e.message, true); c.style.opacity = ""; } };
        return c;
      }
      function audioRow(it) {
        const row = el("div", "prow"); const p = el("button", "btn sm libplay", "▶"); p.onclick = () => play(it.preview, p);
        const name = el("b", "", it.title); name.title = it.attribution;
        const meta = el("span", "", `${it.creator} · ${it.duration ? Math.round(it.duration) + " s · " : ""}${it.license}`);
        const use = el("button", "btn sm primary", t("lib_use"));
        use.onclick = async () => { busy(use, true); try { done(await (await VF.postJson("/api/library/import", { kind: "audio", id: it.id })).json()); } catch (e) { VF.toast(e.message, true); busy(use, false); } };
        row.append(p, name, meta, use); return row;
      }
      go.onclick = () => run(1); q.onkeydown = (e) => { if (e.key === "Enter") run(1); };
      q.value = topics[0]; run(1);
    }
    VF.openModal(t("lib_free_title"), box, () => { if (player) player.pause();
      if (delegate) setTimeout(() => VF.pickAsset(delegate).then(resolve), 0); else resolve(chosen); });
    show(tabsDef[0]);
  });
}
window.VFLibrary = { open: openLibrary };

$("musicLib").onclick = async () => {
  const a = await openLibrary("music"); if (!a) return;
  VF.V.project.music = { asset: a.id, volume: (VF.V.project.music && VF.V.project.music.volume) || 0.15, assetName: a.name };
  VF.renderMusic(); VF.markDirty(); if (a.attribution) VF.toast(t("lib_credit") + " " + a.attribution);
};

/* ---------------- hooks ---------------- */
function onScene() {
  const s = S(); if (!s) return;
  $("sMotion").value = s.motion || "none"; $("sLook").value = s.look || "none"; $("sTrans").value = s.transition || "fade";
  renderVo(); renderSfx(); renderLayers();
  const used = { fxBox: (s.motion && s.motion !== "none") || (s.look && s.look !== "none") || !["fade", "none"].includes(s.transition),
    voBox: !!(s.voiceover && s.voiceover.asset), layerBox: !!(s.stickers && s.stickers.length), sfxBox: !!(s.sfx && s.sfx.asset) };
  Object.entries(used).forEach(([id, on]) => { $(id).classList.toggle("used", on); if (on) $(id).open = true; });
  if (s.background.type === "image" && !$("bgFree")) {
    const b = el("button", "btn sm", t("lib_free_photo")); b.id = "bgFree"; b.style.marginTop = "6px"; b.style.width = "100%";
    b.onclick = async () => { const a = await openLibrary("background"); if (a) { const sc = S(); sc.background.asset = a.id; sc.background.assetName = a.name; VF.loadSceneFields(); changed(); } };
    $("bgExtra").appendChild(b);
  }
}
$("sBgType").addEventListener("change", () => setTimeout(onScene, 0));
VF.on("scene", onScene);
VF.on("ui", () => { fillFx(); onScene(); });
VF.on("ready", () => { fillFx(); onScene(); });
})();
