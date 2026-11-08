# Bridge: motion graphics launch video

A code-driven motion graphics piece announcing the new **Bridge**, built as an
HTML/SVG + GSAP composition and rendered frame by frame to MP4 with a
synthesized soundtrack.

**Watch it:** [`renders/bridge-motion.mp4`](renders/bridge-motion.mp4)
(1920×1080 · 60 fps · 24 s · stereo AAC · 8.7 MB)

Everything here is self-contained in `projects/bridge-launch/`; run the commands below from this folder.

> The current render uses an **animated stand-in phone screen**. Drop your
> screen recording in (see below) and the same composition is re-cut around
> **your recording's own narration**.

## Storyboard

| Time | Scene | What happens |
|---|---|---|
| 0–3 s | **Hook** | "Getting across / just got easier." Masked kinetic type, riser builds |
| 3–7 s | **Title** | Bridge mark draws itself (nodes pop, deck + arc + hangers stroke in, particles cross), "Bridge" lands on an impact hit |
| 7–16 s | **Showcase** | The mark shrinks into a corner logo while the phone flies in on a 3D arc. Callouts 01/02/03 walk through the flow; the mock UI types an amount, taps, shows progress and a success state |
| 16–20 s | **Features** | Instant / Simple / Secure cards with self-drawing icons |
| 20–24 s | **Outro** | Mark returns to hero size, "Bridge is live.", CTA pill with a shine sweep, fade out |

All copy lives in [`content.json`](content.json), so you can change text without touching the animation.

## Using your screen recording: the audio drives the edit

```bash
cd projects/bridge-launch
cp ~/Downloads/nsl\ ajah.mp4 assets/screen-recording.mp4
npm install                 # gsap
npm run setup-asr           # one-time: sherpa-onnx + Whisper base.en + Silero VAD (~200 MB, git-ignored)
npm run build               # prepare_recording.py → render.mjs → renders/bridge-motion.mp4
```

`scripts/prepare_recording.py` uses the recording's narration to make the edit:

1. **Finds the speech** (Silero VAD) and **transcribes it offline** (Whisper, via sherpa-onnx).
2. **Cuts dead air:** trims silence at the start and end and squeezes every long pause
   down to about 0.3 s. Video and audio are cut together, so the screen stays in sync with the voice.
3. **Times the motion graphics to the words.** Each sentence becomes a kinetic caption whose
   words light up as they're spoken. Sentences alternate sides, the phone glides away from
   whichever side is speaking, and a halo and EQ bars react to the voice's loudness.
4. **Mixes the narration on top.** The music bed ducks under the voice automatically.

The narrated cut runs: hook, then title, then the phone playing your recording with its
narration, then the outro. The generic features scene is skipped, since your voice tells the
story (set `"features": {"show": true}` to force it back).

`recording` options in `content.json`:

| key | default | meaning |
|---|---|---|
| `file` | `assets/screen-recording.mp4` | the recording (portrait gets a phone frame, landscape a browser window) |
| `start` / `duration` | `0` / whole file | use only part of the recording |
| `keepAudio` | `true` | use the narration; `false` = silent footage + the `showcase.callouts` instead |
| `tightenPauses` | `true` | remove dead air between phrases |
| `captions` | `true` | kinetic captions from the transcript |
| `speed` | `1` | only used when `keepAudio` is false (speed up silent footage) |

No ASR models? It still works: speech is detected by loudness and the pauses are still
cut, but there are no captions (the `showcase.callouts` are used instead).

## How it works

```
content.json ──► motion/index.html + main.js   one paused GSAP timeline + a procedural layer
                      │                         (particles, typing, voice-reactive bits)
                      ▼
scripts/render.mjs    Playwright opens the page, calls window.__seek(t) for every frame,
                      captures it (4 parallel workers) → ffmpeg x264 (+ film grain) → segments → concat
                      │
scripts/soundtrack.py numpy-synthesized 100 BPM bed (pad / bass / arp / drums, sidechained),
                      whooshes, riser, impact, UI pops, chime, placed on the timeline's cue points;
                      narration mixed on top with ducking → loudnorm (−16 LUFS) → AAC
```

Because rendering is seek-based, every frame is exact and repeatable, no matter how long a frame takes to capture.

### Commands

```bash
npm run render                         # full render (uses build/recording.json if present)
node scripts/render.mjs --mock         # ignore any prepared recording
node scripts/render.mjs --fps 30       # faster draft
node scripts/render.mjs --stills 4 9.5 21   # PNG stills → build/stills/
```

Requirements: Node 18+, Python 3 with numpy, ffmpeg, and Playwright with Chromium
(`npm i -D playwright && npx playwright install chromium` if you don't have it).
Fonts: Inter / Inter Display and JetBrains Mono (falls back to system sans/mono).
