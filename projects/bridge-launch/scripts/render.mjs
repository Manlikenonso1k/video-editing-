#!/usr/bin/env node
/**
 * Frame-exact renderer for motion/index.html.
 *
 *   node scripts/render.mjs                 # full render → content.video.output
 *   node scripts/render.mjs --stills 1.2 4 9 # PNG stills → build/stills/
 *   node scripts/render.mjs --workers 3 --fps 30 --no-audio
 *
 * If build/recording.json exists (made by scripts/prepare-recording.mjs) the
 * phone screen shows your screen recording instead of the animated mock.
 */
import { createRequire } from 'node:module';
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Playwright: use the project's copy if installed, otherwise a global one (NODE_PATH).
const { chromium } = createRequire(import.meta.url)('playwright');

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const BUILD = path.join(ROOT, 'build');
const args = process.argv.slice(2);
const flag = (name) => args.includes(name);
const opt = (name, dflt) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : dflt; };

const content = JSON.parse(fs.readFileSync(path.join(ROOT, 'content.json'), 'utf8'));
if (opt('--fps')) content.video.fps = Number(opt('--fps'));
if (opt('--out')) content.video.output = opt('--out');
const { width: W, height: H } = content.video;

let rec = null;
const recJson = opt('--recording') ? path.resolve(opt('--recording')) : path.join(BUILD, 'recording.json');
if (!flag('--mock') && fs.existsSync(recJson)) {
  rec = JSON.parse(fs.readFileSync(recJson, 'utf8'));
  console.log(`• using screen recording: ${rec.frames} frames, ${rec.orientation}, ${rec.slotSeconds}s slot`);
} else {
  console.log('• no prepared recording, using the animated mock screen');
}

fs.mkdirSync(BUILD, { recursive: true });
const pageUrl = pathToFileURL(path.join(ROOT, 'motion', 'index.html')).href;

async function openPage(browser) {
  const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  page.on('pageerror', (e) => console.error('page error:', e.message));
  page.on('console', (m) => { if (m.type() === 'error') console.error('console:', m.text()); });
  await page.goto(pageUrl, { waitUntil: 'load' });
  const info = await page.evaluate(([c, r]) => window.__init(c, r), [content, rec]);
  // the grain overlay is a costly full-frame blend and bloats the encode; skip it when rendering
  await page.addStyleTag({ content: '#grain{display:none}' });
  const cdp = await page.context().newCDPSession(page);
  const grab = async () => Buffer.from((await cdp.send('Page.captureScreenshot', { format: 'png', optimizeForSpeed: true })).data, 'base64');
  return { page, info, grab };
}

function run(cmd, argv) {
  const r = spawnSync(cmd, argv, { stdio: ['ignore', 'inherit', 'inherit'] });
  if (r.status !== 0) throw new Error(`${cmd} exited with ${r.status}`);
}

const browser = await chromium.launch({ args: ['--disable-gpu', '--font-render-hinting=none', '--force-color-profile=srgb'] });

/* ---------------- stills ---------------- */
if (flag('--stills')) {
  const times = args.slice(args.indexOf('--stills') + 1).filter((a) => !a.startsWith('--')).map(Number);
  const { page, info } = await openPage(browser);
  const list = times.length ? times : [0.8, 3.0, 4.6, 6.0, 7.6, 9.2, 11.0, 13.6, 17.6, 21.5, 23.0];
  const dir = path.join(BUILD, 'stills');
  fs.mkdirSync(dir, { recursive: true });
  // walk forward so every tween initialises in order
  let cur = 0;
  for (const t of list.sort((a, b) => a - b)) {
    for (; cur < t; cur = Math.min(t, cur + 0.1)) await page.evaluate((x) => window.__seek(x), cur);
    await page.evaluate((x) => window.__seek(x), t);
    const out = path.join(dir, `still-${t.toFixed(2)}.png`);
    await page.screenshot({ path: out });
    console.log('  ', path.relative(ROOT, out));
  }
  console.log(`duration ${info.duration}s`);
  await browser.close();
  process.exit(0);
}

/* ---------------- full render ---------------- */
const probe = await openPage(browser);
const { duration, fps, cues, times } = probe.info;
await probe.page.close();
const total = Math.round(duration * fps);
fs.writeFileSync(path.join(BUILD, 'cues.json'), JSON.stringify({ duration, fps, cues, times }, null, 2));
console.log(`• ${duration}s @ ${fps}fps = ${total} frames`);

const workers = Math.max(1, Number(opt('--workers', Math.min(4, os.cpus().length))));
const per = Math.ceil(total / workers);
const t0 = Date.now();
let done = 0;

async function renderChunk(idx, from, to) {
  const { page, grab } = await openPage(browser);
  const seg = path.join(BUILD, `seg-${idx}.mp4`);
  const ff = spawn('ffmpeg', [
    '-y', '-loglevel', 'error',
    '-f', 'image2pipe', '-framerate', String(fps), '-c:v', 'png', '-i', '-',
    // aq-mode 3 biases bits toward dark flat areas, which keeps the gradients from banding
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '18', '-pix_fmt', 'yuv420p',
    '-x264-params', 'aq-mode=3:aq-strength=0.9',
    '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
    '-r', String(fps), seg,
  ], { stdio: ['pipe', 'inherit', 'inherit'] });
  const finished = new Promise((res, rej) => ff.on('close', (c) => (c === 0 ? res() : rej(new Error('ffmpeg ' + c)))));
  // warm up: walk the timeline up to the chunk start so lazily-recorded tweens initialise in order
  for (let t = 0; t < from / fps; t += 0.1) await page.evaluate((x) => window.__seek(x), t);
  for (let f = from; f < to; f++) {
    await page.evaluate((x) => window.__seek(x), f / fps);
    const buf = await grab();
    if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once('drain', r));
    done++;
    if (done % 60 === 0) {
      const el = (Date.now() - t0) / 1000;
      process.stdout.write(`\r  frames ${done}/${total}  ${(done / el).toFixed(1)} fps  eta ${Math.round((total - done) / (done / el))}s   `);
    }
  }
  ff.stdin.end();
  await finished;
  await page.close();
  return seg;
}

const jobs = [];
for (let i = 0; i < workers; i++) {
  const from = i * per, to = Math.min(total, from + per);
  if (from < to) jobs.push(renderChunk(i, from, to));
}
const segs = await Promise.all(jobs);
await browser.close();
process.stdout.write(`\r  frames ${total}/${total} in ${((Date.now() - t0) / 1000).toFixed(0)}s                     \n`);

const list = path.join(BUILD, 'segments.txt');
fs.writeFileSync(list, segs.map((s) => `file '${s}'`).join('\n'));
const silent = path.join(BUILD, 'video-silent.mp4');
run('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', silent]);

const out = path.join(ROOT, content.video.output);
fs.mkdirSync(path.dirname(out), { recursive: true });

if (flag('--no-audio')) {
  fs.copyFileSync(silent, out);
} else {
  const wav = path.join(BUILD, 'soundtrack.wav');
  const py = ['scripts/soundtrack.py', path.join(BUILD, 'cues.json'), wav];
  if (rec && rec.audio) py.push('--rec-audio', path.join(ROOT, rec.audio), '--rec-offset', String(times.rec));
  run('python3', py.map((a, i) => (i === 0 ? path.join(ROOT, a) : a)));
  run('ffmpeg', [
    '-y', '-loglevel', 'error', '-i', silent, '-i', wav,
    '-map', '0:v', '-map', '1:a', '-c:v', 'copy',
    '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11', '-ar', '48000', '-c:a', 'aac', '-b:a', '192k',
    '-shortest', '-movflags', '+faststart', out,
  ]);
}
const mb = (fs.statSync(out).size / 1e6).toFixed(1);
console.log(`✔ ${path.relative(ROOT, out)}  (${mb} MB)`);
