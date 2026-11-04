# Renders Bricklab's built-in drum kits to WAV files in brickchord/kits/<kit>/<lane>.wav.
#
# The kits are designed here, on a computer, at 44.1 kHz with proper filters
# (Butterworth biquads, NumPy only, so it runs anywhere the app does), then
# resampled to the engine's 22.05 kHz through an anti-alias filter.
# The Brick just loads the WAVs, so better sound costs it nothing at runtime.
#
#   python3 tools/make_kits.py            # write the kits
#   python3 tools/make_kits.py --demo d   # also write demo beats to folder d
import os
import sys
import wave

import numpy as np

FS = 44100            # design rate
OUT_SR = 22050        # engine rate
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KITS = os.path.join(ROOT, "brickchord", "kits")
LANES = ["kick", "snare", "clap", "rim", "tom", "hat", "ohat", "shk"]


# ---------------------------------------------------------------- building blocks
def tt(sec):
    return np.arange(int(sec * FS)) / FS


def noise(n, seed):
    return np.random.default_rng(seed).standard_normal(n)


def env(t, decay, att=0.0005, hold=0.0):
    """Exponential decay with a short linear attack; decay is the time to -60 dB."""
    e = np.exp(-6.9 * np.maximum(t - hold, 0) / decay)
    if att:
        e *= np.minimum(t / att, 1.0)
    return e


def sweep(t, f_end, f_start, tau, tau2=None, mid=None):
    """Exponential pitch drop (a second slower stage if tau2 is given)."""
    f = f_end + (f_start - f_end) * np.exp(-t / tau)
    if tau2:
        f += (mid or 0) * np.exp(-t / tau2)
    return 2 * np.pi * np.cumsum(f) / FS


# Butterworth sections: (kind, f, q); a q of None is a first-order stage
_BW_Q = {1: [None], 2: [0.7071], 3: [None, 1.0], 4: [0.5412, 1.3066]}


def _biquad(x, b, a):
    b0, b1, b2 = (v / a[0] for v in b)
    a1, a2 = a[1] / a[0], a[2] / a[0]
    y = np.empty(len(x))
    x1 = x2 = y1 = y2 = 0.0
    for i, v in enumerate(x.tolist()):
        o = b0 * v + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1, y2, y1 = x1, v, y1, o
        y[i] = o
    return y


def _section(x, kind, f, q):
    w = 2 * np.pi * f / FS
    if q is None:                                  # first order (bilinear)
        k = np.tan(w / 2)
        if kind == "lp":
            b, a = [k, k, 0.0], [1 + k, k - 1, 0.0]
        else:
            b, a = [1.0, -1.0, 0.0], [1 + k, k - 1, 0.0]
        return _biquad(x, b, a)
    al, c = np.sin(w) / (2 * q), np.cos(w)
    if kind == "lp":
        b = [(1 - c) / 2, 1 - c, (1 - c) / 2]
    else:
        b = [(1 + c) / 2, -(1 + c), (1 + c) / 2]
    return _biquad(x, b, [1 + al, -2 * c, 1 - al])


def lp(x, f, order=2):
    for q in _BW_Q[order]:
        x = _section(x, "lp", f, q)
    return x


def hp(x, f, order=2):
    for q in _BW_Q[order]:
        x = _section(x, "hp", f, q)
    return x


def bp(x, lo, hi, order=2):
    return lp(hp(x, lo, order), hi, order)


def peak(x, f, q, gain_db):
    """One peaking EQ band (RBJ)."""
    a = 10 ** (gain_db / 40)
    w = 2 * np.pi * f / FS
    al = np.sin(w) / (2 * q)
    return _biquad(x, [1 + al * a, -2 * np.cos(w), 1 - al * a], [1 + al / a, -2 * np.cos(w), 1 - al / a])


def square(ph):
    return np.where(np.sin(ph) >= 0, 1.0, -1.0)


def convolve(x, h):
    n = len(x) + len(h) - 1
    m = 1 << (n - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(x, m) * np.fft.rfft(h, m), m)[:n]


def sat(x, drive=1.5):
    return np.tanh(x * drive) / np.tanh(drive)


def metal(t, freqs):
    """Square-wave bank (the 808/909 cymbal trick): six detuned squares."""
    return sum(square(2 * np.pi * f * t) for f in freqs) / len(freqs)


def room(x, size=0.18, mix=0.14, seed=7, tone=5000):
    """A small synthetic room: decaying filtered noise as an impulse response."""
    t = tt(size)
    ir = lp(noise(len(t), seed), tone) * env(t, size, att=0.002)
    ir[0] = 0
    ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
    wet = convolve(x, ir)[: len(x) + len(t)]
    out = np.zeros(len(wet))
    out[: len(x)] += x
    return out + wet * mix


def fin(x, sec=None, fade=0.006):
    if sec:
        x = x[: int(sec * FS)]
    n = min(len(x), int(fade * FS))
    x = x.copy()
    if n:
        x[-n:] *= np.linspace(1, 0, n) ** 2
    return x


# ---------------------------------------------------------------- kits
def kit_classic():
    """Modern, punchy, works for most styles."""
    k = {}
    t = tt(0.55)
    body = np.sin(sweep(t, 50, 170, 0.018, 0.09, 40)) * env(t, 0.48, att=0.0008)
    click = bp(noise(len(t), 1), 1800, 7000) * env(t, 0.012) * 0.35
    k["kick"] = fin(lp(sat(body * 1.2 + click, 1.8), 9000))
    t = tt(0.4)
    shell = (np.sin(sweep(t, 182, 230, 0.015)) * env(t, 0.16) + np.sin(sweep(t, 330, 380, 0.01)) * env(t, 0.09) * 0.5)
    wires = bp(noise(len(t), 2), 1500, 7500) * env(t, 0.24, att=0.001)
    crack = hp(noise(len(t), 3), 3000) * env(t, 0.01) * 0.5
    k["snare"] = fin(sat(shell * 1.0 + wires * 0.45 + crack, 1.4))
    k["clap"] = clap(seed=4, centre=(900, 2600), spacing=(0.0, 0.009, 0.019, 0.028), tail=0.22)
    t = tt(0.12)
    k["rim"] = fin((np.sin(2 * np.pi * 510 * t) * 0.6 + np.sin(2 * np.pi * 1680 * t) * 0.5 +
                    bp(noise(len(t), 5), 2000, 6000) * 0.5) * env(t, 0.05))
    k["tom"] = tom(t_len=0.7, f_end=98, f_start=150, decay=0.55, seed=6)
    k["hat"] = hat(0.09, seed=8)
    k["ohat"] = hat(0.55, seed=9, open_=True)
    k["shk"] = shaker(seed=10)
    return k


def clap(seed, centre=(1000, 2600), spacing=(0.0, 0.01, 0.02, 0.03), tail=0.2):
    t = tt(0.45)
    nz = bp(noise(len(t), seed), *centre)
    e = np.zeros(len(t))
    for i, d in enumerate(spacing):
        e += np.where(t >= d, np.exp(-(t - d) / 0.0035), 0) * (0.8 + 0.2 * i / len(spacing))
    last = spacing[-1]
    e += np.where(t >= last, np.exp(-6.9 * (t - last) / tail), 0) * 0.55
    return fin(sat(peak(nz * e, 1200, 1.2, 4), 1.4))


def tom(t_len, f_end, f_start, decay, seed):
    t = tt(t_len)
    a = np.sin(sweep(t, f_end, f_start, 0.04)) * env(t, decay)
    b = np.sin(sweep(t, f_end * 1.52, f_start * 1.5, 0.03)) * env(t, decay * 0.5) * 0.3
    stick = lp(noise(len(t), seed), 4000) * env(t, 0.015) * 0.25
    return fin(sat(a + b + stick, 1.2))


def hat(sec, seed, open_=False, freqs=(205.3, 304.4, 369.6, 522.7, 540.0, 800.0), tone=(6500, 10500)):
    t = tt(sec)
    m = metal(t, freqs)
    nz = noise(len(t), seed) * 0.35
    x = hp(bp(m + nz, *tone, order=3), 5500)
    e = env(t, sec * (0.9 if open_ else 0.55), att=0.0003)
    if not open_:
        e = e * 0.85 + env(t, 0.02) * 0.15     # the tick on top
    return fin(peak(x * e, 9000, 1.0, 3))


def shaker(seed):
    t = tt(0.14)
    nz = hp(bp(noise(len(t), seed), 4000, 10500), 3500)
    e = np.minimum(t / 0.018, 1.0) * env(t, 0.12, att=0) + np.where(t > 0.03, env(t - 0.03, 0.06, att=0.004), 0) * 0.35
    return fin(nz * e)


def kit_808():
    k = {}
    t = tt(1.4)
    boom = np.sin(sweep(t, 49, 120, 0.012, 0.06, 12)) * env(t, 1.2, att=0.001)
    k["kick"] = fin(lp(sat(boom * 1.15, 1.25), 4000))
    t = tt(0.32)
    tone = np.sin(sweep(t, 238, 250, 0.01)) * env(t, 0.13) + np.sin(sweep(t, 476, 490, 0.01)) * env(t, 0.08) * 0.5
    snap = hp(bp(noise(len(t), 11), 2500, 9000), 1500) * env(t, 0.2)
    k["snare"] = fin(tone * 0.7 + snap * 0.5)
    k["clap"] = clap(seed=12, centre=(850, 2300), spacing=(0.0, 0.011, 0.022, 0.033), tail=0.3)
    t = tt(0.09)
    k["rim"] = fin((np.sin(2 * np.pi * 1667 * t) + np.sin(2 * np.pi * 455 * t) * 0.6) * env(t, 0.03))
    k["tom"] = tom(t_len=0.9, f_end=110, f_start=128, decay=0.75, seed=13)
    k["hat"] = hat(0.07, seed=14)
    k["ohat"] = hat(0.6, seed=15, open_=True)
    t = tt(0.07)
    k["shk"] = fin(hp(noise(len(t), 16), 6000) * env(t, 0.05, att=0.002))
    return k


def kit_909():
    k = {}
    t = tt(0.6)
    body = np.sin(sweep(t, 54, 260, 0.011, 0.07, 30)) * env(t, 0.42, att=0.0005)
    click = hp(noise(len(t), 21), 2500) * env(t, 0.02) * 0.45
    k["kick"] = fin(sat(lp(body + click, 8000) * 1.3, 2.0))
    t = tt(0.36)
    tone = np.sin(sweep(t, 185, 240, 0.01)) * env(t, 0.1) + np.sin(sweep(t, 330, 360, 0.008)) * env(t, 0.07) * 0.6
    nz = noise(len(t), 22)
    snap = hp(lp(nz, 8500), 1600) * env(t, 0.26, att=0.0005)
    k["snare"] = fin(sat(tone * 0.85 + snap * 0.55, 1.6))
    k["clap"] = clap(seed=23, centre=(1000, 3000), spacing=(0.0, 0.008, 0.016, 0.024), tail=0.25)
    t = tt(0.1)
    k["rim"] = fin(sat((np.sin(2 * np.pi * 480 * t) + np.sin(2 * np.pi * 1300 * t) * 0.7 +
                        hp(noise(len(t), 24), 3000) * 0.4) * env(t, 0.04), 1.6))
    k["tom"] = tom(t_len=0.6, f_end=105, f_start=180, decay=0.45, seed=25)
    # 909 cymbals were 6-bit samples: noisy metal with grit
    k["hat"] = crush(hat(0.1, seed=26, freqs=(263, 400, 421, 474, 587, 845), tone=(7000, 10800)), 6)
    k["ohat"] = crush(hat(0.65, seed=27, open_=True, freqs=(263, 400, 421, 474, 587, 845), tone=(7000, 10800)), 6)
    k["shk"] = shaker(seed=28)
    return k


def crush(x, bits):
    pk = np.max(np.abs(x)) + 1e-9
    q = 2 ** (bits - 1)
    return np.round(x / pk * q) / q * pk


def kit_lofi():
    """Classic pushed through an old sampler: 12 bits at 26 kHz, dull top, tape warmth."""
    k = {}
    for lane, x in kit_classic().items():
        y = lp(x, 7000, 4)
        hold = 2                                       # sample and hold to ~22 kHz-ish grit
        y = np.repeat(y[::hold], hold)[: len(y)]
        y = crush(y, 10)
        y = lp(sat(y * 1.4, 1.8), 5200, 2)
        if lane == "kick":
            y = peak(y, 70, 0.8, 4)
        k[lane] = fin(y)
    return k


def kit_acoustic():
    k = {}
    t = tt(0.6)
    body = np.sin(sweep(t, 58, 95, 0.03)) * env(t, 0.38)
    shell = np.sin(sweep(t, 115, 140, 0.02)) * env(t, 0.12) * 0.35
    beater = lp(noise(len(t), 31), 3500) * env(t, 0.012) * 0.6
    k["kick"] = fin(room(sat(peak(body + shell + beater, 3000, 1.0, 3), 1.3), 0.15, 0.08))
    t = tt(0.55)
    modes = sum(np.sin(2 * np.pi * f * t + p) * env(t, d) * a
                for f, d, a, p in [(196, 0.18, 0.6, 0), (311, 0.12, 0.35, 1), (452, 0.09, 0.25, 2), (608, 0.07, 0.15, 3)])
    wires = bp(noise(len(t), 32), 2000, 9000) * env(t, 0.32, att=0.0015)
    stick = hp(noise(len(t), 33), 2500) * env(t, 0.008) * 0.8
    k["snare"] = fin(room(sat(modes * 0.7 + wires * 0.6 + stick, 1.2), 0.25, 0.16), 0.75)
    k["clap"] = fin(room(clap(seed=34, centre=(800, 2800), spacing=(0.0, 0.012, 0.025), tail=0.18), 0.3, 0.22))
    t = tt(0.15)
    k["rim"] = fin(room((np.sin(2 * np.pi * 620 * t) * 0.5 + np.sin(2 * np.pi * 1480 * t) * 0.35 +
                         bp(noise(len(t), 35), 1500, 5000) * 0.6) * env(t, 0.06), 0.2, 0.15))
    k["tom"] = fin(room(tom(t_len=0.9, f_end=92, f_start=118, decay=0.7, seed=36), 0.3, 0.14))
    # cymbals: a dense inharmonic partial bank instead of squares
    rng = np.random.default_rng(37)
    freqs = np.sort(rng.uniform(3200, 10500, 60))
    for lane, sec, dec in (("hat", 0.18, 0.11), ("ohat", 1.0, 0.85)):
        t = tt(sec)
        part = sum(np.sin(2 * np.pi * f * t + rng.uniform(0, 6.3)) * env(t, dec * rng.uniform(0.5, 1.0)) for f in freqs)
        nz = hp(noise(len(t), 38 if lane == "hat" else 39), 6000) * env(t, dec)
        x = hp(part / 12 + nz * 0.5, 4500) * env(t, dec * 1.3, att=0.0006)
        k[lane] = fin(room(x, 0.2, 0.1))
    t = tt(0.16)
    grains = hp(noise(len(t), 40), 4500) * (np.minimum(t / 0.03, 1) * env(t, 0.14, att=0))
    k["shk"] = fin(room(grains, 0.15, 0.1))
    return k


# ---------------------------------------------------------------- modular kits
def lpg(x, t, decay, lo=200.0, hi=9000.0, res=0.0):
    """A low-pass gate: cutoff and level fall together (the vactrol sound of west-coast modular)."""
    e = np.exp(-6.9 * t / decay)
    fc = lo + (hi - lo) * e
    g = 1.0 - np.exp(-2 * np.pi * fc / FS)
    y = np.empty(len(x))
    a = b = 0.0
    for i, v in enumerate(x.tolist()):
        fb = res * b
        a += g[i] * (v - fb - a)
        b += g[i] * (a - b)
        y[i] = b
    return y * e


def ping(t, f, q_decay, f_drop=0.0, tau=0.03):
    """A resonant filter 'ping': a damped sine with an optional pitch drop."""
    fr = f * (1 + f_drop * np.exp(-t / tau))
    return np.sin(2 * np.pi * np.cumsum(fr) / FS) * env(t, q_decay, att=0.0003)


def fm(t, fc, ratio, index, decay, idecay=None):
    """Two-operator FM: the index decays faster than the level (a bright attack that mellows)."""
    idx = index * np.exp(-6.9 * t / (idecay or decay * 0.4))
    return np.sin(2 * np.pi * fc * t + idx * np.sin(2 * np.pi * fc * ratio * t)) * env(t, decay)


def ringmod(t, f1, f2):
    return square(2 * np.pi * f1 * t) * square(2 * np.pi * f2 * t)


def kit_modular():
    """West-coast and Eurorack percussion: low-pass-gated pings, FM blips, ring-mod metal."""
    k = {}
    t = tt(0.9)
    body = ping(t, 46, 0.75, f_drop=3.5, tau=0.025)
    wob = 1 + 0.04 * np.sin(2 * np.pi * 7 * t) * np.exp(-t * 4)
    k["kick"] = fin(sat(body * wob + lpg(noise(len(t), 51), t, 0.02, 300, 4000) * 0.4, 1.6))
    t = tt(0.45)
    k["snare"] = fin(sat(ping(t, 880, 0.18) * 0.5 + ping(t, 1360, 0.12) * 0.3 +
                         lpg(noise(len(t), 52), t, 0.22, 500, 9000, 0.6) * 0.8, 1.4))
    t = tt(0.4)
    k["clap"] = fin(lpg(noise(len(t), 53), t, 0.16, 400, 7000, 1.2) * 1.6 +
                    lpg(noise(len(t), 54), np.maximum(t - 0.012, 0), 0.12, 400, 6000, 1.2) * 0.8)
    t = tt(0.16)
    k["rim"] = fin(fm(t, 1180, 1.41, 6.0, 0.09, 0.02))
    t = tt(0.8)
    k["tom"] = fin(sat(ping(t, 150, 0.5, f_drop=0.6, tau=0.04) + ping(t, 231, 0.3, f_drop=0.4) * 0.4 +
                       lpg(noise(len(t), 55), t, 0.03, 300, 3000) * 0.3, 1.2))
    t = tt(0.12)
    k["hat"] = fin(hp(ringmod(t, 1530, 2210) * 0.6 + noise(len(t), 56) * 0.2, 6000) * env(t, 0.07, att=0.0002))
    t = tt(0.8)
    k["ohat"] = fin(hp(lpg(ringmod(t, 1530, 2210) + noise(len(t), 57) * 0.3, t, 0.7, 3000, 11000, 0.3), 4500))
    t = tt(0.18)
    zap = np.sin(2 * np.pi * np.cumsum(180 + 3800 * np.exp(-t / 0.018)) / FS) * env(t, 0.14, att=0.0002)
    k["shk"] = fin(zap)
    return k


def kit_industrial():
    """Metal, distortion and weight: anvils, sheet metal, an overdriven kick."""
    k = {}
    t = tt(0.7)
    body = np.sin(sweep(t, 44, 190, 0.012, 0.05, 40)) * env(t, 0.55)
    k["kick"] = fin(lp(sat(body * 2.2 + hp(noise(len(t), 61), 1000) * env(t, 0.03) * 0.6, 3.0), 7000))
    t = tt(0.5)
    modes = sum(np.sin(2 * np.pi * f * t) * env(t, d) * a for f, d, a in
                ((330, 0.3, 0.5), (517, 0.22, 0.4), (881, 0.18, 0.35), (1393, 0.12, 0.3), (2111, 0.08, 0.25)))
    k["snare"] = fin(sat(modes + bp(noise(len(t), 62), 1500, 8000) * env(t, 0.2) * 0.6, 2.2))
    t = tt(0.45)
    k["clap"] = fin(crush(clap(seed=63, centre=(700, 2400), spacing=(0.0, 0.007, 0.015, 0.022), tail=0.25), 6))
    t = tt(0.4)
    k["rim"] = fin(sum(np.sin(2 * np.pi * f * t) * env(t, d) for f, d in ((1870, 0.3), (2973, 0.2), (4410, 0.12))) / 2)
    t = tt(1.0)
    k["tom"] = fin(sat(sum(np.sin(2 * np.pi * f * t) * env(t, d) * a for f, d, a in
                           ((92, 0.8, 0.8), (151, 0.6, 0.5), (247, 0.4, 0.35), (403, 0.25, 0.2))), 1.8))
    t = tt(0.1)
    k["hat"] = fin(crush(hp(noise(len(t), 64), 7000) * env(t, 0.06), 4))
    t = tt(1.1)
    rng = np.random.default_rng(65)
    sheet = sum(np.sin(2 * np.pi * f * t + rng.uniform(0, 6)) * env(t, rng.uniform(0.4, 1.0))
                for f in rng.uniform(1200, 9000, 40)) / 10
    k["ohat"] = fin(hp(sheet + noise(len(t), 66) * env(t, 0.5) * 0.3, 3000))
    t = tt(0.2)
    k["shk"] = fin(sat(hp(noise(len(t), 67), 5000) * (np.sin(2 * np.pi * 60 * t) > 0) * env(t, 0.15), 2.0))
    return k


def kit_glitch():
    """Digital debris: clicks, stutters, chirps and crushed ticks."""
    k = {}
    t = tt(0.35)
    k["kick"] = fin(sat(np.sin(sweep(t, 50, 400, 0.004)) * env(t, 0.25), 2.0))
    t = tt(0.3)
    nz = hp(noise(len(t), 71), 1200)
    gate = ((t % 0.035) < 0.012) * env(t, 0.25)
    k["snare"] = fin(crush(nz * gate, 5))
    t = tt(0.2)
    k["clap"] = fin(np.sin(2 * np.pi * np.cumsum(600 + 5000 * (t / 0.2) ** 2) / FS) * env(t, 0.15))
    t = tt(0.05)
    click = np.zeros(len(t))
    click[:8] = [1, -0.8, 0.6, -0.4, 0.3, -0.2, 0.1, -0.05]
    k["rim"] = fin(bp(click * 4, 1500, 9000) + np.sin(2 * np.pi * 3000 * t) * env(t, 0.02) * 0.4)
    t = tt(0.5)
    k["tom"] = fin(fm(t, 98, 2.0, 4.0, 0.4, 0.08))
    t = tt(0.06)
    k["hat"] = fin(crush(hp(noise(len(t), 72), 8000) * env(t, 0.03), 3))
    t = tt(0.6)
    x = hp(noise(len(t), 73), 4000) * env(t, 0.5)
    hold = np.maximum(1, (1 + 30 * t / 0.6)).astype(int)        # the sample rate falls through the note
    idx = np.minimum(len(x) - 1, (np.arange(len(x)) // hold) * hold)
    k["ohat"] = fin(x[idx])
    t = tt(0.3)
    rng = np.random.default_rng(74)
    g = np.zeros(len(t))
    for _ in range(14):
        a0 = int(rng.uniform(0, len(t) - 300))
        g[a0:a0 + 220] += noise(220, int(rng.integers(1000))) * np.hanning(220)
    k["shk"] = fin(hp(g, 3000) * env(t, 0.28))
    return k


BUILD = {"Classic": kit_classic, "808": kit_808, "909": kit_909, "Lo-fi": kit_lofi, "Acoustic": kit_acoustic,
         "Modular": kit_modular, "Industrial": kit_industrial, "Glitch": kit_glitch}


# ---------------------------------------------------------------- output
def to_out(x):
    # anti-aliased 2:1: windowed-sinc low-pass at 10 kHz, then every other sample
    n = np.arange(-64, 65)
    h = np.sinc(2 * 10000 / FS * n) * np.blackman(len(n))
    h /= h.sum()
    y = convolve(x, h)[64:64 + len(x)][::2]
    pk = np.max(np.abs(y)) + 1e-9
    return (y / pk * 0.9).astype(np.float32)


def write_wav(path, x, sr=OUT_SR, ch=1):
    y = np.clip(x, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((y * 32767).astype("<i2").tobytes())


def demo(kits, folder):
    """A short beat per kit, mixed at the engine's rate like the Brick plays it."""
    os.makedirs(folder, exist_ok=True)
    pat = {"kick": "x.....x...x.....", "snare": "....x.......x...", "hat": "x.x.x.x.x.x.x.x.",
           "ohat": "..............x.", "clap": "............x...", "shk": ".x.x.x.x.x.x.x.x",
           "rim": ".........x......", "tom": "...............x"}
    gain = {"kick": 0.9, "snare": 0.75, "hat": 0.5, "ohat": 0.55, "clap": 0.6, "rim": 0.5, "tom": 0.7, "shk": 0.35}
    step = 60.0 / 112 / 4
    allmix = []
    for name, k in kits.items():
        n = int((16 * step * 2 + 1.2) * OUT_SR)
        mix = np.zeros(n)
        for bar in range(2):
            for lane, p in pat.items():
                for s, ch in enumerate(p):
                    if ch == "x":
                        i = int((bar * 16 + s) * step * OUT_SR + (0.01 * OUT_SR if s % 2 else 0))
                        x = k[lane]
                        j = min(n, i + len(x))
                        mix[i:j] += x[: j - i] * gain[lane]
        mix /= np.max(np.abs(mix)) + 1e-9
        mix *= 0.89
        write_wav(os.path.join(folder, "demo_%s.wav" % name.replace("-", "").lower()), mix)
        allmix.append(mix)
    write_wav(os.path.join(folder, "demo_all_kits.wav"), np.concatenate(allmix))


def main():
    kits = {}
    for name, fn in BUILD.items():
        d = os.path.join(KITS, name)
        os.makedirs(d, exist_ok=True)
        k = {lane: to_out(x) for lane, x in fn().items()}
        for lane in LANES:
            write_wav(os.path.join(d, lane + ".wav"), k[lane])
        kits[name] = k
        print("kit", name, {l: round(len(v) / OUT_SR, 2) for l, v in k.items()})
    if "--demo" in sys.argv:
        demo(kits, sys.argv[sys.argv.index("--demo") + 1])


if __name__ == "__main__":
    main()
