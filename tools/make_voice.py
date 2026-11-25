# Brickchop's robot voice: "brick chop" by formant synthesis (a buzz through three
# moving vocal-tract resonances, plus noise bursts for k, ch and p). No speech
# engine, so the result is ours to ship. Writes brickchord/voice/brickchop_*.wav.
# Usage: python3 tools/make_voice.py   (NumPy + SciPy, runs on a computer, not the Brick)
import numpy as np
from scipy.signal import lfilter, butter, sosfilt
import wave, sys

SR = 44100
rng = np.random.default_rng(7)

# phoneme targets: (F1, F2, F3) and bandwidths
V = {
    "r": (420, 1250, 1650),
    "I": (420, 1950, 2600),
    "A": (760, 1150, 2550),
    "l": (360, 1050, 2700),
    "ae": (680, 1720, 2420),
}

def resonate(x, f, bw):
    """time-varying 2-pole resonator; f and bw arrays per sample"""
    y = np.zeros_like(x)
    y1 = y2 = 0.0
    r = np.exp(-np.pi * bw / SR)
    c1 = 2 * r * np.cos(2 * np.pi * f / SR)
    c2 = -r * r
    g = 1 - r
    for n in range(len(x)):
        v = g[n] * x[n] + c1[n] * y1 + c2[n] * y2
        y2, y1 = y1, v
        y[n] = v
    return y

def env(points, n):
    """piecewise-linear envelope from [(t_seconds, value), ...]"""
    t = np.arange(n) / SR
    ts, vs = zip(*points)
    return np.interp(t, ts, vs)

def bandnoise(n, lo, hi):
    sos = butter(4, [lo, hi], btype="band", fs=SR, output="sos")
    return sosfilt(sos, rng.standard_normal(n))

def voice(f0=100.0, speed=1.0, buzz="saw"):
    s = lambda t: t / speed
    # timeline (seconds): b r I k | gap | tS A p
    tb, tr, tI, tk = s(0.00), s(0.03), s(0.09), s(0.22)
    tkrel = s(0.28)
    tch = s(0.36)            # ch frication starts
    tA = s(0.46)
    tAend = s(0.74)
    tp = s(0.80)
    T = s(0.95)
    n = int(T * SR)
    t = np.arange(n) / SR
    # pitch: robotic monotone with a tiny step down on "chop"
    f = np.where(t < tch, f0, f0 * 0.89)
    ph = np.cumsum(f / SR)
    if buzz == "saw":
        src = 2 * (ph % 1.0) - 1
    else:
        src = np.where((ph % 1.0) < 0.3, 1.0, -0.43)
    src = src - lfilter([1], [1, -0.995], src) * 0.002          # keep DC away
    # formant tracks
    F = {}
    for k in range(3):
        F[k] = env([(tb, V["r"][k] * (0.6 if k == 0 else 0.85)), (tr, V["r"][k]), (tI - s(0.01), V["r"][k]),
                    (tI + s(0.03), V["I"][k]), (tk, V["I"][k]), (tk + s(0.02), V["I"][k] * (1.0 if k else 0.7)),
                    (tch, V["A"][k]), (tA, V["A"][k]), (tAend, V["A"][k]),
                    (tp, V["A"][k] * (0.7 if k < 2 else 1.0)), (T, V["A"][k] * 0.7)], n)
    bws = (70, 110, 160)
    # voicing amplitude: b-onset, r, I, closure for k, ch (unvoiced), A, closure for p
    av = env([(0, 0), (tb + s(0.005), 0.25), (tr, 0.7), (tI, 1.0), (tk - s(0.01), 0.9), (tk, 0.0),
              (tA - s(0.015), 0.0), (tA + s(0.01), 1.0), (tAend, 0.95), (tp - s(0.01), 0.6), (tp, 0.0), (T, 0)], n)
    vo = sum(resonate(src * av, F[k], np.full(n, bws[k])) * (1.0, 0.7, 0.45)[k] for k in range(3))
    out = vo
    # k burst + aspiration
    kb = env([(0, 0), (tkrel, 0), (tkrel + s(0.003), 1.0), (tkrel + s(0.05), 0.15), (tkrel + s(0.07), 0), (T, 0)], n)
    out = out + bandnoise(n, 1500, 3500) * kb * 0.35
    # ch: short t-burst then sh frication
    chb = env([(0, 0), (tch, 0), (tch + s(0.004), 1.0), (tch + s(0.02), 0.6), (tch + s(0.08), 0.8),
               (tA, 0.15), (tA + s(0.02), 0), (T, 0)], n)
    out = out + bandnoise(n, 2200, 7000) * chb * 0.28
    # p release
    pr = tp + s(0.06)
    pb = env([(0, 0), (pr, 0), (pr + s(0.003), 1.0), (pr + s(0.04), 0.1), (pr + s(0.06), 0), (T, 0)], n)
    out = out + bandnoise(n, 400, 2000) * pb * 0.3
    return out

def voice_lab(f0=100.0, speed=1.0, buzz="saw"):
    """ "brick lab": the same "brick" as voice(), then an L gliding into a bright
    "a" (as in cat), closed by a voiced b."""
    s = lambda t: t / speed
    tb, tr, tI, tk = s(0.00), s(0.03), s(0.09), s(0.22)
    tkrel = s(0.28)
    tl = s(0.37)             # L starts (voiced, no gap)
    tae = s(0.45)
    taeend = s(0.70)
    tbc = s(0.74)            # b closure
    tbrel = s(0.80)
    T = s(0.92)
    n = int(T * SR)
    t = np.arange(n) / SR
    f = np.where(t < tl, f0, f0 * 1.06)          # "lab" a touch higher, a robot's question-free lift
    ph = np.cumsum(f / SR)
    src = 2 * (ph % 1.0) - 1 if buzz == "saw" else np.where((ph % 1.0) < 0.3, 1.0, -0.43)
    F = {}
    for k in range(3):
        F[k] = env([(tb, V["r"][k] * (0.6 if k == 0 else 0.85)), (tr, V["r"][k]), (tI - s(0.01), V["r"][k]),
                    (tI + s(0.03), V["I"][k]), (tk, V["I"][k]), (tk + s(0.02), V["I"][k] * (1.0 if k else 0.7)),
                    (tl, V["l"][k]), (tl + s(0.05), V["l"][k]), (tae, V["ae"][k]), (taeend, V["ae"][k]),
                    (tbc, V["ae"][k] * (0.55 if k < 2 else 0.9)), (T, V["ae"][k] * 0.5)], n)
    bws = (70, 110, 160)
    av = env([(0, 0), (tb + s(0.005), 0.25), (tr, 0.7), (tI, 1.0), (tk - s(0.01), 0.9), (tk, 0.0),
              (tl - s(0.01), 0.0), (tl + s(0.02), 0.55), (tl + s(0.06), 0.6), (tae, 1.0), (taeend, 0.95),
              (tbc, 0.5), (tbc + s(0.01), 0.12), (tbrel, 0.12), (tbrel + s(0.01), 0.45), (tbrel + s(0.06), 0.0), (T, 0)], n)
    vo = sum(resonate(src * av, F[k], np.full(n, bws[k])) * (1.0, 0.7, 0.45)[k] for k in range(3))
    kb = env([(0, 0), (tkrel, 0), (tkrel + s(0.003), 1.0), (tkrel + s(0.05), 0.15), (tkrel + s(0.07), 0), (T, 0)], n)
    out = vo + bandnoise(n, 1500, 3500) * kb * 0.35
    bb = env([(0, 0), (tbrel, 0), (tbrel + s(0.002), 1.0), (tbrel + s(0.025), 0.0), (T, 0)], n)
    return out + bandnoise(n, 300, 1600) * bb * 0.25


def robotize(x, crush_bits=0, ring=0.0, sr_hold=1):
    x = x / max(1e-6, np.abs(x).max())
    if ring:
        t = np.arange(len(x)) / SR
        x = x * (1 - ring + ring * np.sin(2 * np.pi * 35 * t))
    if sr_hold > 1:
        x = np.repeat(x[::sr_hold], sr_hold)[:len(x)]
    if crush_bits:
        q = 2 ** (crush_bits - 1)
        gate = np.abs(x) > 0.5 / q
        x = np.round(x * q) / q * gate
    return x

def norm(x, pk=0.89):
    x = x - x.mean()
    fade = int(0.004 * SR)
    x[:fade] *= np.linspace(0, 1, fade)
    x[-fade:] *= np.linspace(1, 0, fade)
    return x * (pk / max(1e-6, np.abs(x).max()))

def write(path, x):
    d = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(d.tobytes())

if __name__ == "__main__":
    import os
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "brickchord", "voice")
    takes = {
        "clean": norm(robotize(voice(100, 1.0), ring=0.15)),
        "robot": norm(robotize(voice(100, 1.0), crush_bits=8, ring=0.25)),
        "deep": norm(robotize(voice(62, 0.85), crush_bits=6, sr_hold=2)),
        "chip": norm(robotize(voice(220, 1.25, "pulse"), crush_bits=5, sr_hold=3)),
    }
    for k, x in takes.items():
        write("%s/brickchop_%s.wav" % (out, k), x)
    lab = {
        "clean": norm(robotize(voice_lab(100, 1.0), ring=0.15)),
        "robot": norm(robotize(voice_lab(100, 1.0), crush_bits=8, ring=0.25)),
        "deep": norm(robotize(voice_lab(62, 0.85), crush_bits=6, sr_hold=2)),
        "chip": norm(robotize(voice_lab(220, 1.25, "pulse"), crush_bits=5, sr_hold=3)),
        "announcer": norm(robotize(voice_lab(82, 0.7), ring=0.1)),
    }
    for k, x in lab.items():
        write("%s/bricklab_%s.wav" % (out, k), x)
    print("ok")
