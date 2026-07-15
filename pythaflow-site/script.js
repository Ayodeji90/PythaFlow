// PythaFlow — purposeful motion only. Everything degrades gracefully
// without JS, and everything pauses under prefers-reduced-motion.
(function () {
  'use strict';

  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var hasIO = 'IntersectionObserver' in window;
  var $  = function (s, c) { return (c || document).querySelector(s); };
  var $$ = function (s, c) { return Array.prototype.slice.call((c || document).querySelectorAll(s)); };

  // ---- Year -------------------------------------------------------------
  var y = document.getElementById('year');
  if (y) y.textContent = new Date().getFullYear();

  // ---- Sticky header hairline ------------------------------------------
  var header = document.getElementById('header');
  var onScroll = function () { if (header) header.classList.toggle('scrolled', window.scrollY > 8); };
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  // ---- Mobile menu ------------------------------------------------------
  var toggle = document.getElementById('navToggle');
  var nav = document.getElementById('nav');
  var menu = document.getElementById('mobileMenu');
  if (toggle && menu) {
    toggle.addEventListener('click', function () {
      var open = menu.style.display === 'block';
      menu.style.display = open ? 'none' : 'block';
      nav.classList.toggle('open', !open);
      toggle.setAttribute('aria-expanded', String(!open));
    });
    $$('a', menu).forEach(function (a) {
      a.addEventListener('click', function () {
        menu.style.display = 'none'; nav.classList.remove('open');
        toggle.setAttribute('aria-expanded', 'false');
      });
    });
  }

  // ---- Staggered reveals ------------------------------------------------
  // Give cards their own reveal so they cascade instead of popping together.
  var grid = $('.cap-grid');
  if (grid) {
    grid.classList.remove('reveal');
    $$('.cap', grid).forEach(function (el, i) { el.classList.add('reveal'); el.style.setProperty('--d', (i * 70) + 'ms'); });
  }
  [['.truths .wrap', '.truth'], ['.principles', '.principle'], ['.steps', '.step'], ['.metrics', '.metric']]
    .forEach(function (pair) {
      var container = $(pair[0]); if (!container) return;
      $$(pair[1], container).forEach(function (el, i) { el.style.setProperty('--d', (i * 80) + 'ms'); });
    });

  var reveals = $$('.reveal');
  if (reduce || !hasIO) {
    reveals.forEach(function (el) { el.classList.add('in'); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } });
    }, { threshold: 0.12, rootMargin: '0px 0px -8% 0px' });
    reveals.forEach(function (el) { io.observe(el); });
  }

  // ---- Count-up ---------------------------------------------------------
  function countUp(el, to, opts) {
    opts = opts || {};
    var prefix = opts.prefix || '', dur = opts.dur || 1100, from = opts.from || 0;
    if (reduce) { el.textContent = prefix + to; return; }
    var start = null;
    var ease = function (t) { return 1 - Math.pow(1 - t, 3); };
    function step(ts) {
      if (start === null) start = ts;
      var p = Math.min((ts - start) / dur, 1);
      el.textContent = prefix + Math.round(from + (to - from) * ease(p));
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function whenVisible(el, cb) {
    if (reduce || !hasIO) { cb(); return; }
    var o = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) { cb(); o.disconnect(); } });
    }, { threshold: 0.5 });
    o.observe(el);
  }

  $$('.count').forEach(function (el) {
    var to = parseInt(el.getAttribute('data-count'), 10);
    if (isNaN(to)) return;
    whenVisible(el, function () { countUp(el, to, { dur: 1000 }); });
  });

  // ---- Live clock (console header) -------------------------------------
  var clock = document.getElementById('clock');
  if (clock) {
    var pad = function (n) { return String(n).padStart(2, '0'); };
    var tick = function () { var d = new Date(); clock.textContent = pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()); };
    tick(); if (!reduce) setInterval(tick, 1000);
  }

  // ---- Hero chat: the concierge handling a real guest, on a loop --------
  var chat = document.getElementById('chat');
  var esc = function (s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); };

  if (chat) {
    var CONVO = [
      { who: 'guest', text: 'Hi — any tables for two tonight, around 8?', t: '23:41' },
      { who: 'bot',   text: 'We’d be glad to host you. I have 8:00 or 8:30 — which suits you better?', t: '23:41' },
      { who: 'guest', text: '8:30 is perfect.', t: '23:42' },
      { who: 'bot',   text: 'Booked. Table for two at 8:30 tonight. Any dietary notes for the kitchen?', t: '23:42' },
      { who: 'guest', text: 'One vegetarian, thank you!', t: '23:43' },
      { who: 'confirm' }
    ];
    var CONFIRM = '<div class="confirm enter"><div class="ck">✓</div><div class="cf-t">' +
                  '<b>Reservation confirmed</b><span>Table for 2 · 8:30pm · 1 vegetarian noted → front desk</span></div></div>';

    var meta = function (step) {
      var tick = step.who === 'bot' ? ' <span class="tick">✓✓</span>' : '';
      return '<span class="bmeta">' + (step.t || '') + tick + '</span>';
    };
    var addMsg = function (step, animate) {
      var html = step.who === 'confirm'
        ? CONFIRM
        : '<div class="bubble ' + step.who + (animate ? ' enter' : '') + '">' + esc(step.text) + meta(step) + '</div>';
      chat.insertAdjacentHTML('beforeend', html);
      chat.scrollTop = chat.scrollHeight;
    };

    if (reduce || !hasIO) {
      CONVO.forEach(function (s) { addMsg(s, false); });          // static, complete transcript
    } else {
      var i = 0, timers = [];
      var wait = function (ms, fn) { timers.push(setTimeout(fn, ms)); };
      var clearTimers = function () { timers.forEach(clearTimeout); timers = []; };

      var next = function () {
        if (i >= CONVO.length) { wait(4600, function () { chat.innerHTML = ''; i = 0; next(); }); return; }
        var s = CONVO[i];
        if (s.who === 'bot') {                                    // show a typing indicator first
          chat.insertAdjacentHTML('beforeend', '<div class="typing enter"><i></i><i></i><i></i></div>');
          chat.scrollTop = chat.scrollHeight;
          wait(1000, function () {
            var t = chat.querySelector('.typing'); if (t) t.remove();
            addMsg(s, true); i++; wait(1150, next);
          });
        } else {
          addMsg(s, true); i++; wait(s.who === 'confirm' ? 500 : 1000, next);
        }
      };

      // The hero is above the fold — start playing right away, then use the
      // observer only to pause off-screen and restart cleanly on return.
      var started = true;
      next();
      if (hasIO) {
        new IntersectionObserver(function (es) {
          es.forEach(function (e) {
            if (e.isIntersecting && !started) { started = true; chat.innerHTML = ''; i = 0; next(); }
            else if (!e.isIntersecting && started) { started = false; clearTimers(); }
          });
        }, { threshold: 0.05 }).observe(chat);
      }
    }
  }

  // ---- Scrollspy: highlight the current section in the nav --------------
  var spy = $$('.nav-links a').filter(function (a) { return a.getAttribute('href').indexOf('#') === 0; });
  var sections = spy.map(function (a) { return document.getElementById(a.getAttribute('href').slice(1)); }).filter(Boolean);
  if (sections.length && hasIO) {
    var setActive = function (id) { spy.forEach(function (a) { a.classList.toggle('active', a.getAttribute('href') === '#' + id); }); };
    var visible = {};
    var sio = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { visible[e.target.id] = e.isIntersecting ? e.intersectionRatio : 0; });
      var best = null, bestR = 0;
      Object.keys(visible).forEach(function (k) { if (visible[k] > bestR) { bestR = visible[k]; best = k; } });
      if (best) setActive(best);
    }, { rootMargin: '-45% 0px -45% 0px', threshold: [0, 0.25, 0.5, 1] });
    sections.forEach(function (s) { sio.observe(s); });
  }
})();
