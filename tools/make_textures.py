"""Texture beds for Brickglide Play: unpitched room sounds made from noise, 10 s
each, mono 22.05 kHz 16-bit. Run from the repo root: python3 tools/make_textures.py"""
import os
import wave

import numpy as np

SR = 22050
OUT = os.path.join(os.path.dirname(__file__), "..", "brickchord", "samples", "textures")
rng = np.random.RandomState(7)
N = SR * 10


def onepole(x, cutoff):
    """A one-pole low-pass (no SciPy needed)."""
    a = 1 - np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty(len(x))
    acc = 0.0
    xs = x.tolist()
    for i, v in enumerate(xs):
        acc += a * (v - acc)
        y[i] = acc
    return y


def save(name, x):
    x = x / (np.abs(x).max() + 1e-9) * 0.8
    os.makedirs(OUT, exist_ok=True)
    w = wave.open(os.path.join(OUT, name + ".wav"), "wb")
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((x * 32767).astype("<i2").tobytes()); w.close()


noise = rng.randn(N)
# Rain: a soft wash plus many small drops
wash = onepole(noise, 2500) - 0.6 * onepole(noise, 300)
drops = np.zeros(N)
for _ in range(1400):
    p = rng.randint(0, N - 400)
    f = rng.uniform(1800, 5200)
    t = np.arange(300) / SR
    drops[p:p + 300] += np.sin(2 * np.pi * f * t) * np.exp(-t * rng.uniform(60, 140)) * rng.uniform(0.05, 0.35)
save("Rain", 0.8 * wash + drops)
# Vinyl: low hiss and crackle
hiss = onepole(rng.randn(N), 6000) * 0.25
crk = np.zeros(N)
for _ in range(900):
    p = rng.randint(0, N - 40)
    crk[p:p + rng.randint(2, 30)] += rng.uniform(-1, 1) * rng.uniform(0.2, 1.0)
save("Vinyl", hiss + onepole(crk, 4000) + 0.15 * np.sin(2 * np.pi * 0.555 * np.arange(N) / SR) * onepole(rng.randn(N), 80))
# Wind: band of noise whose brightness and level swell slowly
t = np.arange(N) / SR
lfo = 0.5 + 0.5 * np.sin(2 * np.pi * 0.07 * t) * np.sin(2 * np.pi * 0.031 * t + 1)
w1 = onepole(rng.randn(N), 900) - onepole(rng.randn(N), 120) * 0.3
w2 = onepole(rng.randn(N), 2200)
save("Wind", w1 * (0.4 + 0.6 * lfo) + w2 * 0.35 * lfo ** 2)
# Tape: hiss with a slow flutter
save("Tape Hiss", onepole(rng.randn(N), 9000) * (1 + 0.15 * np.sin(2 * np.pi * 4.3 * t)) - 0.7 * onepole(rng.randn(N), 400))
# Brook: bubbling water, many quick resonant blips
brook = onepole(rng.randn(N), 1200) * 0.4
for _ in range(2600):
    p = rng.randint(0, N - 600)
    f0 = rng.uniform(400, 1400)
    tt = np.arange(500) / SR
    brook[p:p + 500] += np.sin(2 * np.pi * (f0 + 900 * tt * 20) * tt) * np.exp(-tt * 45) * rng.uniform(0.05, 0.25)
save("Brook", brook)
print("textures written to", os.path.abspath(OUT))
