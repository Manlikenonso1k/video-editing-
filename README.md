# Birthday tribute video: Mr. Akapo Emmanuel

A Claude Code workspace that turns staff "happy birthday" clips into a polished
3-5 minute tribute, plus a vertical version and a WhatsApp teaser.

## What's inside

| Path | What it is |
| --- | --- |
| `CLAUDE.md` | Rules and pipeline Claude follows every session |
| `PROMPT.md` | Master prompt, phase prompts, feedback prompts |
| `scripts/vkit.py` | Helper CLI: inventory, conform, transcribe, roughcut, check, export |
| `.claude/skills/remotion-*` | Remotion Agent Skills ([remotion-dev/skills](https://github.com/remotion-dev/skills)) |
| `vendor/video-use/` | [browser-use/video-use](https://github.com/browser-use/video-use) (MIT): craft rules, optional full workflow |
| `brief/` | `project.md` (fill it in) and `staff.csv` (names as they appear on screen) |
| `plan/` | Claude writes `story.md` and `edl.json` here |
| `raw/` `photos/` `music/` `reference/` `brand/` | Your inputs |

## Quick start (MacBook, recommended)

```bash
git clone <your repo> akapo-birthday-video && cd akapo-birthday-video
./setup.sh                      # ffmpeg, node, Whisper, git-lfs; then runs a check
# add clips to raw/, photos to photos/, music to music/, fonts/logo to brand/
# fill in brief/project.md and brief/staff.csv
claude                          # then paste the master prompt from PROMPT.md
```

Optional: `./setup.sh --video-use` and an ElevenLabs API key in `.env` gives more
accurate transcripts for accents and mixed languages (vkit uses it automatically).

## Running it in the cloud instead

Use Git LFS (already configured in `.gitattributes`) so GitHub accepts large clips:

```bash
git lfs install
git add raw photos music reference brand brief
git commit -m "Add clips" && git push
```

Then give Claude (Claude Code on the web, or a Claude chat with the repo attached)
the repo and the master prompt. Each file can be up to 2 GB; GitHub Free includes
10 GiB of LFS storage and bandwidth.

## Commands

```bash
python scripts/vkit.py doctor
python scripts/vkit.py inventory
python scripts/vkit.py transcribe            # --language auto for mixed languages
python scripts/vkit.py roughcut plan/edl.json [--aspect 9:16]
python scripts/vkit.py check output/edl_16x9.mp4
python scripts/vkit.py export output/final_16x9.mp4
```

Use `.venv/bin/python` instead of `python` after `setup.sh`.

## Licences

- Remotion is free for individuals and teams of up to 3 people; see remotion.dev/license.
- video-use is MIT (see `vendor/video-use/LICENSE`). vkit's HDR tone-mapping chain is adapted from it.
- Music: use tracks you have the right to use (Pixabay Music and the YouTube Audio Library are free).
