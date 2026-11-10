/* Speech to text: live typing while the speaker talks, live waveform, editable transcript, SRT/TXT export,
   hand-off to Text-to-Speech / translator / audio editor. Also adds microphone dictation to the Voice tab. */
(() => {
"use strict";
const VF = window.VF, $ = VF.$, t = VF.t, tf = VF.tf;
let rec = null, recog = null, lastBlob = null, lastExt = "weba", segs = [], t0 = 0;
const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const esc = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);

function fillLangs() {
  [$("sttLang"), $("trMicLang"), $("sttTo")].forEach((sel) => { if (sel) { const cur = sel.value; VF.fillLanguages(sel, cur || (sel.id === "sttTo" ? "en-US" : "ar-SA")); } });
}
function count() { const n = ($("sttText").value.trim().match(/\S+/g) || []).length; $("sttCount").textContent = tf("stt_words", n); }

async function start() {
  if (!VFMic.supported.speech) $("sttNote").textContent = t("stt_unsupported");
  try { rec = await VFMic.record({ canvas: $("sttWave"), onTick: (s) => ($("sttTime").textContent = fmt(s)) }); }
  catch (e) { rec = null; return VF.toast(e.message === "NO_MIC" ? t("mic_unsupported") : t("mic_denied"), true); }
  const base = $("sttText").value.trim();
  $("sttBtn").textContent = t("stt_stop"); $("sttBtn").classList.add("on"); $("sttState").textContent = t("stt_live"); $("sttState").className = "pill live";
  $("sttText").style.display = "none"; $("sttLive").style.display = "block"; t0 = performance.now();
  const lang = $("sttLang").value;
  $("sttLive").dir = /^(ar|fa|ur|he|ps|sd|ug|yi|dv)\b/.test(lang) ? "rtl" : "ltr"; $("sttText").dir = $("sttLive").dir;
  const show = (fin, interim) => {
    const full = (base ? base + " " : "") + fin;
    $("sttLive").innerHTML = `${esc(full)} <span class="interim">${esc(interim)}</span><span class="caret"></span>`;
    $("sttLive").scrollTop = $("sttLive").scrollHeight;
    $("sttText").value = full;
  };
  show("", "");
  recog = VFMic.recognizer(lang, (fin, interim, s) => { segs = s; show(fin, interim); }, (err) => { $("sttNote").textContent = t("stt_err") + err; });
}
async function stop() {
  $("sttBtn").disabled = true;
  const r = await rec.stop(); rec = null;
  if (recog) { recog.stop(); recog = null; }
  lastBlob = r.blob; lastExt = r.ext;
  $("sttBtn").textContent = t("stt_start"); $("sttBtn").classList.remove("on"); $("sttBtn").disabled = false;
  $("sttState").textContent = ""; $("sttState").className = "pill";
  $("sttLive").style.display = "none"; $("sttText").style.display = "block"; count();
  $("sttAudio").src = URL.createObjectURL(r.blob); $("sttRecCard").style.display = "block";
}
$("sttBtn").onclick = () => (rec ? stop() : start());
$("sttText").oninput = count;
$("sttClear").onclick = () => { $("sttText").value = ""; segs = []; count(); };
$("sttCopy").onclick = async () => { try { await navigator.clipboard.writeText($("sttText").value); VF.toast(t("stt_copied")); } catch (_) { $("sttText").select(); document.execCommand("copy"); } };
const download = (name, text, type = "text/plain") => { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([text], { type: type + ";charset=utf-8" })); a.download = name; a.click(); };
$("sttTxt").onclick = () => download("transcript.txt", $("sttText").value);
$("sttSrt").onclick = () => {
  const ts = (x) => { const ms = Math.round(x * 1000), h = Math.floor(ms / 3600000), m = Math.floor(ms / 60000) % 60, s = Math.floor(ms / 1000) % 60;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")},${String(ms % 1000).padStart(3, "0")}`; };
  let list = segs.length ? segs : [];
  if (!list.length) {   // no timing (typed text): ~2.6 words per second
    let tt = 0; list = $("sttText").value.split(/(?<=[.!?؟。])\s+/).filter(Boolean).map((x) => { tt += Math.max(1.5, x.split(/\s+/).length / 2.6); return { t: tt, text: x }; });
  }
  let prev = 0; const out = list.map((sg, i) => { const a = prev, b = Math.max(a + 0.8, sg.t); prev = b; return `${i + 1}\n${ts(a)} --> ${ts(b)}\n${sg.text}\n`; });
  download("captions.srt", out.join("\n"));
};
$("sttToTts").onclick = () => { VF.voiceText($("sttText").value); VF.setVoiceLang($("sttLang").value); VF.showView("voice"); window.scrollTo({ top: $("studio").offsetTop - 70, behavior: "smooth" }); };
$("sttTrBtn").onclick = async () => {
  const text = $("sttText").value; if (!text.trim()) return VF.toast(t("tr_empty"), true);
  const b = $("sttTrBtn"); b.disabled = true;
  try { const r = await (await VF.postJson("/api/translate", { text, to: $("sttTo").value, from: $("sttLang").value })).json();
    $("sttText").value = r.text; $("sttText").dir = "auto"; segs = []; count(); VF.toast(tf("tr_done", VF.langLabel($("sttTo").value)));
    $("sttLang").value = $("sttTo").value; }
  catch (e) { VF.toast(e.message, true); } finally { b.disabled = false; }
};
const recFile = () => new File([lastBlob], `recording.${lastExt}`, { type: lastBlob.type });
$("sttEdit").onclick = () => { if (lastBlob && window.VFAudio) { VFAudio.openBlob(lastBlob, "recording"); VF.showView("audio"); } };
$("sttSave").onclick = async () => { if (!lastBlob) return; const [m] = await VF.uploadFiles([recFile()]); if (m) VF.toast(t("stt_saved")); };

/* ---- dictation in the Voice tab (speak, then translate) ---- */
let dict = null;
$("trMic").onclick = () => {
  if (dict) { dict.stop(); dict = null; $("trMic").textContent = t("tr_mic"); $("trMic").classList.remove("on"); return; }
  if (!VFMic.supported.speech) return VF.toast(t("stt_unsupported"), true);
  const base = VF.voiceText().trim();
  dict = VFMic.recognizer($("trMicLang").value, (fin, interim) => { VF.voiceText((base ? base + " " : "") + fin + (interim ? " " + interim : "")); },
    (err) => VF.toast(t("stt_err") + err, true));
  if (!dict) return;
  $("trMic").textContent = t("tr_mic_stop"); $("trMic").classList.add("on");
};

VF.on("ready", () => { fillLangs(); $("sttLang").value = "ar-SA"; $("trMicLang").value = "en-US"; $("sttTo").value = "en-US"; count();
  if (!VFMic.supported.speech) { $("sttNote").textContent = t("stt_unsupported"); } $("sttPrivacy").textContent = t("stt_privacy"); });
VF.on("ui", () => { fillLangs(); $("sttBtn").textContent = t(rec ? "stt_stop" : "stt_start"); $("trMic").textContent = t(dict ? "tr_mic_stop" : "tr_mic"); count(); $("sttPrivacy").textContent = t("stt_privacy"); });
})();
