#!/usr/bin/env python3
"""
Mix the clip's own song with light sound design on the motion-graphics cues.

    python3 scripts/audio.py build/cues.json build/song.wav build/mix.wav

The song stays the star: effects are placed on the cue times exported by the
timeline (slams, whooshes, pops) and sit ~10 dB under the music. The tail fades
with the picture. Loudness normalisation happens in render.mjs.
"""
import json
import sys
import wave

import numpy as np

SR = 48000
rng = np.random.default_rng(3)


def t_axis(d):
    return np.arange(int(d * SR)) / SR


def lp(x, cutoff):
    cutoff = np.broadcast_to(np.asarray(cutoff, float), x.shape)
    a = 1 - np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    z = 0.0
    for i in range(len(x)):
        z += a[i] * (x[i] - z)
        y[i] = z
    return y


def bp(x, cutoff, q=1.0):
    cutoff = np.broadcast_to(np.asarray(cutoff, float), x.shape)
    f = 2 * np.sin(np.pi * np.minimum(cutoff, SR / 6) / SR)
    low = band = 0.0
    y = np.empty_like(x)
    for i in range(len(x)):
        low += f[i] * band
        high = x[i] - low - band / q
        band += f[i] * high
        y[i] = band
    return y


def pan(m, p):
    p = np.broadcast_to(np.asarray(p, float), m.shape)
    a = (p + 1) * np.pi / 4
    return np.stack([m * np.cos(a), m * np.sin(a)], 1)


def whoosh(d=0.7, lo=300, hi=6000, p0=-0.6, p1=0.6):
    t = t_axis(d)
    x = t / d
    cut = lo + (hi - lo) * np.sin(np.pi * np.clip(x * 0.9, 0, 1)) ** 1.5
    n = rng.standard_normal(len(t))
    s = (bp(n, cut, 1.2) + 0.5 * lp(n, cut * 0.5)) * np.sin(np.pi * x) ** 2.2
    return pan(s, np.linspace(p0, p1, len(t)))


def riser(d):
    t = t_axis(d)
    x = t / d
    n = bp(rng.standard_normal(len(t)), 500 + 8000 * x ** 1.7, 1.6)
    f = 220 * 2 ** (x * 2.4)
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.3
    s = (n + tone) * x ** 2.6 * np.minimum(1, (d - t) / 0.015)
    return pan(s, 0.3 * np.sin(2 * np.pi * 1.5 * t))


def impact(big=True):
    t = t_axis(1.6)
    f = 38 + 80 * np.exp(-t / 0.05)
    boom = np.tanh(2 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / (0.5 if big else 0.25)))
    crack = lp(rng.standard_normal(len(t)), 5000) * np.exp(-t / 0.06)
    s = boom + crack * (0.6 if big else 0.35)
    return pan(s, 0)


def hit():
    t = t_axis(0.35)
    f = 70 + 120 * np.exp(-t / 0.02)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.09) + lp(rng.standard_normal(len(t)), 3000) * np.exp(-t / 0.02) * 0.5
    return pan(s, 0)


def pop(p=0.0):
    t = t_axis(0.2)
    f = 950 * (0.55 + 0.45 * np.exp(-t / 0.025))
    return pan(np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.05) * np.minimum(1, t * 2000), p)


def tick():
    t = t_axis(0.05)
    return pan(np.sin(2 * np.pi * 2800 * t) * np.exp(-t / 0.008), 0)


def place(bus, sig, t, gain):
    i = int(round(t * SR))
    if i < 0:
        sig, i = sig[-i:], 0
    j = min(len(bus), i + len(sig))
    if j > i:
        bus[i:j] += sig[: j - i] * gain


def main():
    cues_path, song_path, out = sys.argv[1:4]
    data = json.load(open(cues_path))
    with wave.open(song_path) as w:
        assert w.getframerate() == SR
        song = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float).reshape(-1, w.getnchannels()) / 32768
    if song.shape[1] == 1:
        song = np.repeat(song, 2, 1)
    D = data['duration']
    N = int(D * SR)
    song = np.pad(song, ((0, max(0, N - len(song))), (0, 0)))[:N]

    sfx = np.zeros((N, 2))
    for c in data['cues']:
        t, k = c['t'], c['type']
        if k == 'whoosh':
            place(sfx, whoosh(), t - 0.3, 0.55)
        elif k == 'whoosh_soft':
            place(sfx, whoosh(0.5, 800, 7000, 0.4, -0.4), t - 0.2, 0.3)
        elif k == 'riser':
            place(sfx, riser(c['end'] - t), t, 0.4)
        elif k == 'impact':
            place(sfx, impact(True), t, 0.85)
        elif k == 'hit':
            place(sfx, hit(), t, 0.5)
        elif k == 'pop':
            place(sfx, pop(c.get('pan', 0)), t, 0.35)
        elif k == 'tick':
            place(sfx, tick(), t, 0.25)

    # sit the effects ~10 dB under the music's average level
    r_song = np.sqrt(np.mean(song ** 2)) or 1e-3
    r_sfx = np.sqrt(np.mean(sfx[np.abs(sfx).max(1) > 1e-4] ** 2)) if np.any(np.abs(sfx) > 1e-4) else 1
    mix = song + sfx * (r_song * 0.32 / r_sfx)

    fade = np.clip((D - np.arange(N) / SR) / 0.6, 0, 1)  # follow the picture fade
    mix *= fade[:, None]
    peak = np.max(np.abs(mix)) or 1
    if peak > 0.98:
        mix = np.tanh(mix / peak * 1.2) / np.tanh(1.2) * 0.97
    with wave.open(out, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())
    print(f'✔ mix {out} ({D:.2f}s, {len(data["cues"])} cues)')


if __name__ == '__main__':
    main()
