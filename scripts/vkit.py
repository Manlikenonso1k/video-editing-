#!/usr/bin/env python3
"""vkit: helper toolkit for the birthday tribute video.

Every command reads from the repo folders (raw/, photos/, music/, brand/,
brief/, plan/) and writes only to work/ and output/. raw/ is never modified.

  python scripts/vkit.py doctor                   check tools, fonts, folders
  python scripts/vkit.py inventory                probe clips, contact sheets, suggested trims
  python scripts/vkit.py conform [--aspect 9:16]  same size/fps/loudness for every clip
  python scripts/vkit.py transcribe               word-level transcripts -> work/transcripts.md
  python scripts/vkit.py roughcut plan/edl.json   assemble the video from the edit plan
  python scripts/vkit.py check output/x.mp4       loudness, black frames, silences, contact sheets
  python scripts/vkit.py frames output/x.mp4 --at 12.5,40   frames at given times (for review)
  python scripts/vkit.py export output/x.mp4      small 720p copy + poster still

Requires ffmpeg/ffprobe on PATH. transcribe needs faster-whisper (pip) or an
ELEVENLABS_API_KEY in the environment or .env.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
PHOTOS = ROOT / "photos"
MUSIC = ROOT / "music"
BRAND = ROOT / "brand"
BRIEF = ROOT / "brief"
PLAN = ROOT / "plan"
WORK = ROOT / "work"
OUT = ROOT / "output"

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".3gp", ".webm", ".mkv", ".avi", ".mts"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac"}
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}
# Tone-map iPhone HLG / HDR10 clips to normal Rec.709 so they don't look washed out.
TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
           "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
GRADES = {
    "none": "",
    "warm": "eq=contrast=1.04:saturation=1.08,colorbalance=rm=0.03:gm=0.0:bm=-0.03",
    "punch": "eq=contrast=1.07:saturation=1.06:gamma=0.98",
}
FPS = 30
ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
AAC = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]


# ----------------------------------------------------------------- helpers

def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd: list, cwd: Path | None = None, capture: bool = True) -> subprocess.CompletedProcess:
    cmd = [str(c) for c in cmd]
    p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=capture, text=True)
    if p.returncode != 0:
        tail = (p.stderr or "")[-2500:]
        raise SystemExit(f"\nCommand failed ({p.returncode}): {' '.join(cmd[:6])} ...\n{tail}")
    return p


def ffmpeg(args: list, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error", *args], cwd=cwd)


def probe(path: Path) -> dict:
    p = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path])
    return json.loads(p.stdout)


def tag_of(aspect: str) -> str:
    return aspect.replace(":", "x")


def slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", Path(name).stem).strip("-").lower()
    return s or "clip"


def rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


def clip_info(path: Path) -> dict:
    d = probe(path)
    v = next((s for s in d["streams"] if s.get("codec_type") == "video"), None)
    a = next((s for s in d["streams"] if s.get("codec_type") == "audio"), None)
    if v is None:
        raise ValueError(f"{path.name}: no video stream")
    w, h = int(v["width"]), int(v["height"])
    rot = 0
    for sd in v.get("side_data_list") or []:
        if sd.get("rotation") is not None:
            rot = int(round(float(sd["rotation"])))
    if rot == 0 and (v.get("tags") or {}).get("rotate"):
        rot = int(v["tags"]["rotate"])
    if rot % 180 != 0:
        w, h = h, w
    dur = float(d["format"].get("duration") or v.get("duration") or 0)
    num, _, den = (v.get("avg_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    return {
        "width": w, "height": h, "duration": round(dur, 3), "fps": round(fps, 2),
        "orientation": "portrait" if h > w else ("square" if h == w else "landscape"),
        "hdr": v.get("color_transfer") in HDR_TRANSFERS,
        "has_audio": a is not None, "vcodec": v.get("codec_name"),
        "size_mb": round(int(d["format"].get("size", 0)) / 1e6, 1),
    }


def load_staff() -> dict:
    """brief/staff.csv rows keyed by slug of the file name (with or without extension)."""
    path = BRIEF / "staff.csv"
    rows = {}
    if not path.exists():
        return rows
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
            if r.get("file"):
                rows[slugify(r["file"])] = r
    return rows


def load_inventory() -> list:
    p = WORK / "inventory.json"
    if not p.exists():
        raise SystemExit("No work/inventory.json yet. Run: python scripts/vkit.py inventory")
    return json.loads(p.read_text())


def find_item(slug: str, inv: list) -> dict:
    for it in inv:
        if it["slug"] == slug:
            return it
    raise SystemExit(f"Clip '{slug}' is not in work/inventory.json. Slugs: {', '.join(i['slug'] for i in inv)}")


def find_fonts(preferred: str | None = None) -> dict:
    """Return {'bold': path, 'regular': path}. Brand fonts win over system fonts."""
    def pick(cands):
        for c in cands:
            if c and Path(c).exists():
                return Path(c)
        return None

    brand = sorted([p for p in BRAND.glob("*") if p.suffix.lower() in (".ttf", ".otf")]) if BRAND.exists() else []
    b_bold = [p for p in brand if re.search(r"bold|black|heavy|semibold", p.name, re.I)]
    b_reg = [p for p in brand if re.search(r"regular|book|medium", p.name, re.I)]
    fc_bold = fc_reg = None
    if shutil.which("fc-match"):
        try:
            fc_bold = subprocess.run(["fc-match", "-f", "%{file}", "sans:bold"], capture_output=True, text=True).stdout
            fc_reg = subprocess.run(["fc-match", "-f", "%{file}", "sans"], capture_output=True, text=True).stdout
        except OSError:
            pass
    sys_bold = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
                "C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", fc_bold]
    sys_reg = ["/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
               "C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", fc_reg]
    bold = pick([preferred and (ROOT / preferred), *b_bold, *brand, *sys_bold])
    reg = pick([*b_reg, *brand, *sys_reg]) or bold
    if not bold:
        raise SystemExit("No font found. Put a .ttf (e.g. Poppins-Bold.ttf, Poppins-Regular.ttf) in brand/.")
    return {"bold": bold, "regular": reg}


def stage_fonts(dest: Path, preferred: str | None = None) -> None:
    """Copy fonts under simple names so filter graphs never need path escaping."""
    f = find_fonts(preferred)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(f["bold"], dest / "bold.ttf")
    shutil.copyfile(f["regular"], dest / "regular.ttf")


def silence_and_loudness(path: Path, noise_db: int = -35) -> dict:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-i", str(path), "-vn",
                        "-af", f"silencedetect=n={noise_db}dB:d=0.5,ebur128", "-f", "null", "-"],
                       capture_output=True, text=True)
    err = p.stderr
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", err)]
    m = re.findall(r"I:\s+(-?[\d.]+|-inf) LUFS", err)
    lufs = None
    if m and m[-1] != "-inf":
        lufs = float(m[-1])
    return {"starts": starts, "ends": ends, "lufs": lufs}


def write_textfile(dirpath: Path, text: str) -> str:
    name = f"t{uuid.uuid4().hex[:10]}.txt"
    (dirpath / name).write_text(text, encoding="utf-8")
    return name


def q(expr: str) -> str:
    """Quote a filter option value (expressions with commas)."""
    return "'" + expr.replace("'", "") + "'"


def fit(size: int, text: str, max_w: float, k: float = 0.62) -> int:
    """Shrink a font size so the text (estimated at k*size per character) fits max_w pixels."""
    est = max(len(text), 1) * size * k
    return int(size if est <= max_w else max_w / (max(len(text), 1) * k))


def fade_alpha(t0: float, t1: float, f: float = 0.35) -> str:
    """drawtext alpha: 0 before t0, fade in, hold, fade out by t1."""
    return q(f"if(lt(t,{t0:.3f}),0,if(lt(t,{t0 + f:.3f}),(t-{t0:.3f})/{f},"
             f"if(lt(t,{t1 - f:.3f}),1,if(lt(t,{t1:.3f}),({t1:.3f}-t)/{f},0))))")


# ----------------------------------------------------------------- doctor

def cmd_doctor(args) -> None:
    ok = True

    def line(good, msg, fix=""):
        nonlocal ok
        ok = ok and good
        log(f"  [{'ok' if good else '!!'}] {msg}" + (f"\n        fix: {fix}" if (fix and not good) else ""))

    log("vkit doctor")
    ff = shutil.which("ffmpeg")
    line(bool(ff), f"ffmpeg: {ff or 'missing'}", "macOS: brew install ffmpeg | Windows: winget install Gyan.FFmpeg")
    if ff:
        ver = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.split("\n")[0]
        log(f"        {ver}")
        flt = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
        for name in ["drawtext", "xstack", "zscale", "loudnorm", "sidechaincompress", "gblur"]:
            line(re.search(rf"\s{name}\s", flt) is not None, f"ffmpeg filter '{name}'",
                 "macOS: brew uninstall ffmpeg && brew install ffmpeg-full (drawtext needs libfreetype, zscale needs zimg)")
    line(bool(shutil.which("ffprobe")), "ffprobe")
    node = shutil.which("node")
    nv = subprocess.run(["node", "-v"], capture_output=True, text=True).stdout.strip() if node else ""
    major = int(nv.lstrip("v").split(".")[0]) if nv else 0
    line(major >= 18, f"node {nv or 'missing'} (Remotion needs 18+, HyperFrames 22+)", "brew install node")
    line(sys.version_info >= (3, 9), f"python {sys.version.split()[0]}")
    try:
        import faster_whisper  # noqa: F401
        fw = True
    except Exception:
        fw = False
    key = bool(os.environ.get("ELEVENLABS_API_KEY") or read_dotenv().get("ELEVENLABS_API_KEY"))
    log(f"  [{'ok' if (fw or key) else '!!'}] transcription: faster-whisper {'yes' if fw else 'no'}, "
        f"ElevenLabs key {'yes' if key else 'no'}")
    if not (fw or key):
        ok = False
        log("        fix: .venv/bin/pip install faster-whisper   (or put ELEVENLABS_API_KEY=... in .env)")
    try:
        fonts = find_fonts()
        line(True, f"fonts: bold={fonts['bold'].name}, regular={fonts['regular'].name}")
    except SystemExit as e:
        line(False, str(e))
    skills = sorted(p.name for p in (ROOT / ".claude" / "skills").glob("*")) if (ROOT / ".claude" / "skills").exists() else []
    line(any(s.startswith("remotion") for s in skills), f"project skills: {', '.join(skills) or 'none'}",
         "npx -y skills add remotion-dev/skills --agent claude-code --skill '*' --copy -y")
    line((ROOT / "vendor" / "video-use" / "SKILL.md").exists(), "vendor/video-use (craft rules + timeline_view)",
         "./setup.sh  (clones it)")
    clips = [p for p in RAW.glob("*") if p.suffix.lower() in VIDEO_EXT] if RAW.exists() else []
    log(f"  [..] raw/ clips: {len(clips)} | photos/: {count(PHOTOS, IMAGE_EXT)} | music/: {count(MUSIC, AUDIO_EXT)}")
    log(f"  [..] brief/staff.csv rows: {len(load_staff())}")
    log("All good." if ok else "Fix the items marked !! above.")


def count(folder: Path, exts: set) -> int:
    return len([p for p in folder.glob("*") if p.suffix.lower() in exts]) if folder.exists() else 0


def read_dotenv() -> dict:
    env = {}
    for p in [ROOT / ".env", ROOT / "vendor" / "video-use" / ".env"]:
        if p.exists():
            for ln in p.read_text().splitlines():
                if "=" in ln and not ln.strip().startswith("#"):
                    k, v = ln.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env


# ----------------------------------------------------------------- inventory

def contact_sheet(src: Path, dest: Path, dur: float, hdr: bool, n: int = 6) -> None:
    rate = max(n / max(dur, 0.5), 0.01)
    pre = (TONEMAP + ",") if hdr else ""
    vf = (f"{pre}fps={rate:.5f},scale=360:360:force_original_aspect_ratio=decrease,"
          f"pad=360:360:(ow-iw)/2:(oh-ih)/2:color=0x202020,tile=3x2:padding=6:color=white")
    ffmpeg(["-i", src, "-vf", vf, "-frames:v", "1", "-q:v", "4", dest])


def cmd_inventory(args) -> None:
    src = ROOT / args.src
    clips = sorted(p for p in src.glob("*") if p.suffix.lower() in VIDEO_EXT)
    if not clips:
        raise SystemExit(f"No video files in {rel(src)}/")
    is_raw = args.src.strip("/") == "raw"
    staff = load_staff() if is_raw else {}
    base = "inventory" if is_raw else f"inventory_{slugify(args.src)}"
    sheets = WORK / ("sheets" if is_raw else f"sheets_{slugify(args.src)}")
    sheets.mkdir(parents=True, exist_ok=True)
    items, seen = [], set()
    for i, f in enumerate(clips, 1):
        slug = slugify(f.name)
        while slug in seen:
            slug += "-b"
        seen.add(slug)
        log(f"[{i}/{len(clips)}] {f.name}")
        try:
            info = clip_info(f)
        except Exception as e:  # noqa: BLE001
            log(f"   skipped: {e}")
            continue
        dur = info["duration"]
        sl = silence_and_loudness(f) if info["has_audio"] else {"starts": [], "ends": [], "lufs": None}
        speech_start, speech_end = 0.0, dur
        if sl["starts"] and sl["starts"][0] <= 0.05 and sl["ends"]:
            speech_start = sl["ends"][0]
        # trailing silence runs to the end (ffmpeg may or may not print a final silence_end)
        if sl["starts"] and (len(sl["starts"]) > len(sl["ends"]) or sl["ends"][-1] >= dur - 0.15) \
                and sl["starts"][-1] > speech_start:
            speech_end = sl["starts"][-1]
        speech_end = max(speech_end, speech_start + 0.5)
        sheet = sheets / f"{slug}.jpg"
        contact_sheet(f, sheet, dur, info["hdr"])
        row = staff.get(slug, {})
        warn = []
        if not info["has_audio"]:
            warn.append("no audio")
        elif sl["lufs"] is not None and sl["lufs"] < -35:
            warn.append(f"very quiet ({sl['lufs']} LUFS)")
        if dur < 2.5:
            warn.append("very short")
        if dur > 60:
            warn.append("long, needs a tight trim")
        if info["hdr"]:
            warn.append("HDR (will be tone-mapped)")
        if is_raw and not row:
            warn.append("not in brief/staff.csv")
        items.append({
            "slug": slug, "file": rel(f), **info,
            "name": row.get("name", ""), "role": row.get("role", ""),
            "department": row.get("department", ""), "notes": row.get("notes", ""),
            "lufs": sl["lufs"], "speech_start": round(speech_start, 2), "speech_end": round(speech_end, 2),
            "suggest_in": round(max(0.0, speech_start - 0.15), 2),
            "suggest_out": round(min(dur, speech_end + 0.35), 2),
            "sheet": rel(sheet), "warnings": warn,
        })
    WORK.mkdir(exist_ok=True)
    (WORK / f"{base}.json").write_text(json.dumps(items, indent=2))
    lines = [f"# Clip inventory: {args.src}/", "",
             f"{len(items)} clips, {sum(i['duration'] for i in items):.0f} s in total. "
             f"Contact sheets (6 frames each) are in {rel(sheets)}/.", "",
             "| slug | person | dur s | shape | LUFS | suggested in-out | warnings |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for it in items:
        who = ", ".join(x for x in [it["name"], it["role"] or it["department"]] if x) or "?"
        lines.append(f"| {it['slug']} | {who} | {it['duration']:.1f} | {it['orientation']} {it['width']}x{it['height']} "
                     f"| {it['lufs'] if it['lufs'] is not None else '-'} | {it['suggest_in']}-{it['suggest_out']} "
                     f"| {'; '.join(it['warnings'])} |")
    extra = []
    for folder, exts, label in [(PHOTOS, IMAGE_EXT, "photos"), (MUSIC, AUDIO_EXT, "music")]:
        files = sorted(p for p in folder.glob("*") if p.suffix.lower() in exts) if folder.exists() else []
        extra.append(f"- {label}/: " + (", ".join(p.name for p in files) or "(empty)"))
    lines += ["", "## Other assets", *extra, ""]
    (WORK / f"{base}.md").write_text("\n".join(lines))
    log(f"\nWrote work/{base}.md and work/{base}.json ({len(items)} clips).")


# ----------------------------------------------------------------- conform

def conform_one(it: dict, aspect: str, grade: str, force: bool = False) -> Path:
    W, H = ASPECTS[aspect]
    src = ROOT / it["file"]
    out = WORK / "conformed" / tag_of(aspect) / f"{it['slug']}.mp4"
    if out.exists() and not force and out.stat().st_mtime > src.stat().st_mtime:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    pre = (TONEMAP + ",") if it.get("hdr") else ""
    g = GRADES.get(grade, grade or "")
    bw, bh = W // 4, H // 4
    vf = (f"[0:v]{pre}setsar=1,split[a][b];"
          f"[a]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},gblur=sigma=12,"
          f"eq=brightness=-0.06:saturation=0.9,scale={W}:{H}[bg];"
          f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
          f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={FPS},format=yuv420p,setsar=1"
          + (f",{g}" if g else "") + "[v]")
    args = ["-i", src]
    if it.get("has_audio"):
        m = measure_loudnorm(src, -16)
        if m:
            ln = (f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
                  f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
        else:
            ln = "loudnorm=I=-16:TP=-1.5:LRA=11"
        af = f"[0:a]highpass=f=70,{ln},aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo[a]"
        fc = vf + ";" + af
        maps = ["-map", "[v]", "-map", "[a]"]
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        fc = vf
        maps = ["-map", "[v]", "-map", "1:a", "-shortest"]
    ffmpeg([*args, "-filter_complex", fc, *maps, *X264, "-crf", "18", *AAC, "-movflags", "+faststart", out])
    return out


def measure_loudnorm(path: Path, target: float) -> dict | None:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(path), "-vn", "-af",
                        f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr, re.S)
    if not m:
        return None
    d = json.loads(m.group(0))
    if d.get("input_i") in (None, "-inf") or not math.isfinite(float(d["input_i"])):
        return None
    return d


def cmd_conform(args) -> None:
    inv = load_inventory()
    if args.only:
        wanted = set(args.only.split(","))
        inv = [i for i in inv if i["slug"] in wanted]
    for n, it in enumerate(inv, 1):
        t = time.time()
        out = conform_one(it, args.aspect, args.grade, args.force)
        log(f"[{n}/{len(inv)}] {it['slug']} -> {rel(out)} ({time.time() - t:.1f}s)")


# ----------------------------------------------------------------- transcribe

def transcribe_whisper(wav: Path, model_name: str, language: str | None) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise SystemExit("faster-whisper is not installed: .venv/bin/pip install faster-whisper")
    global _WHISPER
    if "_WHISPER" not in globals() or _WHISPER[0] != model_name:
        log(f"   loading Whisper model '{model_name}' (first run downloads it)...")
        _WHISPER = (model_name, WhisperModel(model_name, device="auto", compute_type="int8"))
    model = _WHISPER[1]
    segs, info = model.transcribe(str(wav), language=language, word_timestamps=True, vad_filter=True,
                                  beam_size=5, condition_on_previous_text=False)
    words = []
    for s in segs:
        for w in s.words or []:
            words.append({"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3)})
    return {"engine": f"whisper:{model_name}", "language": info.language, "words": words, "events": []}


def transcribe_scribe(wav: Path, key: str, language: str | None, model_id: str) -> dict:
    boundary = uuid.uuid4().hex
    fields = {"model_id": model_id, "timestamps_granularity": "word", "tag_audio_events": "true", "diarize": "false"}
    if language:
        fields["language_code"] = language
    body = b""
    for k, v in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{wav.name}\"\r\n"
             f"Content-Type: audio/wav\r\n\r\n").encode() + wav.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request("https://api.elevenlabs.io/v1/speech-to-text", data=body, method="POST",
                                 headers={"xi-api-key": key, "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read().decode())
    words, events = [], []
    for w in d.get("words", []):
        kind = w.get("type", "word")
        if kind == "word":
            words.append({"w": w["text"].strip(), "s": round(w["start"], 3), "e": round(w["end"], 3)})
        elif kind == "audio_event":
            events.append({"t": w["text"], "s": round(w["start"], 3), "e": round(w["end"], 3)})
    return {"engine": f"elevenlabs:{model_id}", "language": d.get("language_code"), "words": words, "events": events}


def pack_phrases(words: list, gap: float = 0.5, max_words: int = 16) -> list:
    phrases, cur = [], []
    for w in words:
        if cur and (w["s"] - cur[-1]["e"] >= gap or len(cur) >= max_words):
            phrases.append(cur)
            cur = []
        cur.append(w)
    if cur:
        phrases.append(cur)
    return [(p[0]["s"], p[-1]["e"], " ".join(x["w"] for x in p)) for p in phrases]


def cmd_transcribe(args) -> None:
    inv = load_inventory()
    if args.only:
        wanted = set(args.only.split(","))
        inv = [i for i in inv if i["slug"] in wanted]
    key = os.environ.get("ELEVENLABS_API_KEY") or read_dotenv().get("ELEVENLABS_API_KEY")
    engine = args.engine
    if engine == "auto":
        engine = "scribe" if key else "whisper"
    if engine == "scribe" and not key:
        raise SystemExit("ELEVENLABS_API_KEY not set (environment or .env).")
    tdir, adir = WORK / "transcripts", WORK / "audio"
    tdir.mkdir(parents=True, exist_ok=True)
    adir.mkdir(parents=True, exist_ok=True)
    lang = None if args.language == "auto" else args.language
    for n, it in enumerate(inv, 1):
        src = ROOT / it["file"]
        out = tdir / f"{it['slug']}.json"
        stamp = f"{src.stat().st_size}:{int(src.stat().st_mtime)}"
        if out.exists() and not args.force and json.loads(out.read_text()).get("stamp") == stamp:
            log(f"[{n}/{len(inv)}] {it['slug']}: cached")
            continue
        if not it.get("has_audio"):
            log(f"[{n}/{len(inv)}] {it['slug']}: no audio, skipped")
            continue
        wav = adir / f"{it['slug']}.wav"
        ffmpeg(["-i", src, "-vn", "-ac", "1", "-ar", "16000", wav])
        t = time.time()
        if engine == "scribe":
            d = transcribe_scribe(wav, key, lang, args.scribe_model)
        else:
            d = transcribe_whisper(wav, args.model, lang)
        d.update({"slug": it["slug"], "source": it["file"], "duration": it["duration"], "stamp": stamp})
        out.write_text(json.dumps(d, indent=1, ensure_ascii=False))
        log(f"[{n}/{len(inv)}] {it['slug']}: {len(d['words'])} words via {d['engine']} ({time.time() - t:.0f}s)")
    pack_all(load_inventory())


def pack_all(inv: list) -> None:
    lines = ["# Transcripts (packed)", "",
             "Times are seconds in each source clip. Phrases break on pauses of 0.5 s or more.", ""]
    for it in inv:
        p = WORK / "transcripts" / f"{it['slug']}.json"
        who = ", ".join(x for x in [it.get("name"), it.get("role") or it.get("department")] if x) or "unknown"
        lines.append(f"## {it['slug']} - {who} (dur {it['duration']:.1f}s, suggested {it['suggest_in']}-{it['suggest_out']})")
        if not p.exists():
            lines += ["  (no transcript)", ""]
            continue
        d = json.loads(p.read_text())
        for s, e, text in pack_phrases(d["words"]):
            lines.append(f"  [{s:06.2f}-{e:06.2f}] {text}")
        for ev in d.get("events", []):
            lines.append(f"  [{ev['s']:06.2f}] {ev['t']}")
        lines.append("")
    (WORK / "transcripts.md").write_text("\n".join(lines))
    log("Wrote work/transcripts.md")


# ----------------------------------------------------------------- roughcut

class Look:
    def __init__(self, edl: dict, W: int, H: int):
        self.W, self.H = W, H
        self.short = min(W, H)
        self.accent = edl.get("accent", "#E8A317")
        self.ink = edl.get("text_color", "#FFFFFF")
        self.bg = edl.get("bg_color", "#0F1B2D")
        self.portrait = H > W


def caption_chunks(words: list, t_in: float, t_out: float, max_words: int = 5, max_chars: int = 30) -> list:
    ws = [w for w in words if w["e"] > t_in + 0.05 and w["s"] < t_out - 0.05]
    chunks, cur = [], []
    for w in ws:
        text_len = len(" ".join(x["w"] for x in cur + [w]))
        if cur and (len(cur) >= max_words or text_len > max_chars or w["s"] - cur[-1]["e"] > 0.35
                    or cur[-1]["w"][-1:] in ".?!"):
            chunks.append(cur)
            cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    out = []
    for i, c in enumerate(chunks):
        s = max(c[0]["s"] - t_in, 0.0)
        nxt = chunks[i + 1][0]["s"] - t_in if i + 1 < len(chunks) else None
        e = c[-1]["e"] - t_in + 0.25
        if nxt is not None:
            e = min(e, nxt) if nxt - s > 0.6 else nxt
        e = max(e, s + 0.6)
        out.append((round(s, 3), round(min(e, t_out - t_in), 3), " ".join(x["w"] for x in c)))
    return out


def text_filters(tmp: Path, look: Look, lines: list, base_y: float, t0: float, t1: float,
                 stagger: float = 0.4, big: int = 0) -> list:
    """Centered stacked lines. Line `big` is large and white; lines above it are an accent-coloured
    kicker, lines below are regular weight. Lines reveal one after another."""
    big = min(max(int(big), 0), len(lines) - 1) if lines else 0
    sizes = [fit(int(look.short * (0.088 if i == big else 0.05)), t, look.W * 0.88) for i, t in enumerate(lines)]
    gap = int(look.short * 0.028)
    total = sum(sizes) + gap * (len(lines) - 1)
    y = base_y - total / 2
    out = []
    for i, (txt, sz) in enumerate(zip(lines, sizes)):
        tf = write_textfile(tmp, txt)
        font = "bold.ttf" if i <= big else "regular.ttf"
        color = look.accent if i < big else look.ink
        out.append(f"drawtext=fontfile={font}:textfile={tf}:fontsize={sz}:fontcolor={color}:"
                   f"x=(w-text_w)/2:y={int(y)}:borderw={max(2, sz // 24)}:bordercolor=black@0.6:"
                   f"alpha={fade_alpha(t0 + i * stagger, t1)}")
        y += sz + gap
    return out


def render_clip(seg: dict, i: int, tmp: Path, look: Look, aspect: str, inv: list, edl: dict, out: Path) -> float:
    it = find_item(seg["slug"], inv)
    src = conform_one(it, aspect, edl.get("grade", "warm"))
    t_in = float(seg.get("in", it["suggest_in"]))
    t_out = float(seg.get("out", it["suggest_out"]))
    t_out = min(t_out, it["duration"])
    dur = round(t_out - t_in, 3)
    if dur <= 0.3:
        raise SystemExit(f"Segment {i} ({seg['slug']}): out must be after in.")
    W, H = look.W, look.H
    vf = ["setpts=PTS-STARTPTS"]
    name = seg.get("name") or it.get("name") or ""
    role = seg.get("role") or it.get("role") or it.get("department") or ""
    if seg.get("lower_third", True) and name:
        n_sz, r_sz = int(look.short * 0.058), int(look.short * 0.038)
        x0 = int(W * (0.07 if look.portrait else 0.055))
        y0 = int(H * (0.60 if look.portrait else 0.66))
        n_sz, r_sz = fit(n_sz, name, W - 2 * x0), fit(r_sz, role, W - 2 * x0, 0.55)
        a0, a1 = 0.35, min(4.6, dur - 0.2)
        vf.append(f"drawbox=x={x0 - 22}:y={y0 - 8}:w=10:h={n_sz + r_sz + 34}:color={look.accent}@0.95:t=fill:"
                  f"enable='between(t,{a0 + 0.1},{a1 - 0.1})'")
        vf.append(f"drawtext=fontfile=bold.ttf:textfile={write_textfile(tmp, name)}:fontsize={n_sz}:fontcolor=white:"
                  f"x={x0}:y={y0}:box=1:boxcolor=black@0.55:boxborderw=12:alpha={fade_alpha(a0, a1)}")
        if role:
            vf.append(f"drawtext=fontfile=regular.ttf:textfile={write_textfile(tmp, role)}:fontsize={r_sz}:"
                      f"fontcolor={look.accent}:x={x0}:y={y0 + n_sz + 24}:box=1:boxcolor=black@0.55:boxborderw=10:"
                      f"alpha={fade_alpha(a0 + 0.15, a1)}")
    tpath = WORK / "transcripts" / f"{it['slug']}.json"
    if seg.get("captions", edl.get("captions", True)) and tpath.exists():
        words = json.loads(tpath.read_text())["words"]
        for fix_from, fix_to in (edl.get("caption_fixes") or {}).items():
            for w in words:
                if w["w"].strip(".,!?").lower() == fix_from.lower():
                    w["w"] = w["w"].lower().replace(fix_from.lower(), fix_to)
        c_sz = int(look.short * (0.05 if look.portrait else 0.046))
        cy = int(H * (0.78 if look.portrait else 0.865))
        for s, e, text in caption_chunks(words, t_in, t_out):   # captions go LAST in the chain
            vf.append(f"drawtext=fontfile=bold.ttf:textfile={write_textfile(tmp, text)}:fontsize={c_sz}:fontcolor=white:"
                      f"x=(w-text_w)/2:y={cy}:borderw={max(3, c_sz // 14)}:bordercolor=black:"
                      f"enable='between(t,{s},{e})'")
    vol = float(seg.get("volume_db", 0))
    af = f"asetpts=PTS-STARTPTS,volume={vol}dB,afade=t=in:st=0:d=0.03,afade=t=out:st={max(dur - 0.03, 0):.3f}:d=0.03"
    if edl.get("transition") == "dip":
        vf.insert(1, f"fade=t=in:st=0:d=0.15,fade=t=out:st={dur - 0.15:.3f}:d=0.15")
    ffmpeg(["-ss", f"{t_in:.3f}", "-i", src, "-t", f"{dur:.3f}", "-vf", ",".join(vf), "-af", af,
            "-r", FPS, *X264, "-crf", "18", *AAC, out], cwd=tmp)
    return dur


def still_background(src: Path | None, look: Look, secs: float, motion: bool) -> tuple:
    """Return (input args, filter prefix producing [bg0]) for a photo or solid colour."""
    W, H = look.W, look.H
    if src is None:
        return (["-f", "lavfi", "-i", f"color=c={look.bg}:s={W}x{H}:r={FPS}:d={secs:.3f}"],
                "[0:v]format=yuv420p,setsar=1[bg0]")
    n = max(int(secs * FPS), 1)
    W2, H2 = W * 2, H * 2
    comp = (f"[0:v]scale={W2 // 8}:{H2 // 8}:force_original_aspect_ratio=increase,crop={W2 // 8}:{H2 // 8},"
            f"gblur=sigma=10,eq=brightness=-0.08,scale={W2}:{H2},setsar=1[pb];"
            f"[0:v]scale={W2}:{H2}:force_original_aspect_ratio=decrease,setsar=1[pf];"
            f"[pb][pf]overlay=(W-w)/2:(H-h)/2,format=yuv420p")
    if motion:
        comp += (f",zoompan=z='1+0.08*in/{n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:"
                 f"s={W}x{H}:fps={FPS}")
    else:
        comp += f",scale={W}:{H}"
    return (["-framerate", FPS, "-loop", "1", "-t", f"{secs:.3f}", "-i", src], comp + ",setsar=1[bg0]")


def render_card(seg: dict, i: int, tmp: Path, look: Look, out: Path) -> float:
    secs = float(seg.get("seconds", 4))
    bg = seg.get("bg") or seg.get("file")
    img = None
    if bg and not str(bg).startswith("#"):
        img = (ROOT / bg)
        if not img.exists():
            raise SystemExit(f"Segment {i}: image not found: {bg}")
    if bg and str(bg).startswith("#"):
        look = Look({"bg_color": bg, "accent": look.accent, "text_color": look.ink}, look.W, look.H)
    inputs, fc = still_background(img, look, secs, seg.get("motion", True))
    chain = []
    lines = seg.get("lines") or ([seg["text"]] if seg.get("text") else [])
    if seg.get("type") == "photo":
        cap = seg.get("caption")
        if cap:
            chain.append(f"drawbox=x=0:y=ih*0.80:w=iw:h=ih*0.20:color=black@0.35:t=fill")
            chain += text_filters(tmp, look, [cap], look.H * 0.89, 0.5, secs, 0)
    elif lines:
        if img is not None:
            chain.append("drawbox=x=0:y=0:w=iw:h=ih:color=black@0.50:t=fill")
        chain += text_filters(tmp, look, lines, look.H * 0.5, 0.35, secs + 1, big=seg.get("big", 0))
    chain.append(f"fade=t=in:st=0:d=0.3,fade=t=out:st={secs - 0.35:.3f}:d=0.35")
    fc += ";[bg0]" + ",".join(chain) + "[v]"
    ffmpeg([*inputs, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-filter_complex", fc,
            "-map", "[v]", "-map", "1:a", "-t", f"{secs:.3f}", "-r", FPS, *X264, "-crf", "18", *AAC, out], cwd=tmp)
    return secs


def render_grid(seg: dict, i: int, tmp: Path, look: Look, aspect: str, inv: list, edl: dict, out: Path) -> float:
    items = seg.get("items") or [{"slug": s} for s in seg.get("slugs", [])]
    if not items:
        raise SystemExit(f"Segment {i}: grid needs 'items' or 'slugs'.")
    secs = float(seg.get("seconds", 3.5))
    n = len(items)
    W, H = look.W, look.H
    cols = math.ceil(math.sqrt(n * (W / H) / (16 / 9))) if not look.portrait else max(2, math.ceil(math.sqrt(n / 2)))
    cols = max(1, min(cols, n))
    rows = math.ceil(n / cols)
    cw, ch = W // cols // 2 * 2, H // rows // 2 * 2
    args, parts, layout, amix = [], [], [], []
    for k, item in enumerate(items):
        it = find_item(item["slug"], inv)
        src = conform_one(it, aspect, edl.get("grade", "warm"))
        t_in = float(item.get("in", it["suggest_in"]))
        args += ["-ss", f"{t_in:.3f}", "-t", f"{secs + 0.5:.3f}", "-i", src]
        parts.append(f"[{k}:v]setpts=PTS-STARTPTS,scale={cw}:{ch}:force_original_aspect_ratio=increase,"
                     f"crop={cw}:{ch},tpad=stop_mode=clone:stop_duration={secs:.2f},trim=duration={secs:.3f},"
                     f"setsar=1[g{k}]")
        parts.append(f"[{k}:a]asetpts=PTS-STARTPTS,apad,atrim=duration={secs:.3f},aformat=sample_rates=48000:channel_layouts=stereo[ga{k}]")
        r, c = divmod(k, cols)
        in_row = cols if r < rows - 1 else n - cols * (rows - 1)
        xoff = (W - in_row * cw) // 2
        layout.append(f"{xoff + c * cw}_{r * ch}")
        amix.append(f"[ga{k}]")
    vin = "".join(f"[g{k}]" for k in range(n))
    stack = (f"{vin}xstack=inputs={n}:layout={'|'.join(layout)}:fill=black" if n > 1 else "[g0]null")
    parts.append(f"{stack},scale={W}:{H},fps={FPS},format=yuv420p,setsar=1[gs]")
    text = seg.get("text")
    post = []
    if text:
        band = int(look.short * 0.16)
        post.append(f"drawbox=x=0:y={H // 2 - band // 2}:w=iw:h={band}:color=black@0.45:t=fill:enable='gte(t,0.4)'")
        post += text_filters(tmp, look, [text], H * 0.5, 0.5, secs + 1)
    post.append(f"fade=t=out:st={secs - 0.3:.3f}:d=0.3")
    parts.append("[gs]" + ",".join(post) + "[v]")
    if n > 1:
        parts.append(f"{''.join(amix)}amix=inputs={n}:normalize=1,volume={min(3.0, math.sqrt(n)):.2f},"
                     f"afade=t=out:st={secs - 0.3:.3f}:d=0.3[a]")
    else:
        parts.append("[ga0]anull[a]")
    ffmpeg([*args, "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]", "-t", f"{secs:.3f}",
            "-r", FPS, *X264, "-crf", "18", *AAC, out], cwd=tmp)
    return secs


def cmd_roughcut(args) -> None:
    edl_path = Path(args.edl)
    if not edl_path.is_absolute():
        edl_path = ROOT / edl_path
    edl = json.loads(edl_path.read_text())
    aspect = args.aspect or edl.get("aspect", "16:9")
    W, H = ASPECTS[aspect]
    look = Look(edl, W, H)
    inv = load_inventory()
    name = args.name or f"{edl_path.stem}_{tag_of(aspect)}"
    tmp = WORK / "segments" / name
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    stage_fonts(tmp, edl.get("font"))
    segs = edl.get("segments", [])
    if not segs:
        raise SystemExit("EDL has no segments.")
    files, timeline, t = [], [], 0.0
    for i, seg in enumerate(segs):
        kind = seg.get("type", "clip")
        f = tmp / f"{i:03d}_{kind}.mp4"
        st = time.time()
        if kind == "clip":
            d = render_clip(seg, i, tmp, look, aspect, inv, edl, f)
            label = f"{seg['slug']} ({seg.get('name') or find_item(seg['slug'], inv).get('name') or '?'})"
        elif kind in ("card", "title", "photo", "end"):
            d = render_card(seg, i, tmp, look, f)
            label = seg.get("caption") or " / ".join(seg.get("lines") or [seg.get("text", "")]) or seg.get("file", "")
        elif kind == "grid":
            d = render_grid(seg, i, tmp, look, aspect, inv, edl, f)
            label = f"grid of {len(seg.get('items') or seg.get('slugs'))} clips"
        else:
            raise SystemExit(f"Segment {i}: unknown type '{kind}' (clip, card, photo, grid)")
        files.append(f)
        timeline.append((t, t + d, kind, label))
        log(f"[{i + 1}/{len(segs)}] {kind:5s} {d:5.1f}s  {label}  ({time.time() - st:.0f}s)")
        t += d
    total = t
    # ---- concat + music bed with ducking
    args_in, fc = [], []
    for f in files:
        args_in += ["-i", f]
    cat_in = "".join(f"[{k}:v][{k}:a]" for k in range(len(files)))
    fc.append(f"{cat_in}concat=n={len(files)}:v=1:a=1[v][voice]")
    music = edl.get("music") or []
    k0 = len(files)
    if music:
        mlabels = []
        for j, m in enumerate(music):
            mp = ROOT / m["file"]
            if not mp.exists():
                raise SystemExit(f"Music file not found: {m['file']}")
            args_in += ["-stream_loop", "-1", "-i", mp]
            st = float(m.get("start", 0))
            en = min(float(m.get("end", total)), total)
            ln = max(en - st, 0.5)
            fi, fo = float(m.get("fade_in", 1.5)), float(m.get("fade_out", 2.5))
            ms = int(st * 1000)
            fc.append(f"[{k0 + j}:a]aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo,"
                      f"atrim=duration={ln:.3f},asetpts=PTS-STARTPTS,afade=t=in:st=0:d={fi},"
                      f"afade=t=out:st={max(ln - fo, 0):.3f}:d={fo},volume={float(m.get('volume', 0.3))},"
                      f"adelay={ms}|{ms}[m{j}]")
            mlabels.append(f"[m{j}]")
        if len(mlabels) > 1:
            fc.append(f"{''.join(mlabels)}amix=inputs={len(mlabels)}:normalize=0:duration=longest[mus]")
        else:
            fc.append(f"{mlabels[0]}anull[mus]")
        fc.append("[voice]asplit=2[vo1][vo2]")
        fc.append("[mus][vo1]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=450[duck]")
        fc.append("[vo2][duck]amix=inputs=2:duration=first:normalize=0[mix]")
        alabel = "[mix]"
    else:
        alabel = "[voice]"
    OUT.mkdir(exist_ok=True)
    stage = tmp / "mix.mp4"
    ffmpeg([*args_in, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", alabel, "-t", f"{total:.3f}",
            *X264, "-crf", str(args.crf), "-c:a", "pcm_s16le", "-ar", "48000", stage.with_suffix(".mov")])
    # ---- master loudness: two-pass loudnorm on the mix, video copied
    final = OUT / f"{name}.mp4"
    target = float(edl.get("loudness", -14))
    m = measure_loudnorm(stage.with_suffix(".mov"), target)
    ln = (f"loudnorm=I={target}:TP=-1.0:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true"
          if m else f"loudnorm=I={target}:TP=-1.0:LRA=11")
    ffmpeg(["-i", stage.with_suffix(".mov"), "-map", "0:v", "-map", "0:a", "-c:v", "copy", "-af",
            f"{ln},aresample=48000", *AAC, "-movflags", "+faststart", final])
    tl = [f"# Timeline: {final.name}", "", f"Total {total:.1f}s ({int(total // 60)}:{int(total % 60):02d}).", "",
          "| # | start | end | type | what |", "| --- | --- | --- | --- | --- |"]
    for n_, (a, b, kind, label) in enumerate(timeline):
        tl.append(f"| {n_} | {a:.2f} | {b:.2f} | {kind} | {label} |")
    final.with_suffix(".timeline.md").write_text("\n".join(tl) + "\n")
    stage.with_suffix(".mov").unlink(missing_ok=True)
    log(f"\nDone: {rel(final)}  ({total:.1f}s). Timeline: {rel(final.with_suffix('.timeline.md'))}")
    log(f"Next: python scripts/vkit.py check {rel(final)}")


# ----------------------------------------------------------------- check / frames / export

def tile_frames(video: Path, times: list, dest: Path, cols: int = 4) -> None:
    tmp = dest.parent / f".frames_{uuid.uuid4().hex[:6]}"
    tmp.mkdir(parents=True, exist_ok=True)
    stage_fonts(tmp)
    try:
        for k, t in enumerate(times):
            ffmpeg(["-ss", f"{t:.3f}", "-i", video, "-frames:v", "1", "-vf",
                    f"scale=480:-2,drawtext=fontfile=bold.ttf:text='{t:.1f}s':x=8:y=8:fontsize=22:fontcolor=white:"
                    f"box=1:boxcolor=black@0.6:boxborderw=4", f"f{k:03d}.jpg"], cwd=tmp)
        rows = math.ceil(len(times) / cols)
        ffmpeg(["-framerate", "1", "-i", "f%03d.jpg", "-vf",
                f"tile={cols}x{rows}:padding=6:color=white", "-frames:v", "1", "-q:v", "3", dest.resolve()], cwd=tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_check(args) -> None:
    v = Path(args.video).resolve()
    info = clip_info(v)
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-i", str(v), "-af",
                        "ebur128=peak=true,silencedetect=n=-45dB:d=2.5", "-vf", "blackdetect=d=0.4:pix_th=0.08",
                        "-f", "null", "-"], capture_output=True, text=True)
    err = p.stderr
    I = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    tp = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", err)
    blacks = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", err)
    sil = re.findall(r"silence_start: ([\d.]+)", err)
    dur = info["duration"]
    log(f"{v.name}: {info['width']}x{info['height']} {info['fps']}fps {dur:.1f}s {info['size_mb']} MB")
    warn = []
    if I:
        lufs = float(I[-1])
        log(f"  loudness {lufs} LUFS integrated, true peak {tp[-1] if tp else '?'} dBTP")
        if not -16.5 <= lufs <= -12.5:
            warn.append(f"loudness {lufs} LUFS is outside -16.5 to -12.5")
        if tp and float(tp[-1]) > -0.9:
            warn.append(f"true peak {tp[-1]} dBTP is above -1")
    mid_blacks = [(float(a), float(b)) for a, b in blacks if float(a) > 0.5 and float(b) < dur - 0.5]
    for a, b in mid_blacks:
        warn.append(f"black frames {a:.1f}-{b:.1f}s")
    for s in sil:
        if 0.5 < float(s) < dur - 3:
            warn.append(f"silence of 2.5s+ starting {float(s):.1f}s")
    cdir = WORK / "check" / v.stem
    cdir.mkdir(parents=True, exist_ok=True)
    step = max(dur / 24, 1.0)
    times = [min(dur - 0.1, step * k + 0.5) for k in range(int(dur // step) + 1)]
    sheets = []
    for k in range(0, len(times), 12):
        dest = cdir / f"sheet_{k // 12 + 1:02d}.jpg"
        tile_frames(v, times[k:k + 12], dest)
        sheets.append(rel(dest))
    tl = v.with_suffix(".timeline.md")
    if tl.exists():
        cuts = [float(m) for m in re.findall(r"^\| \d+ \| ([\d.]+) \|", tl.read_text(), re.M)][1:]
        if cuts:
            times_c = sorted({max(0.0, c + d) for c in cuts for d in (-0.4, 0.4)})
            dest = cdir / "cuts.jpg"
            tile_frames(v, times_c[:48], dest, cols=6)
            sheets.append(rel(dest))
    log("  contact sheets: " + ", ".join(sheets))
    log("  warnings: " + ("; ".join(warn) if warn else "none"))


def cmd_frames(args) -> None:
    v = Path(args.video).resolve()
    times = [float(x) for x in args.at.split(",") if x.strip()]
    dest = WORK / "check" / f"{v.stem}_frames.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tile_frames(v, times, dest, cols=min(4, len(times)))
    log(f"Wrote {rel(dest)}")


def cmd_export(args) -> None:
    v = Path(args.video).resolve()
    small = OUT / f"{v.stem}_720p_small.mp4"
    info = clip_info(v)
    scale = "scale=1280:-2" if info["width"] >= info["height"] else "scale=-2:1280"
    ffmpeg(["-i", v, "-vf", scale, *X264, "-crf", "27", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", small])
    poster = OUT / f"{v.stem}_poster.jpg"
    at = args.poster_at if args.poster_at is not None else min(6.0, info["duration"] / 2)
    ffmpeg(["-ss", f"{at:.2f}", "-i", v, "-frames:v", "1", "-q:v", "2", poster])
    log(f"Wrote {rel(small)} ({small.stat().st_size / 1e6:.1f} MB) and {rel(poster)}")


# ----------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description="Birthday video toolkit", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    p = sub.add_parser("inventory")
    p.add_argument("--src", default="raw")
    p.set_defaults(fn=cmd_inventory)
    p = sub.add_parser("conform")
    p.add_argument("--aspect", default="16:9", choices=list(ASPECTS))
    p.add_argument("--grade", default="warm", help="none | warm | punch | raw ffmpeg filter")
    p.add_argument("--only", help="comma-separated slugs")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_conform)
    p = sub.add_parser("transcribe")
    p.add_argument("--engine", default="auto", choices=["auto", "whisper", "scribe"])
    p.add_argument("--model", default="large-v3-turbo", help="Whisper model: large-v3-turbo | medium | small")
    p.add_argument("--scribe-model", default="scribe_v1")
    p.add_argument("--language", default="en", help="en | auto | yo | ig | ha ...")
    p.add_argument("--only")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_transcribe)
    p = sub.add_parser("roughcut")
    p.add_argument("edl")
    p.add_argument("--aspect", choices=list(ASPECTS))
    p.add_argument("--name")
    p.add_argument("--crf", type=int, default=19)
    p.set_defaults(fn=cmd_roughcut)
    p = sub.add_parser("check")
    p.add_argument("video")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("frames")
    p.add_argument("video")
    p.add_argument("--at", required=True, help="comma-separated seconds")
    p.set_defaults(fn=cmd_frames)
    p = sub.add_parser("export")
    p.add_argument("video")
    p.add_argument("--poster-at", type=float)
    p.set_defaults(fn=cmd_export)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
