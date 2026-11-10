/* Site chrome: colour themes, build number (Riyadh time) in the footer, feature cards. */
(() => {
"use strict";
const VF = window.VF, $ = VF.$, t = VF.t;
const LIGHT = { daylight: "#2f6bff", paper: "#e8590c", mint: "#0c9f6e", sky: "#7048e8" };
const DARK = { midnight: "#7c5cff", ocean: "#00b4d8", sunset: "#ff6b4a", forest: "#2ec27e" };
const THEMES = { ...LIGHT, ...DARK };
function setTheme(name) {
  if (!THEMES[name]) name = "midnight";
  document.documentElement.dataset.theme = name; try { localStorage.setItem("vf-theme", name); } catch (_) {}
  document.querySelectorAll(".tdot").forEach((d) => d.classList.toggle("on", d.dataset.t === name));
  window.dispatchEvent(new Event("resize"));   // redraw canvases with the new accent colour
}
function drawPicker() {
  const box = $("themePick"); box.innerHTML = "";
  const dot = ([k, c]) => { const b = document.createElement("button"); b.className = "tdot"; b.dataset.t = k;
    b.style.background = k in LIGHT ? `linear-gradient(135deg,#fff 0 45%,${c} 45%)` : c;
    b.title = t("th_" + k); b.setAttribute("aria-label", t("theme") + ": " + t("th_" + k)); b.onclick = () => setTheme(k); box.appendChild(b); };
  Object.entries(LIGHT).forEach(dot); const sep = document.createElement("span"); sep.className = "theme-sep"; box.appendChild(sep); Object.entries(DARK).forEach(dot);
  setTheme(document.documentElement.dataset.theme || "midnight");
}
document.querySelectorAll(".feat[data-go]").forEach((f) => f.addEventListener("click", () => { VF.showView(f.dataset.go); $("studio").scrollIntoView({ behavior: "smooth" }); }));
async function build() {
  try { const c = await (await fetch("/api/config")).json(); const b = c.build || {}; $("buildInfo").textContent = VF.tf("build", b.build ?? "dev", b.display || "");
    $("buildInfo").title = (b.commit ? "commit " + b.commit + " · " : "") + (b.time || ""); } catch (_) {}
}
function marquee() {
  const c = VF.catalog, langs = new Set((c.languages || []).map((l) => l.code.split("-")[0])).size;
  const items = t("mq_items")(langs, (c.voices || []).length);
  const track = $("mqTrack"); track.innerHTML = "";
  for (let r = 0; r < 2; r++) items.forEach(([b, rest]) => { const s = document.createElement("span"); const bb = document.createElement("b"); bb.textContent = b;
    s.dir = document.documentElement.dir || "ltr"; s.append(bb, document.createTextNode(" " + rest)); if (r) s.setAttribute("aria-hidden", "true"); track.appendChild(s); });
}
VF.on("ready", () => { drawPicker(); build(); marquee(); });
VF.on("ui", () => { drawPicker(); build(); marquee(); });
})();
