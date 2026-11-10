/* Site chrome: colour themes, build number (Riyadh time) in the footer, feature cards. */
(() => {
"use strict";
const VF = window.VF, $ = VF.$, t = VF.t;
const THEMES = { midnight: "#7c5cff", daylight: "#2f6bff", ocean: "#00b4d8", sunset: "#ff6b4a", forest: "#2ec27e" };
function setTheme(name) {
  if (!THEMES[name]) name = "midnight";
  document.documentElement.dataset.theme = name; try { localStorage.setItem("vf-theme", name); } catch (_) {}
  document.querySelectorAll(".tdot").forEach((d) => d.classList.toggle("on", d.dataset.t === name));
  window.dispatchEvent(new Event("resize"));   // redraw canvases with the new accent colour
}
function drawPicker() {
  const box = $("themePick"); box.innerHTML = "";
  Object.entries(THEMES).forEach(([k, c]) => { const b = document.createElement("button"); b.className = "tdot"; b.dataset.t = k; b.style.background = c;
    b.title = t("th_" + k); b.setAttribute("aria-label", t("theme") + ": " + t("th_" + k)); b.onclick = () => setTheme(k); box.appendChild(b); });
  setTheme(document.documentElement.dataset.theme || "midnight");
}
document.querySelectorAll(".feat[data-go]").forEach((f) => f.addEventListener("click", () => { VF.showView(f.dataset.go); $("studio").scrollIntoView({ behavior: "smooth" }); }));
async function build() {
  try { const c = await (await fetch("/api/config")).json(); const b = c.build || {}; $("buildInfo").textContent = VF.tf("build", b.build ?? "dev", b.display || "");
    $("buildInfo").title = (b.commit ? "commit " + b.commit + " · " : "") + (b.time || ""); } catch (_) {}
}
VF.on("ready", () => { drawPicker(); build(); });
VF.on("ui", () => { drawPicker(); build(); });
})();
