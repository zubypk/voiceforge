/* Video Studio "Play preview": plays every scene in the browser (slide image, AI or recorded voice, captions,
   music, sound effect, motion, transition) without rendering an MP4. Voices are cached per text/voice. */
(() => {
"use strict";
const VF = window.VF, $ = VF.$, t = VF.t, tf = VF.tf;
const voiceCache = new Map();     // key -> object URL
let session = 0;

async function slideUrl(payload, i) {
  const blob = await (await VF.postJson("/api/video/preview", { project: payload, index: i, stickers: true })).blob();
  return URL.createObjectURL(blob);
}
async function voiceUrl(scene, voice) {
  if (scene.voiceover && scene.voiceover.asset) return `/api/assets/${scene.voiceover.asset}/file`;
  const text = (scene.narration || "").trim(); if (!text) return null;
  const key = JSON.stringify([text, voice.voice, voice.lang, voice.gender, voice.rate, voice.pitch]);
  if (voiceCache.has(key)) return voiceCache.get(key);
  const blob = await (await VF.postJson("/api/export", { text: text.slice(0, 12000), voice: voice.voice || undefined, lang: voice.lang, gender: voice.gender, rate: voice.rate, pitch: voice.pitch })).blob();
  const url = URL.createObjectURL(blob); voiceCache.set(key, url); return url;
}
const audioLen = (url) => new Promise((res) => { if (!url) return res(0); const a = new Audio(); a.preload = "metadata";
  a.onloadedmetadata = () => res(isFinite(a.duration) ? a.duration : 0); a.onerror = () => res(0); a.src = url; setTimeout(() => res(0), 15000); });
function chunks(text) {     // caption pieces, like the renderer
  const words = (text || "").split(/\s+/).filter(Boolean), out = []; let cur = "";
  words.forEach((w) => { if ((cur + " " + w).trim().length > 84) { out.push(cur.trim()); cur = w; } else cur += " " + w; }); if (cur.trim()) out.push(cur.trim());
  return out;
}
const MOTION_CSS = { zoom_in: ["scale(1)", "scale(1.12)"], zoom_out: ["scale(1.12)", "scale(1)"], pan_left: ["scale(1.18) translateX(7%)", "scale(1.18) translateX(-7%)"],
  pan_right: ["scale(1.18) translateX(-7%)", "scale(1.18) translateX(7%)"], pan_up: ["scale(1.18) translateY(7%)", "scale(1.18) translateY(-7%)"] };
const LOOK_CSS = { grayscale: "grayscale(1)", sepia: "sepia(.85)", vintage: "sepia(.5) contrast(.95) saturate(.8)", warm: "sepia(.25) saturate(1.2)", cool: "hue-rotate(15deg) saturate(.9)",
  vivid: "saturate(1.4) contrast(1.06)", blur: "none", vignette: "none", dark: "brightness(.82)" };

async function playAll() {
  const p = VF.V.project, payload = VF.projectPayload(), n = p.scenes.length, my = ++session;
  const box = document.createElement("div"); box.className = "vp";
  box.innerHTML = `<div class="vp-stage"><img class="vp-a" alt=""><img class="vp-b" alt=""><div class="vp-cap"></div><div class="vp-load"></div></div>
    <div class="vp-ctl"><button class="btn sm" data-a="prev">⏮</button><button class="btn sm primary" data-a="pause">❚❚</button><button class="btn sm" data-a="next">⏭</button>
    <div class="vp-bar"><i></i></div><span class="hint vp-n"></span></div>`;
  const [a, b] = box.querySelectorAll("img"), cap = box.querySelector(".vp-cap"), load = box.querySelector(".vp-load"), bar = box.querySelector(".vp-bar i"), cnt = box.querySelector(".vp-n");
  const stage = box.querySelector(".vp-stage"); const [rw, rh] = p.ratio.split(":").map(Number); stage.style.aspectRatio = `${rw} / ${rh}`;
  const voice = new Audio(), music = p.music && p.music.asset ? new Audio(`/api/assets/${p.music.asset}/file`) : null, sfx = new Audio();
  if (music) { music.loop = true; music.volume = Math.min(1, p.music.volume || 0.15); }
  let idx = 0, paused = false, front = a, timer = 0, raf = 0, sceneStart = 0, sceneDur = 0, pauseAt = 0;
  const prep = new Map();
  const prepare = (i) => { if (i >= n || prep.has(i)) return prep.get(i); const pr = (async () => { const url = await slideUrl(payload, i); const v = await voiceUrl(payload.scenes[i], payload.voice); return { url, v, len: await audioLen(v) }; })(); prep.set(i, pr); return pr; };
  const stopAll = () => { clearTimeout(timer); cancelAnimationFrame(raf); voice.pause(); sfx.pause(); if (music) music.pause(); };
  VF.openModal(t("vp_title"), box, () => { session++; stopAll(); });
  box.querySelector('[data-a="pause"]').onclick = (e) => { paused = !paused; e.target.textContent = paused ? "▶" : "❚❚";
    if (paused) { pauseAt = performance.now(); clearTimeout(timer); voice.pause(); if (music) music.pause(); front.style.animationPlayState = "paused"; }
    else { sceneStart += performance.now() - pauseAt; voice.play().catch(() => {}); if (music) music.play().catch(() => {}); front.style.animationPlayState = "running";
      timer = setTimeout(next, Math.max(0, sceneDur * 1000 - (performance.now() - sceneStart))); tick(); } };
  box.querySelector('[data-a="next"]').onclick = () => next();
  box.querySelector('[data-a="prev"]').onclick = () => { idx = Math.max(0, idx - 2); next(); };
  function tick() { if (paused || my !== session) return; const el = (performance.now() - sceneStart) / 1000;
    bar.style.width = Math.min(100, ((idx - 1) + Math.min(1, el / sceneDur)) / n * 100) + "%";
    const s = payload.scenes[idx - 1], ch = s && p.captions ? chunks(s.narration) : [];
    if (ch.length) { const speak = Math.max(0.5, sceneDur - 0.5), k = Math.min(ch.length - 1, Math.floor(el / speak * ch.length)); cap.textContent = ch[k]; cap.style.display = ""; } else cap.style.display = "none";
    raf = requestAnimationFrame(tick); }
  async function show(i) {
    load.textContent = tf("vp_loading", i + 1, n); load.style.display = "grid";
    let item; try { item = await prepare(i); } catch (e) { load.textContent = e.message; return; }
    if (my !== session) return; load.style.display = "none"; prepare(i + 1);   // prefetch the next scene
    const s = payload.scenes[i], back = front === a ? b : a;
    back.src = item.url; back.style.filter = LOOK_CSS[s.look] || "none";
    const mv = MOTION_CSS[s.motion]; back.getAnimations().forEach((x) => x.cancel());
    sceneDur = s.duration || (item.len ? Math.max(2, item.len + 0.5) : 5);
    if (mv) back.animate([{ transform: mv[0] }, { transform: mv[1] }], { duration: sceneDur * 1000, fill: "forwards", easing: "linear" }); else back.style.transform = "none";
    const prevT = i ? payload.scenes[i - 1].transition : "fade", fadeMs = prevT === "none" ? 0 : 450;
    const dir = /left/.test(prevT) ? -1 : /right/.test(prevT) ? 1 : 0;
    back.animate([{ opacity: 0, translate: `${dir * 6}% 0` }, { opacity: 1, translate: "0 0" }], { duration: fadeMs || 1, fill: "forwards" });
    back.style.zIndex = 2; front.style.zIndex = 1; front = back;
    cnt.textContent = tf("vp_scene", i + 1, n);
    voice.pause(); if (item.v) { voice.src = item.v; voice.currentTime = 0; voice.play().catch(() => {}); }
    if (s.sfx && s.sfx.asset) { sfx.src = `/api/assets/${s.sfx.asset}/file`; sfx.volume = Math.min(1, s.sfx.volume == null ? 0.8 : s.sfx.volume); setTimeout(() => { if (my === session && !paused) sfx.play().catch(() => {}); }, (s.sfx.at || 0) * 1000); }
    if (music && music.paused && !paused) music.play().catch(() => {});
    sceneStart = performance.now(); clearTimeout(timer); timer = setTimeout(next, sceneDur * 1000); cancelAnimationFrame(raf); tick();
  }
  function next() { if (my !== session) return; if (idx >= n) { stopAll(); bar.style.width = "100%"; cap.style.display = "none"; return; } show(idx++); }
  next();
}
$("vPlayAll").onclick = playAll;
window.VFPreview = { playAll };
})();
