#!/usr/bin/env python3
"""
Prepare the gameplay clip for the edit.

    python3 scripts/prep.py            # reads content.json → source

  build/frames/00001.jpg …   graded 30 fps frames of the footage
  build/song.wav             the clip's own music track (48 kHz stereo)
  build/beats.json           tempo, every beat and every bar downbeat

The beat grid is what the motion graphics are timed to, so every slam, punch-in,
flash and callout lands on the music.
"""
import json
import os
import shutil
import subprocess
import wave

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
BUILD = os.path.join(ROOT, 'build')


def sh(*cmd):
    subprocess.run(cmd, check=True)


def beat_grid(wav_path, bpm_range=(70, 180), downbeat_phase=None):
    with wave.open(wav_path) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float) / 32768
    hop, nfft = 256, 1024
    n = 1 + (len(x) - nfft) // hop
    win = np.hanning(nfft)
    spec = np.abs(np.array([np.fft.rfft(x[i * hop:i * hop + nfft] * win) for i in range(n)]))
    flux = np.maximum(0, np.diff(np.log1p(100 * spec), axis=0)).sum(axis=1)
    flux = np.concatenate([[0], flux])
    flux = (flux - flux.mean()) / (flux.std() + 1e-9)
    fr = sr / hop

    # tempo: autocorrelation of the onset envelope (plus its double, to avoid half-tempo picks)
    ac = np.correlate(flux, flux, 'full')[len(flux) - 1:]
    best = max(
        (ac[int(round(fr * 60 / b))] + 0.5 * ac[min(len(ac) - 1, int(round(2 * fr * 60 / b)))], b)
        for b in np.arange(bpm_range[0], bpm_range[1] + 0.5, 0.5))
    bpm = best[1]
    period = fr * 60 / bpm

    # peak of the onset envelope in a ±2-frame window (single-frame samples are too noisy)
    peak = np.maximum.reduce([np.roll(flux, s) for s in range(-2, 3)])

    def onset_sum(phase, step):
        idx = np.round(np.arange(phase, len(flux), step)).astype(int)
        return peak[idx[idx < len(flux)]].mean()

    phase = max(np.arange(0, period, 0.25), key=lambda p: onset_sum(p, period))
    beats = [(phase + k * period) / fr for k in range(int((len(flux) - phase) / period) + 1)]
    beats = [round(float(b), 3) for b in beats if b < len(x) / sr]
    # downbeat = the beat position in the bar (of 4) where the song's biggest accents land:
    # take the strongest ~12 onsets (≥0.25 s apart) and let each vote for its bar position
    order = np.argsort(peak)[::-1]
    top = []
    for i in order:
        if all(abs(i - j) > 0.25 * fr for j in top):
            top.append(i)
        if len(top) >= 12:
            break
    votes = np.zeros(4)
    for i in top:
        k = (i - phase) / period
        if abs(k - round(k)) < 0.15:            # on the beat grid
            votes[int(round(k)) % 4] += peak[i]
    which = int(np.argmax(votes)) if downbeat_phase is None else int(downbeat_phase) % 4
    downbeats = [b for i, b in enumerate(beats) if i % 4 == which]
    return {'bpm': float(bpm), 'beat': round(60 / bpm, 4), 'downbeatPhase': which, 'beats': beats, 'downbeats': downbeats,
            'duration': round(len(x) / sr, 3)}


def main():
    content = json.load(open(os.path.join(ROOT, 'content.json')))
    src = os.path.join(ROOT, content['source']['file'])
    fps = content['video']['fps']
    grade = content['source'].get('grade', 'eq=contrast=1.06:saturation=1.18:gamma=0.98')
    os.makedirs(BUILD, exist_ok=True)

    frames = os.path.join(BUILD, 'frames')
    shutil.rmtree(frames, ignore_errors=True)
    os.makedirs(frames)
    print('• extracting graded frames…')
    sh('ffmpeg', '-v', 'error', '-y', '-i', src, '-vf', f'fps={fps},{grade}', '-q:v', '2', os.path.join(frames, '%05d.jpg'))
    n = len([f for f in os.listdir(frames) if f.endswith('.jpg')])

    print('• extracting the music track…')
    song = os.path.join(BUILD, 'song.wav')
    sh('ffmpeg', '-v', 'error', '-y', '-i', src, '-vn', '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', song)
    mono = os.path.join(BUILD, 'song-mono22k.wav')
    sh('ffmpeg', '-v', 'error', '-y', '-i', src, '-vn', '-ar', '22050', '-ac', '1', '-c:a', 'pcm_s16le', mono)

    phase_override = content.get('music', {}).get('downbeatPhase', 'auto')
    grid = beat_grid(mono, downbeat_phase=None if phase_override == 'auto' else phase_override)
    w, h = map(int, subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=width,height',
                                    '-of', 'csv=p=0', src], capture_output=True, text=True).stdout.strip().split(','))
    out = dict(grid, frames=n, fps=fps, width=w, height=h, dir='../build/frames')
    json.dump(out, open(os.path.join(BUILD, 'beats.json'), 'w'), indent=1)
    print(f'✔ {n} frames ({w}x{h}), {grid["bpm"]} BPM, {len(grid["beats"])} beats, '
          f'downbeats at {", ".join(f"{d:.2f}" for d in grid["downbeats"])}')


if __name__ == '__main__':
    main()
