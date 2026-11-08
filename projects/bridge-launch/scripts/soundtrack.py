#!/usr/bin/env python3
"""
Procedural soundtrack for the motion piece (numpy only, no samples needed).

    python3 scripts/soundtrack.py build/cues.json build/soundtrack.wav \
        [--rec-audio build/rec-audio.wav --rec-offset 7.0]

Music: a 100 BPM pad / bass / arp / drums bed whose downbeat lands on the title
impact. SFX: whooshes, riser, impact, pops, typing ticks, tap, chime and shine,
placed at the cue times the HTML timeline exported (build/cues.json).
"""
import argparse
import json
import math
import wave

import numpy as np

SR = 48000
rng = np.random.default_rng(7)


def midi(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def t_axis(dur):
    return np.arange(int(dur * SR)) / SR


def env_adsr(n, a, d, s, r, sustain_len=None):
    a, d, r = int(a * SR), int(d * SR), int(r * SR)
    sus = n - a - d - r if sustain_len is None else int(sustain_len * SR)
    sus = max(0, sus)
    e = np.concatenate([np.linspace(0, 1, a, endpoint=False) if a else [],
                        np.linspace(1, s, d, endpoint=False) if d else [],
                        np.full(sus, s),
                        np.linspace(s, 0, r) if r else []])
    out = np.zeros(n)
    out[:min(n, len(e))] = e[:n]
    return out


def onepole_lp(x, cutoff):
    """Time-varying one-pole low-pass. cutoff: scalar or per-sample array (Hz)."""
    cutoff = np.broadcast_to(np.asarray(cutoff, dtype=float), x.shape)
    a = 1 - np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    z = 0.0
    for i in range(len(x)):
        z += a[i] * (x[i] - z)
        y[i] = z
    return y


def svf_bp(x, cutoff, q=0.7):
    """Time-varying state-variable band-pass."""
    cutoff = np.broadcast_to(np.asarray(cutoff, dtype=float), x.shape)
    f = 2 * np.sin(np.pi * np.minimum(cutoff, SR / 6) / SR)
    damp = 1 / q
    low = band = 0.0
    y = np.empty_like(x)
    for i in range(len(x)):
        low += f[i] * band
        high = x[i] - low - damp * band
        band += f[i] * high
        y[i] = band
    return y


def pan_stereo(mono, pan):
    """pan: scalar or per-sample array in [-1, 1] (equal power)."""
    pan = np.broadcast_to(np.asarray(pan, dtype=float), mono.shape)
    ang = (pan + 1) * np.pi / 4
    return np.stack([mono * np.cos(ang), mono * np.sin(ang)], axis=1)


class Bus:
    def __init__(self, n):
        self.x = np.zeros((n, 2))

    def add(self, sig, t, gain=1.0):
        if sig.ndim == 1:
            sig = np.stack([sig, sig], axis=1)
        i = int(round(t * SR))
        if i < 0:
            sig, i = sig[-i:], 0
        j = min(len(self.x), i + len(sig))
        if j > i:
            self.x[i:j] += sig[: j - i] * gain


# ---------------------------------------------------------------- instruments

def pad_voice(freq, dur, detune_cents=7):
    t = t_axis(dur)
    out = np.zeros((len(t), 2))
    for ch, sgn in ((0, -1), (1, 1)):
        f = freq * 2 ** (sgn * detune_cents / 1200)
        v = np.zeros(len(t))
        for k in range(1, 9):
            v += np.sin(2 * np.pi * f * k * t + k * 0.7 + ch) / k ** 1.6
        out[:, ch] = v
    return out


def pluck(freq, dur=0.5, bright=1.0):
    t = t_axis(dur)
    v = np.zeros(len(t))
    for k in range(1, 6):
        v += np.sin(2 * np.pi * freq * k * t) * np.exp(-t * (6 + 9 * k / bright)) / k
    return v * np.minimum(1, t * 400)


def kick():
    t = t_axis(0.45)
    f = 46 + 95 * np.exp(-t / 0.035)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t / 0.16)
    click = rng.standard_normal(len(t)) * np.exp(-t / 0.003) * 0.25
    return np.tanh(1.6 * (body + click))


def snare():
    t = t_axis(0.3)
    noise = svf_bp(rng.standard_normal(len(t)), 3200, 0.8) * np.exp(-t / 0.07)
    body = np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.05)
    return 0.6 * noise + 0.5 * body


def hat(open_=False):
    t = t_axis(0.25 if open_ else 0.06)
    n = rng.standard_normal(len(t))
    n = n - onepole_lp(n, 7000)
    return n * np.exp(-t / (0.06 if open_ else 0.012))


def bass(freq, dur):
    t = t_axis(dur)
    v = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(2 * np.pi * 2 * freq * t)
    return np.tanh(1.3 * v) * env_adsr(len(t), 0.01, 0.15, 0.7, 0.12)


# ---------------------------------------------------------------- sfx

def whoosh(dur=0.75, lo=250, hi=5200, strength=1.0, pan_from=-0.6, pan_to=0.6):
    t = t_axis(dur)
    x = t / dur
    shape = np.sin(np.pi * np.clip(x, 0, 1)) ** 2.2
    cutoff = lo + (hi - lo) * np.sin(np.pi * np.clip(x * 0.9, 0, 1)) ** 1.5
    n = rng.standard_normal(len(t))
    b = svf_bp(n, cutoff, 1.2) * 0.9 + onepole_lp(n, cutoff * 0.5) * 0.6
    sig = b * shape * strength
    return pan_stereo(sig, np.linspace(pan_from, pan_to, len(t)))


def riser(dur):
    t = t_axis(dur)
    x = t / dur
    amp = x ** 2.4
    n = rng.standard_normal(len(t))
    noise = svf_bp(n, 600 + 7000 * x ** 1.6, 1.5)
    f = 180 * 2 ** (x * 2.6)
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.35
    tone2 = np.sin(2 * np.pi * np.cumsum(f * 1.5) / SR) * 0.2
    tail = np.minimum(1, (dur - t) / 0.02)
    sig = (noise * 0.8 + tone + tone2) * amp * tail
    return pan_stereo(sig, 0.35 * np.sin(2 * np.pi * 1.3 * t))


def impact(soft=False):
    t = t_axis(2.2)
    f = 34 + 70 * np.exp(-t / 0.06)
    boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / (0.45 if soft else 0.7))
    n = rng.standard_normal(len(t))
    crack = onepole_lp(n, 2500 if soft else 4500) * np.exp(-t / (0.05 if soft else 0.09))
    sig = np.tanh(1.8 * boom) * (0.7 if soft else 1.0) + crack * (0.35 if soft else 0.7)
    return sig


def pop(freq=880):
    t = t_axis(0.22)
    f = freq * (0.55 + 0.45 * np.exp(-t / 0.025))
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.05)
    return s * np.minimum(1, t * 2000)


def tick(freq=2600):
    t = t_axis(0.05)
    return np.sin(2 * np.pi * freq * t) * np.exp(-t / 0.008)


def type_click(i):
    t = t_axis(0.04)
    n = rng.standard_normal(len(t))
    hp = n - onepole_lp(n, 2500)
    f = 2100 + 260 * ((i * 37) % 5)
    return (hp * 0.5 + np.sin(2 * np.pi * f * t) * 0.6) * np.exp(-t / 0.006)


def tap():
    t = t_axis(0.2)
    thump = np.sin(2 * np.pi * (120 + 80 * np.exp(-t / 0.01)) * t) * np.exp(-t / 0.045)
    click = tick(3200)
    out = thump * 0.9
    out[: len(click)] += click * 0.5
    return out


def bell(freq, dur=1.8):
    t = t_axis(dur)
    parts = [(1, 1.0, 1.4), (2.0, 0.35, 0.8), (2.76, 0.3, 0.5), (5.4, 0.12, 0.25)]
    s = sum(a * np.sin(2 * np.pi * freq * r * t) * np.exp(-t / d) for r, a, d in parts)
    return s * np.minimum(1, t * 800)


def shine():
    t = t_axis(1.0)
    x = t / 1.0
    n = svf_bp(rng.standard_normal(len(t)), 5000 + 6000 * x, 2.0) * np.sin(np.pi * x) ** 2 * 0.5
    out = pan_stereo(n, np.linspace(-0.7, 0.7, len(t)))
    for k, m in enumerate((96, 100, 103, 108)):
        b = bell(midi(m), 0.9) * 0.18
        st = int((0.18 + k * 0.09) * SR)
        e = min(len(out), st + len(b))
        out[st:e] += pan_stereo(b[: e - st], -0.5 + k * 0.33)
    return out


# ---------------------------------------------------------------- reverb

def reverb(x, seconds=2.4, mix=1.0):
    n_ir = int(seconds * SR)
    t = np.arange(n_ir) / SR
    out = np.zeros_like(x)
    for ch in range(2):
        ir = rng.standard_normal(n_ir) * np.exp(-t * 6.9 / seconds)
        ir = onepole_lp(ir, 5200)
        ir[: int(0.012 * SR)] = 0  # pre-delay
        ir /= np.sqrt(np.sum(ir ** 2))
        n = len(x[:, ch]) + n_ir
        N = 1 << (n - 1).bit_length()
        y = np.fft.irfft(np.fft.rfft(x[:, ch], N) * np.fft.rfft(ir, N), N)[: len(x)]
        out[:, ch] = y
    return out * mix


def compress(x, thresh_db=-26, ratio=3.0, win_ms=30, release_ms=180):
    """Gentle RMS compressor so a narration with loud and quiet words sits evenly in the mix."""
    mono = np.abs(x).max(axis=1)
    w = max(1, int(SR * win_ms / 1000))
    env = np.sqrt(np.convolve(mono ** 2, np.ones(w) / w, mode='same') + 1e-12)
    thr = 10 ** (thresh_db / 20)
    gain = np.where(env > thr, (env / thr) ** (1 / ratio - 1), 1.0)
    r = max(1, int(SR * release_ms / 1000))
    gain = np.minimum(gain, np.convolve(gain, np.ones(r) / r, mode='same'))  # fast attack, smooth release
    return x * gain[:, None]


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cues')
    ap.add_argument('out')
    ap.add_argument('--rec-audio')
    ap.add_argument('--rec-offset', type=float, default=0)
    a = ap.parse_args()

    data = json.load(open(a.cues))
    cues = data['cues']
    D = data['duration']
    N = int((D + 0.6) * SR)
    get = lambda typ: [c for c in cues if c['type'] == typ]
    drop = get('drop')[0]['t'] if get('drop') else 3.6
    soft = get('impact_soft')[0]['t'] if get('impact_soft') else D - 3.5

    music, drums, sfx, send = Bus(N), Bus(N), Bus(N), Bus(N)

    # ---- music bed: 100 BPM, downbeat on the title impact ----
    beat = 0.6
    bar = beat * 4
    prog = [  # (bass midi, pad voicing)
        (41, [57, 60, 64, 67]),   # Fmaj9
        (45, [55, 60, 64, 69]),   # Am7
        (48, [55, 59, 64, 67]),   # Cmaj7
        (43, [55, 59, 62, 64]),   # G6
    ]
    first_bar = math.floor((0 - drop) / bar) - 1
    last_bar = math.ceil((D - drop) / bar) + 1
    end_music = soft + 2 * bar           # final chord rings out after the outro hit
    for b in range(first_bar, last_bar):
        t0 = drop + b * bar
        if t0 > end_music:
            break
        bass_m, voicing = prog[b % 4]
        if t0 >= soft:  # resolve to Fmaj9 for the outro and hold
            bass_m, voicing = prog[0]
        length = (bar * 2.2) if t0 >= soft else bar + 0.9
        for m in voicing:
            v = pad_voice(midi(m), length)
            v *= env_adsr(len(v), 0.35, 0.4, 0.8, 0.9)[:, None]
            music.add(v * 0.05, max(0, t0 - 0.05))
        if t0 >= drop - 0.01 and t0 < soft:
            for k in range(4):  # bass: root on every beat, octave pop on the "and" of 4
                music.add(bass(midi(bass_m), beat * 0.9) * 0.22, t0 + k * beat)
            music.add(bass(midi(bass_m + 12), beat * 0.4) * 0.08, t0 + 3.5 * beat)
            arp = sorted(voicing)
            pat = [0, 2, 1, 3, 2, 1, 3, 2]
            for k, p in enumerate(pat):
                pl = pluck(midi(arp[p] + 12), 0.45) * 0.05
                music.add(pan_stereo(pl, -0.4 if k % 2 else 0.4), t0 + k * beat / 2)
        if t0 >= soft and t0 < soft + bar:
            for k, m in enumerate(sorted(voicing)):
                music.add(pan_stereo(pluck(midi(m + 12), 1.4, 0.6) * 0.07, -0.3 + 0.2 * k), t0 + 0.08 * k)
            music.add(bass(midi(bass_m), bar * 1.6) * 0.22, t0)

    # pre-drop: soft filtered pulse so the hook isn't silent
    for k in range(int(drop / (beat / 2))):
        tt = k * beat / 2
        music.add(pan_stereo(pluck(midi(81 if k % 4 else 76), 0.3, 0.5) * 0.025, 0.3 if k % 2 else -0.3), tt)

    # drums from the drop until the outro hit
    K, S, HC, HO = kick(), snare(), hat(), hat(True)
    kick_times = []
    tt = drop
    while tt < soft - 0.01:
        rel = round((tt - drop) / beat) % 4
        if rel in (0, 2):
            drums.add(K * 0.55, tt)
            kick_times.append(tt)
        if rel in (1, 3):
            drums.add(S * 0.18, tt)
        drums.add(HC * 0.10, tt + beat / 2)
        if rel == 3:
            drums.add(HO * 0.06, tt + beat * 0.75)
        tt += beat
    drums.add(K * 0.6, soft)
    kick_times.append(soft)

    # sidechain pump on the music bus
    t = np.arange(N) / SR
    duck = np.ones(N)
    for kt in kick_times:
        i = int(kt * SR)
        seg = t[i:] - kt
        n = min(len(seg), int(0.45 * SR))
        duck[i:i + n] = np.minimum(duck[i:i + n], 1 - 0.45 * np.exp(-seg[:n] / 0.11))
    music.x *= duck[:, None]

    # global music envelope: fade in, fade out with the picture
    fade = np.clip(t / 1.2, 0, 1) * np.clip((D + 0.4 - t) / 1.6, 0, 1)
    music.x *= fade[:, None]
    drums.x *= fade[:, None]

    # ---- sfx ----
    type_i = 0
    for c in cues:
        typ, tc, pan = c['type'], c['t'], c.get('pan', 0)
        if typ == 'swish':
            s = whoosh(0.45, 1500, 7500, 0.35, pan - 0.3, pan + 0.3)
            sfx.add(s, tc - 0.12)
        elif typ == 'whoosh':
            s = whoosh(0.8, 250, 5200, 0.9, pan - 0.7, pan + 0.7)
            sfx.add(s, tc - 0.3)
            send.add(s * 0.3, tc - 0.3)
        elif typ == 'whoosh_big':
            s = whoosh(1.1, 120, 4200, 1.2, pan - 0.5, pan + 0.6)
            sfx.add(s, tc - 0.35)
            send.add(s * 0.35, tc - 0.35)
        elif typ == 'riser':
            s = riser(c['end'] - tc)
            sfx.add(s * 0.5, tc)
            send.add(s * 0.25, tc)
        elif typ in ('impact', 'impact_soft'):
            s = impact(typ == 'impact_soft')
            sfx.add(s * (0.55 if typ == 'impact_soft' else 0.9), tc)
            send.add(s * 0.5, tc)
        elif typ == 'pop':
            s = pan_stereo(pop(880 if pan <= 0 else 990), pan)
            sfx.add(s * 0.35, tc)
            send.add(s * 0.15, tc)
        elif typ == 'tick':
            sfx.add(pan_stereo(tick(), pan) * 0.25, tc)
        elif typ == 'type':
            sfx.add(pan_stereo(type_click(type_i), 0.15) * 0.22, tc)
            type_i += 1
        elif typ == 'tap':
            sfx.add(tap() * 0.5, tc)
        elif typ == 'chime':
            for k, m in enumerate((88, 95, 100)):
                b = bell(midi(m)) * (0.16 - 0.03 * k)
                sfx.add(pan_stereo(b, -0.3 + 0.3 * k), tc + 0.09 * k)
                send.add(pan_stereo(b, 0) * 0.4, tc + 0.09 * k)
        elif typ == 'shine':
            s = shine()
            sfx.add(s * 0.6, tc)
            send.add(s * 0.3, tc)

    # ---- narration from the screen recording: it leads, the music ducks under it ----
    voice = None
    if a.rec_audio:
        with wave.open(a.rec_audio) as w:
            raw = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float) / 32768
            raw = raw.reshape(-1, w.getnchannels())
            if raw.shape[1] == 1:
                raw = np.repeat(raw, 2, axis=1)
        voice = Bus(N)
        voice.add(raw[:, :2], a.rec_offset)
        # speech-presence envelope (200 ms windows, smoothed) drives the ducking
        lvl = np.abs(voice.x).max(axis=1)
        win = SR // 5
        k = np.convolve((lvl > 0.02).astype(float), np.ones(win) / win, mode='same')
        k = np.convolve(np.clip(k * 3, 0, 1), np.ones(win) / win, mode='same')
        music.x *= (1 - 0.72 * k)[:, None]
        drums.x *= (1 - 0.85 * k)[:, None]
        voice.x = compress(voice.x)

    wet = reverb(send.x + music.x * 0.25, 2.6)

    mix = music.x * 1.0 + drums.x * 0.9 + sfx.x * 1.0 + wet * 0.45
    if voice is not None:
        # the narration leads: its speaking level sits ~2 dB above the music-only intro
        active = k > 0.5
        intro = mix[: max(SR, int(a.rec_offset * SR))]
        r_bed = np.sqrt(np.mean(intro ** 2)) or 1e-3
        r_voice = np.sqrt(np.mean(voice.x[active] ** 2)) if active.any() else 1
        mix = mix + voice.x * (r_bed * 1.26 / r_voice)

    peak = np.max(np.abs(mix)) or 1
    mix = np.tanh(mix / peak * 1.3) / np.tanh(1.3) * 0.89

    pcm = (np.clip(mix, -1, 1) * 32767).astype(np.int16)
    with wave.open(a.out, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f'✔ soundtrack {a.out}  ({D:.2f}s, {len(cues)} cues)')


if __name__ == '__main__':
    main()
