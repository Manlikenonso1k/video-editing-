#!/usr/bin/env python3
"""
Prepare a screen recording so its AUDIO drives the edit.

    python3 scripts/prepare_recording.py            # uses content.json → recording.*

What it does
  1. Finds the speech in the recording's narration (Silero VAD) and transcribes
     each phrase offline (Whisper via sherpa-onnx; run scripts/setup-asr.sh once).
  2. Builds an edit decision list from the speech: dead air at the start/end is
     trimmed and long pauses are tightened (video and audio are cut together, so
     what's on screen stays in sync with what's being said).
  3. Exports the cut as JPEG frames + a 48 kHz WAV, remaps every caption/word
     time onto the new cut, and measures a loudness envelope so the motion
     graphics can react to the voice.
  4. Writes build/recording.json, which scripts/render.mjs picks up automatically.

Falls back gracefully: no ASR models → energy-based speech detection, no captions
(the callouts from content.json are used); keepAudio=false → silent, speed-adjusted
footage exactly like before.
"""
import json
import math
import os
import shutil
import subprocess
import sys
import wave

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
BUILD = os.path.join(ROOT, 'build')
MODELS = os.path.join(ROOT, 'tools', 'models')
FPS = 30


def sh(*cmd, capture=False):
    r = subprocess.run(cmd, check=True, stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE if capture else None)
    return r.stdout.decode() if capture else None


def probe(path):
    info = json.loads(sh('ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path, capture=True))
    v = next((s for s in info['streams'] if s['codec_type'] == 'video'), None)
    a = next((s for s in info['streams'] if s['codec_type'] == 'audio'), None)
    if not v:
        sys.exit(f'no video stream in {path}')
    w, h = int(v['width']), int(v['height'])
    rot = 0
    for sd in v.get('side_data_list', []) or []:
        if 'rotation' in sd:
            rot = int(float(sd['rotation']))
    rot = int(v.get('tags', {}).get('rotate', rot) or rot)
    if abs(rot) % 180 == 90:
        w, h = h, w
    return {'duration': float(info['format']['duration']), 'width': w, 'height': h, 'has_audio': a is not None}


def read_wav(path):
    with wave.open(path) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        return x.reshape(-1, w.getnchannels()), w.getframerate()


# ------------------------------------------------------------------ speech

def speech_segments_asr(wav16, language):
    import sherpa_onnx  # noqa: deferred so the fallback works without it
    model_dir = next((os.path.join(MODELS, d) for d in sorted(os.listdir(MODELS)) if d.startswith('sherpa-onnx-whisper')), None)
    if not model_dir:
        raise FileNotFoundError('no whisper model')
    name = os.path.basename(model_dir).replace('sherpa-onnx-whisper-', '')
    pick = lambda part: next(p for p in (os.path.join(model_dir, f'{name}-{part}.int8.onnx'), os.path.join(model_dir, f'{name}-{part}.onnx')) if os.path.exists(p))
    rec = sherpa_onnx.OfflineRecognizer.from_whisper(
        encoder=pick('encoder'), decoder=pick('decoder'), tokens=os.path.join(model_dir, f'{name}-tokens.txt'),
        language='' if name.endswith('.en') else (language or 'en'), task='transcribe', num_threads=os.cpu_count() or 2)

    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = os.path.join(MODELS, 'silero_vad.onnx')
    cfg.silero_vad.threshold = 0.45
    cfg.silero_vad.min_silence_duration = 0.35
    cfg.silero_vad.min_speech_duration = 0.2
    cfg.silero_vad.max_speech_duration = 18
    cfg.sample_rate = 16000
    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=max(60, int(len(wav16) / 16000) + 30))
    win = cfg.silero_vad.window_size

    segs = []

    def drain():
        while not vad.empty():
            s = vad.front
            st = rec.create_stream()
            st.accept_waveform(16000, s.samples)
            rec.decode_stream(st)
            text = st.result.text.strip()
            start = s.start / 16000
            segs.append({'start': round(start, 3), 'end': round(start + len(s.samples) / 16000, 3), 'text': text})
            print(f'  {start:6.2f}s  {text}')
            vad.pop()

    for i in range(0, len(wav16), win):
        vad.accept_waveform(wav16[i:i + win])
        drain()
    vad.flush()
    drain()
    return [s for s in segs if s['text'] and not s['text'].startswith(('[', '('))]


def speech_segments_energy(wav16):
    """Fallback without models: RMS gate with hysteresis."""
    hop = 160  # 10 ms
    n = len(wav16) // hop
    rms = np.sqrt(np.mean(wav16[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    floor = np.percentile(db, 20)
    on = db > max(floor + 12, -45)
    segs, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        if not v and start is not None:
            if i - start > 15:
                segs.append({'start': start / 100, 'end': i / 100, 'text': ''})
            start = None
    if start is not None:
        segs.append({'start': start / 100, 'end': n / 100, 'text': ''})
    merged = []
    for s in segs:  # bridge tiny gaps
        if merged and s['start'] - merged[-1]['end'] < 0.3:
            merged[-1]['end'] = s['end']
        else:
            merged.append(s)
    return merged


def add_word_timing(seg):
    words = seg['text'].split()
    if not words:
        seg['words'] = []
        return seg
    weights = np.array([len(w) + 1.5 for w in words], dtype=float)
    span = seg['end'] - seg['start']
    edges = seg['start'] + np.concatenate([[0], np.cumsum(weights)]) / weights.sum() * span
    seg['words'] = [{'w': w, 'start': round(float(edges[i]), 3), 'end': round(float(edges[i + 1]), 3)} for i, w in enumerate(words)]
    return seg


# ------------------------------------------------------------------ edit decision list

def build_edl(segs, total, pad_in=0.12, pad_out=0.28, keep_gap=0.32):
    """Keep speech (+ padding); squeeze every pause down to at most keep_gap seconds."""
    if not segs:
        return [(0.0, total)]
    rng = []
    for s in segs:
        a, b = max(0.0, s['start'] - pad_in), min(total, s['end'] + pad_out)
        if rng and a - rng[-1][1] <= keep_gap:
            rng[-1] = (rng[-1][0], max(rng[-1][1], b))
        else:
            rng.append((a, b))
    return [(round(a, 3), round(b, 3)) for a, b in rng]


def remap(t, edl):
    acc = 0.0
    for a, b in edl:
        if t < a:
            return acc
        if t <= b:
            return acc + (t - a)
        acc += b - a
    return acc


# ------------------------------------------------------------------ main

def main():
    content = json.load(open(os.path.join(ROOT, 'content.json')))
    rc = content.get('recording', {})
    src = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(ROOT, rc.get('file', 'assets/screen-recording.mp4'))
    if not os.path.exists(src):
        sys.exit(f'✖ recording not found: {os.path.relpath(src, ROOT)}  (put your screen recording there)')

    start = float(rc.get('start') or 0)
    info = probe(src)
    dur = float(rc.get('duration') or (info['duration'] - start))
    keep_audio = bool(rc.get('keepAudio', True)) and info['has_audio']
    speed = 1.0 if keep_audio else float(rc.get('speed') or 1)
    portrait = info['height'] >= info['width']
    print(f'• {os.path.relpath(src, ROOT)}: {info["width"]}x{info["height"]}, {info["duration"]:.1f}s, audio={info["has_audio"]}')

    os.makedirs(BUILD, exist_ok=True)
    frames_dir = os.path.join(BUILD, 'rec')
    shutil.rmtree(frames_dir, ignore_errors=True)
    os.makedirs(frames_dir)

    captions, edl, envelope = [], [(0.0, dur)], []
    rec_audio = None

    if keep_audio:
        wav16_path = os.path.join(BUILD, 'rec-16k.wav')
        sh('ffmpeg', '-y', '-loglevel', 'error', '-ss', str(start), '-t', str(dur), '-i', src, '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', wav16_path)
        wav16 = read_wav(wav16_path)[0][:, 0]
        try:
            print('• transcribing narration (offline Whisper)…')
            segs = speech_segments_asr(wav16, rc.get('language', 'en'))
        except Exception as e:  # models missing or sherpa-onnx not installed
            print(f'  ASR unavailable ({e}); using energy-based speech detection, no captions')
            segs = speech_segments_energy(wav16)
        if rc.get('tightenPauses', True):
            edl = build_edl(segs, dur)
        for s in segs:
            if s['text']:
                s = add_word_timing(dict(s))
                s['start'], s['end'] = round(remap(s['start'], edl), 3), round(remap(s['end'], edl), 3)
                for w in s['words']:
                    w['start'], w['end'] = round(remap(w['start'], edl), 3), round(remap(w['end'], edl), 3)
                captions.append(s)

    # ---- cut video (+audio) along the EDL in one ffmpeg pass ----
    long_side = 1752 if portrait else 1600
    scale = f'scale=-2:{long_side}' if portrait else f'scale={long_side}:-2'
    parts, labels = [], []
    for i, (a, b) in enumerate(edl):
        parts.append(f'[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS[v{i}]')
        lab = f'[v{i}]'
        if keep_audio:
            fade = min(0.015, (b - a) / 4)
            parts.append(f'[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS,afade=t=in:d={fade},afade=t=out:st={b - a - fade}:d={fade}[a{i}]')
            lab += f'[a{i}]'
        labels.append(lab)
    n = len(edl)
    parts.append(''.join(labels) + f'concat=n={n}:v=1:a={1 if keep_audio else 0}' + ('[vc][ac]' if keep_audio else '[vc]'))
    vchain = f'[vc]setpts=PTS/{speed},fps={FPS},{scale}[vo]'
    parts.append(vchain)
    graph = ';'.join(parts)
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-ss', str(start), '-t', str(dur), '-i', src, '-filter_complex', graph,
           '-map', '[vo]', '-q:v', '2', os.path.join(frames_dir, '%05d.jpg')]
    if keep_audio:
        rec_audio = os.path.join(BUILD, 'rec-audio.wav')
        cmd += ['-map', '[ac]', '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', rec_audio]
    sh(*cmd)

    frames = len([f for f in os.listdir(frames_dir) if f.endswith('.jpg')])
    slot = round(frames / FPS, 3)

    if rec_audio:
        x, sr = read_wav(rec_audio)
        mono = np.abs(x).mean(axis=1)
        hop = sr // FPS
        k = len(mono) // hop
        rms = np.sqrt(np.mean(mono[: k * hop].reshape(k, hop) ** 2, axis=1))
        ref = np.percentile(rms, 95) or 1
        env = np.clip(rms / ref, 0, 1) ** 0.8
        sm = np.copy(env)
        for i in range(1, len(sm)):  # fast attack, slow release
            sm[i] = env[i] if env[i] > sm[i - 1] else sm[i - 1] * 0.82 + env[i] * 0.18
        envelope = [round(float(v), 3) for v in sm]

    out = {
        'source': os.path.relpath(src, ROOT),
        'frames': frames, 'fps': FPS, 'dir': '../build/rec',
        'orientation': 'portrait' if portrait else 'landscape',
        'width': info['width'], 'height': info['height'],
        'slotSeconds': slot,
        'audio': os.path.relpath(rec_audio, ROOT) if rec_audio else None,
        'edl': edl,
        'removedSeconds': round(dur - sum(b - a for a, b in edl), 2),
        'captions': captions,
        'envelope': envelope,
    }
    json.dump(out, open(os.path.join(BUILD, 'recording.json'), 'w'), indent=1)
    print(f'✔ build/recording.json  {frames} frames ({slot}s), {len(captions)} captions, '
          f'{out["removedSeconds"]}s of pauses removed across {len(edl)} cuts')


if __name__ == '__main__':
    main()
