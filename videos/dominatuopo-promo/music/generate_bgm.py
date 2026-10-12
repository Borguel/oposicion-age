"""Genera la música de fondo del promo (pista original, sintetizada, sin derechos de terceros).

120 BPM (1 beat = 0.5 s, 1 compás = 2 s) para que los cortes del vídeo (6, 14, 20, 26 y 31 s)
caigan en beats. Progresión Am - F - C - G. Secciones:

    0-6   tensión: pad oscuro + latido suave + riser
    6-14  entra el groove (bombo 4x4, hats, bajo, arpegio)
    14-20 energía máxima (clap, arpegio doble octava)
    20-26 groove sostenido (hats a 16avos)
    26-31 oferta: sube hacia el final
    31-35 cierre: impacto, acorde final que decae

Uso: python generate_bgm.py <salida.mp3>
"""
import subprocess
import sys

import numpy as np
import soundfile as sf
from scipy import signal

SR = 44100
DUR = 35.0
BPM = 120
BEAT = 60.0 / BPM
N = int(SR * DUR)
rng = np.random.default_rng(7)  # determinista


def t_arr(n):
    return np.arange(n) / SR


def midi(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def lowpass(x, fc, order=2):
    b, a = signal.butter(order, fc / (SR / 2), "low")
    return signal.lfilter(b, a, x)


def highpass(x, fc, order=2):
    b, a = signal.butter(order, fc / (SR / 2), "high")
    return signal.lfilter(b, a, x)


def bandpass(x, lo, hi, order=2):
    b, a = signal.butter(order, [lo / (SR / 2), hi / (SR / 2)], "band")
    return signal.lfilter(b, a, x)


def add(buf, start, sig, gain=1.0):
    i = int(start * SR)
    if i >= len(buf):
        return
    j = min(len(buf), i + len(sig))
    buf[i:j] += sig[: j - i] * gain


def saw(f, n, detune=(0.0,)):
    t = t_arr(n)
    out = np.zeros(n)
    for d in detune:
        out += signal.sawtooth(2 * np.pi * f * (1 + d) * t)
    return out / len(detune)


# ---------- instrumentos ----------
def kick(vol=1.0):
    n = int(SR * 0.45)
    t = t_arr(n)
    f = 45 + 110 * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-t * 7.5)
    click = np.exp(-t * 400) * 0.35
    return (x + click) * vol


def hat(vol=1.0, open_=False):
    n = int(SR * (0.22 if open_ else 0.06))
    t = t_arr(n)
    x = highpass(rng.standard_normal(n), 7000) * np.exp(-t * (18 if open_ else 70))
    return x * vol * 0.5


def clap(vol=1.0):
    n = int(SR * 0.28)
    t = t_arr(n)
    base = bandpass(rng.standard_normal(n), 900, 3800)
    env = np.exp(-t * 18)
    for off in (0.0, 0.011, 0.022):
        env += 0.8 * np.exp(-np.maximum(t - off, 0) * 60) * (t >= off) * 0.6
    return base * env * vol * 0.5


def bass(f, dur, vol=1.0):
    n = int(SR * dur)
    t = t_arr(n)
    x = np.sin(2 * np.pi * f * t) + 0.5 * signal.square(2 * np.pi * f * t) * 0.35
    x = lowpass(x, 420)
    env = np.minimum(1, t / 0.005) * np.exp(-t * 3.0)
    return x * env * vol


def pluck(f, dur=0.34, vol=1.0, bright=3200):
    n = int(SR * dur)
    t = t_arr(n)
    x = saw(f, n, (-0.004, 0.0, 0.004))
    x = lowpass(x, bright)
    env = np.minimum(1, t / 0.003) * np.exp(-t * 11)
    return x * env * vol


def pad(freqs, dur, vol=1.0, bright=1400):
    n = int(SR * dur)
    t = t_arr(n)
    x = np.zeros(n)
    for f in freqs:
        x += saw(f, n, (-0.006, 0.0, 0.006))
    x = lowpass(x / len(freqs), bright)
    att = np.minimum(1, t / 0.4)
    rel = np.minimum(1, (dur - t) / 0.5)
    return x * att * rel * vol


def riser(dur, vol=1.0):
    n = int(SR * dur)
    t = t_arr(n)
    x = rng.standard_normal(n)
    # barrido de filtro por bloques
    out = np.zeros(n)
    block = 2048
    for i in range(0, n, block):
        frac = i / n
        fc = 300 + 9000 * frac ** 2
        seg = x[i : i + block]
        b, a = signal.butter(2, min(fc, 18000) / (SR / 2), "low")
        out[i : i + block] = signal.lfilter(b, a, seg)
    out = highpass(out, 250)
    return out * (t / dur) ** 2 * vol * 0.6


def impact(vol=1.0, dur=1.6):
    n = int(SR * dur)
    t = t_arr(n)
    boom = np.sin(2 * np.pi * (38 + 60 * np.exp(-t * 9)) * t) * np.exp(-t * 3.2)
    wash = highpass(lowpass(rng.standard_normal(n), 9000), 400) * np.exp(-t * 3.5) * 0.35
    return (boom + wash) * vol


def sidechain(n, hits, depth=0.65, rel=0.28):
    g = np.ones(n)
    for h in hits:
        i = int(h * SR)
        m = int(rel * SR)
        if i >= n:
            continue
        seg = np.arange(min(m, n - i)) / m
        g[i : i + len(seg)] = np.minimum(g[i : i + len(seg)], 1 - depth * (1 - seg ** 1.5))
    return g


# ---------- partitura ----------
BARS = {
    0: dict(root=45, tones=[57, 60, 64]),  # Am
    1: dict(root=41, tones=[57, 60, 65]),  # F
    2: dict(root=48, tones=[55, 60, 64]),  # C
    3: dict(root=43, tones=[55, 59, 62]),  # G
}
CUTS = [6, 14, 20, 26, 31]


def chord_at(t):
    return BARS[int(t // (2 * BEAT)) % 4]


def section(t):
    if t < 6:
        return 0
    if t < 14:
        return 1
    if t < 20:
        return 2
    if t < 26:
        return 3
    if t < 31:
        return 4
    return 5


drums = np.zeros(N)
kick_bus = np.zeros(N)
bass_bus = np.zeros(N)
arp_bus = np.zeros(N)
pad_bus = np.zeros(N)
fx_bus = np.zeros(N)

kick_times = []
step = BEAT / 2  # corcheas
nsteps = int(DUR / step)

# kicks / hats / clap / bajo / arpegio por paso
for s in range(nsteps):
    t = s * step
    sec = section(t)
    beat_pos = (t / BEAT) % 4  # 0..4
    on_beat = abs(beat_pos - round(beat_pos)) < 1e-6
    bi = int(round(beat_pos)) % 4 if on_beat else None
    chord = chord_at(t)

    if sec == 0:
        # latido suave desde el segundo 2, en beats 1 y 3
        if t >= 2 and on_beat and bi in (0, 2):
            add(kick_bus, t, kick(0.55)); kick_times.append(t)
    elif sec in (1, 2, 3, 4):
        if on_beat:
            add(kick_bus, t, kick(1.0)); kick_times.append(t)
            if sec >= 2 and bi in (1, 3):
                add(drums, t, clap(0.9 if sec == 2 else 0.7))
        else:
            add(drums, t, hat(0.9))  # contratiempo
        if sec in (2, 3) and on_beat:
            add(drums, t, hat(0.5))
        # bajo a corcheas sincopadas
        if sec >= 1 and (s % 2 == 0 or (s % 4 == 3)):
            f = midi(chord["root"] + (12 if (s % 8) in (3, 7) else 0))
            add(bass_bus, t, bass(f, step * 1.8, 0.9 if sec != 4 else 0.8))
        # arpegio
        idx = [0, 1, 2, 0, 2, 1, 2, 1][s % 8]
        note = chord["tones"][idx % 3] + (12 if (s % 8) in (3,) else 0)
        gain = {1: 0.30, 2: 0.42, 3: 0.34, 4: 0.40}[sec]
        add(arp_bus, t, pluck(midi(note + 12), 0.34, gain))
        if sec == 2:
            add(arp_bus, t, pluck(midi(note + 24), 0.22, gain * 0.35, 5000))
    elif sec == 5:
        if t < 33 and on_beat:
            add(kick_bus, t, kick(0.9)); kick_times.append(t)

# pads por compás
for bar in range(int(DUR / (2 * BEAT)) + 1):
    t0 = bar * 2 * BEAT
    if t0 >= DUR:
        break
    chord = chord_at(t0)
    sec = section(t0)
    freqs = [midi(n) for n in chord["tones"]] + [midi(chord["root"] + 12)]
    vol = {0: 0.16, 1: 0.20, 2: 0.24, 3: 0.20, 4: 0.22, 5: 0.26}[sec]
    bright = 700 if sec == 0 else 1600
    add(pad_bus, t0, pad(freqs, 2 * BEAT + 0.25, vol, bright))

# riser + impactos en los cortes
for c in CUTS:
    rlen = 2.0 if c in (6, 31) else 1.0
    add(fx_bus, c - rlen, riser(rlen, 0.8 if c in (6, 31) else 0.5))
    add(fx_bus, c, impact(0.8 if c in (6, 31) else 0.5))

# acorde final (stabs) y cola
final = [midi(n) for n in (57, 60, 64, 69)]
for off in (0.0, 0.5, 1.0):
    add(arp_bus, 31 + off, pad(final, 1.2, 0.30, 3000))
add(pad_bus, 31, pad([midi(n) for n in (45, 57, 60, 64, 69)], 4.0, 0.34, 1800))
add(kick_bus, 33.0, kick(0.9)); kick_times.append(33.0)

# ---------- mezcla ----------
sc = sidechain(N, kick_times)
mix = (
    kick_bus * 1.0
    + drums * 0.8
    + bass_bus * 0.85 * sc
    + arp_bus * 0.9 * (0.55 + 0.45 * sc)
    + pad_bus * 0.9 * sc
    + fx_bus * 0.9
)
# pequeño reverb sintético (cola corta) sobre arpegio+pad
tail = rng.standard_normal(int(SR * 0.45)) * np.exp(-t_arr(int(SR * 0.45)) * 7)
tail = lowpass(tail, 5000)
wet = signal.fftconvolve(arp_bus * 0.9 + pad_bus * 0.5, tail)[:N] * 0.06
mix = mix + wet

# estéreo: decorrelación ligera del arpegio/hats
delay = int(0.011 * SR)
L = mix.copy()
R = mix.copy()
R[delay:] += arp_bus[:-delay] * 0.25
L[delay * 2 :] += pad_bus[: -delay * 2] * 0.15

# fundidos y limitador suave
fade_in = np.minimum(1, t_arr(N) / 0.25)
fade_out = np.minimum(1, (DUR - t_arr(N)) / 1.6)
L *= fade_in * fade_out
R *= fade_in * fade_out
stereo = np.stack([L, R], axis=1)
peak = np.max(np.abs(stereo))
stereo = np.tanh(stereo / peak * 1.4) / np.tanh(1.4) * 0.89  # ~ -1 dBFS

out = sys.argv[1] if len(sys.argv) > 1 else "bgm.mp3"
wav = out.rsplit(".", 1)[0] + ".wav"
sf.write(wav, stereo.astype(np.float32), SR, subtype="PCM_16")
subprocess.run(
    ["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-codec:a", "libmp3lame", "-b:a", "192k", out],
    check=True,
)
print(f"ok: {out}  ({DUR}s, {BPM} BPM)")
