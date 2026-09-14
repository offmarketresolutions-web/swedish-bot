/* Nordland VVS support widget — paste-on-WordPress embed (plan §10).
 * <script src="https://bot.nordlandvvs.se/static/widget/nordland-widget.js" data-lang="sv" defer></script>
 * Vanilla JS, no deps. Talks to our VPS via the anonymous session public_id.
 * Familiar support-chat conventions (Intercom/Crisp style): floating launcher,
 * panel with header/status, grouped bubbles, typing dots, quick-reply chips,
 * auto-grow composer, file attach, sessionStorage persistence, mobile sheet.
 */
(function () {
  "use strict";
  var script = document.currentScript;
  var API = new URL(script.src).origin;
  var LANG = (script.getAttribute("data-lang") || "sv").slice(0, 5);  // sv: the customers' language
  var AUTO_OPEN = script.getAttribute("data-open") === "1";  // open the chat on load (chat pages)
  // Languages offered in the in-widget selector (value must have a widget/i18n/<v>.json).
  var LANGS = [["sv", "Svenska"], ["en", "English"]];
  var BLUE = "#1a74bf", BLUE_DARK = "#155f9e";  // Nordland brand blue + hover shade
  var STORE_KEY = "nordland-chat:" + LANG;       // sessionStorage namespace
  var MAX_FILE = 10 * 1024 * 1024;               // 10 MB attach guard
  var OK_TYPES = ["image/", "application/pdf"];
  var REQUEST_TIMEOUT_MS = 20000;                // our Vertex quota can stall sockets — abort, don't hang
  var RATE_LIMIT_BACKOFF_MS = 4000;              // 429: pause before letting the customer hammer retry

  // i18n — defaults; loadI18n() overlays the locale catalog. Extra UX strings
  // beyond the shared catalog keys fall back to these and are safe if absent.
  var I18N = {
    send: "Send", placeholder: "Describe your problem…",
    typing: "Assistant is typing…", photo: "📷 Photo",
    title: "Nordland VVS — Support",
    error: "Connection problem. Please try again.",
    timeout: "That took too long. Please try again.",
    rate_limited: "Too many requests — please wait a moment and try again.",
    retry: "Try again",
    open: "Open chat", close: "Close chat", minimize: "Minimize",
    nudge: "Chat with us",
    status: "Usually replies within a few minutes",
    attach: "Attach file", remove: "Remove attachment",
    file_too_big: "File is too large (max 10 MB).",
    file_bad_type: "Only images and PDF files are allowed."
  };
  var reduceMotion = false;
  try { reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) {}

  var sessionId = null, busy = false, lastWho = null, unread = 0, started = false;
  var pendingFile = null;

  function el(tag, cls, txt) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }
  function svgNS(s) {
    var d = document.createElement("div"); d.innerHTML = s; return d.firstElementChild;
  }

  // ---- styles (scoped by .nl- prefix) ---------------------------------
  var css = "" +
    ".nl-launcher{position:fixed;right:20px;bottom:20px;width:60px;height:60px;border-radius:50%;border:none;background:" + BLUE + ";color:#fff;cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,.25);z-index:2147483000;display:flex;align-items:center;justify-content:center;transition:transform .15s ease,background .15s ease;padding:0}" +
    ".nl-launcher:hover{background:" + BLUE_DARK + ";transform:translateY(-2px)}" +
    ".nl-launcher:focus-visible{outline:3px solid rgba(26,116,191,.4);outline-offset:2px}" +
    ".nl-launcher svg{width:28px;height:28px;display:block;transition:transform .2s ease,opacity .2s ease}" +
    ".nl-ic-x{position:absolute;opacity:0;transform:rotate(-90deg) scale(.6)}" +
    ".nl-open .nl-ic-chat{opacity:0;transform:rotate(90deg) scale(.6)}" +
    ".nl-open .nl-ic-x{opacity:1;transform:rotate(0) scale(1)}" +
    ".nl-badge{position:absolute;top:-2px;right:-2px;min-width:20px;height:20px;padding:0 5px;border-radius:10px;background:#d9370c;color:#fff;font:700 12px/20px system-ui,Arial,sans-serif;text-align:center;box-shadow:0 0 0 2px #fff;display:none}" +
    ".nl-badge.nl-show{display:block}" +
    // blue callout that points at the launcher bubble (shown while the chat is closed)
    ".nl-nudge{position:fixed;right:24px;bottom:90px;max-width:200px;background:" + BLUE + ";color:#fff;font:600 14px/1.35 system-ui,Arial,sans-serif;padding:9px 13px;border-radius:14px;box-shadow:0 6px 18px rgba(26,116,191,.35);z-index:2147483400;cursor:pointer;display:none}" +
    ".nl-nudge.nl-show{display:block;animation:nl-nudge-in .3s ease}" +
    ".nl-nudge::after{content:'';position:absolute;right:18px;bottom:-6px;width:13px;height:13px;background:" + BLUE + ";transform:rotate(45deg);border-radius:0 0 3px 0}" +
    "@keyframes nl-nudge-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}" +
    ".nl-panel{position:fixed;right:20px;bottom:92px;width:380px;max-width:calc(100vw - 32px);height:600px;max-height:calc(100vh - 120px);background:#fff;border-radius:16px;box-shadow:0 16px 48px rgba(0,0,0,.28);display:none;flex-direction:column;overflow:hidden;z-index:2147483000;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif}" +
    ".nl-panel.nl-show{display:flex;animation:nl-rise .18s ease}" +
    "@keyframes nl-rise{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}" +
    ".nl-header{display:flex;align-items:center;gap:10px;padding:12px 14px;background:#fff;border-bottom:1px solid #e8edf3}" +
    ".nl-avatar{width:38px;height:38px;border-radius:50%;background:#eef4fb;display:flex;align-items:center;justify-content:center;flex:0 0 auto;overflow:hidden}" +
    ".nl-avatar img{max-width:30px;max-height:30px;width:auto;height:auto;display:block}" +
    ".nl-htext{flex:1;min-width:0}" +
    ".nl-name{font-weight:700;font-size:15px;color:#10233a;line-height:1.2}" +
    ".nl-status{font-size:12px;color:#6b7a8d;display:flex;align-items:center;gap:5px;margin-top:1px}" +
    ".nl-dot{width:7px;height:7px;border-radius:50%;background:#2bb673;flex:0 0 auto}" +
    ".nl-hbtns{display:flex;gap:2px}" +
    ".nl-iconbtn{border:none;background:none;cursor:pointer;color:#6b7a8d;width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center;padding:0}" +
    ".nl-iconbtn:hover{background:#f0f3f7;color:#10233a}" +
    ".nl-iconbtn:focus-visible{outline:2px solid " + BLUE + ";outline-offset:1px}" +
    ".nl-iconbtn svg{width:20px;height:20px;display:block}" +
    ".nl-lang{border:1px solid #d6deea;background:#fff;color:#1b2b3d;border-radius:8px;font:500 12px system-ui,Arial,sans-serif;padding:4px 6px;cursor:pointer;outline:none;max-width:108px}" +
    ".nl-lang:focus-visible{outline:2px solid " + BLUE + ";outline-offset:1px}" +
    ".nl-log{flex:1;overflow-y:auto;padding:14px;background:#f6f8fb;display:flex;flex-direction:column;gap:2px}" +
    ".nl-row{display:flex;margin-top:2px}" +
    ".nl-row.nl-user{justify-content:flex-end}" +
    ".nl-row.nl-grp{margin-top:8px}" +
    ".nl-bubble{max-width:80%;padding:9px 13px;border-radius:16px;font-size:14px;line-height:1.45;white-space:pre-wrap;word-wrap:break-word}" +
    ".nl-row.nl-bot .nl-bubble{background:#fff;color:#1b2b3d;border:1px solid #e6ecf3;border-bottom-left-radius:5px}" +
    ".nl-row.nl-user .nl-bubble{background:" + BLUE + ";color:#fff;border-bottom-right-radius:5px}" +
    ".nl-row.nl-cont.nl-bot .nl-bubble{border-bottom-left-radius:16px;border-top-left-radius:5px}" +
    ".nl-row.nl-cont.nl-user .nl-bubble{border-bottom-right-radius:16px;border-top-right-radius:5px}" +
    ".nl-typing{display:flex;gap:4px;align-items:center;padding:12px 14px}" +
    ".nl-typing span{width:7px;height:7px;border-radius:50%;background:#9bb0c4;display:inline-block}" +
    (reduceMotion ? "" :
      ".nl-typing span{animation:nl-bounce 1.2s infinite ease-in-out}" +
      ".nl-typing span:nth-child(2){animation-delay:.18s}" +
      ".nl-typing span:nth-child(3){animation-delay:.36s}" +
      "@keyframes nl-bounce{0%,60%,100%{transform:translateY(0);opacity:.5}30%{transform:translateY(-5px);opacity:1}}") +
    ".nl-chips{display:flex;flex-wrap:wrap;gap:7px;padding:2px 14px 8px;background:#f6f8fb}" +
    ".nl-chip{border:1px solid " + BLUE + ";color:" + BLUE + ";background:#fff;border-radius:18px;padding:6px 13px;font-size:13px;cursor:pointer;transition:background .12s ease,color .12s ease;font-family:inherit}" +
    ".nl-chip:hover{background:" + BLUE + ";color:#fff}" +
    ".nl-chip:focus-visible{outline:2px solid " + BLUE + ";outline-offset:1px}" +
    ".nl-chip-link{text-decoration:none;display:inline-block}" +
    ".nl-composer{border-top:1px solid #e8edf3;background:#fff;padding:8px 10px}" +
    ".nl-filechip{display:none;align-items:center;gap:8px;background:#eef4fb;border:1px solid #d6e4f3;border-radius:10px;padding:6px 10px;margin-bottom:8px;font-size:13px;color:#1b2b3d}" +
    ".nl-filechip.nl-show{display:inline-flex}" +
    ".nl-filechip .nl-fname{max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}" +
    ".nl-filex{border:none;background:none;cursor:pointer;color:#6b7a8d;font-size:16px;line-height:1;padding:0 2px}" +
    ".nl-filex:hover{color:#d9370c}" +
    ".nl-inputrow{display:flex;align-items:flex-end;gap:6px}" +
    ".nl-attach{flex:0 0 auto;border:none;background:none;cursor:pointer;color:#6b7a8d;width:38px;height:38px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:18px;padding:0}" +
    ".nl-attach:hover{background:#f0f3f7;color:" + BLUE + "}" +
    ".nl-attach:focus-visible{outline:2px solid " + BLUE + ";outline-offset:1px}" +
    ".nl-ta{flex:1;resize:none;border:1px solid #cdd7e2;border-radius:20px;padding:9px 14px;font:14px/1.4 inherit;max-height:120px;overflow-y:auto;outline:none;color:#1b2b3d}" +
    ".nl-ta:focus{border-color:" + BLUE + ";box-shadow:0 0 0 3px rgba(26,116,191,.12)}" +
    ".nl-send{flex:0 0 auto;border:none;background:" + BLUE + ";color:#fff;width:38px;height:38px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .12s ease;padding:0}" +
    ".nl-send:hover:not(:disabled){background:" + BLUE_DARK + "}" +
    ".nl-send:disabled{background:#c3d2e0;cursor:default}" +
    ".nl-send:focus-visible{outline:2px solid " + BLUE + ";outline-offset:2px}" +
    ".nl-send svg{width:19px;height:19px;display:block}" +
    ".nl-err{font-size:12px;color:#d9370c;padding:0 14px 6px;display:none}" +
    ".nl-err.nl-show{display:block}" +
    ".nl-retry{display:block;margin-top:7px;border:1px solid currentColor;background:transparent;color:inherit;border-radius:12px;padding:4px 11px;font:600 12px system-ui,Arial,sans-serif;cursor:pointer}" +
    ".nl-retry:disabled{opacity:.5;cursor:default}" +
    // dvh (iOS 15.4+) gives the real visible height under the keyboard/URL bar;
    // the vh line first is the fallback for browsers that don't know dvh.
    "@media (max-width:480px){.nl-panel{inset:0;width:100%;max-width:100%;height:100vh;max-height:100vh;height:100dvh;max-height:100dvh;border-radius:0}.nl-panel.nl-show{display:flex;animation:nl-slide .2s ease}.nl-bubble{max-width:85%}}" +
    "@keyframes nl-slide{from{transform:translateY(100%)}to{transform:none}}" +
    (reduceMotion ? ".nl-panel.nl-show,.nl-launcher,.nl-launcher svg{animation:none!important;transition:none!important}" : "");
  var styleTag = el("style"); styleTag.textContent = css; document.head.appendChild(styleTag);

  // ---- inline SVG glyphs ----------------------------------------------
  var CHAT_SVG = '<svg class="nl-ic-chat" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M21 11.5a8.38 8.38 0 0 1-8.9 8.4 9 9 0 0 1-4.1-.9L3 20l1.1-4a8.38 8.38 0 0 1-.9-4 8.5 8.5 0 0 1 8.9-8.4 8.5 8.5 0 0 1 8.9 8.4z" fill="currentColor"/></svg>';
  var X_SVG = '<svg class="nl-ic-x" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>';
  var CHEVRON_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>';
  var CLOSE_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>';
  var SEND_SVG = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M3.4 20.4 21 12 3.4 3.6 3 10l12 2-12 2z"/></svg>';

  // ---- build DOM ------------------------------------------------------
  var launcher = el("button", "nl-launcher");
  launcher.type = "button";
  launcher.setAttribute("data-testid", "widget-bubble");
  launcher.setAttribute("aria-label", I18N.open);
  launcher.setAttribute("aria-expanded", "false");
  launcher.style.background = BLUE;  // inline too, so computed bg is the brand blue even if CSS is blocked
  launcher.innerHTML = CHAT_SVG + X_SVG;
  var badge = el("span", "nl-badge"); badge.setAttribute("aria-hidden", "true");
  launcher.appendChild(badge);

  var panel = el("div", "nl-panel");
  panel.setAttribute("data-testid", "widget-panel");
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-modal", "true");
  panel.setAttribute("aria-label", I18N.title);

  // header
  var header = el("div", "nl-header");
  var avatar = el("div", "nl-avatar");
  var logo = el("img");
  logo.src = API + "/static/brand/nordland-logo.png";
  logo.alt = I18N.title;
  avatar.appendChild(logo);
  var htext = el("div", "nl-htext");
  var nameEl = el("div", "nl-name", "Nordland VVS");
  var statusEl = el("div", "nl-status");
  var srOnline = el("span", null, "Online — ");  // give the green dot an accessible meaning
  srOnline.style.cssText = "position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap";
  statusEl.append(srOnline, el("span", "nl-dot"));
  var statusTxt = el("span", null, I18N.status);
  statusEl.appendChild(statusTxt);
  htext.append(nameEl, statusEl);
  var hbtns = el("div", "nl-hbtns");
  var minBtn = el("button", "nl-iconbtn"); minBtn.type = "button";
  minBtn.setAttribute("aria-label", I18N.minimize); minBtn.innerHTML = CHEVRON_SVG;
  var closeBtn = el("button", "nl-iconbtn"); closeBtn.type = "button";
  closeBtn.setAttribute("aria-label", I18N.close); closeBtn.innerHTML = CLOSE_SVG;
  // language selector — lets the customer pick the conversation language
  var langSel = el("select", "nl-lang");
  langSel.setAttribute("data-testid", "widget-lang");
  langSel.setAttribute("aria-label", "Language / Språk");
  LANGS.forEach(function (pair) {
    var o = document.createElement("option");
    o.value = pair[0]; o.textContent = pair[1];
    if (pair[0] === LANG) o.selected = true;
    langSel.appendChild(o);
  });
  hbtns.append(langSel, minBtn, closeBtn);
  header.append(avatar, htext, hbtns);

  // transcript
  var log = el("div", "nl-log");
  log.setAttribute("data-testid", "widget-log");
  log.setAttribute("role", "log");
  log.setAttribute("aria-live", "polite");
  log.setAttribute("aria-relevant", "additions");  // role=log default; avoid re-announce on stream edits

  // chips
  var chipsBar = el("div", "nl-chips");

  // composer
  var composer = el("div", "nl-composer");
  var errLine = el("div", "nl-err");
  errLine.setAttribute("role", "alert");  // screen-reader announces errors as they appear
  var fileChip = el("div", "nl-filechip");
  var fileName = el("span", "nl-fname");
  var fileX = el("button", "nl-filex"); fileX.type = "button"; fileX.textContent = "✕";
  fileX.setAttribute("aria-label", I18N.remove);
  fileChip.append(fileName, fileX);
  var inputRow = el("div", "nl-inputrow");
  var attachBtn = el("button", "nl-attach"); attachBtn.type = "button";
  attachBtn.setAttribute("aria-label", I18N.attach); attachBtn.textContent = "📎";
  var fileInput = el("input"); fileInput.type = "file";
  fileInput.accept = "image/*,application/pdf"; fileInput.style.display = "none";
  var input = el("textarea", "nl-ta");
  input.setAttribute("data-testid", "widget-input");
  input.setAttribute("rows", "1");
  input.placeholder = I18N.placeholder;
  input.setAttribute("aria-label", I18N.placeholder);
  var sendBtn = el("button", "nl-send"); sendBtn.type = "button";
  sendBtn.setAttribute("data-testid", "widget-send");
  sendBtn.setAttribute("aria-label", I18N.send);
  sendBtn.innerHTML = SEND_SVG;
  sendBtn.disabled = true;
  inputRow.append(attachBtn, input, sendBtn);
  composer.append(errLine, fileChip, inputRow, fileInput);

  panel.append(header, log, chipsBar, composer);
  var nudge = el("button", "nl-nudge", I18N.nudge);
  nudge.type = "button";
  nudge.setAttribute("data-testid", "widget-nudge");
  nudge.onclick = function () { openPanel(); };
  document.body.append(launcher, panel, nudge);

  // ---- persistence ----------------------------------------------------
  // We persist the transcript (text + who), the chips, the session id and open
  // state so a reopen restores the conversation without a new session.
  var convo = [];   // {text, who}
  var lastChips = [];
  function save() {
    try {
      sessionStorage.setItem(STORE_KEY, JSON.stringify({
        sessionId: sessionId, convo: convo, chips: lastChips, lang: LANG, unread: unread,
        open: panel.classList.contains("nl-show")
      }));
    } catch (e) {}
  }
  function load() {
    try {
      var raw = sessionStorage.getItem(STORE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }

  // ---- rendering ------------------------------------------------------
  function rowFor(who) {
    var grouped = who === lastWho;
    var row = el("div", "nl-row " + (who === "user" ? "nl-user" : "nl-bot") +
      (grouped ? " nl-cont" : " nl-grp"));
    lastWho = who;
    return row;
  }
  function addMsg(text, who, persist) {
    var row = rowFor(who);
    var b = el("div", "nl-bubble", text);
    b.setAttribute("data-testid", who === "user" ? "msg-user" : "msg-bot");
    row.appendChild(b);
    log.appendChild(row);
    scrollDown();
    if (persist !== false) { convo.push({ text: text, who: who }); save(); }
    return b;
  }
  function scrollDown() { log.scrollTop = log.scrollHeight; }

  function clearChips() { chipsBar.innerHTML = ""; }
  function renderChips(chips) {
    clearChips();
    lastChips = chips || [];
    lastChips.forEach(function (c) {
      if (c.url) {
        var a = el("a", "nl-chip nl-chip-link", c.label || c.value);
        a.href = c.url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.setAttribute("data-testid", "chip-link");
        a.setAttribute("data-value", c.value || c.url);
        chipsBar.appendChild(a);
        return;
      }
      var btn = el("button", "nl-chip", c.label || c.value);
      btn.type = "button";
      btn.setAttribute("data-testid", "chip");
      btn.setAttribute("data-value", c.value);
      btn.onclick = function () { send(c.value, c.label || c.value); };
      chipsBar.appendChild(btn);
    });
    save();
  }

  // animated typing bubble (separate node; replaced by streamed text)
  function showTyping() {
    var row = rowFor("bot");
    var b = el("div", "nl-bubble");
    var t = el("div", "nl-typing");
    t.append(el("span"), el("span"), el("span"));
    b.appendChild(t);
    b.setAttribute("data-testid", "msg-bot");
    b.setAttribute("aria-label", I18N.typing);   // announce "Assistant is typing…" to screen readers
    row.appendChild(b);
    log.appendChild(row);
    scrollDown();
    return b;
  }

  function showError(msg) {
    errLine.classList.remove("nl-show");          // reset so a repeat error re-announces
    errLine.textContent = msg;
    void errLine.offsetWidth;                      // reflow → role=alert fires again
    errLine.classList.add("nl-show");
    setTimeout(function () { errLine.classList.remove("nl-show"); }, 7000);
  }

  // ---- transport --------------------------------------------------------
  // Wraps fetch with a hard timeout (AbortController) so a stalled socket
  // (observed in prod against our Vertex quota) can't spin the UI forever.
  function fetchWithTimeout(url, opts, ms) {
    // There is a real browser window with fetch and WITHOUT AbortController (Chrome
    // 42-65, Safari 10.1-12) and this demographic runs old devices — constructing it
    // unguarded would throw and kill every send. Degrade to an untimed fetch: slower to
    // fail, but it still works, which is the whole point.
    if (typeof AbortController === "undefined") return fetch(url, opts || {});
    var ctrl = new AbortController();
    var timedOut = false;
    var timer = setTimeout(function () { timedOut = true; ctrl.abort(); }, ms || REQUEST_TIMEOUT_MS);
    opts = opts || {};
    opts.signal = ctrl.signal;
    return fetch(url, opts).then(
      function (r) { clearTimeout(timer); return r; },
      function (err) { clearTimeout(timer); err.timedOut = timedOut; throw err; }
    );
  }
  // Appends a "try again" control to a bubble that resends the same request —
  // the customer never has to retype what they already sent. A 429 disables
  // the button for a short backoff instead of letting them hammer retry.
  function appendRetryButton(bubble, onRetry, rateLimited) {
    var btn = el("button", "nl-retry", I18N.retry);
    btn.type = "button";
    btn.setAttribute("data-testid", "widget-retry");
    if (rateLimited) {
      btn.disabled = true;
      setTimeout(function () { btn.disabled = false; }, RATE_LIMIT_BACKOFF_MS);
    }
    btn.onclick = function () { btn.disabled = true; onRetry(); };
    bubble.appendChild(btn);
  }
  function loadI18n() {
    fetch(API + "/static/widget/i18n/" + LANG + ".json")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j) return;
        Object.assign(I18N, j);
        logo.alt = I18N.title;
        panel.setAttribute("aria-label", I18N.title);
        input.placeholder = I18N.placeholder;
        input.setAttribute("aria-label", I18N.placeholder);
        sendBtn.setAttribute("aria-label", I18N.send);
        statusTxt.textContent = I18N.status;
        attachBtn.setAttribute("aria-label", I18N.attach);
        launcher.setAttribute("aria-label", isOpen() ? I18N.close : I18N.open);
        nudge.textContent = I18N.nudge;
      })
      .catch(function () {});
  }
  function openSession() {
    fetchWithTimeout(API + "/api/chat/session", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language: LANG })
    })
      .then(function (r) {
        if (r.status === 429) { var e = new Error("rate_limited"); e.rateLimited = true; throw e; }
        return r.json();
      })
      .then(function (j) {
        if (!j || !j.public_id) { var e2 = new Error("bad_session"); throw e2; }
        sessionId = j.public_id;
        addMsg(j.message, "bot");
        renderChips(j.chips);
      })
      .catch(function (err) {
        var msg = err && err.timedOut ? I18N.timeout : err && err.rateLimited ? I18N.rate_limited : I18N.error;
        var bubble = addMsg(msg, "bot", false);  // transient — don't persist the error into the transcript
        appendRetryButton(bubble, openSession, !!(err && err.rateLimited));
      });
  }
  function streamReply(opts) {
    busy = true;
    syncSend();
    var typingBubble = showTyping();
    var first = true;
    function fail(msg, rateLimited) {
      busy = false; syncSend();
      typingBubble.textContent = msg;
      appendRetryButton(typingBubble, function () { streamReply(opts); }, rateLimited);
    }
    fetchWithTimeout(API + "/api/chat/" + sessionId + "/message", opts).then(function (resp) {
      if (resp.status === 429) { fail(I18N.rate_limited, true); return; }
      if (!resp.ok || !resp.body) {  // 5xx: don't hang on a dead 'typing…'
        fail(I18N.error, false); return;
      }
      var reader = resp.body.getReader(), dec = new TextDecoder(), buf = "";
      function pump() {
        return reader.read().then(function (res) {
          if (res.done) { busy = false; syncSend(); save(); return; }
          buf += dec.decode(res.value, { stream: true });
          var i;
          while ((i = buf.indexOf("\n\n")) >= 0) {
            var frame = buf.slice(0, i); buf = buf.slice(i + 2);
            var line = frame.split("\n").find(function (l) { return l.indexOf("data: ") === 0; });
            if (!line) continue;
            var ev = JSON.parse(line.slice(6));
            if (ev.type === "message") {
              typingBubble.textContent = ev.message;
              if (first) { convo.push({ text: ev.message, who: "bot" }); first = false; }
              else { convo[convo.length - 1].text = ev.message; }
              renderChips(ev.chips);
              scrollDown();
              if (!isOpen()) bumpUnread();
            }
          }
          return pump();
        });
      }
      return pump();
    }).catch(function (err) {
      fail(err && err.timedOut ? I18N.timeout : I18N.error, false);
    });
  }
  function send(value, label) {
    if (busy || !value || !sessionId) return;
    addMsg(label || value, "user");
    clearChips(); lastChips = [];
    streamReply({
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: value })
    });
  }
  function sendFile(file, message) {
    if (busy || !sessionId) return;
    addMsg((file.type === "application/pdf" ? "📄 " : "📷 ") + file.name +
      (message ? "\n" + message : ""), "user");
    clearChips(); lastChips = [];
    var fd = new FormData();
    fd.append("image", file);
    fd.append("message", message || "");
    streamReply({ method: "POST", body: fd });
  }

  // ---- composer behaviour ---------------------------------------------
  function autoGrow() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  }
  function hasText() { return input.value.trim().length > 0; }
  function syncSend() {
    sendBtn.disabled = busy || !(hasText() || pendingFile);
    sendBtn.setAttribute("aria-busy", busy ? "true" : "false");
    var wasDisabled = input.disabled;
    input.disabled = busy;  // slow connection: no typing into a turn that's already in flight, no double-send
    // Re-enabling a focused element drops the caret, so a customer who was mid-thought had
    // to click back into the box after every reply. Give it straight back.
    if (wasDisabled && !busy && panel.classList.contains("nl-show")) {
      input.focus();
    }
  }
  function clearPending() {
    pendingFile = null; fileInput.value = "";
    fileChip.classList.remove("nl-show"); fileName.textContent = "";
    syncSend();
  }
  function submit() {
    if (busy) return;
    var v = input.value.trim();
    if (pendingFile) {
      var f = pendingFile; clearPending();
      input.value = ""; autoGrow();
      sendFile(f, v);
    } else if (v) {
      input.value = ""; autoGrow(); syncSend();
      send(v, v);
    }
  }

  attachBtn.onclick = function () { fileInput.click(); };
  fileInput.addEventListener("change", function () {
    var f = fileInput.files[0];
    if (!f) return;
    var typeOk = OK_TYPES.some(function (p) { return f.type.indexOf(p) === 0; });
    if (!typeOk) { showError(I18N.file_bad_type); fileInput.value = ""; return; }
    if (f.size > MAX_FILE) { showError(I18N.file_too_big); fileInput.value = ""; return; }
    pendingFile = f;
    fileName.textContent = f.name;
    fileChip.classList.add("nl-show");
    syncSend();
    input.focus();
  });
  fileX.onclick = function () { clearPending(); input.focus(); };

  input.addEventListener("input", function () {
    autoGrow(); syncSend();
    if (hasText() && lastChips.length) { clearChips(); lastChips = []; save(); }
  });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
  });
  sendBtn.onclick = submit;

  // iOS Safari resizes the visual viewport (not the layout viewport) when the
  // on-screen keyboard opens/closes; re-pin the log to the newest message and
  // keep the composer in view instead of letting the keyboard cover it.
  input.addEventListener("focus", function () { setTimeout(scrollDown, 300); });
  try {
    if (window.visualViewport) {
      window.visualViewport.addEventListener("resize", function () { if (isOpen()) scrollDown(); });
    }
  } catch (e) {}

  // ---- open / close ---------------------------------------------------
  function isOpen() { return panel.classList.contains("nl-show"); }
  function bumpUnread() {
    unread += 1;
    badge.textContent = unread > 9 ? "9+" : String(unread);
    badge.classList.add("nl-show");
    launcher.setAttribute("aria-label", I18N.open + " (" + (unread > 9 ? "9+" : unread) + ")");
  }
  function clearUnread() {
    unread = 0; badge.classList.remove("nl-show"); badge.textContent = "";
  }
  function openPanel() {
    panel.classList.add("nl-show");
    launcher.classList.add("nl-open");
    launcher.setAttribute("aria-expanded", "true");
    launcher.setAttribute("aria-label", I18N.close);
    nudge.classList.remove("nl-show");  // hide the pointer once the chat is open
    clearUnread();
    if (!started) {
      started = true;
      if (!sessionId) openSession();
    }
    scrollDown();
    // Caret straight into the composer so the customer can just start typing.
    setTimeout(function () { if (!input.disabled) input.focus(); }, reduceMotion ? 0 : 60);
    save();
  }
  function closePanel(restoreFocus) {
    panel.classList.remove("nl-show");
    launcher.classList.remove("nl-open");
    launcher.setAttribute("aria-expanded", "false");
    launcher.setAttribute("aria-label", I18N.open);
    nudge.classList.add("nl-show");  // re-show the pointer when the chat is closed
    if (restoreFocus !== false) launcher.focus();
    save();
  }
  launcher.onclick = function () { isOpen() ? closePanel() : openPanel(); };
  minBtn.onclick = function () { closePanel(); };
  closeBtn.onclick = function () { closePanel(); };
  // switching language restarts the chat in the chosen language (the bot replies in it)
  function switchLang(v) {
    if (!v || v === LANG) return;
    LANG = v;
    loadI18n();                          // localize the widget chrome
    sessionId = null; started = true; lastWho = null;
    convo.length = 0; lastChips = [];
    log.innerHTML = ""; clearChips();
    openSession();                       // fresh greeting + chips in the new language
    save();
  }
  langSel.onchange = function () { switchLang(langSel.value); };
  panel.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { e.stopPropagation(); closePanel(); return; }
    if (e.key !== "Tab") return;
    // trap focus inside the open dialog (don't let Tab reach the page behind it)
    var f = Array.prototype.filter.call(
      panel.querySelectorAll('button,[href],input,textarea,select,[tabindex]:not([tabindex="-1"])'),
      function (n) { return !n.disabled && n.offsetParent !== null; });
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  // ---- restore prior session ------------------------------------------
  (function restore() {
    var s = load();
    if (s && s.lang) { LANG = s.lang; try { langSel.value = LANG; } catch (e) {} }
    if (s && s.convo && s.convo.length) {
      sessionId = s.sessionId || null;
      started = !!sessionId;
      lastWho = null;
      s.convo.forEach(function (m) { addMsg(m.text, m.who, false); });
      renderChips(s.chips || []);
      if (s.open) { panel.classList.add("nl-show"); openPanel(); }
      else if (s.unread) {  // restore the unread badge without re-incrementing
        unread = s.unread;
        badge.textContent = unread > 9 ? "9+" : String(unread);
        badge.classList.add("nl-show");
        launcher.setAttribute("aria-label", I18N.open + " (" + badge.textContent + ")");
      }
    }
  })();

  // Localize the chrome up front. The launcher's aria-label and the nudge bubble are
  // the only widget text a visitor sees before clicking, and loading the catalogue on
  // first open left both in the built-in English on the Swedish site.
  loadI18n();

  // ---- auto-open (a dedicated chat page sets data-open="1") ------------
  if (AUTO_OPEN && !isOpen()) openPanel();
  // otherwise nudge the visitor toward the bubble with a blue pointer
  else if (!isOpen()) setTimeout(function () { if (!isOpen()) nudge.classList.add("nl-show"); }, 1000);
})();
