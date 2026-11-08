# Prompts for Claude Code

Open a terminal in this repo and run `claude`. Paste one prompt at a time.
`CLAUDE.md` loads automatically, so the prompts stay short.

---

## Master prompt (runs the whole job with two approval stops)

```
You are editing a birthday tribute video for Mr. Akapo Emmanuel, my boss.
Read CLAUDE.md, brief/project.md and brief/staff.csv first.

Phase 1, ingest: run `python scripts/vkit.py doctor` and fix anything you can.
Then `inventory`, then `transcribe` (use --language auto for clips staff.csv marks
as Yoruba, Igbo, Hausa or Pidgin). Read work/inventory.md and work/transcripts.md
and look at every contact sheet in work/sheets/. Also run `inventory --src reference`
and look at those sheets to learn the look I want.

Tell me in a short list: clips that are unusable or need a decision (no audio,
too dark, sideways, missing from staff.csv, duplicates), the 3 best lines for the
cold open, and anything that could embarrass anyone.

Phase 2, plan: write plan/story.md (the run of show with times, which clip goes
where and why, music per section, total runtime) and plan/edl.json.
STOP and wait for my approval.

Phase 3, rough cut: after I approve, run `roughcut plan/edl.json`, then `check`,
look at the contact sheets and cuts.jpg, fix problems (max 3 passes), then tell me
the runtime, the loudness numbers and anything you could not fix.
STOP and wait for my notes.

Phase 4, polish: when I say the cut is right, build the Remotion version in
remotion/ using the /remotion-* skills, following CLAUDE.md. Render
output/final_16x9.mp4 and output/final_9x16.mp4, a teaser_9x16.mp4 of 30 s or
less, then `export` and `check` each. Update plan/project-log.md.
```

---

## Phase prompts (if you prefer to go step by step)

**1. Setup check**
```
Run `python scripts/vkit.py doctor`. Explain anything marked !! and fix what you can.
```

**2. Ingest**
```
Run vkit inventory and transcribe. Read work/inventory.md and work/transcripts.md,
look at every contact sheet, and give me: unusable clips, clips missing from
staff.csv, the best 3 cold-open lines, the funniest 5 and the most touching 5.
```

**3. Plan**
```
Using CLAUDE.md's story shape and brief/project.md, write plan/story.md and
plan/edl.json. Target [4] minutes. Fun wishes first, heartfelt after the photo
tribute, [name of most senior person] last. Grid finale with every shout clip.
Music: music/[upbeat].mp3 for part 1, music/[soft].mp3 from the photo tribute on.
Don't render yet. Show me the run of show.
```

**4. Rough cut**
```
Approved. Render the rough cut, run check, look at the sheets, fix issues,
then report runtime and loudness.
```

**5. Polish in Remotion**
```
The cut is final. Build remotion/ with the /remotion-* skills: it must read
plan/edl.json and the conformed clips so the timing matches the rough cut exactly.
Upgrade the graphics: animated title with his photo, sliding lower-thirds in our
brand colours, word-by-word captions, a photo tribute with slow zoom, a grid finale
where faces pop in one by one, rolling credits with every name from staff.csv.
Render 16:9 and 9:16, then check both.
```

**6. Deliver**
```
Make the teaser (best 25 s, 9:16), run export on the 16:9 final, check everything,
and list the files in output/ with sizes.
```

---

## Feedback prompts (after you watch a render)

```
Swap the order of [Ada] and [Tunde]. Trim [Emeka] to end after "God bless you".
```
```
[Ngozi] is hard to hear over the music; raise her clip 3 dB.
```
```
Captions misspell his name as "Akpo": add a caption_fixes entry and re-render.
```
```
Cut the whole video to 3 minutes: drop the weakest wishes, keep every department.
```
```
Make a 60-second version for WhatsApp Status from the same plan.
```
