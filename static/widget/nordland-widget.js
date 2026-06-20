/* Nordland VVS support widget — paste-on-WordPress embed (plan §10).
 * <script src="https://bot.nordlandvvs.se/static/widget/nordland-widget.js" data-lang="sv" defer></script>
 * Vanilla JS, no deps. Talks to our VPS via the anonymous session public_id.
 */
(function () {
  "use strict";
  var script = document.currentScript;
  var API = new URL(script.src).origin;
  var LANG = (script.getAttribute("data-lang") || "en").slice(0, 5);
  var NAVY = "#0E2A4F", ORANGE = "#C2410C";

  var I18N = { send: "Send", placeholder: "Describe your problem…",
    typing: "Assistant is typing…", photo: "📷 Photo", title: "Nordland VVS — Support",
    error: "Connection problem. Please try again." };
  var sessionId = null, busy = false;

  function el(tag, css, txt) { var e = document.createElement(tag); if (css) e.style.cssText = css; if (txt != null) e.textContent = txt; return e; }

  // ---- UI -------------------------------------------------------------
  var bubble = el("button", "position:fixed;right:20px;bottom:20px;width:60px;height:60px;border-radius:50%;border:none;background:" + NAVY + ";color:#fff;font-size:26px;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.25);z-index:2147483000", "💬");
  var panel = el("div", "position:fixed;right:20px;bottom:90px;width:360px;max-width:92vw;height:520px;max-height:78vh;background:#fff;border-radius:14px;box-shadow:0 10px 40px rgba(0,0,0,.3);display:none;flex-direction:column;overflow:hidden;z-index:2147483000;font-family:system-ui,Arial,sans-serif");
  var header = el("div", "background:" + NAVY + ";color:#fff;padding:12px 14px;font-weight:600", I18N.title);
  var log = el("div", "flex:1;overflow-y:auto;padding:12px;background:#f5f7fa;font-size:14px");
  var chipsBar = el("div", "padding:0 12px 6px;display:flex;flex-wrap:wrap;gap:6px;background:#f5f7fa");
  var inputRow = el("div", "display:flex;gap:6px;padding:10px;border-top:1px solid #eee;align-items:center");
  var input = el("input", "flex:1;border:1px solid #ccc;border-radius:18px;padding:8px 12px;font-size:14px"); input.placeholder = I18N.placeholder;
  var fileBtn = el("label", "cursor:pointer;font-size:18px", I18N.photo);
  var fileInput = el("input"); fileInput.type = "file"; fileInput.accept = "image/*"; fileInput.style.display = "none";
  var sendBtn = el("button", "border:none;background:" + ORANGE + ";color:#fff;border-radius:18px;padding:8px 14px;cursor:pointer;font-size:14px", I18N.send);
  fileBtn.appendChild(fileInput);
  inputRow.append(input, fileBtn, sendBtn);
  panel.append(header, log, chipsBar, inputRow);
  document.body.append(bubble, panel);

  function addMsg(text, who) {
    var row = el("div", "margin:6px 0;display:flex;" + (who === "user" ? "justify-content:flex-end" : ""));
    var b = el("div", "max-width:80%;padding:8px 12px;border-radius:12px;white-space:pre-wrap;" +
      (who === "user" ? "background:" + NAVY + ";color:#fff" : "background:#fff;border:1px solid #e3e8ef"), text);
    row.appendChild(b); log.appendChild(row); log.scrollTop = log.scrollHeight; return b;
  }
  function renderChips(chips) {
    chipsBar.innerHTML = "";
    (chips || []).forEach(function (c) {
      var btn = el("button", "border:1px solid " + NAVY + ";color:" + NAVY + ";background:#fff;border-radius:14px;padding:5px 10px;font-size:13px;cursor:pointer", c.label || c.value);
      btn.onclick = function () { send(c.value, c.label || c.value); };
      chipsBar.appendChild(btn);
    });
  }

  // ---- transport ------------------------------------------------------
  function loadI18n() {
    fetch(API + "/static/widget/i18n/" + LANG + ".json").then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { if (j) { Object.assign(I18N, j); header.textContent = I18N.title; input.placeholder = I18N.placeholder; sendBtn.textContent = I18N.send; } })
      .catch(function () {});
  }
  function openSession() {
    fetch(API + "/api/chat/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ language: LANG }) })
      .then(function (r) { return r.json(); })
      .then(function (j) { sessionId = j.public_id; addMsg(j.message, "bot"); renderChips(j.chips); })
      .catch(function () { addMsg(I18N.error, "bot"); });
  }
  function streamReply(opts) {
    busy = true; var typing = addMsg(I18N.typing, "bot");
    fetch(API + "/api/chat/" + sessionId + "/message", opts).then(function (resp) {
      var reader = resp.body.getReader(), dec = new TextDecoder(), buf = "";
      function pump() {
        return reader.read().then(function (res) {
          if (res.done) { busy = false; return; }
          buf += dec.decode(res.value, { stream: true });
          var i; while ((i = buf.indexOf("\n\n")) >= 0) {
            var frame = buf.slice(0, i); buf = buf.slice(i + 2);
            var line = frame.split("\n").find(function (l) { return l.indexOf("data: ") === 0; });
            if (!line) continue;
            var ev = JSON.parse(line.slice(6));
            if (ev.type === "message") { typing.textContent = ev.message; renderChips(ev.chips); }
          }
          return pump();
        });
      }
      return pump();
    }).catch(function () { typing.textContent = I18N.error; busy = false; });
  }
  function send(value, label) {
    if (busy || !value || !sessionId) return;
    addMsg(label || value, "user"); renderChips([]);
    streamReply({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: value }) });
  }
  function sendPhoto(file) {
    if (busy || !sessionId) return;
    addMsg("📷 " + file.name, "user");
    var fd = new FormData(); fd.append("image", file); fd.append("message", "");
    streamReply({ method: "POST", body: fd });
  }

  // ---- wire up --------------------------------------------------------
  bubble.onclick = function () {
    var show = panel.style.display === "none";
    panel.style.display = show ? "flex" : "none";
    if (show && !sessionId) { loadI18n(); openSession(); }
  };
  sendBtn.onclick = function () { var v = input.value.trim(); if (v) { input.value = ""; send(v, v); } };
  input.addEventListener("keydown", function (e) { if (e.key === "Enter") sendBtn.onclick(); });
  fileInput.addEventListener("change", function () { if (fileInput.files[0]) sendPhoto(fileInput.files[0]); fileInput.value = ""; });
})();
