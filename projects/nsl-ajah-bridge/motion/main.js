/* global gsap */
/*
 * NSL Ajah: Third Mainland Bridge, a beat-synced motion edit of the gameplay clip.
 *
 * Every animation is placed with at(bar, beat) on the song's own beat grid
 * (build/beats.json from scripts/prep.py), so slams, punch-ins, flashes and
 * callouts land on the music. The renderer calls window.__init() once and
 * window.__seek(t) for every frame.
 */
(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const SVGNS = 'http://www.w3.org/2000/svg';

  let C, B, tl, DURATION;
  const cues = [];
  const cue = (t, type, extra) => cues.push(Object.assign({ t: +t.toFixed(3), type }, extra || {}));

  // bar/beat → seconds on the song's grid
  const at = (bar, beat = 0) => B.downbeats[0] + (bar * 4 + beat) * B.beat;

  // camera state (tweened by GSAP) + procedural punch/shake on top
  const cam = { s: 1.05, ox: 960, oy: 540, x: 0, y: 0, punch: 1 };
  const shakes = [];
  const shake = (t, amp) => shakes.push({ t, amp });
  const trk = { p: 0 };

  function el(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }

  /* ------------------------------------------------------------ build */

  function build() {
    tl = gsap.timeline({ paused: true, defaults: { ease: 'expo.out' } });
    const route = C.title.route.join('  •  ');

    /* ---------- bar 0: push toward the in-game sign ---------- */
    tl.set(cam, { s: 1.16, ox: 1010, oy: 300 }, 0);
    tl.to(cam, { s: 1.32, duration: at(1) - 0.05, ease: 'power2.in' }, 0);
    tl.fromTo('#shade', { opacity: 0 }, { opacity: 0.55, duration: 0.6, ease: 'power1.out' }, at(0, 1.5));

    $('#kicker').textContent = C.intro.kicker;
    tl.fromTo('#kicker', { y: 300, opacity: 0, scale: 0.7 }, { y: 340, opacity: 1, scale: 1, duration: 0.5, ease: 'back.out(2.2)' }, at(0, 0) + 0.05);
    tl.to('#kicker', { y: 0, duration: 0.35, ease: 'power3.out' }, at(0, 2) - 0.1);
    cue(at(0, 0) + 0.05, 'pop');

    // the sign fills in one word per beat: THIRD (beat 3) · MAINLAND (beat 4) · BRIDGE (next downbeat)
    const words = $('#signWords');
    const sw = C.title.words.map((w) => { const s = el('span', 'sw'); s.textContent = w; words.appendChild(s); return s; });
    const wordTimes = [at(0, 2), at(0, 3), at(1, 0)];
    tl.fromTo('#titleSign', { scale: 0.55, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.45, ease: 'back.out(1.7)' }, wordTimes[0] - 0.08);
    gsap.set(sw, { opacity: 0.16 });
    sw.forEach((s, i) => {
      const t = wordTimes[i] ?? wordTimes[wordTimes.length - 1];
      tl.fromTo(s, { scale: 1.35, opacity: 0.16 }, { scale: 1, opacity: 1, duration: 0.3, ease: 'power4.out', immediateRender: false }, t - 0.04);
      cue(t, i === sw.length - 1 ? 'impact' : 'hit');
    });
    cue(at(0, 1.6), 'riser', { end: at(1) });

    /* ---------- bar 1: BRIDGE lands — flash, shake, cut to the clean wide ---------- */
    tl.set(cam, { s: 1.13, ox: 1060, oy: 540 }, at(1));
    tl.fromTo('#flash', { opacity: 0.7 }, { opacity: 0, duration: 0.45, ease: 'power2.out', immediateRender: false }, at(1));
    tl.fromTo('#titleSign', { scale: 1.08 }, { scale: 1, duration: 0.45, ease: 'power3.out', immediateRender: false }, at(1));
    shake(at(1), 20);
    tl.to(cam, { s: 1.18, duration: at(2) - at(1), ease: 'sine.inOut' }, at(1));

    const sr = $('#signRoute');
    const rcs = [...route].map((ch) => { const s = el('span', 'rc'); s.textContent = ch === ' ' ? ' ' : ch; sr.appendChild(s); return s; });
    tl.fromTo(rcs, { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.3, stagger: 0.012, ease: 'power2.out' }, at(1, 1));
    cue(at(1, 1), 'tick');

    // title out on the "and" before bar 2
    const tOut = at(2) - B.beat / 2;
    tl.to(['#titleSign', '#kicker'], { y: -90, opacity: 0, scale: 0.92, duration: 0.28, ease: 'power3.in' }, tOut);
    tl.to('#shade', { opacity: 0, duration: 0.3, ease: 'power1.in' }, tOut);
    cue(tOut - 0.05, 'whoosh');

    /* ---------- bars 2–6: the drive, with a route tracker ---------- */
    tl.fromTo('#flash', { opacity: 0.28 }, { opacity: 0, duration: 0.3, ease: 'power2.out', immediateRender: false }, at(2));
    tl.to(cam, { s: 1.05, ox: 960, duration: 0.5, ease: 'power3.out' }, at(2));
    buildTracker(C.title.route);
    tl.fromTo('#tracker', { y: -150, opacity: 0 }, { y: 0, opacity: 1, duration: 0.6, ease: 'back.out(1.4)' }, at(2));
    tl.fromTo(trk, { p: 0 }, { p: 1, duration: at(7) - at(2), ease: 'none' }, at(2));
    tl.to('#tracker', { y: -150, opacity: 0, duration: 0.3, ease: 'power3.in' }, at(7) - 0.35);

    // callouts that point at what's on screen
    C.callouts.forEach((c) => buildCallout(c));

    // bar 3: one word per beat
    const bw = $('#beatword');
    const bws = C.beatWords.words.map((w, i) => { const s = el('div', 'bw' + (i % 2 ? ' g' : '')); s.textContent = w; bw.appendChild(s); return s; });
    const b0 = C.beatWords.bar;
    tl.to('#shade', { opacity: 0.3, duration: 0.15 }, at(b0) - 0.1);
    bws.forEach((s, i) => {
      const t = at(b0, i);
      tl.fromTo(s, { scale: 1.5, opacity: 0, yPercent: -50 }, { scale: 1, opacity: 1, yPercent: -50, duration: 0.2, ease: 'power4.out' }, t - 0.03);
      tl.to(s, { opacity: 0, scale: 0.92, duration: 0.08, ease: 'none' }, (i < bws.length - 1 ? at(b0, i + 1) : at(b0 + 1)) - 0.09);
      shake(t, 7);
    });
    tl.to('#shade', { opacity: 0, duration: 0.2 }, at(b0 + 1) - 0.1);

    // bar 5: lower banner
    $('#bannerTitle').textContent = C.banner.title;
    $('#bannerSub').textContent = C.banner.sub;
    const bb = C.banner.bar;
    tl.fromTo('#banner', { y: 80, opacity: 0, scale: 0.9 }, { y: 0, opacity: 1, scale: 1, duration: 0.55, ease: 'back.out(1.6)' }, at(bb));
    tl.fromTo(['#bannerTitle', '#bannerSub'], { y: 20, opacity: 0 }, { y: 0, opacity: 1, duration: 0.4, stagger: 0.1 }, at(bb) + 0.12);
    tl.to('#banner', { y: 40, opacity: 0, duration: 0.25, ease: 'power3.in' }, at(bb + 1) - 0.4);
    cue(at(bb), 'whoosh_soft');

    /* ---------- bar 7: outro — the gantry sign drops on the downbeat ---------- */
    const o = at(C.outro.bar);
    $('#gantryTitle').textContent = C.title.words.join(' ');
    $('#gantryRoute').textContent = route;
    $('#outroLine').textContent = C.outro.line;
    $('#outroCta').textContent = C.outro.cta;
    tl.to('#shade', { opacity: 0.55, duration: 0.25, ease: 'power2.out' }, o - 0.2);
    tl.fromTo('#gantry', { y: -620, opacity: 1 }, { y: 0, duration: 0.42, ease: 'power3.in' }, o - 0.42);
    tl.to('#gantry', { keyframes: [{ y: -18, duration: 0.12, ease: 'power2.out' }, { y: 0, duration: 0.16, ease: 'power2.in' }] }, o);
    tl.fromTo('#flash', { opacity: 0.45 }, { opacity: 0, duration: 0.4, ease: 'power2.out', immediateRender: false }, o);
    shake(o, 16);
    cue(o - 0.45, 'whoosh');
    cue(o, 'impact');
    tl.set(cam, { s: 1.1 }, o);
    tl.to(cam, { s: 1.2, duration: DURATION_GUESS() - o, ease: 'none' }, o);
    tl.fromTo('#outroLine', { scale: 0.4, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.45, ease: 'back.out(2.4)' }, at(C.outro.bar, 1));
    cue(at(C.outro.bar, 1), 'pop');
    tl.fromTo('#outroCta', { y: 24, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5 }, at(C.outro.bar, 2));

    DURATION = DURATION_GUESS();
    tl.fromTo('#fade', { opacity: 0 }, { opacity: 1, duration: 0.55, ease: 'power1.in' }, DURATION - 0.55);
    tl.set({}, {}, DURATION);
  }

  function DURATION_GUESS() {
    return +Math.min(B.duration, B.frames / B.fps).toFixed(3);
  }

  function buildTracker(names) {
    const box = $('#tracker');
    const x0 = 110, x1 = 800 - 110;
    names.forEach((n, i) => {
      const x = x0 + (x1 - x0) * (i / (names.length - 1));
      const node = el('div', 'trk-node'); node.style.left = `${x}px`;
      const lab = el('div', 'trk-label'); lab.style.left = `${x}px`; lab.textContent = n;
      box.append(node, lab);
    });
  }

  function buildCallout(c) {
    const layer = $('#callouts');
    const t0 = at(c.bar, c.beat || 0);
    const t1 = at(c.bar + 1) - 0.22;
    const lab = el('div', 'co-label', `<i></i>${c.text}`);
    lab.style.left = `${c.label.x}px`;
    lab.style.top = `${c.label.y}px`;
    layer.appendChild(lab);
    const w = lab.offsetWidth, h = lab.offsetHeight;
    // leader runs from the label edge nearest the target
    const ax = clamp(c.target.x, c.label.x, c.label.x + w);
    const ay = clamp(c.target.y, c.label.y, c.label.y + h);
    const svg = document.createElementNS(SVGNS, 'svg');
    svg.setAttribute('width', '1920'); svg.setAttribute('height', '1080');
    const line = document.createElementNS(SVGNS, 'line');
    Object.entries({ x1: ax, y1: ay, x2: c.target.x, y2: c.target.y, stroke: '#fff', 'stroke-width': 5, 'stroke-linecap': 'round' })
      .forEach(([k, v]) => line.setAttribute(k, v));
    svg.appendChild(line);
    layer.insertBefore(svg, lab);
    const len = Math.hypot(c.target.x - ax, c.target.y - ay);
    line.style.strokeDasharray = `${len} ${len}`;
    line.style.strokeDashoffset = len;
    const dot = el('div', 'co-dot'); dot.style.left = `${c.target.x}px`; dot.style.top = `${c.target.y}px`;
    const ring = el('div', 'co-ring'); ring.style.left = `${c.target.x}px`; ring.style.top = `${c.target.y}px`;
    layer.append(ring, dot);

    tl.fromTo(lab, { scale: 0.5, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.35, ease: 'back.out(2.2)' }, t0);
    tl.to(line, { strokeDashoffset: 0, duration: 0.25, ease: 'power2.out' }, t0 + 0.08);
    tl.fromTo(dot, { scale: 0 }, { scale: 1, duration: 0.3, ease: 'back.out(3)' }, t0 + 0.22);
    gsap.set(ring, { opacity: 0 });
    for (let k = 0; t0 + 0.25 + k * 2 * B.beat < t1; k++) { // ring pulses every other beat
      tl.fromTo(ring, { scale: 0.3, opacity: 1 }, { scale: 1.8, opacity: 0, duration: 0.7, ease: 'power2.out', immediateRender: false }, t0 + 0.25 + k * 2 * B.beat);
    }
    tl.to([lab, svg, dot], { opacity: 0, scale: 0.9, duration: 0.2, ease: 'power3.in' }, t1);
    cue(t0, 'pop');
  }

  /* ------------------------------------------------------------ per-frame */

  let lastSrc = '';
  async function frame(t) {
    const img = $('#clip');
    const idx = clamp(Math.floor(t * B.fps + 1e-6), 0, B.frames - 1) + 1;
    const src = `${B.dir}/${String(idx).padStart(5, '0')}.jpg`;
    if (src !== lastSrc) {
      lastSrc = src;
      img.src = src;
      try { await img.decode(); } catch (e) { /* keep previous */ }
    }
  }

  function procedural(t) {
    // beat punch: a short zoom kick on every beat, bigger on downbeats
    let punch = 0;
    for (let i = B.beats.length - 1; i >= 0; i--) {
      const b = B.beats[i];
      if (b <= t) {
        const down = B.downbeats.some((d) => Math.abs(d - b) < 0.01);
        punch = (down ? 0.026 : 0.009) * Math.exp(-(t - b) / 0.11);
        break;
      }
    }
    let sx = 0, sy = 0;
    shakes.forEach((s) => {
      const d = t - s.t;
      if (d >= 0 && d < 0.6) {
        const k = s.amp * Math.exp(-d / 0.12);
        sx += k * Math.sin(d * 97 + s.t);
        sy += k * Math.sin(d * 71 + 1.3 + s.t);
      }
    });
    const c = $('#cam');
    c.style.transformOrigin = `${cam.ox}px ${cam.oy}px`;
    c.style.transform = `translate(${(cam.x + sx).toFixed(2)}px, ${(cam.y + sy).toFixed(2)}px) scale(${(cam.s * (1 + punch)).toFixed(5)})`;

    // route tracker: car position + nodes lighting up as you pass them
    const fill = $('#trkFill'), car = $('#trkCar');
    if (fill) {
      fill.style.transform = `scaleX(${trk.p.toFixed(4)})`;
      car.style.left = `${110 + 580 * trk.p}px`;
      const nodes = $$('.trk-node'), labs = $$('.trk-label');
      nodes.forEach((n, i) => {
        const on = trk.p >= i / (nodes.length - 1) - 0.001 && t >= at(2);
        n.classList.toggle('on', on);
        labs[i].classList.toggle('on', on);
      });
    }
  }

  window.__init = async (content, beats) => {
    C = content; B = beats;
    await document.fonts.ready;
    build();
    tl.seek(0, true);
    procedural(0);
    await frame(0);
    return { duration: DURATION, fps: B.fps, cues };
  };

  window.__seek = async (t) => {
    tl.seek(t, true);
    procedural(t);
    await frame(t);
  };
})();
