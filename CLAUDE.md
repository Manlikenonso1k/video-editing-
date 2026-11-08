# Birthday tribute video: Mr. Akapo Emmanuel

This repo turns staff "happy birthday" clips into one polished tribute video for
Mr. Akapo Emmanuel (the boss). Read `brief/project.md` first in every session:
it has the date, company, tone, names and anything to avoid.

## Folders

| Folder | What is in it | You may write? |
| --- | --- | --- |
| `raw/` | Staff clips, untouched originals | **Never** modify, rename or delete |
| `reference/` | Example videos/screenshots of the look we want | No |
| `photos/` | Photos of Mr. Akapo | No |
| `music/` | Royalty-free tracks | No |
| `brand/` | Logo, `.ttf` fonts, colours | No |
| `brief/` | `project.md` (the brief), `staff.csv` (names) | Only when asked |
| `plan/` | `story.md` (plain-English plan), `edl.json` (the edit) | Yes |
| `work/` | Generated: inventory, contact sheets, transcripts, conformed clips | Yes |
| `remotion/` | Remotion project for the polished graphics | Yes |
| `output/` | Renders | Yes |
| `vendor/video-use/` | browser-use's video-use skill, kept for its craft rules | No |

## Hard rules

1. **Names come only from `brief/staff.csv`**, spelled exactly. A clip without a row:
   ask the user. Never take a name from the transcript or the file name alone.
2. **Plan, then get approval, then render.** Write `plan/story.md` (order, what each
   clip contributes, runtime) and wait for the user's OK before the first render.
3. **Save tokens.** Read `work/inventory.md`, `work/transcripts.md` and the contact
   sheets in `work/sheets/`. Never read video files, never dump frames in bulk.
   For a specific moment use `python scripts/vkit.py frames <video> --at 12.5,40`.
4. **Never re-transcribe** a clip that is cached (vkit does this automatically).
5. **Cut on word boundaries.** Start 0.05-0.15 s before the first kept word, end
   0.2-0.35 s after the last. Keep laughs and reactions after a punchline.
6. **Each wish 8-20 s.** Whole video 3-5 min unless the brief says otherwise.
7. **Captions are applied last**, after every other overlay, so nothing hides them.
8. **Sound:** final master -14 LUFS integrated, true peak at or below -1 dBTP,
   music ducked under speech. You cannot listen: measure with `vkit check` and
   report the numbers.
9. **Check before showing.** After every render run `vkit check`, look at the
   contact sheets (including `cuts.jpg`), fix problems, and only then report.
   At most 3 fix-and-re-render passes; then list what is left for the user.
10. **Kind and private.** Nothing embarrassing about Mr. Akapo or any staff member;
    drop clips that could hurt. Never upload, post or share anything.

## Story shape (default; the brief can override)

Cold open (best single line) -> title card -> fun wishes -> photo tribute ->
heartfelt wishes (most senior / most emotional last) -> grid finale (everyone's
"Happy birthday, sir!" shout) -> end card with all names -> bloopers.

## Commands (`python scripts/vkit.py <cmd>`; use `.venv/bin/python` if it exists)

| Command | Does |
| --- | --- |
| `doctor` | Checks ffmpeg filters, node, fonts, transcription, skills |
| `inventory` | Probes `raw/`, contact sheets, loudness, suggested in/out, `work/inventory.md` |
| `inventory --src reference` | Same for `reference/` (separate files) |
| `conform [--aspect 9:16] [--grade warm]` | Every clip to 1920x1080 (or 1080x1920) 30 fps, blurred fill for other shapes, HDR tone-mapped, loudness -16 LUFS |
| `transcribe [--language auto]` | Word timestamps -> `work/transcripts/*.json` + `work/transcripts.md`. ElevenLabs if `ELEVENLABS_API_KEY` is set, else local Whisper |
| `roughcut plan/edl.json [--aspect 9:16]` | Renders the whole video from the EDL: lower-thirds, captions, cards, photos, grid, music with ducking, -14 LUFS master. Writes a `.timeline.md` |
| `check output/x.mp4` | Loudness, true peak, black frames, long silences, contact sheets |
| `frames output/x.mp4 --at 3,10.5` | Frames at given times in one image |
| `export output/x.mp4` | 720p small copy for WhatsApp + poster still |

## EDL (`plan/edl.json`)

Top level: `aspect` ("16:9" | "9:16"), `accent` (hex), `bg_color`, `grade`
("warm" | "punch" | "none"), `captions` (bool), `transition` ("cut" | "dip"),
`loudness` (-14), `font` (path in brand/, optional), `caption_fixes`
({"wrong": "right"} for names Whisper mishears), `music`
([{"file", "start", "end", "volume" 0-1, "fade_in", "fade_out"}]), `segments`.

Segment types:
- `{"type":"clip","slug","in","out","name"?,"role"?,"captions"?,"lower_third"?,"volume_db"?}`
  (`in`/`out` default to the inventory's suggested trim; name/role default to staff.csv)
- `{"type":"card","lines":[...],"big":1,"seconds","bg": "#hex" | "photos/x.jpg"}`
  (line `big` is large; lines above it are an accent kicker)
- `{"type":"photo","file":"photos/x.jpg","seconds","caption"?}` (slow zoom)
- `{"type":"grid","items":[{"slug","in"?}],"seconds":3.5,"text"?}` (everyone at once)

See `plan/edl.example.json`.

## Phases

1. Ingest: `doctor`, `inventory`, `transcribe`; read the outputs; look at every contact sheet.
2. Plan: `plan/story.md` + `plan/edl.json`. Ask for approval.
3. Rough cut: `roughcut`, `check`, fix, show the user. Iterate on their notes.
4. Polish (when the cut is approved): build `remotion/` with the `/remotion-*` skills.
   It reads `plan/edl.json`, `work/conformed/<aspect>/*.mp4` and `work/transcripts/*.json`
   (copy what it needs into `remotion/public/`). Animated title, lower-thirds,
   captions, photo tribute, grid, credits. Load fonts from `brand/` and assert they
   loaded before rendering. Never linear easing.
5. Deliver: `output/final_16x9.mp4`, `output/final_9x16.mp4`, a <=30 s
   `output/teaser_9x16.mp4`, `export` for the small copy and poster, then `check` each.

Keep `plan/project-log.md` updated: one short section per session with decisions
and what is outstanding. Read it at the start of a session.

Craft reference: `vendor/video-use/SKILL.md` (cut craft, subtitles, music, self-eval).
Its workflow and helpers are optional here; vkit is the main pipeline.
