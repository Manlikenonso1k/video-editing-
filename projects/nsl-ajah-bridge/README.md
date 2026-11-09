# NSL Ajah: Third Mainland Bridge (motion edit)

A 19-second, beat-synced motion graphics edit of the gameplay clip announcing the new
**Third Mainland Bridge** in NSL Ajah. The footage and the song come from the
original recording; the graphics are timed to the song's beat.

**Watch:** [`renders/nsl-ajah-third-mainland-bridge.mp4`](renders/nsl-ajah-third-mainland-bridge.mp4)
(1920×1080 · 30 fps · 19 s · −14 LUFS, ready for WhatsApp / Instagram / TikTok / YouTube)

Source clip: [`assets/nsl-ajah-raw.mp4`](assets/nsl-ajah-raw.mp4) (1920×864, 19 s, CapCut export with music).

## The edit

The song runs at **100 BPM**, so a bar is 2.4 s. Every graphic lands on a beat:

| Time | Bar | On screen |
|---|---|---|
| 0.0–2.4 s | 0 | Push-in toward the in-game sign, "NEW IN NSL AJAH". The title sign lights up THIRD → MAINLAND on beats 3 and 4 |
| 2.4 s | 1 | **BRIDGE** slams on the downbeat (flash + shake), then "Lagos Island • Oworonshoki • Mainland" types on |
| 4.8 s | 2 | Route tracker drops in; the car moves from Lagos Island to the Mainland over the rest of the drive. Callout: **OVER THE LAGOON** |
| 7.2 s | 3 | **ISLAND · TO · MAIN · LAND**, one word per beat |
| 9.6 s | 4 | Callout: **LAGOS SKYLINE** |
| 12.0 s | 5 | Banner: **LAGOS' LONGEST BRIDGE**, now drivable in NSL Ajah |
| 14.4 s | 6 | Callout on the speedometer: **FLAT OUT** (≈145 km/h) |
| 16.8 s | 7 | The green gantry sign drops on the downbeat, "NOW IN NSL AJAH", "Hop in and drive it.", fade |

There's also a small zoom punch on every beat (bigger on downbeats). The CapCut
watermark is kept out of frame by the crop and zoom. The sound is the original song
with light whooshes and hits on the transitions, mastered to −14 LUFS / −1 dBTP.

## Change it

All text, the bar each graphic lands on, and the callout positions are in
[`content.json`](content.json). Then rebuild:

```bash
cd projects/nsl-ajah-bridge
npm install          # gsap
npm run build        # prep (frames + song + beat grid) → render → renders/*.mp4
npm run stills -- 2.5 7.3 17.2   # quick PNG previews in build/stills/
```

- **Different clip:** replace `assets/nsl-ajah-raw.mp4` (or point `source.file` at it) and re-run `npm run build`.
  The beat grid is detected from the clip's own music.
- **Graphics land a beat early or late:** set `"music": {"downbeatPhase": 0..3}`. `"auto"` picks the bar
  position where the song's strongest accents fall.
- **Callouts:** `label` is the label's top-left corner and `target` is where the line points (1920×1080 pixels).

## How it works

```
scripts/prep.py      ffmpeg → graded 30 fps frames + song.wav;  numpy onset/tempo/downbeat
                     detection → build/beats.json
motion/              HTML/CSS + GSAP timeline, placed with at(bar, beat) on that grid
scripts/render.mjs   Playwright seeks every frame (4 parallel workers) → x264 → concat;
                     mixes song + SFX (scripts/audio.py) → two-pass loudnorm → AAC
```

Requirements: Node 18+, Python 3 with numpy, ffmpeg, Playwright with Chromium
(`npm i -D playwright && npx playwright install chromium`). Fonts: Inter / Inter Display.
