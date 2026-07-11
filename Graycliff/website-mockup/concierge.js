/* PythaFlow Concierge widget — v0 prototype.
 *
 * Drops onto any host page via one script tag:
 *   <script async src=".../concierge.js" data-restaurant="graycliff"
 *           data-api="https://api.pythaflow.com"></script>
 *
 * v0 scope: Shadow-DOM shell + text conversation against the existing
 * /api/voice/interpret endpoint. The streaming voice pipeline (mic,
 * VAD, STT/TTS) lands with the voice-gateway; this file is its home.
 * Design rule: the widget may never break or restyle the host page —
 * all styles live inside the shadow root, all failures degrade to a
 * phone-number card.
 */
(function () {
  "use strict";

  var script = document.currentScript;
  var CONFIG = {
    restaurant: (script && script.dataset.restaurant) || "graycliff",
    api: (script && script.dataset.api) || "http://localhost:8000",
    phone: (script && script.dataset.phone) || "+1 242 302 9150",
  };

  var host = document.createElement("div");
  host.id = "pythaflow-concierge";
  var root = host.attachShadow({ mode: "closed" });
  document.body.appendChild(host);

  root.innerHTML =
    '<style>' +
    ':host { all: initial; }' +
    '* { box-sizing: border-box; margin: 0; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }' +
    '.fab { position: fixed; right: 22px; bottom: 22px; z-index: 2147483000;' +
    '  width: 62px; height: 62px; border-radius: 50%; border: none; cursor: pointer;' +
    '  background: #b3902f; color: #17140f; box-shadow: 0 6px 24px rgba(0,0,0,0.35);' +
    '  display: flex; align-items: center; justify-content: center; transition: transform .15s; }' +
    '.fab:hover { transform: scale(1.06); }' +
    '.fab svg { width: 26px; height: 26px; }' +
    '.fab .badge { position: absolute; top: -4px; right: -4px; background: #17140f; color: #b3902f;' +
    '  font-size: 8.5px; letter-spacing: .08em; padding: 2px 6px; border-radius: 999px; border: 1px solid #b3902f; }' +
    '.panel { position: fixed; right: 22px; bottom: 96px; z-index: 2147483000;' +
    '  width: min(380px, calc(100vw - 32px)); height: min(560px, calc(100vh - 130px));' +
    '  background: #1c1813; color: #f3ead8; border: 1px solid rgba(179,144,47,.45); border-radius: 16px;' +
    '  display: none; flex-direction: column; overflow: hidden; box-shadow: 0 18px 60px rgba(0,0,0,.5); }' +
    '.panel.open { display: flex; }' +
    '.head { padding: 16px 18px 12px; border-bottom: 1px solid rgba(243,234,216,.12); }' +
    '.head .brand { font-family: "Berkshire Swash", Georgia, serif; letter-spacing: .01em; font-size: 21px; color: #ffffff; }' +
    '.head .sub { font-size: 10.5px; color: #9b9384; letter-spacing: .06em; margin-top: 3px; }' +
    '.head .sub b { color: #b3902f; font-weight: 600; }' +
    '.log { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; }' +
    '.msg { max-width: 86%; padding: 10px 13px; border-radius: 12px; font-size: 13.5px; line-height: 1.5; }' +
    '.msg.guest { align-self: flex-end; background: #b3902f; color: #17140f; border-bottom-right-radius: 4px; }' +
    '.msg.agent { align-self: flex-start; background: #29241c; border-bottom-left-radius: 4px; }' +
    '.msg.agent.thinking { color: #9b9384; font-style: italic; }' +
    '.card { align-self: flex-start; width: 92%; background: rgba(179,144,47,.10);' +
    '  border: 1px solid rgba(179,144,47,.4); border-radius: 12px; padding: 12px 14px; font-size: 12.5px; }' +
    '.card .title { color: #b3902f; letter-spacing: .1em; font-size: 10.5px; margin-bottom: 8px; }' +
    '.card .row { display: flex; justify-content: space-between; gap: 10px; padding: 3px 0; }' +
    '.card .row span:last-child { color: #b3902f; white-space: nowrap; }' +
    '.chips { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 16px 10px; }' +
    '.chip { font-size: 11px; color: #cfc7b4; background: transparent; border: 1px solid rgba(243,234,216,.25);' +
    '  border-radius: 999px; padding: 5px 11px; cursor: pointer; }' +
    '.chip:hover { border-color: #b3902f; color: #b3902f; }' +
    '.inbar { display: flex; gap: 8px; padding: 12px 14px; border-top: 1px solid rgba(243,234,216,.12); }' +
    '.inbar input { flex: 1; background: #14100c; color: #f3ead8; border: 1px solid rgba(243,234,216,.18);' +
    '  border-radius: 10px; padding: 10px 12px; font-size: 13.5px; outline: none; }' +
    '.inbar input:focus { border-color: #b3902f; }' +
    '.inbar button { background: #b3902f; color: #17140f; border: none; border-radius: 10px;' +
    '  padding: 0 16px; font-size: 13px; font-weight: 600; cursor: pointer; }' +
    '.inbar button:disabled { opacity: .5; cursor: default; }' +
    '.mic { background: transparent; border: 1px dashed rgba(243,234,216,.3); color: #9b9384;' +
    '  border-radius: 10px; width: 40px; cursor: not-allowed; font-size: 15px; }' +
    '.foot { text-align: center; font-size: 9.5px; color: #6d675c; padding: 0 0 9px; }' +
    '@media (max-width: 480px) { .panel { right: 16px; } .fab { right: 16px; } }' +
    '</style>' +

    '<button class="fab" aria-label="Open Graycliff concierge">' +
    '  <span class="badge">BETA</span>' +
    '  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">' +
    '    <rect x="9" y="3" width="6" height="11" rx="3"></rect>' +
    '    <path d="M5 11a7 7 0 0 0 14 0"></path><path d="M12 18v3"></path>' +
    '  </svg>' +
    '</button>' +

    '<div class="panel" role="dialog" aria-label="Graycliff concierge">' +
    '  <div class="head">' +
    '    <div class="brand">Graycliff</div>' +
    '    <div class="sub">AI Concierge · <b>prototype</b> — reservations &amp; dining questions</div>' +
    '  </div>' +
    '  <div class="log"></div>' +
    '  <div class="chips">' +
    '    <button class="chip">Book a table for two tomorrow at 8pm</button>' +
    '    <button class="chip">What pairs with the lobster?</button>' +
    '    <button class="chip">Two conch fritters please</button>' +
    '  </div>' +
    '  <div class="inbar">' +
    '    <button class="mic" title="Voice arrives with the streaming gateway" aria-disabled="true">🎙</button>' +
    '    <input type="text" placeholder="Ask the house anything…" aria-label="Message">' +
    '    <button class="send">Send</button>' +
    '  </div>' +
    '  <div class="foot">powered by PythaFlow · text prototype — streaming voice next</div>' +
    '</div>';

  var fab = root.querySelector(".fab");
  var panel = root.querySelector(".panel");
  var log = root.querySelector(".log");
  var input = root.querySelector("input");
  var send = root.querySelector(".send");
  var greeted = false;

  fab.addEventListener("click", function () {
    panel.classList.toggle("open");
    if (panel.classList.contains("open")) {
      if (!greeted) {
        greeted = true;
        agentSay("Good evening — welcome to Graycliff. I can book your table or answer questions about the restaurant. How may I help?");
      }
      input.focus();
    }
  });

  function bubble(cls, text) {
    var el = document.createElement("div");
    el.className = "msg " + cls;
    el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }
  function agentSay(text) { return bubble("agent", text); }

  function actionCard(action) {
    if (!action || action.type === "none") return;
    var el = document.createElement("div");
    el.className = "card";
    var html = "";
    if (action.type === "reservation") {
      var r = action.reservation;
      html = '<div class="title">RESERVATION CONFIRMED</div>' +
        '<div class="row"><span>' + esc(r.guest_name) + " · party of " + r.party_size + "</span>" +
        "<span>" + esc(r.date) + " · " + esc(r.time) + "</span></div>";
    } else if (action.type === "order") {
      var o = action.order;
      html = '<div class="title">SENT TO THE KITCHEN · #' + o.id + "</div>";
      o.items.forEach(function (it) {
        html += '<div class="row"><span>' + it.qty + " × " + esc(it.name) + "</span><span>$" +
          (it.unit_price * it.qty).toFixed(0) + "</span></div>";
      });
      html += '<div class="row"><span><b>Total</b></span><span><b>$' + o.total.toFixed(0) + "</b></span></div>";
    }
    el.innerHTML = html;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  var busy = false;
  function submit(text) {
    text = (text || "").trim();
    if (!text || busy) return;
    busy = true; send.disabled = true;
    bubble("guest", text);
    input.value = "";
    var thinking = bubble("agent thinking", "…");

    fetch(CONFIG.api + "/api/voice/interpret", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript: text }),
    })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        thinking.remove();
        agentSay(d.reply);
        actionCard(d.action);
      })
      .catch(function () {
        thinking.remove();
        agentSay("I'm having trouble reaching the house right now — please call us at " +
          CONFIG.phone + " and we'll take care of you directly.");
      })
      .finally(function () { busy = false; send.disabled = false; input.focus(); });
  }

  send.addEventListener("click", function () { submit(input.value); });
  input.addEventListener("keydown", function (e) { if (e.key === "Enter") submit(input.value); });
  root.querySelectorAll(".chip").forEach(function (c) {
    c.addEventListener("click", function () { submit(c.textContent); });
  });

  // Deep link: a "#concierge" hash opens the panel (usable from any
  // "Chat with us" link on the host site). "#concierge=<text>" also
  // sends a first message — handy for demos.
  if (location.hash.indexOf("#concierge") === 0) {
    fab.click();
    var preset = decodeURIComponent(location.hash.split("=")[1] || "");
    if (preset) setTimeout(function () { submit(preset); }, 400);
  }
})();
