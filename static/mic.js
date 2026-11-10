/* Shared microphone helpers: recording with a live level/waveform, and live speech recognition (Web Speech API). */
(() => {
"use strict";
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

function pickMime() {
  const c = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
  return (window.MediaRecorder && c.find((m) => MediaRecorder.isTypeSupported(m))) || "";
}
const extFor = (mime) => (mime.includes("mp4") ? "m4a" : mime.includes("ogg") ? "oga" : "weba");

// Draw a scrolling live waveform (history of peak levels) + current oscilloscope line.
function liveWave(canvas, analyser, getHistory) {
  const ctx = canvas.getContext("2d"), buf = new Uint8Array(analyser.fftSize);
  let raf = 0;
  function frame() {
    const dpr = devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
    if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
    analyser.getByteTimeDomainData(buf);
    let peak = 0; for (let i = 0; i < buf.length; i++) peak = Math.max(peak, Math.abs(buf[i] - 128) / 128);
    const hist = getHistory(); hist.push(peak);
    const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#7c5cff";
    const bars = Math.floor(w / 3), start = Math.max(0, hist.length - bars);
    ctx.fillStyle = accent;
    for (let i = start; i < hist.length; i++) { const v = Math.max(1, hist[i] * h * 0.9); ctx.fillRect((i - start) * 3, (h - v) / 2, 2, v); }
    ctx.strokeStyle = "rgba(255,255,255,.55)"; ctx.lineWidth = 1; ctx.beginPath();
    for (let i = 0; i < buf.length; i += 4) { const x = (i / buf.length) * w, y = (buf[i] / 255) * h; i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
    ctx.stroke(); raf = requestAnimationFrame(frame);
  }
  frame();
  return () => cancelAnimationFrame(raf);
}

// Start recording. Returns { stop(): Promise<{blob, ext, seconds, peaks}>, cancel() }.
async function record({ canvas, onTick } = {}) {
  if (!navigator.mediaDevices || !window.MediaRecorder) throw new Error("NO_MIC");
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  const mime = pickMime(), rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined), chunks = [];
  const ac = new (window.AudioContext || window.webkitAudioContext)(), src = ac.createMediaStreamSource(stream), an = ac.createAnalyser();
  an.fftSize = 2048; src.connect(an);
  const hist = [], t0 = performance.now();
  const stopWave = canvas ? liveWave(canvas, an, () => hist) : () => {};
  const tick = setInterval(() => onTick && onTick((performance.now() - t0) / 1000), 200);
  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  rec.start(250);
  const cleanup = () => { clearInterval(tick); stopWave(); stream.getTracks().forEach((t) => t.stop()); ac.close().catch(() => {}); };
  return {
    stop: () => new Promise((res) => { rec.onstop = () => { cleanup(); const type = rec.mimeType || mime || "audio/webm";
      res({ blob: new Blob(chunks, { type }), ext: extFor(type), seconds: (performance.now() - t0) / 1000, peaks: hist.slice() }); }; rec.stop(); }),
    cancel: () => { try { rec.stop(); } catch (_) {} cleanup(); },
    get seconds() { return (performance.now() - t0) / 1000; },
  };
}

// Live speech recognition. Calls onText(finalText, interimText, segments) as the speaker talks.
// Restarts itself on silence timeouts until stop() is called.
function recognizer(lang, onText, onError) {
  if (!SR) return null;
  const r = new SR(); r.lang = lang; r.continuous = true; r.interimResults = true; r.maxAlternatives = 1;
  let final = "", stopped = false; const segs = [], t0 = performance.now();
  r.onresult = (e) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const res = e.results[i], txt = res[0].transcript;
      if (res.isFinal) { const clean = txt.trim(); if (clean) { final += (final && !/\s$/.test(final) ? " " : "") + clean; segs.push({ t: (performance.now() - t0) / 1000, text: clean }); } }
      else interim += txt;
    }
    onText(final, interim, segs);
  };
  r.onerror = (e) => { if (e.error !== "no-speech" && e.error !== "aborted" && onError) onError(e.error); };
  r.onend = () => { if (!stopped) { try { r.start(); } catch (_) {} } };
  try { r.start(); } catch (e) { if (onError) onError(e.message); }
  return { stop: () => { stopped = true; try { r.stop(); } catch (_) {} return { text: final, segments: segs }; },
           setText: (v) => { final = v; } };
}

window.VFMic = { record, recognizer, liveWave, supported: { record: !!(navigator.mediaDevices && window.MediaRecorder), speech: !!SR } };
})();
