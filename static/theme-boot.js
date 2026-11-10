/* runs before first paint so the saved theme never flashes */
try { document.documentElement.dataset.theme = localStorage.getItem("vf-theme") || "midnight"; } catch (e) {}
