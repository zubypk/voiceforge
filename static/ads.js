/* Google AdSense: loaded only when the server is configured with ADSENSE_CLIENT (see README).
   Ads go in three fixed, non-intrusive places outside the editors (.ad-slot), or AdSense Auto ads if no slot ids. */
(() => {
"use strict";
async function init() {
  let ads = null;
  try { ads = (await (await fetch("/api/config")).json()).ads; } catch (_) { return; }
  if (!ads || !ads.client) return;
  const s = document.createElement("script"); s.async = true; s.crossOrigin = "anonymous";
  s.src = "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=" + encodeURIComponent(ads.client);
  document.head.appendChild(s);
  const slots = ads.slots || {};
  document.querySelectorAll(".ad-slot[data-ad]").forEach((box) => {
    const id = slots[box.dataset.ad]; if (!id) return;
    const ins = document.createElement("ins"); ins.className = "adsbygoogle"; ins.style.display = "block";
    ins.dataset.adClient = ads.client; ins.dataset.adSlot = id; ins.dataset.adFormat = "auto"; ins.dataset.fullWidthResponsive = "true";
    const lab = document.createElement("span"); lab.className = "ad-label"; lab.textContent = document.documentElement.lang === "ar" ? "إعلان" : "Advertisement";
    box.append(lab, ins); box.hidden = false;
    try { (window.adsbygoogle = window.adsbygoogle || []).push({}); } catch (_) {}
  });
}
init();
})();
