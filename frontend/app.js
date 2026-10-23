const $ = s => document.querySelector(s);
const body = document.body, feed = $("#feed"), input = $("#input"), live = $("#live"), hint = $("#hint");
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let history = [], busy = false, muted = false, rec = null, audio = null, currentAbort = null;

const SUGGESTIONS = [
  "Best noise-cancelling headphones under ₹5000",
  "Cafés open now near Malviya Nagar, Jaipur",
  "Latest news on ISRO",
  "Book a train from Jaipur to Delhi tomorrow",
  "Show me a good pasta recipe video",
];
SUGGESTIONS.forEach(t => {
  const b = document.createElement("button"); b.className = "chip"; b.textContent = t;
  b.onclick = () => send(t); $("#chips").append(b);
});

const setState = s => { body.dataset.state = s; };
function setMode(m) {
  body.dataset.mode = m; stopAll();
  $("#m-voice").setAttribute("aria-selected", m === "voice");
  $("#m-text").setAttribute("aria-selected", m === "text");
  $("#hero-sub").textContent = m === "voice" ? "Tap the orb and ask anything." : "Type below and I’ll search the web for you.";
  if (m === "text") input.focus();
  if (m === "voice" && !SR) hint.textContent = "Voice input isn’t supported in this browser. Use Chrome, Edge or Safari.";
}
$("#m-voice").onclick = () => setMode("voice");
$("#m-text").onclick = () => setMode("text");
$("#mute").onclick = e => { muted = !muted; e.currentTarget.classList.toggle("off", muted); if (muted) stopSpeaking(); };

/* ---------- voice input ---------- */
function listen() {
  if (!SR) return;
  stopSpeaking();
  rec = new SR(); rec.lang = navigator.language || "en-IN"; rec.interimResults = true; rec.continuous = false;
  let finalText = "";
  rec.onstart = () => { setState("listening"); live.hidden = false; live.textContent = "Listening…"; hint.textContent = "Tap again to stop"; };
  rec.onresult = e => {
    let interim = "";
    for (const r of e.results) r.isFinal ? (finalText += r[0].transcript) : (interim += r[0].transcript);
    live.textContent = finalText + interim || "Listening…";
  };
  rec.onerror = e => { live.textContent = e.error === "not-allowed" ? "Microphone blocked. Allow access in the address bar." : ""; };
  rec.onend = () => {
    rec = null; live.hidden = true; hint.textContent = "Tap the orb to speak";
    if (finalText.trim()) send(finalText.trim()); else if (!busy) setState("idle");
  };
  rec.start();
}
$("#orb").onclick = () => {
  if (body.dataset.mode === "text") return;
  if (rec) return rec.stop();
  if (busy) return;
  listen();
};

/* ---------- voice output ---------- */
function stopSpeaking() {
  if (audio) { audio.pause(); audio = null; }
  speechSynthesis.cancel();
}
async function speak(text) {
  if (muted || !text) return setState("idle");
  setState("speaking");
  const done = () => setState("idle");
  try {
    const r = await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    if (!r.ok) throw 0;
    audio = new Audio(URL.createObjectURL(await r.blob()));
    audio.onended = done; audio.onerror = done; await audio.play();
  } catch {
    const u = new SpeechSynthesisUtterance(text); u.onend = done; u.onerror = done; speechSynthesis.speak(u);
  }
}
function stopAll() { if (rec) { rec.onend = null; rec.abort(); rec = null; } live.hidden = true; stopSpeaking(); if (!busy) setState("idle"); }

/* ---------- chat ---------- */
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt) e.textContent = txt; return e; };
const scroll = () => feed.scrollTo({ top: feed.scrollHeight });

async function send(text) {
  if (busy || !text) return;
  busy = true; input.value = ""; stopSpeaking(); body.classList.add("chatting");
  feed.append(el("div", "msg user", text));
  const msg = el("div", "msg bot"), trail = el("div", "trail"), status = el("div", "status"), say = el("div", "say"), cards = el("div", "cards");
  status.append(el("i"), el("span", "", "Thinking"));
  msg.append(trail, status, say, cards); feed.append(msg); scroll(); setState("thinking");

  let speech = "";
  try {
    const res = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history: history.slice(-10) }) });
    const reader = res.body.getReader(), dec = new TextDecoder(); let buf = "";
    while (true) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let i; while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1); if (!line) continue;
        const ev = JSON.parse(line);
        if (ev.type === "status") {
          const prev = status.querySelector("span").textContent;
          if (prev !== "Thinking") trail.append(el("div", "", prev));
          status.querySelector("span").textContent = ev.text;
        } else if (ev.type === "result") {
          speech = ev.speech; status.classList.add("done");
          say.textContent = ev.speech; renderCards(cards, ev.cards);
        } else if (ev.type === "error") { status.classList.add("done"); say.className = "say err"; say.textContent = ev.text; }
      }
      scroll();
    }
  } catch (e) { status.classList.add("done"); say.className = "say err"; say.textContent = "Couldn’t reach the server."; }

  history.push({ role: "user", text }, { role: "model", text: speech || "…" });
  busy = false; scroll();
  speech ? speak(speech) : setState("idle");
}

function renderCards(wrap, list) {
  list.forEach((c, i) => {
    const host = new URL(c.url).hostname.replace(/^www\./, "");
    const fav = `https://www.google.com/s2/favicons?domain=${host}&sz=64`;
    const a = el("a", "card"); a.href = c.url; a.target = "_blank"; a.rel = "noopener noreferrer"; a.style.animationDelay = `${i * 70}ms`;
    const th = el("div", "thumbbox");
    if (c.image) { th.style.backgroundImage = `url("${c.image.replace(/"/g, "%22")}")`; }
    else { const f = el("img", "fav"); f.src = fav; f.alt = ""; th.append(f); }
    if (c.badge) th.append(el("span", "badge", c.badge));
    const b = el("div", "cbody"), site = el("div", "site");
    const fi = el("img"); fi.src = fav; fi.alt = ""; site.append(fi, el("span", "", host));
    b.append(site, el("div", "ctitle", c.title), el("div", "cdesc", c.description), el("div", "open", "Open page ↗"));
    a.append(th, b); wrap.append(a);
  });
}

$("#composer").onsubmit = e => { e.preventDefault(); send(input.value.trim()); };
setMode("voice");
