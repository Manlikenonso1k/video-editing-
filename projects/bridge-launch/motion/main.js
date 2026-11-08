/* global gsap */
/*
 * Bridge launch: motion composition.
 *
 * Everything is driven by ONE paused GSAP timeline plus a small "procedural"
 * layer (particles, grain, typing). The renderer calls window.__init(content, rec)
 * once, then window.__seek(t) for every frame, so output is frame-exact and
 * deterministic regardless of how long each screenshot takes.
 */
(() => {
  'use strict';

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  const SVGNS = 'http://www.w3.org/2000/svg';

  let C;              // content.json
  let REC = null;     // prepared screen recording (or null → animated mock screen)
  let FPS = 60;
  let tl;             // master timeline
  let DURATION = 0;
  const T = {};       // named times, filled in by build()
  const cues = [];    // sound-design cues, consumed by scripts/soundtrack.py
  const state = { particles: 0, pulse: 0, progress: 0 };
  const bridge = {};
  const mockEls = {};

  const cue = (t, type, extra) => cues.push(Object.assign({ t: +t.toFixed(3), type }, extra || {}));

  function el(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function svgEl(tag, attrs) {
    const e = document.createElementNS(SVGNS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }
  const hash = (n) => { // deterministic 0..1 noise per integer
    let x = (n * 374761393 + 668265263) | 0;
    x = Math.imul(x ^ (x >>> 13), 1274126177);
    return ((x ^ (x >>> 16)) >>> 0) / 4294967296;
  };

  /* ---------------- text splitting ---------------- */

  function splitWords(node, text, gradWords = []) {
    node.textContent = '';
    const inners = [];
    text.split(' ').forEach((w, i, a) => {
      const outer = el('span', 'w');
      const inner = el('span', 'wi' + (gradWords.includes(i) ? ' grad-ch' : ''));
      inner.textContent = w;
      outer.appendChild(inner);
      node.appendChild(outer);
      if (i < a.length - 1) node.appendChild(document.createTextNode(' '));
      inners.push(inner);
    });
    return inners;
  }

  function splitChars(node, text) {
    node.textContent = '';
    return [...text].map((c) => {
      const s = el('span', 'ch');
      s.textContent = c === ' ' ? ' ' : c;
      node.appendChild(s);
      return s;
    });
  }

  // One continuous gradient across spans that animate independently.
  function spanGradient(spans) {
    const rects = spans.map((s) => s.getBoundingClientRect());
    const minL = Math.min(...rects.map((r) => r.left));
    const maxR = Math.max(...rects.map((r) => r.right));
    spans.forEach((s, i) => {
      s.classList.add('grad-ch');
      s.style.backgroundSize = `${maxR - minL}px 100%`;
      s.style.backgroundPosition = `${-(rects[i].left - minL)}px 0`;
    });
  }

  /* ---------------- the bridge mark ---------------- */

  const BR = { L: 100, R: 700, deck: 210, ctrl: -30 };
  const arcY = (x) => {
    const u = (x - BR.L) / (BR.R - BR.L);
    return (1 - u) * (1 - u) * BR.deck + 2 * (1 - u) * u * BR.ctrl + u * u * BR.deck;
  };

  function buildBridge() {
    const lines = $('#bridgeLines'), glow = $('#bridgeGlow'), nodes = $('#bridgeNodes'), parts = $('#bridgeParticles');
    const arcD = `M${BR.L},${BR.deck} Q400,${BR.ctrl} ${BR.R},${BR.deck}`;
    const deckD = `M${BR.L - 50},${BR.deck} L${BR.R + 50},${BR.deck}`;
    const mk = (parent, d, w, op = 1) => {
      const p = svgEl('path', { d, fill: 'none', stroke: 'url(#gStroke)', 'stroke-width': w, 'stroke-linecap': 'round', opacity: op });
      parent.appendChild(p);
      return p;
    };
    bridge.deckGlow = mk(glow, deckD, 14);
    bridge.arcGlow = mk(glow, arcD, 18);
    bridge.deck = mk(lines, deckD, 8);
    bridge.arc = mk(lines, arcD, 10);
    bridge.hangers = [];
    for (let x = 175; x <= 625; x += 75) bridge.hangers.push(mk(lines, `M${x},${arcY(x) + 9} L${x},${BR.deck - 7}`, 4, 0.7));

    bridge.nodes = [BR.L, BR.R].map((x) => {
      const outer = svgEl('g', { transform: `translate(${x},${BR.deck})` });
      const g = svgEl('g', {});
      const pulse = svgEl('circle', { r: 30, fill: 'none', stroke: '#7FF0DD', 'stroke-width': 2, opacity: 0 });
      const ring = svgEl('circle', { r: 32, fill: '#070A14', stroke: 'url(#gStroke)', 'stroke-width': 3 });
      const core = svgEl('circle', { r: 17, fill: 'url(#gNode)' });
      g.append(ring, core);
      outer.append(pulse, g);
      nodes.appendChild(outer);
      return { g, pulse };
    });

    bridge.particles = Array.from({ length: 8 }, (_, i) => {
      const c = svgEl('circle', { r: i % 2 ? 4 : 5.5, fill: i % 3 === 0 ? '#9DF5E6' : '#FFFFFF', opacity: 0 });
      parts.appendChild(c);
      return { c, onArc: i % 2 === 0, phase: (i * 0.618) % 1, speed: 0.36 + (i % 3) * 0.06 };
    });

    [bridge.deckGlow, bridge.arcGlow, bridge.deck, bridge.arc, ...bridge.hangers].forEach((p) => {
      const L = p.getTotalLength();
      p.style.strokeDasharray = `${L} ${L}`;
      p.style.strokeDashoffset = L;
    });
  }

  // Where the mark sits as a small logo (top-left corner) during the middle scenes.
  function logoTransform() {
    const vis = { x: 50, y: 85, w: 700, h: 157 };  // visible bounds of the svg content
    const targetW = 118, targetL = 66, targetCY = 74;
    const s = targetW / vis.w;
    const mark = $('#mark');
    const left = targetL - vis.x * s;
    const top = targetCY - (vis.y + vis.h / 2) * s;
    const wm = $('#wordmark');
    wm.style.left = `${targetL + targetW + 18}px`;
    wm.style.top = `${targetCY - 22}px`;
    return { x: left - mark.offsetLeft, y: top - mark.offsetTop, scale: s };
  }

  /* ---------------- mock app screen (stand-in until a recording is supplied) ---------------- */

  function buildMock() {
    const m = C.mockScreen;
    const recv = (parseFloat(m.amount) - m.fee).toFixed(2);
    $('#mock').innerHTML = `
      <div class="m-status"><span>9:41</span><span class="bars"><i style="height:5px"></i><i style="height:8px"></i><i style="height:11px"></i><i style="height:14px"></i></span></div>
      <div class="m-head"><span class="back"></span>${m.appTitle}<span class="gear"></span></div>
      <div class="m-card from" id="mFrom">
        <div class="m-label">From</div>
        <div class="m-chip" id="mChipFrom"><span class="dot"></span>${m.from}</div>
        <div class="m-amount dim" id="mAmt"><span class="val" id="mAmtVal">0.00</span><span class="caret" id="mCaret"></span><span class="unit">${m.unit}</span></div>
        <div class="m-sub">Balance ${m.balance} ${m.unit}</div>
      </div>
      <div class="m-swap" id="mSwap"></div>
      <div class="m-card to" id="mTo">
        <div class="m-label">To</div>
        <div class="m-chip" id="mChipTo"><span class="dot"></span>${m.to}</div>
        <div class="m-amount dim" id="mRcv"><span class="val" id="mRcvVal">0.00</span><span class="unit">${m.unit}</span></div>
        <div class="m-sub">You receive</div>
      </div>
      <div class="m-details">
        <div class="m-row"><span>Network fee</span><b>${m.fee.toFixed(2)} ${m.unit}</b></div>
        <div class="m-row"><span>Arrives in</span><b>${m.eta}</b></div>
        <div class="m-row"><span>Route</span><span class="m-route"><i></i><s></s><i></i></span></div>
      </div>
      <div class="m-recent">
        <div class="m-label">Recent</div>
        <div class="m-rrow"><span class="m-route"><i></i><s></s><i></i></span><span class="m-rtxt">${m.from} → ${m.to}</span><b>120.00</b></div>
      </div>
      <div class="m-btn" id="mBtn"><span class="fill" id="mFill"></span><span class="lbl" id="mBtnLbl">${m.button}</span></div>
      <div class="m-home"></div>
      <div class="m-done" id="mDone">
        <svg viewBox="0 0 150 150">
          <circle id="doneRing" cx="75" cy="75" r="66" fill="rgba(62,230,201,.12)" stroke="#3EE6C9" stroke-width="6" stroke-linecap="round" transform="rotate(-90 75 75)"/>
          <path id="doneTick" d="M46 77 L66 97 L106 55" fill="none" stroke="#fff" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <h3 id="mDoneTitle">${m.doneTitle}</h3>
        <p id="mDoneBody">${recv} ${m.unit}<br>${m.doneBody} ${m.to}</p>
      </div>`;
    ['mAmt', 'mAmtVal', 'mCaret', 'mRcv', 'mRcvVal', 'mBtn', 'mBtnLbl', 'mFill', 'mDone', 'doneRing', 'doneTick', 'mSwap', 'mChipFrom', 'mChipTo', 'mDoneTitle', 'mDoneBody']
      .forEach((id) => { mockEls[id] = $('#' + id); });
    ['doneRing', 'doneTick'].forEach((id) => {
      const p = mockEls[id], L = p.getTotalLength();
      p.style.strokeDasharray = `${L} ${L}`;
      p.style.strokeDashoffset = L;
    });
  }

  /* ---------------- callouts ---------------- */

  function screenRect() {
    const s = $('#screen'), d = s.parentElement;
    return { x: d.offsetLeft + s.offsetLeft, y: d.offsetTop + s.offsetTop, w: s.offsetWidth, h: s.offsetHeight, devL: d.offsetLeft, devR: d.offsetLeft + d.offsetWidth };
  }

  function buildCallouts() {
    const box = $('#callouts');
    const sr = screenRect();
    const GAP = 64, W = 400;
    return C.showcase.callouts.map((c) => {
      const tx = sr.x + c.target.x * sr.w;
      const ty = sr.y + c.target.y * sr.h;
      const co = el('div', `callout ${c.side}`, `<div class="c-num">${c.num}</div><div class="c-title">${c.title}</div><div class="c-body">${c.body}</div>`);
      const ld = el('div', `leader ${c.side}`, '<span class="ln"></span><span class="ring"></span><span class="pt"></span>');
      if (c.side === 'left') {
        const right = sr.devL - GAP;
        co.style.left = `${right - W}px`;
        ld.style.left = `${right + 22}px`;
        ld.style.width = `${Math.max(40, tx - right - 22)}px`;
      } else {
        const left = sr.devR + GAP;
        co.style.left = `${left}px`;
        ld.style.left = `${tx}px`;
        ld.style.width = `${Math.max(40, left - 22 - tx)}px`;
      }
      box.append(co, ld);
      co.style.top = `${ty - 56}px`;           // align the title's first line with the leader
      ld.style.top = `${ty - 1}px`;
      return { c, co, ld, ln: $('.ln', ld), pt: $('.pt', ld), ring: $('.ring', ld), parts: [...co.children] };
    });
  }

  /* ---------------- narration captions (recording mode) ---------------- */

  // Split each transcribed sentence into short, readable chunks (<=7 words, prefer punctuation).
  function captionChunks() {
    const chunks = [];
    REC.captions.forEach((seg, si) => {
      const side = si % 2 === 0 ? 'left' : 'right';
      let cur = [];
      seg.words.forEach((w, wi) => {
        cur.push(w);
        const punct = /[,.!?;:]$/.test(w.w);
        const last = wi === seg.words.length - 1;
        if (last || cur.length >= 7 || (punct && cur.length >= 3)) {
          const prev = chunks[chunks.length - 1];
          if (cur.length <= 2 && prev && prev.seg === si && prev.words.length + cur.length <= 9) prev.words.push(...cur);
          else chunks.push({ seg: si, side, words: cur });
          cur = [];
        }
      });
    });
    chunks.forEach((c) => { c.start = c.words[0].start; c.end = c.words[c.words.length - 1].end; });
    return chunks;
  }

  const SHIFT = 110; // the phone glides away from whichever side is speaking
  function buildCaptions() {
    const layer = $('#captions');
    const dev = $('.device');
    return captionChunks().map((c) => {
      const cap = el('div', `cap ${c.side}`, '<div class="cap-eq">' + '<i></i>'.repeat(5) + '</div><div class="cap-text"></div>');
      const txt = $('.cap-text', cap);
      c.spans = c.words.map((w, i) => {
        const sp = el('span', 'cw');
        sp.textContent = w.w;
        txt.appendChild(sp);
        if (i < c.words.length - 1) txt.appendChild(document.createTextNode(' '));
        return sp;
      });
      if (c.side === 'left') cap.style.left = `${dev.offsetLeft + SHIFT - 70 - 600}px`;
      else cap.style.left = `${dev.offsetLeft + dev.offsetWidth - SHIFT + 70}px`;
      layer.appendChild(cap);
      c.el = cap;
      return c;
    });
  }

  /* ---------------- feature cards ---------------- */

  const ICONS = {
    bolt: '<path d="M29 3 L9 30 H25 L22 49 L43 20 H27 Z"/>',
    tap: '<path d="M20 27 V12 a5 5 0 0 1 10 0 V24 l8.5 2.4 a5 5 0 0 1 3.6 5.7 L40.4 43 a6 6 0 0 1 -5.9 5 H25 a6 6 0 0 1 -4.6 -2.2 L10.5 33.6 a4.2 4.2 0 0 1 6.3 -5.4 Z"/><path d="M12 13 a13 13 0 0 1 26 0"/>',
    shield: '<path d="M26 3 L44 10 V24 C44 36.5 36.5 45 26 49 C15.5 45 8 36.5 8 24 V10 Z"/><path d="M17 25.5 L23.5 32 L35.5 19.5"/>',
    globe: '<circle cx="26" cy="26" r="21"/><path d="M5 26 H47"/><path d="M26 5 C33 12 33 40 26 47 C19 40 19 12 26 5 Z"/>',
    clock: '<circle cx="26" cy="26" r="21"/><path d="M26 14 V26 L34 31"/>',
  };

  function buildCards() {
    const wrap = $('#cards');
    return C.features.items.map((f) => {
      const card = el('div', 'card', `
        <div class="icon"><svg viewBox="0 0 52 52" fill="none" stroke="#E9FFFB" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">${ICONS[f.icon] || ICONS.bolt}</svg></div>
        <h3>${f.title}</h3><p>${f.body}</p><span class="bar"></span>`);
      wrap.appendChild(card);
      const paths = $$('path, circle', card);
      paths.forEach((p) => {
        const L = p.getTotalLength();
        p.style.strokeDasharray = `${L} ${L}`;
        p.style.strokeDashoffset = L;
      });
      return { card, icon: $('.icon', card), paths, h3: $('h3', card), p: $('p', card), bar: $('.bar', card) };
    });
  }

  /* ---------------- grain ---------------- */

  function buildGrain() {
    const cv = document.createElement('canvas');
    cv.width = cv.height = 256;
    const ctx = cv.getContext('2d');
    const img = ctx.createImageData(256, 256);
    for (let i = 0; i < 256 * 256; i++) {
      const v = Math.floor(hash(i + 17) * 255);
      img.data[i * 4] = img.data[i * 4 + 1] = img.data[i * 4 + 2] = v;
      img.data[i * 4 + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
    $('#grain').style.backgroundImage = `url(${cv.toDataURL('image/png')})`;
  }

  /* ================================================================
   *  TIMELINE
   * ================================================================ */

  function build() {
    const ease = { out: 'expo.out', in: 'power3.in', io: 'expo.inOut' };
    tl = gsap.timeline({ paused: true, defaults: { ease: ease.out } });

    buildBridge();
    buildGrain();

    // ----- recording vs mock, phone vs browser -----
    const device = $('#phone');
    if (REC) {
      document.body.classList.add('has-rec');
      if (REC.orientation === 'landscape') device.className = 'device browser';
    }
    if (!REC) buildMock();

    /* ---------- 1. HOOK ---------- */
    const h1 = splitWords($('#hook1'), C.hook[0]);
    const h2 = splitWords($('#hook2'), C.hook[1]);
    spanGradient(h2);
    tl.fromTo(h1, { yPercent: 115 }, { yPercent: 0, duration: 1.0, ease: 'power4.out', stagger: 0.09 }, 0.15);
    tl.fromTo(h2, { yPercent: 115 }, { yPercent: 0, duration: 1.0, ease: 'power4.out', stagger: 0.09 }, 0.55);
    tl.fromTo('#s-hook', { scale: 1 }, { scale: 1.045, duration: 2.9, ease: 'none' }, 0);
    cue(0.12, 'swish', { pan: -0.3 });
    cue(0.52, 'swish', { pan: 0.3 });
    tl.to([...h1, ...h2], { yPercent: -115, duration: 0.5, ease: ease.in, stagger: 0.035 }, 2.5);
    cue(1.75, 'riser', { end: 3.6 });
    cue(2.62, 'whoosh', { pan: 0 });

    /* ---------- 2. TITLE ---------- */
    T.title = 2.95;
    const tt = T.title;
    bridge.nodes.forEach((n, i) => {
      tl.fromTo(n.g, { scale: 0, transformOrigin: '50% 50%' }, { scale: 1, duration: 0.7, ease: 'back.out(2.6)' }, tt + 0.05 + i * 0.12);
      cue(tt + 0.05 + i * 0.12, 'pop', { pan: i ? 0.6 : -0.6 });
    });
    tl.to([bridge.deck, bridge.deckGlow], { strokeDashoffset: 0, duration: 0.75, ease: 'power2.inOut' }, tt + 0.1);
    tl.to([bridge.arc, bridge.arcGlow], { strokeDashoffset: 0, duration: 0.9, ease: 'power3.inOut' }, tt + 0.2);
    tl.to(bridge.hangers, { strokeDashoffset: 0, duration: 0.35, ease: 'power2.out', stagger: 0.045 }, tt + 0.55);
    tl.to(state, { particles: 1, duration: 0.6, ease: 'none' }, tt + 0.9);
    tl.to(state, { pulse: 1, duration: 0.4, ease: 'none' }, tt + 0.7);

    const tw = $('#titleWord');
    const chars = splitChars(tw, C.title.word);
    tl.fromTo(chars,
      { yPercent: 90, rotationX: -85, opacity: 0, transformPerspective: 900, transformOrigin: '50% 100%' },
      { yPercent: 0, rotationX: 0, opacity: 1, duration: 1.1, stagger: 0.045 }, tt + 0.6);
    T.impact = tt + 0.65;
    cue(T.impact, 'impact');
    cue(T.impact, 'drop');
    tl.fromTo('#world', { scale: 1.035 }, { scale: 1, duration: 1.0, immediateRender: false }, T.impact);

    $('#badge').textContent = C.title.badge;
    $('#eyebrow').textContent = C.title.eyebrow;
    tl.fromTo('#badge', { scale: 0.5, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.7, ease: 'back.out(2.2)' }, tt + 1.0);
    tl.fromTo('#eyebrow', { x: -24, opacity: 0 }, { x: 0, opacity: 1, duration: 0.8 }, tt + 1.1);
    cue(tt + 1.0, 'tick', { pan: -0.1 });
    const sub = splitWords($('#subtitle'), C.title.subtitle);
    tl.fromTo(sub, { yPercent: 110 }, { yPercent: 0, duration: 0.9, stagger: 0.035, ease: 'power4.out' }, tt + 1.3);

    /* ---------- title → showcase ---------- */
    T.t1 = 6.55;
    tl.to(chars, { yPercent: -60, opacity: 0, duration: 0.45, ease: ease.in, stagger: 0.025 }, T.t1);
    tl.to(['#eyebrowRow', '#subtitle'], { y: -26, opacity: 0, duration: 0.4, ease: ease.in }, T.t1);
    const logo = logoTransform();
    tl.to('#mark', { x: logo.x, y: logo.y, scale: logo.scale, duration: 1.0, ease: ease.io }, T.t1 + 0.2);
    tl.to(state, { particles: 0, pulse: 0, duration: 0.4, ease: 'none' }, T.t1 + 0.2);
    tl.fromTo('#wordmark', { x: -16, opacity: 0 }, { x: 0, opacity: 1, duration: 0.7 }, T.t1 + 1.05);
    $('#wordmark').textContent = C.title.word;
    cue(T.t1 + 0.2, 'whoosh', { pan: -0.5 });

    /* ---------- 3. SHOWCASE ---------- */
    T.show = 7.0;
    const captionMode = !!(REC && REC.captions && REC.captions.length && C.recording.captions !== false);
    T.captionMode = captionMode;
    T.lead = REC && REC.audio ? 0.9 : 0;          // phone lands, then the narration starts
    T.rec = T.show + T.lead;                        // recording t=0 on the master timeline
    const L = REC ? T.lead + REC.slotSeconds + (REC.audio ? 0.6 : 0) : C.showcase.seconds;
    T.showEnd = T.show + L;
    const s0 = T.show;

    tl.fromTo('#deviceWrap',
      { y: 980, rotationX: 40, rotationZ: -7, scale: 0.78, opacity: 0 },
      { y: 0, rotationX: 0, rotationZ: 0, scale: 1, opacity: 1, duration: 1.5, ease: 'expo.out' }, s0);
    tl.set('#deviceWrap', { opacity: 1 }, s0 + 0.15);
    tl.fromTo('#deviceGlow', { scale: 0.5, opacity: 0 }, { scale: 1, opacity: 1, duration: 1.4 }, s0 + 0.2);
    tl.fromTo('#deviceWrap', { rotationY: -7 }, { rotationY: 5, duration: L, ease: 'sine.inOut', immediateRender: false }, s0);
    cue(s0 + 0.02, 'whoosh_big', { pan: 0.2 });

    // camera: slow push-in while the callouts play, ease back out before features
    if (!captionMode) tl.to('#camera', { scale: 1.055, y: -8, duration: Math.max(2, L - 3.4), ease: 'sine.inOut' }, s0 + 1.2);
    tl.to('#camera', { scale: 1, y: 0, duration: 1.2, ease: 'sine.inOut' }, T.showEnd - 1.6);

    // narration captions: every sentence takes a side, the phone glides away from it,
    // and each chunk's words light up exactly when they're spoken
    if (captionMode) {
      const caps = buildCaptions();
      const r0 = T.rec;
      caps.forEach((c, i) => {
        const at = r0 + c.start;
        const dir = c.side === 'left' ? -1 : 1;
        const prev = caps[i - 1];
        if (!prev || prev.seg !== c.seg) {
          const mv = Math.max(s0 + 0.35, at - 0.45);
          tl.to('#rig', { x: -dir * SHIFT, rotationY: dir * 7, duration: 0.9, ease: 'expo.inOut' }, mv);
          tl.to('#camera', { scale: c.seg % 2 ? 1.0 : 1.035, duration: 0.9, ease: 'expo.inOut' }, mv);
        }
        const sameSide = prev && prev.side === c.side;
        // a new sentence slides in from its side; a continuation on the same side rises in
        tl.fromTo(c.el,
          sameSide ? { opacity: 0, x: 0, y: 26, yPercent: -50 } : { opacity: 0, x: dir * 40, y: 0, yPercent: -50 },
          { opacity: 1, x: 0, y: 0, yPercent: -50, duration: 0.5 }, sameSide ? at - 0.1 : at - 0.22);
        c.spans.forEach((sp, k) => {
          const w = c.words[k];
          tl.fromTo(sp, { opacity: 0.16, y: 14 }, { opacity: 1, y: 0, duration: 0.3, ease: 'power2.out' }, r0 + w.start - 0.04);
          tl.set(sp, { className: 'cw hl' }, r0 + w.start - 0.04);
          tl.set(sp, { className: 'cw' }, r0 + w.end + 0.08);
        });
        const next = caps[i + 1];
        const nextSame = next && next.side === c.side;
        const outAt = next
          ? Math.max(at + 0.4, r0 + next.start - (nextSame ? 0.3 : 0.25))
          : Math.min(T.showEnd - 0.5, r0 + c.end + 0.5);
        tl.to(c.el, { opacity: 0, y: -26, duration: nextSame ? 0.18 : 0.3, ease: 'power2.in' }, outAt);
      });
      tl.to('#rig', { x: 0, rotationY: 0, duration: 0.8, ease: 'expo.inOut' }, T.showEnd - 1.0);
    }

    // callouts (mock / silent-recording mode)
    const callouts = captionMode ? [] : buildCallouts();
    callouts.forEach((k, i) => {
      const at = s0 + k.c.at;
      const dir = k.c.side === 'left' ? 1 : -1;
      tl.fromTo(k.ln, { scaleX: 0 }, { scaleX: 1, duration: 0.6, ease: 'power3.out' }, at);
      tl.fromTo(k.pt, { scale: 0 }, { scale: 1, duration: 0.5, ease: 'back.out(3)' }, at + 0.35);
      gsap.set(k.ring, { opacity: 0 });
      tl.fromTo(k.ring, { scale: 0.4, opacity: 0.9 }, { scale: 1.7, opacity: 0, duration: 1.0, ease: 'power2.out', immediateRender: false }, at + 0.4);
      tl.fromTo(k.parts, { x: 34 * dir, opacity: 0 }, { x: 0, opacity: 1, duration: 0.8, stagger: 0.07 }, at + 0.05);
      cue(at + 0.05, 'pop', { pan: k.c.side === 'left' ? -0.55 : 0.55 });
      const next = callouts[i + 1];
      if (next) tl.to([k.co, k.ld], { opacity: 0.32, duration: 0.5, ease: 'power2.out' }, s0 + next.c.at);
    });
    tl.to(callouts.map((k) => k.co), { x: (i) => (callouts[i].c.side === 'left' ? -40 : 40), opacity: 0, duration: 0.45, ease: ease.in }, T.showEnd - 0.75);
    tl.to(callouts.map((k) => k.ld), { opacity: 0, duration: 0.35, ease: 'none' }, T.showEnd - 0.75);

    // mock screen choreography
    if (!REC) {
      const m = C.mockScreen;
      T.typeStart = s0 + 2.75; T.typeStep = 0.15;
      T.caretOn = s0 + 2.2; T.caretOff = s0 + 4.3;
      T.busy = s0 + 4.75; T.done = s0 + 6.4;
      tl.fromTo(mockEls.mSwap, { rotation: 0 }, { rotation: 180, duration: 0.8, ease: 'back.inOut(1.6)' }, s0 + 1.55);
      tl.fromTo([mockEls.mChipFrom, mockEls.mChipTo], { scale: 1 }, { scale: 1.08, duration: 0.25, ease: 'power2.out', yoyo: true, repeat: 1, stagger: 0.12, immediateRender: false }, s0 + 1.6);
      for (let i = 0; i < m.amount.length; i++) cue(T.typeStart + i * T.typeStep, 'type', { pan: 0.1 });
      const tapX = 16 + 186, tapY = 755 + 39;
      gsap.set('#tap', { left: tapX - 42, top: tapY - 42 });
      tl.fromTo('#tap', { scale: 0.3, opacity: 0.95 }, { scale: 1.6, opacity: 0, duration: 0.7, ease: 'power2.out', immediateRender: false }, s0 + 4.6);
      tl.fromTo(mockEls.mBtn, { scale: 1 }, { scale: 0.95, duration: 0.12, ease: 'power2.out', yoyo: true, repeat: 1, immediateRender: false }, s0 + 4.58);
      cue(s0 + 4.6, 'tap');
      tl.to(state, { progress: 1, duration: T.done - T.busy - 0.1, ease: 'power1.inOut' }, T.busy);
      tl.fromTo(mockEls.mDone, { opacity: 0 }, { opacity: 1, duration: 0.45, ease: 'power2.out' }, T.done);
      tl.to(mockEls.doneRing, { strokeDashoffset: 0, duration: 0.7, ease: 'power2.inOut' }, T.done + 0.05);
      tl.to(mockEls.doneTick, { strokeDashoffset: 0, duration: 0.45, ease: 'power3.out' }, T.done + 0.45);
      tl.fromTo([mockEls.mDoneTitle, mockEls.mDoneBody], { y: 24, opacity: 0 }, { y: 0, opacity: 1, duration: 0.7, stagger: 0.08 }, T.done + 0.35);
      cue(T.done + 0.45, 'chime');
    }

    /* ---------- 4. FEATURES ---------- */
    const f0 = T.showEnd;
    T.feat = f0;
    tl.to('#deviceWrap', { y: -1150, rotationX: -28, scale: 0.9, duration: 0.85, ease: 'power3.in' }, f0 - 0.45);
    tl.to('#deviceGlow', { opacity: 0, duration: 0.6, ease: 'none' }, f0 - 0.4);
    cue(f0 - 0.2, 'whoosh', { pan: 0 });

    // the features scene is generic copy; when the narration tells the story we skip it
    const showFeatures = C.features.show === true || (C.features.show !== false && !captionMode);
    let fOut = f0 - 0.45;
    if (!showFeatures) gsap.set('#s-feat', { display: 'none' });
    if (showFeatures) {
    $('#featEyebrow').textContent = C.features.eyebrow;
    tl.fromTo('#featEyebrow', { y: 22, opacity: 0 }, { y: 0, opacity: 1, duration: 0.8 }, f0 + 0.32);
    tl.fromTo('#featRule', { scaleX: 0 }, { scaleX: 1, duration: 0.9, ease: 'expo.inOut' }, f0 + 0.36);
    const cards = buildCards();
    cards.forEach((k, i) => {
      const at = f0 + 0.35 + i * 0.13;
      tl.fromTo(k.card, { y: 170, rotationX: 38, opacity: 0, transformOrigin: '50% 100%' }, { y: 0, rotationX: 0, opacity: 1, duration: 1.15 }, at);
      tl.fromTo(k.icon, { scale: 0.4, rotation: -20 }, { scale: 1, rotation: 0, duration: 0.9, ease: 'back.out(2)' }, at + 0.2);
      tl.to(k.paths, { strokeDashoffset: 0, duration: 0.8, ease: 'power2.inOut', stagger: 0.1 }, at + 0.35);
      tl.fromTo([k.h3, k.p], { y: 24, opacity: 0 }, { y: 0, opacity: 1, duration: 0.8, stagger: 0.07 }, at + 0.3);
      tl.fromTo(k.bar, { scaleX: 0 }, { scaleX: 1, duration: 1.0, ease: 'expo.inOut' }, at + 0.45);
      tl.to(k.card, { y: -10, duration: 2.0, ease: 'sine.inOut' }, at + 1.15);
      cue(at + 0.05, 'pop', { pan: (i - 1) * 0.6 });
    });
    fOut = f0 + 3.35;
    tl.to(cards.map((k) => k.card), { y: -70, scale: 0.94, opacity: 0, duration: 0.5, ease: ease.in, stagger: 0.07 }, fOut);
    tl.to(['#featEyebrow', '#featRule'], { y: -20, opacity: 0, duration: 0.4, ease: ease.in }, fOut);
    cue(fOut + 0.1, 'whoosh', { pan: 0.4 });
    }

    /* ---------- 5. OUTRO ---------- */
    const o0 = fOut + 0.45;
    T.outro = o0;
    tl.to('#wordmark', { x: -12, opacity: 0, duration: 0.3, ease: ease.in }, o0 - 0.15);
    tl.to('#mark', { x: 0, y: 0, scale: 1, duration: 1.1, ease: ease.io }, o0);
    tl.to(state, { particles: 1, pulse: 1, duration: 0.6, ease: 'none' }, o0 + 0.7);

    const outroWords = C.outro.title.split(' ');
    const ow = splitWords($('#outroTitle'), C.outro.title);
    spanGradient([ow[outroWords.length - 1]]);
    tl.fromTo(ow, { yPercent: 115 }, { yPercent: 0, duration: 1.05, stagger: 0.08, ease: 'power4.out' }, o0 + 0.75);
    cue(o0 + 0.8, 'impact_soft');
    $('#ctaLabel').textContent = C.outro.cta;
    tl.fromTo('#cta', { scale: 0.6, opacity: 0, xPercent: -50 }, { scale: 1, opacity: 1, xPercent: -50, duration: 0.9, ease: 'back.out(1.8)' }, o0 + 1.15);
    cue(o0 + 1.2, 'pop', { pan: 0 });
    const ctaW = $('#cta').offsetWidth;
    tl.fromTo('#ctaShine', { x: -140 }, { x: ctaW + 60, duration: 0.95, ease: 'power2.inOut' }, o0 + 1.95);
    cue(o0 + 1.95, 'shine');
    $('#footnote').textContent = C.outro.footnote;
    tl.fromTo('#footnote', { y: 16, opacity: 0 }, { y: 0, opacity: 1, duration: 0.9 }, o0 + 1.45);
    tl.fromTo('#world', { scale: 1 }, { scale: 1.03, duration: 3.6, ease: 'sine.inOut', immediateRender: false }, o0 + 0.6);

    DURATION = +(o0 + 4.25).toFixed(3);
    tl.fromTo('#fade', { opacity: 0 }, { opacity: 1, duration: 0.7, ease: 'power1.in' }, DURATION - 0.7);
    cue(DURATION, 'end');
    tl.set({}, {}, DURATION);

    T.duration = DURATION;
  }

  /* ================================================================
   *  PROCEDURAL LAYER (runs every frame after the timeline seek)
   * ================================================================ */

  const bg = {};
  function procedural(t) {
    if (!bg.b1) { bg.b1 = $('.b1'); bg.b2 = $('.b2'); bg.b3 = $('.b3'); bg.grid = $('.grid'); bg.grain = $('#grain'); }
    bg.b1.style.transform = `translate(${Math.sin(t * 0.31) * 90}px, ${Math.cos(t * 0.27) * 70}px)`;
    bg.b2.style.transform = `translate(${Math.cos(t * 0.23) * 110}px, ${Math.sin(t * 0.29) * 80}px)`;
    bg.b3.style.transform = `translate(${Math.sin(t * 0.19 + 1) * 120}px, ${Math.cos(t * 0.33) * 60}px)`;
    bg.grid.style.backgroundPosition = `${-t * 8}px ${-t * 14}px`;
    const f = Math.round(t * FPS);
    bg.grain.style.transform = `translate(${Math.floor(hash(f) * 64) - 32}px, ${Math.floor(hash(f + 7919) * 64) - 32}px)`;

    // particles riding the bridge
    const P = state.particles;
    bridge.particles.forEach((p) => {
      const u = (t * p.speed + p.phase) % 1;
      const x = BR.L + (BR.R - BR.L) * u;
      const y = p.onArc ? arcY(x) : BR.deck;
      p.c.setAttribute('cx', x.toFixed(2));
      p.c.setAttribute('cy', y.toFixed(2));
      p.c.setAttribute('opacity', (P * Math.pow(Math.sin(Math.PI * u), 0.7)).toFixed(3));
    });
    bridge.nodes.forEach((n, i) => {
      const k = (((t / 1.7) + i * 0.5) % 1 + 1) % 1;
      n.pulse.setAttribute('r', (32 + k * 40).toFixed(2));
      n.pulse.setAttribute('opacity', ((1 - k) * 0.6 * state.pulse).toFixed(3));
    });

    if (REC && REC.envelope && REC.envelope.length) {
      if (!bg.voice) { bg.voice = $('#voiceGlow'); bg.eqs = $$('.cap-eq i'); }
      const fi = Math.floor((t - T.rec) * REC.fps);
      const env = fi >= 0 && fi < REC.envelope.length ? REC.envelope[fi] : 0;
      bg.voice.style.opacity = (env * 0.75).toFixed(3);
      bg.voice.style.transform = `scale(${(1 + env * 0.06).toFixed(4)})`;
      bg.eqs.forEach((b, i) => {
        const wob = 0.55 + 0.45 * Math.sin(t * 13 + i * 1.9) * Math.sin(t * 7.3 + i);
        b.style.height = `${(8 + env * 32 * wob).toFixed(1)}px`;
      });
    }

    if (!REC && mockEls.mAmtVal) {
      const m = C.mockScreen;
      const n = clamp(Math.floor((t - T.typeStart) / T.typeStep) + 1, 0, m.amount.length);
      const typed = m.amount.slice(0, n);
      mockEls.mAmtVal.textContent = n ? typed : '0.00';
      mockEls.mAmt.classList.toggle('dim', !n);
      const rc = Math.max(0, (parseFloat(typed) || 0) - m.fee);
      mockEls.mRcvVal.textContent = n ? rc.toFixed(2) : '0.00';
      mockEls.mRcv.classList.toggle('dim', !n);
      const typing = t >= T.typeStart && t < T.typeStart + m.amount.length * T.typeStep + 0.2;
      const blink = Math.floor((t - T.caretOn) * 2.4) % 2 === 0;
      mockEls.mCaret.style.opacity = t >= T.caretOn && t < T.caretOff && (typing || blink) ? 1 : 0;
      mockEls.mBtnLbl.textContent = t >= T.busy && t < T.done ? m.busy : m.button;
      mockEls.mFill.style.transform = `scaleX(${state.progress.toFixed(4)})`;
    }
  }

  /* ---------------- recording frames ---------------- */

  let lastSrc = '';
  async function recFrame(t) {
    const img = $('#recFrame');
    const local = clamp(t - T.rec, 0, REC.slotSeconds);
    const idx = clamp(Math.floor(local * REC.fps), 0, REC.frames - 1) + 1;
    const src = `${REC.dir}/${String(idx).padStart(5, '0')}.jpg`;
    if (src !== lastSrc) {
      lastSrc = src;
      img.src = src;
      try { await img.decode(); } catch (e) { /* keep last frame */ }
    }
  }

  /* ---------------- renderer API ---------------- */

  window.__init = async (content, rec) => {
    C = content;
    REC = rec || null;
    FPS = C.video.fps;
    await document.fonts.ready;
    build();
    procedural(0);
    tl.seek(0, true);
    return { duration: DURATION, fps: FPS, cues, times: T };
  };

  window.__seek = async (t) => {
    tl.seek(t, true);
    procedural(t);
    if (REC && t >= T.show - 0.5 && t <= T.showEnd + 0.5) await recFrame(t);
  };
})();
