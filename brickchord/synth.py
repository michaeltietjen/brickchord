"""Brickchord analog-VA engine.

Notes are rendered offline with NumPy as band-limited wavetables whose
harmonics are shaped per control block by a resonant 2-pole low-pass
response, so filter sweeps, detuned saws, PWM and a sub oscillator all
come out alias-free and cheap enough for an ARM handheld.
Each note is split into an attack segment and a seamless sustain loop.
"""
import math
import os

import numpy as np

SR = 22050
TABLE = 2048
NH = TABLE // 2          # harmonics available in a table (index 1..NH-1)
BLOCK = 128              # control-rate block in samples

# ---------------------------------------------------------------- patches
# osc: (wave, cents, level, pan, octave)   wave: saw | square | pulse | tri
PATCHES = [
    dict(name="Juno Pad", oscs=[("saw", -9, .55, -.7, 0), ("saw", 9, .55, .7, 0), ("square", 0, .35, 0, -1)],
         cutoff=900, res=1.6, fenv=1.6, fa=.9, fd=1.8, fs=.35, a=.45, d=1.0, s=.85, r=1.4, pwm=0),
    dict(name="Poly Brass", oscs=[("saw", -6, .6, -.5, 0), ("saw", 7, .6, .5, 0)],
         cutoff=700, res=1.2, fenv=2.6, fa=.06, fd=.55, fs=.45, a=.03, d=.4, s=.8, r=.35, pwm=0),
    dict(name="PWM Strings", gain=1.4, oscs=[("pulse", -12, .55, -.8, 0), ("pulse", 11, .55, .8, 0), ("saw", 0, .25, 0, 1)],
         cutoff=1800, res=.9, fenv=.6, fa=.6, fd=1.5, fs=.6, a=.6, d=1.0, s=.9, r=1.6, pwm=.8),
    dict(name="Square Keys", gain=1.8, oscs=[("square", -4, .6, -.4, 0), ("pulse", 4, .4, .4, 0)],
         cutoff=1400, res=1.4, fenv=1.8, fa=.005, fd=.35, fs=.25, a=.004, d=.6, s=.55, r=.3, pwm=.35),
    dict(name="Saw Pluck", oscs=[("saw", -5, .6, -.5, 0), ("saw", 5, .6, .5, 0), ("square", 0, .3, 0, -1)],
         cutoff=380, res=2.4, fenv=4.2, fa=.002, fd=.28, fs=0, a=.002, d=.9, s=.0, r=.35, pwm=0),
    dict(name="Dark Sync-ish", oscs=[("saw", 0, .55, -.3, 0), ("saw", 702, .35, .3, 0), ("tri", 0, .4, 0, -1)],
         cutoff=600, res=3.2, fenv=2.0, fa=.25, fd=1.2, fs=.3, a=.08, d=1.0, s=.8, r=.8, pwm=0),
    dict(name="Wide Supersaw", oscs=[("saw", -18, .4, -1, 0), ("saw", -7, .45, -.4, 0), ("saw", 0, .45, 0, 0),
                                     ("saw", 7, .45, .4, 0), ("saw", 18, .4, 1, 0)],
         cutoff=2200, res=1.0, fenv=.8, fa=.3, fd=1.2, fs=.6, a=.25, d=1.0, s=.85, r=1.2, pwm=0),
    dict(name="Prophet Poly", oscs=[("saw", -5, .55, -.5, 0), ("pulse", 6, .45, .5, 0)],
         cutoff=650, res=2.2, fenv=2.4, fa=.01, fd=.6, fs=.35, a=.01, d=.8, s=.7, r=.6, pwm=.25),
    dict(name="Electric Piano", gain=2.0, oscs=[("sine", 0, .7, -.2, 0), ("sine", 1902, .18, .2, 0), ("tri", 3, .25, 0, 0)],
         cutoff=5000, res=.7, fenv=0, fa=.01, fd=.2, fs=1, a=.004, d=1.6, s=.0, r=.5, pwm=0),
    dict(name="Glass Bells", gain=1.8, oscs=[("sine", 0, .6, -.3, 0), ("sine", 1757, .35, .3, 0), ("sine", 2914, .22, 0, 0)],
         cutoff=6000, res=.7, fenv=0, fa=.01, fd=.2, fs=1, a=.002, d=2.4, s=.0, r=1.2, pwm=0),
    dict(name="Choir Pad", gain=1.4, oscs=[("pulse", -8, .5, -.7, 0), ("pulse", 8, .5, .7, 0), ("sine", 0, .3, 0, 1)],
         cutoff=900, res=3.0, fenv=.5, fa=.8, fd=1.5, fs=.7, a=.7, d=1.2, s=.9, r=1.8, pwm=.9),
    dict(name="Acid Chord", oscs=[("saw", 0, .6, -.2, 0), ("square", 4, .35, .2, 0)],
         cutoff=300, res=6.0, fenv=4.5, fa=.003, fd=.22, fs=.05, a=.003, d=.5, s=.4, r=.25, pwm=0),
    dict(name="Lofi Strings", oscs=[("saw", -14, .5, -.8, 0), ("saw", 12, .5, .8, 0), ("tri", 0, .3, 0, -1)],
         cutoff=1100, res=.8, fenv=.4, fa=.9, fd=1.5, fs=.8, a=.9, d=1.0, s=.9, r=2.0, pwm=0),
    dict(name="Sub Pad", oscs=[("tri", -3, .6, -.4, 0), ("tri", 3, .6, .4, 0), ("sine", 0, .7, 0, -1)],
         cutoff=1500, res=.7, fenv=.3, fa=.5, fd=1.0, fs=.8, a=.5, d=1.0, s=.9, r=1.5, pwm=0),
    dict(name="Soft Tri Organ", oscs=[("tri", 0, .6, -.3, 0), ("tri", 1200, .35, .3, 0), ("tri", 3, .3, 0, -1)],
         cutoff=4000, res=.8, fenv=0, fa=.01, fd=.1, fs=1, a=.02, d=.2, s=1, r=.2, pwm=0),
    # ---- other synth engines (engine=...): FM, plucked string, air/noise; vox = formant wavetable
    dict(name="FM Keys", engine="fm", oscs=[], fm=dict(ratio=1.0, idx=3.2, idx_s=0.6, idx_t=0.35, det=4),
         cutoff=6000, res=.7, fenv=0, fa=.01, fd=.2, fs=1, a=.003, d=1.4, s=.35, r=.5, pwm=0),
    dict(name="FM Bell", engine="fm", oscs=[], fm=dict(ratio=3.5, idx=5.0, idx_s=1.0, idx_t=0.6, det=3),
         cutoff=8000, res=.7, fenv=0, fa=.01, fd=.2, fs=1, a=.002, d=2.6, s=.0, r=1.4, pwm=0),
    dict(name="FM Brass", engine="fm", oscs=[], fm=dict(ratio=1.0, idx=1.0, idx_s=3.0, idx_t=0.25, det=6),
         cutoff=6000, res=.7, fenv=0, fa=.01, fd=.2, fs=1, a=.06, d=.6, s=.8, r=.35, pwm=0),
    dict(name="Nylon Guitar", engine="pluck", oscs=[], pluck=dict(bright=.35, t60=2.2, body=.25),
         cutoff=6000, res=.7, fenv=0, fa=.01, fd=.2, fs=1, a=.002, d=2.2, s=.0, r=.25, pwm=0),
    dict(name="Steel Guitar", engine="pluck", oscs=[], pluck=dict(bright=.75, t60=3.2, body=.15),
         cutoff=6000, res=.7, fenv=0, fa=.01, fd=.2, fs=1, a=.002, d=2.8, s=.0, r=.3, pwm=0),
    dict(name="Drawbar Organ", gain=1.3, oscs=[("sine", 0, .55, -.2, 0), ("sine", 1200, .4, .2, 0), ("sine", 1902, .3, 0, 0),
                                               ("sine", 2400, .22, -.3, 0), ("sine", 0, .5, .3, -1)],
         cutoff=8000, res=.7, fenv=0, fa=.01, fd=.1, fs=1, a=.008, d=.2, s=1, r=.12, pwm=0),
    dict(name="Vox Pad", gain=1.6, oscs=[("vox", -7, .6, -.6, 0), ("vox", 7, .6, .6, 0), ("sine", 0, .25, 0, -1)],
         cutoff=5000, res=.7, fenv=0, fa=.5, fd=1.0, fs=1, a=.6, d=1.0, s=.9, r=1.6, pwm=.9),
    dict(name="Air Pad", engine="noise", oscs=[], noise=dict(width=.035, tilt=.9, floor=.04),
         cutoff=3500, res=.7, fenv=0, fa=.5, fd=1.0, fs=1, a=.9, d=1.0, s=.9, r=2.0, pwm=0),
]


def _adsr(n, a, d, s, rate):
    """Envelope sampled at `rate` Hz for n points (no release stage)."""
    t = np.arange(n) / rate
    env = np.empty(n, np.float32)
    a = max(a, 1e-4)
    d = max(d, 1e-4)
    m1 = t < a
    env[m1] = t[m1] / a
    m2 = ~m1
    env[m2] = s + (1 - s) * np.exp(-(t[m2] - a) / (d / 3.0))
    return env


def _harm_amps(wave, k, duty):
    """Base harmonic amplitudes. k: (H,), duty: (B,) -> (B,H)."""
    if wave == "saw":
        return np.broadcast_to(1.0 / k, (len(duty), len(k)))
    if wave == "square":
        a = np.where(k % 2 == 1, 1.0 / k, 0.0)
        return np.broadcast_to(a, (len(duty), len(k)))
    if wave == "sine":
        a = np.where(k == 1, 1.0, 0.0)
        return np.broadcast_to(a, (len(duty), len(k)))
    if wave == "tri":
        a = np.where(k % 2 == 1, 1.0 / (k * k), 0.0) * np.where(((k - 1) // 2) % 2 == 0, 1, -1)
        return np.broadcast_to(a * 1.6, (len(duty), len(k)))
    if wave.startswith("sync"):
        # a hard-synced saw: the slave resets every master cycle; its spectrum, per
        # master harmonic, from one period (cached per ratio)
        r = float(wave.split(":")[1]) if ":" in wave else 2.0
        a = _sync_amps(r)[:len(k)]
        return np.broadcast_to(a, (len(duty), len(k)))
    # pulse with time-varying duty
    return (2.0 / (np.pi * k))[None, :] * np.sin(np.pi * k[None, :] * duty[:, None])


_SYNC_CACHE = {}


def _sync_amps(r):
    key = round(r, 2)
    a = _SYNC_CACHE.get(key)
    if a is None:
        th = np.arange(4096) / 4096.0
        y = ((th * key) % 1.0) * 2.0 - 1.0
        c = np.fft.rfft(y) / 2048.0
        a = np.abs(c[1:NH + 1]).astype(np.float32)
        if len(a) < NH:
            a = np.pad(a, (0, NH - len(a)))
        _SYNC_CACHE[key] = a
    return a


WAVES = ["saw", "square", "pulse", "tri", "sine", "vox"]


def _vox_amps(k, f, duty):
    """Formant wavetable: a saw shaped by vowel formants that morph from 'ah' to
    'oh' as duty (the PWM LFO) moves. -> (B,H)"""
    m = np.clip((duty - 0.1) / 0.8, 0, 1)[:, None]              # 0 = ah, 1 = oh
    hz = (k * f)[None, :]
    out = np.full((len(duty), len(k)), 0.04, np.float32)
    for fa, fo, bw, g in ((800, 450, 110, 1.0), (1150, 800, 140, 0.6), (2900, 2830, 220, 0.3)):
        F = fa + (fo - fa) * m
        out = out + g * np.exp(-((hz - F) / bw) ** 2)
    return (out / k[None, :] ** 0.3).astype(np.float32)

# Sound Editor parameters: (key, label, min, max, step)
EDIT_PARAMS = [
    ("wave", "Osc Wave", None, None, None),
    ("detune", "Detune", 0.0, 3.0, 0.25),
    ("sub", "Sub Osc", 0.0, 1.0, 0.1),
    ("cutoff", "Cutoff", 80.0, 8000.0, None),
    ("res", "Resonance", 0.5, 8.0, 0.25),
    ("fenv", "Filter Env", 0.0, 5.0, 0.25),
    ("fa", "Filt Attack", 0.002, 3.0, None),
    ("fd", "Filt Decay", 0.02, 4.0, None),
    ("fs", "Filt Sustain", 0.0, 1.0, 0.05),
    ("a", "Amp Attack", 0.002, 3.0, None),
    ("d", "Amp Decay", 0.02, 4.0, None),
    ("s", "Amp Sustain", 0.0, 1.0, 0.05),
    ("r", "Release", 0.05, 4.0, None),
    ("pwm", "PWM Depth", 0.0, 1.0, 0.1),
]


# ---------------------------------------------------------------- machine banks
# Bricklab's Lead, Bass and Drone machines have their own sounds. The ladder
# patches use the 4-pole response above, which is what makes them Moog-ish.
def _ld(name, oscs, **kw):
    p = dict(name=name, oscs=oscs, ladder=True, cutoff=1200, res=1.5, fenv=2.0, fa=.005, fd=.4, fs=.3,
             a=.004, d=.3, s=.7, r=.25, pwm=0)
    p.update(kw)
    return p


LEAD_PATCHES = [
    _ld("Fat Saw", [("saw", -7, .6, -.3, 0), ("saw", 7, .6, .3, 0), ("square", 0, .35, 0, -1)],
        cutoff=1500, res=1.8, fenv=2.2, fd=.5, drive=.3),
    _ld("Hollow Square", [("square", 0, .7, 0, 0), ("pulse", 4, .3, 0, 0)], cutoff=1100, res=2.4, fenv=1.4,
        pwm=.5, fd=.6, s=.6, gain=1.8),
    _ld("Sync Lead", [("saw", 0, .7, 0, 0), ("saw", 1203, .5, 0, 0)], cutoff=2600, res=2.8, fenv=3.2, fa=.0, fd=.22,
        fs=.15, d=.25, s=.55, drive=.5),
    _ld("Sub Lead", [("tri", 0, .7, 0, 0), ("sine", 0, .5, 0, -1)], cutoff=700, res=1.0, fenv=1.2, fd=.5, s=.8),
    _ld("Brass Lead", [("saw", -4, .6, -.2, 0), ("saw", 4, .6, .2, 0)], cutoff=600, res=1.3, fenv=3.0, fa=.08, fd=.35,
        fs=.5, a=.04, d=.3, s=.8, r=.3),
    _ld("Acid", [("saw", 0, .8, 0, 0)], cutoff=500, res=3.4, fenv=3.4, fa=.0, fd=.18, fs=.1, d=.2, s=.4, drive=.6, gain=1.2),
    _ld("Flute", [("sine", 0, .6, 0, 0), ("tri", 3, .35, 0, 1)], cutoff=1800, res=0.8, fenv=.6, fa=.06, fd=.4, fs=.6,
        a=.05, d=.3, s=.85, r=.3, noise=.25),
    _ld("Whistle", [("sine", 0, .7, 0, 1), ("sine", 5, .3, 0, 2)], cutoff=4000, res=0.7, fenv=.3, a=.04, d=.2, s=.9, r=.2,
        noise=.12),
    _ld("Glass Lead", [("pulse", -3, .5, -.4, 1), ("pulse", 3, .5, .4, 1)], cutoff=3200, res=1.6, fenv=1.0, pwm=.6,
        fd=.8, s=.7, gain=1.6),
    _ld("Wire", [("saw", 0, .5, 0, 1), ("square", 2, .4, 0, 0)], cutoff=2200, res=3.2, fenv=2.6, fd=.3, fs=.2, s=.5,
        drive=.4, gain=1.3),
]

BASS_PATCHES = [
    _ld("Moog Bass", [("saw", 0, .7, 0, 0), ("square", 0, .5, 0, -1)], cutoff=520, res=1.9, fenv=2.6, fd=.28, fs=.2,
        d=.5, s=.6, r=.2, drive=.3),
    _ld("Sub", [("sine", 0, .9, 0, 0), ("tri", 0, .3, 0, 1)], cutoff=400, res=0.8, fenv=.8, fd=.4, s=.9, r=.15),
    _ld("Pulse Bass", [("pulse", 0, .75, 0, 0), ("sine", 0, .4, 0, -1)], cutoff=700, res=2.0, fenv=2.0, pwm=.4, fd=.3,
        fs=.25, s=.6, r=.2, gain=1.4),
    _ld("Acid Bass", [("saw", 0, .8, 0, 0)], cutoff=380, res=3.5, fenv=3.6, fd=.2, fs=.08, d=.25, s=.45, r=.15, drive=.7, gain=1.2),
    _ld("Reese", [("saw", -14, .55, -.5, 0), ("saw", 14, .55, .5, 0), ("sine", 0, .4, 0, -1)], cutoff=900, res=1.2,
        fenv=.6, fa=.2, fd=1.0, fs=.7, a=.02, d=.6, s=.85, r=.3),
    _ld("Pluck Bass", [("saw", 0, .6, 0, 0), ("square", 0, .4, 0, -1)], cutoff=600, res=2.2, fenv=3.0, fd=.14, fs=.0,
        d=.18, s=.0, r=.2, gain=1.4),
    _ld("Hollow Bass", [("square", 0, .8, 0, 0)], cutoff=450, res=1.6, fenv=1.6, fd=.4, s=.7, r=.2, gain=1.8),
    _ld("Fuzz Bass", [("saw", -5, .6, 0, 0), ("saw", 5, .6, 0, 0)], cutoff=800, res=1.4, fenv=1.8, fd=.4, s=.7, r=.2,
        drive=.9),
]


def _dr(name, oscs, **kw):
    p = dict(name=name, oscs=oscs, cutoff=900, res=1.0, fenv=1.2, fa=2.5, fd=3.0, fs=.6, a=1.2, d=2.0, s=.9, r=2.5,
             pwm=.3, gain=1.2)
    p.update(kw)
    return p


DRONE_PATCHES = [
    _dr("Deep Space", [("saw", -14, .5, -.8, -1), ("saw", 14, .5, .8, -1), ("sine", 0, .5, 0, 0)], cutoff=500, fenv=1.6,
        fa=3.0, a=2.0, noise=.08, noise_dark=True),
    _dr("Tape Choir", [("vox", -8, .6, -.6, 0), ("vox", 8, .6, .6, 0), ("sine", 0, .3, 0, -1)], cutoff=1400, fenv=.8,
        a=1.5, pwm=.5),
    _dr("Organ Swell", [("square", 0, .5, 0, 0), ("sine", 0, .5, 0, 1), ("sine", 2, .35, 0, 2)], cutoff=2000, res=.8,
        fenv=1.0, fa=1.8, a=1.4, pwm=0),
    _dr("Cathedral", [("saw", -5, .4, -.7, 0), ("saw", 5, .4, .7, 0), ("sine", 0, .6, 0, -1), ("sine", 1, .3, 0, 1)],
        cutoff=700, fenv=1.4, fa=3.5, fd=4.0, a=2.5),
    _dr("Dark Pad", [("pulse", -11, .5, -.8, 0), ("pulse", 11, .5, .8, 0), ("tri", 0, .4, 0, -1)], cutoff=380, res=1.3,
        fenv=1.2, fa=4.0, a=1.8, pwm=.7),
    _dr("Shimmer", [("saw", -3, .35, -.5, 1), ("saw", 3, .35, .5, 1), ("sine", 0, .5, 0, 0), ("sine", 7, .3, 0, 2)],
        cutoff=2400, res=.9, fenv=1.0, fa=2.0, a=1.2, pwm=.4),
    _dr("Breath", [("tri", -6, .5, -.6, 0), ("tri", 6, .5, .6, 0)], cutoff=1100, fenv=.9, fa=2.2, a=1.6, noise=.35),
    _dr("Sub Drone", [("sine", 0, .8, 0, -1), ("sine", 0, .5, 0, 0), ("saw", 0, .15, 0, 0)], cutoff=300, res=.9,
        fenv=.6, fa=3.0, a=2.0),
]

MACHINES = ["chord", "lead", "bass", "drone", "macro", "drums", "sample"]
MACHINE_NAME = {"chord": "Chord", "lead": "Lead", "bass": "Bass", "drone": "Drone", "drums": "Drums", "sample": "Sample",
                "macro": "Macro"}


def machine_bank(machine):
    """The sound list a machine chooses from (Chord keeps the 23 Brickchord sounds)."""
    return {"lead": LEAD_PATCHES, "bass": BASS_PATCHES, "drone": DRONE_PATCHES,
            "macro": MACRO_PATCHES}.get(machine, PATCHES)


def edited_patch(base, edits):
    """Apply Sound Editor edits to a base patch (returns a new dict)."""
    p = dict(base)
    if base.get("sample") or base.get("macro") is not None:
        return p
    oscs = [list(o) for o in base["oscs"]]
    if edits:
        for k in ("cutoff", "res", "fenv", "fa", "fd", "fs", "a", "d", "s", "r", "pwm"):
            if k in edits:
                p[k] = edits[k]
        if "detune" in edits:
            for o in oscs:
                if abs(o[1]) < 60:          # only detune, not interval offsets
                    o[1] = o[1] * edits["detune"]
        if "wave" in edits:
            for o in oscs:
                if o[4] >= 0:
                    o[0] = edits["wave"]
        if "sub" in edits:
            subs = [o for o in oscs if o[4] < 0]
            if subs:
                for o in subs:
                    o[2] = edits["sub"]
            elif edits["sub"] > 0:
                oscs.append(["square", 0, edits["sub"], 0, -1])
    p["oscs"] = [tuple(o) for o in oscs]
    return p


def param_value(p, key):
    """Current value of an editable parameter on an (edited) patch."""
    if key == "wave":
        main = [o for o in p["oscs"] if o[4] >= 0]
        return main[0][0] if main else "saw"
    if key == "detune":
        return None
    if key == "sub":
        subs = [o for o in p["oscs"] if o[4] < 0]
        return subs[0][2] if subs else 0.0
    return p[key]


_IR = None


def reverb_ir(sec=1.7, predelay=0.018):
    """Synthetic stereo hall: decorrelated decaying noise, darker as it decays."""
    global _IR
    if _IR is None:
        n = int(sec * SR)
        t = np.arange(n) / SR
        rng = np.random.default_rng(7)
        ir = rng.standard_normal((n, 2)).astype(np.float32)
        # progressive darkening: blend toward a smoothed copy over time
        sm = ir.copy()
        for _ in range(3):
            sm = (sm + np.roll(sm, 1, 0) + np.roll(sm, 2, 0)) / 3
        mix = np.clip(t / sec * 1.6, 0, 1)[:, None]
        ir = ir * (1 - mix) + sm * mix * 1.7
        ir *= np.exp(-t * 6.9 / sec)[:, None]          # ~60 dB over `sec`
        pd = int(predelay * SR)
        ir = np.concatenate([np.zeros((pd, 2), np.float32), ir])
        ir /= np.sqrt((ir ** 2).sum(0, keepdims=True)) * 1.15
        _IR = ir.astype(np.float32)
    return _IR


# ---------------------------------------------------------------- reverb types
REVERBS = ["Hall", "Room", "Plate", "Big Hall", "Spring", "Reverse", "Gated", "Lo-fi Dark"]
_REV_CACHE = {}


def _smooth(x, passes):
    for _ in range(passes):
        x = (x + np.roll(x, 1, 0) + np.roll(x, 2, 0)) / 3
    return x


def _norm(ir, level=1.15):
    return (ir / (np.sqrt((ir ** 2).sum(0, keepdims=True)) * level)).astype(np.float32)


def make_reverb(name):
    """Impulse response for each reverb type (stereo float32). The engine
    convolves the synth with it, so any shape costs the same per second of tail."""
    if name in _REV_CACHE:
        return _REV_CACHE[name]
    rng = np.random.default_rng(11)

    def noise(sec):
        n = int(sec * SR)
        return np.arange(n) / SR, rng.standard_normal((n, 2)).astype(np.float32)

    def pre(ir, sec):
        return np.concatenate([np.zeros((int(sec * SR), 2), np.float32), ir])

    if name == "Hall":
        ir = reverb_ir(1.2)
    elif name == "Room":
        t, x = noise(0.5)
        ir = (x * 0.7 + _smooth(x, 2) * 0.6) * np.exp(-t * 6.9 / 0.5)[:, None]
        # a few strong early reflections
        for d, g in ((0.007, 0.9), (0.013, 0.7), (0.021, 0.55), (0.029, 0.4)):
            i = int(d * SR)
            ir[i] += g * np.array([1.0, 0.8] if i % 2 else [0.8, 1.0], np.float32) * 6
        ir = _norm(pre(ir, 0.004))
    elif name == "Plate":
        t, x = noise(1.9)
        ir = x * np.exp(-t * 6.9 / 1.9)[:, None]           # bright and dense, no darkening
        ir = _norm(pre(ir, 0.002), 1.25)
    elif name == "Big Hall":
        t, x = noise(2.7)
        sm = _smooth(x, 4)
        mix = np.clip(t / 2.7 * 1.8, 0, 1)[:, None]
        ir = (x * (1 - mix) + sm * mix * 1.9) * np.exp(-t * 6.9 / 2.7)[:, None]
        ir = _norm(pre(ir, 0.035), 1.05)
    elif name == "Spring":
        t, x = noise(1.6)
        ir = _smooth(x, 1) * np.exp(-t * 6.9 / 1.6)[:, None] * 0.5
        # the "boing": a falling chirp repeating every ~38 ms, decaying
        tc = np.arange(int(0.03 * SR)) / SR
        chirp = np.sin(2 * np.pi * (3200 * tc - 40000 * tc * tc)) * np.exp(-tc * 90)
        for k in range(40):
            i = int((0.012 + k * 0.038) * SR)
            if i + len(chirp) >= len(ir):
                break
            g = 0.9 * np.exp(-k * 0.11)
            ir[i:i + len(chirp), k % 2] += chirp * g * 3
            ir[i:i + len(chirp), 1 - k % 2] += chirp * g * 2
        ir = _norm(ir, 1.1)
    elif name == "Reverse":
        t, x = noise(1.0)
        env = (t / 1.0) ** 2.2                             # swells up, then stops dead
        ir = _smooth(x, 1) * env[:, None]
        ir = _norm(pre(ir, 0.01), 1.3)
    elif name == "Gated":
        t, x = noise(0.38)
        env = np.where(t < 0.3, 1.0 - t * 0.5, np.clip(1 - (t - 0.3) / 0.08, 0, 1))
        ir = (x * 0.8 + _smooth(x, 1) * 0.5) * env[:, None]
        ir = _norm(pre(ir, 0.006), 1.2)
    elif name == "Lo-fi Dark":
        t, x = noise(1.7)
        ir = _smooth(x, 14) * np.exp(-t * 6.9 / 1.7)[:, None]       # very dark
        ir = np.round(ir * 40) / 40                                   # a little crunch
        ir = _norm(pre(ir, 0.045), 1.0)
    else:
        ir = reverb_ir(1.2)
    _REV_CACHE[name] = ir.astype(np.float32)
    return _REV_CACHE[name]


def _convolve(x, ir, out_len):
    nfft = 1 << int(math.ceil(math.log2(len(x) + len(ir))))
    y = np.empty((out_len, 2), np.float32)
    for c in range(2):
        X = np.fft.rfft(x[:, c], nfft)
        H = np.fft.rfft(ir[:, c], nfft)
        y[:, c] = np.fft.irfft(X * H, nfft)[:out_len]
    return y


SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")
SAMPLE_PATCH = {"sample": None, "root": 60, "tune": 0, "start": 0.0, "end": 1.0, "rev": False, "loop": False,
                "grain": False, "gsize": 80, "gdens": 40, "gpos": 0.3, "gspray": 0.3, "gpitch": 0.0,
                "slices": 0,
                "a": 0.0, "d": 0.0, "s": 0.0, "r": 0.25, "fa": 0.0, "fd": 0.0, "fs": 1.0, "fenv": 0.0,
                "cutoff": 9000.0, "res": 0.5, "name": "", "oscs": []}


def sample_files(folder=None):
    """WAV files a Sample track can play: samples/*.wav (kits live in sub-folders)."""
    folder = folder or SAMPLE_DIR
    try:
        return sorted(f for f in os.listdir(folder) if f.lower().endswith(".wav")
                      and os.path.isfile(os.path.join(folder, f)))
    except OSError:
        return []


def sample_patch(file, **kw):
    p = dict(SAMPLE_PATCH)
    p["sample"] = file
    p["name"] = os.path.splitext(file)[0][:16]
    p.update(kw)
    return p


def _grain_cloud(x, r, p, secs=2.5, seed=11):
    """A granular cloud rendered into a note: grains of gsize ms, gdens per
    second, taken around gpos (0..1) with gspray wander and gpitch semitones of
    random detune, each pitched by r and Hann-windowed."""
    rng = np.random.RandomState(seed)
    n = int(secs * SR)
    out = np.zeros(n + int(0.5 * SR), np.float32)
    gl = max(8, int(p.get("gsize", 80) / 1000.0 * SR))
    count = max(4, int(p.get("gdens", 40) * secs))
    win = np.hanning(gl).astype(np.float32)
    pos, spray, pj = p.get("gpos", 0.3), p.get("gspray", 0.3), p.get("gpitch", 0.0)
    L = len(x)
    for g in range(count):
        rr = r * 2.0 ** (rng.uniform(-pj, pj) / 12.0)
        src = int((pos + rng.uniform(-spray, spray) * 0.5) * L) % max(1, L - 1)
        idx = src + np.arange(gl) * rr
        idx = np.clip(idx, 0, L - 1.001)
        i0 = idx.astype(np.int64)
        fr = (idx - i0).astype(np.float32)
        grain = (x[i0] * (1 - fr) + x[i0 + 1] * fr) * win
        at = int(rng.uniform(0, n))
        out[at:at + gl] += grain
    out = out[:n]
    env = np.minimum(np.arange(n) / (0.05 * SR), 1.0).astype(np.float32)           # soft start
    out *= env / (max(1.0, np.sqrt(count * gl / n)) * 0.5)
    pk = np.max(np.abs(out)) + 1e-9
    return (out / pk * 0.9).astype(np.float32)


# ---------------------------------------------------------------- the Macro machine
# A macro oscillator in the spirit of the Eurorack ones: one sound engine per
# model, each driven by the same three controls, HARMONICS, TIMBRE and MORPH
# (0..1). Sustaining models render a seamless, period-locked loop; String and
# Modal are struck and ring out.
MACRO_MODELS = ["Analog", "Fold", "Sync", "Vowel", "Additive", "Table", "String", "Modal", "Bowed", "Blown"]
MACRO_VA = (0, 2)          # these run on the full analog engine: detuned oscillators, ladder filter, envelopes
MACRO_STRUCK = (6, 7)
MACRO_PATCH = {"macro": 0, "harm": 0.5, "timbre": 0.5, "morph": 0.5, "decay": 0.5, "sub": 0.25, "fenv": 2.0,
               "fa": 0.005, "fd": 0.45, "fs": 0.35, "drive": 0.25,
               "a": 0.005, "d": 0.3, "s": 0.7, "r": 0.3, "cutoff": 9000.0, "res": 0.5, "oscs": [], "name": ""}
_FORMANTS = [(730, 1090, 2440), (530, 1840, 2480), (270, 2290, 3010), (570, 840, 2410), (300, 870, 2240)]   # a e i o u
_FM_RATIOS = [0.5, 1.0, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 7.0]


def _macro_wave(model, ph, h, t, m, f):
    """One sustaining model, from phase (radians), with the three controls."""
    if model == 0:                                     # Analog: saw to square, with a detuned twin
        saw = ((ph / np.pi) % 2.0) - 1.0
        pw = 0.5 + 0.45 * (t - 0.5)
        sq = np.where(((ph / (2 * np.pi)) % 1.0) < pw, 1.0, -1.0)
        x = saw * (1 - m) + sq * m
        ph2 = ph * (1.0 + 0.012 * h)
        x2 = ((ph2 / np.pi) % 2.0) - 1.0
        return 0.6 * x + 0.4 * h * x2
    if model == 1:                                     # Fold: a sine through a wavefolder
        x = np.sin(ph) * (1 + m * 0.6) + h * 0.5 * np.sin(2 * ph)
        g = 1 + t * 7
        y = np.sin(x * g)
        return y
    if model == 3:                                     # Vowel: a pulse train through three formants
        k = np.arange(1, int(min(60, 9000 / max(f, 30))) + 1)
        pos = m * (len(_FORMANTS) - 1)
        i0 = int(pos)
        i1 = min(len(_FORMANTS) - 1, i0 + 1)
        fr = pos - i0
        fm_ = [(a * (1 - fr) + b * fr) * (0.8 + 0.5 * t) for a, b in zip(_FORMANTS[i0], _FORMANTS[i1])]
        amp = sum(np.exp(-((k * f - F) / (80 + 60 * h)) ** 2) * w for F, w in zip(fm_, (1.0, 0.6, 0.3)))
        return sum(a * np.sin(n * ph) for n, a in zip(k, amp)) / (np.sum(amp) + 1e-6) * 2.0
    if model == 4:                                     # Additive: centre and tilt, odd vs even
        k = np.arange(1, 33)
        centre = 1 + h * 15
        amp = np.exp(-((k - centre) / (2 + t * 10)) ** 2) + (1.0 / k) * 0.3
        amp *= np.where(k % 2 == 0, 1 - m, 1.0)
        return sum(a * np.sin(n * ph) for n, a in zip(k, amp)) / (np.sum(amp) + 1e-6) * 2.0
    if model == 5:                                     # Table: scan through four shapes
        sh = [np.sin(ph), np.abs(((ph / np.pi) % 2.0) - 1.0) * 2 - 1, ((ph / np.pi) % 2.0) - 1.0,
              np.sign(np.sin(ph)) * np.abs(np.sin(ph)) ** (0.2 + 0.8 * (1 - t))]
        pos = m * 3
        i0 = int(min(2, pos))
        fr = pos - i0
        x = sh[i0] * (1 - fr) + sh[i0 + 1] * fr
        return x + h * 0.4 * np.sin(3 * ph + x)
    return np.sin(ph)


def _ks_string(f, secs, h, t, m, seed):
    """String: Karplus-Strong. TIMBRE brightens the pluck, MORPH lengthens the ring,
    HARMONICS adds a second detuned string."""
    n = int(secs * SR)
    out = np.zeros(n)
    for j, (df, g) in enumerate(((1.0, 1.0), (1.0 + 0.004 + 0.01 * h, h * 0.6))):
        if g <= 0.001:
            continue
        L = max(2, int(round(SR / (f * df))))
        rng = np.random.RandomState(seed + j)
        buf = rng.uniform(-1, 1, L)
        b = 0.2 + 0.75 * t
        for _ in range(int((1 - t) * 4)):              # a darker pluck is a smoother one
            buf = 0.5 * (buf + np.roll(buf, 1))
        loss = 0.990 + 0.0095 * m
        y = np.empty(n)
        prev = 0.0
        idx = 0
        bl = buf.tolist()
        for i in range(n):
            v = bl[idx]
            y[i] = v
            nv = loss * (b * v + (1 - b) * prev) if True else v
            prev = v
            bl[idx] = 0.5 * (nv + bl[(idx + 1) % L] * loss) if L > 2 else nv
            idx = (idx + 1) % L
        out += y * g
    return out


def _modal(f, secs, h, t, m, seed):
    """Modal: a struck resonator bank. HARMONICS bends the partials from a string
    to a bar, a bell and a plate; TIMBRE is brightness; MORPH is how long it rings."""
    n = int(secs * SR)
    tt = np.arange(n) / SR
    k = np.arange(1, 17)
    if h < 0.33:
        ratios = k * (1 + (h / 0.33) * 0.002 * k ** 2)
    elif h < 0.66:
        ratios = np.array([1.0, 2.756, 5.404, 8.933, 13.34, 18.64, 24.81, 31.87] * 2)[:16] ** (0.8 + 0.6 * (h - 0.33) / 0.33)
    else:
        ratios = np.array([1.0, 1.59, 2.14, 2.30, 2.65, 2.92, 3.16, 3.50, 3.60, 3.65, 4.06, 4.15, 4.60, 4.83, 5.40, 5.66])
    ratios = ratios[:16]
    out = np.zeros(n)
    rng = np.random.RandomState(seed)
    base_dec = 0.2 + 3.5 * m
    for i, r in enumerate(ratios):
        fr = f * r
        if fr > SR * 0.45:
            continue
        a = np.exp(-i * (1.6 - 1.4 * t)) * (0.6 + 0.4 * rng.rand())
        dec = base_dec / (1 + i * (0.25 + 0.5 * (1 - m)))
        out += a * np.sin(2 * np.pi * fr * tt + rng.uniform(0, 6.28)) * np.exp(-tt / max(0.02, dec))
    click = rng.randn(min(n, 64)) * np.linspace(1, 0, min(n, 64)) * 0.3 * t
    out[:len(click)] += click
    return out


def _resonator_drive(f, secs, h, t, m, model, seed):
    """Bowed and Blown: a continuous exciter through a resonator bank (the modal
    voice idea): the exciter's spectrum is shaped by the resonator's peaks in the
    frequency domain. HARMONICS bends the partials, TIMBRE brightens the exciter,
    MORPH narrows the peaks (more ringing, more pitch)."""
    n = int(secs * SR)
    rng = np.random.RandomState(seed)
    nz = rng.randn(n)
    if model == 8:                                     # bow: noise plus a stick-slip pulse train at the pitch
        ph = (np.arange(n) * f / SR) % 1.0
        exc = nz * (0.3 + 0.7 * t) + (ph < 0.08).astype(float) * (2.0 - 1.5 * t)
    else:                                              # blow: breath noise with a slow wobble
        exc = nz * (1.0 + 0.3 * np.sin(2 * np.pi * 3.1 * np.arange(n) / SR))
    X = np.fft.rfft(exc)
    fr = np.fft.rfftfreq(n, 1.0 / SR)
    if h < 0.5:
        ratios = np.arange(1, 25) * (1 + (h / 0.5) * 0.003 * np.arange(1, 25) ** 2)
    else:
        ratios = np.array([1.0, 2.756, 5.404, 8.933, 13.34, 18.64, 24.81, 31.87]) ** (0.8 + 0.5 * (h - 0.5) / 0.5)
    bw = f * (0.06 - 0.055 * m) + 1.0
    H = np.zeros_like(fr)
    for i, r in enumerate(ratios):
        fc = f * r
        if fc > SR * 0.45:
            break
        amp = np.exp(-i * (0.9 - 0.7 * t)) if model == 8 else np.exp(-i * (1.2 - 0.8 * t))
        H += amp / (1.0 + ((fr - fc) / (bw * (1 + 0.15 * i))) ** 2)
    y = np.fft.irfft(X * H, n)
    if model == 9:
        y += np.fft.irfft(X * np.exp(-((fr - 3000 - 4000 * t) / 2500) ** 2), n) * 0.05   # a breath of air on top
    return y


def macro_va_patch(p):
    """Analog and Sync on the analog engine. HARMONICS spreads voices (one oscillator
    up to five detuned, plus the sub); TIMBRE is the ladder cutoff; MORPH moves the
    wave from saw to pulse with PWM (Analog) or the sync ratio's second oscillator (Sync)."""
    model = int(p.get("macro", 0))
    h, t, m = (float(p.get(k, 0.5)) for k in ("harm", "timbre", "morph"))
    oscs = []
    if model == 0:
        nv = 1 + int(round(h * 4))
        spread = 3 + 22 * h
        for i in range(nv):
            c = 0.0 if nv == 1 else (i / (nv - 1) - 0.5) * 2 * spread
            pan = 0.0 if nv == 1 else (i / (nv - 1) - 0.5) * 1.2
            wv = "saw" if m < 0.34 else ("pulse" if m > 0.66 or i % 2 else "saw")
            oscs.append((wv, c, 0.75 / max(1.0, nv ** 0.5), pan, 0))
        pwm = max(0.0, (m - 0.34) / 0.66) * 0.8
    else:
        r = 1.5 + h * 5.0
        oscs.append(("sync:%.2f" % r, 0, 0.7, -0.25 * m, 0))
        if m > 0.05:
            oscs.append(("sync:%.2f" % (r * (1 + 0.5 * m)), 7 * m, 0.55 * m, 0.25 * m, 0))
        pwm = 0.0
    sub = float(p.get("sub", 0.25))
    if sub > 0:
        oscs.append(("square" if model == 0 and m > 0.5 else "sine", 0, sub, 0, -1))
    return dict(name=p.get("name", ""), oscs=oscs, ladder=True, pwm=pwm,
                cutoff=110.0 * 2 ** (t * 6.3), res=float(p.get("res", 1.6)), fenv=float(p.get("fenv", 2.0)),
                fa=float(p.get("fa", 0.005)), fd=float(p.get("fd", 0.45)), fs=float(p.get("fs", 0.35)),
                a=float(p.get("a", 0.005)), d=float(p.get("d", 0.3)), s=float(p.get("s", 0.75)),
                r=float(p.get("r", 0.3)), drive=float(p.get("drive", 0.25)), gain=float(p.get("gain", 1.0)) * 2.0)


def render_macro(midi, p, arrays=False):
    model = int(p.get("macro", 0)) % len(MACRO_MODELS)
    if model in MACRO_VA:
        return render_note(midi, macro_va_patch(p), arrays=arrays)
    h, t, m = (float(p.get(k, 0.5)) for k in ("harm", "timbre", "morph"))
    f = 440.0 * 2 ** ((midi - 69) / 12.0)
    if model >= 8:                                     # bowed / blown: sustaining resonator, crossfaded loop
        y = _resonator_drive(f, 3.0, h, t, m, model, midi)
        y = y / (np.max(np.abs(y[int(0.2 * SR):])) + 1e-9)
        att_n = int(max(0.2, float(p.get("a", 0.1)) + float(p.get("d", 0.3))) * SR)
        loop_n = int(1.6 * SR)
        F = int(0.25 * SR)
        loop = y[att_n:att_n + loop_n].copy()
        ramp = np.linspace(0, 1, F)
        # the loop's end fades into the audio just before its start, so both the
        # attack-to-loop join and the loop's own wrap are continuous
        loop[-F:] = loop[-F:] * (1 - ramp) + y[att_n - F:att_n] * ramp
        env = _adsr(att_n, float(p.get("a", 0.1)), float(p.get("d", 0.3)), float(p.get("s", 0.85)), SR)
        att = y[:att_n] * env[:att_n]
        loop = loop * float(p.get("s", 0.85))
        g = GAIN * 1.4
        a_st = np.repeat(att[:, None], 2, axis=1).astype(np.float32) * g
        l_st = np.repeat(loop[:, None], 2, axis=1).astype(np.float32) * g
        if arrays:
            return np.ascontiguousarray(a_st), np.ascontiguousarray(l_st)
        return _to_bytes(a_st), _to_bytes(l_st), att_n / SR
    if model in MACRO_STRUCK:                          # struck models ring out
        secs = 0.4 + 3.5 * float(p.get("decay", 0.5))
        x = _ks_string(f, min(secs, 3.0), h, t, m, midi) if model == 6 else _modal(f, secs, h, t, m, midi)
        x = x / (np.max(np.abs(x)) + 1e-9)
        fade = int(0.01 * SR)
        x[-fade:] *= np.linspace(1, 0, fade)
        st = np.repeat(x[:, None], 2, axis=1).astype(np.float32) * (GAIN * 2.4)
        if arrays:
            return np.ascontiguousarray(st), None
        return _to_bytes(st), None, len(x) / SR
    # sustaining models: an attack part, then a loop of whole periods so it repeats seamlessly
    cycles = max(1, int(round(0.25 * f)))
    loop_n = max(64, int(round(cycles * SR / f)))
    f_lock = cycles * SR / loop_n
    att_sec = max(0.08, float(p.get("a", 0.005)) + float(p.get("d", 0.3)) + 0.05)
    att_n = int(np.ceil(att_sec * SR / loop_n)) * loop_n
    n = att_n + loop_n
    ph = 2 * np.pi * f_lock * np.arange(n) / SR
    x = _macro_wave(model, ph, h, t, m, f_lock).astype(np.float64)
    x -= np.mean(x[att_n:])
    pk = np.max(np.abs(x)) + 1e-9
    x /= pk
    env = _adsr(att_n, float(p.get("a", 0.005)), float(p.get("d", 0.3)), float(p.get("s", 0.7)), SR)
    att = x[:att_n] * env[:att_n]
    loop = x[att_n:] * float(p.get("s", 0.7))
    g = GAIN * 1.1
    a_st = np.repeat(att[:, None], 2, axis=1).astype(np.float32) * g
    l_st = np.repeat(loop[:, None], 2, axis=1).astype(np.float32) * g
    if arrays:
        return np.ascontiguousarray(a_st), np.ascontiguousarray(l_st)
    return _to_bytes(a_st), _to_bytes(l_st), att_n / SR


def _mc(name, model, harm, timbre, morph, **kw):
    p = dict(MACRO_PATCH, name=name, macro=model, harm=harm, timbre=timbre, morph=morph)
    p.update(kw)
    return p


MACRO_PATCHES = [
    # analog: the full engine, voices and ladder from the three controls
    _mc("Prophet Brass", 0, 0.5, 0.45, 0.1, fa=0.08, fd=0.5, fs=0.55, fenv=2.4, a=0.04, d=0.4, s=0.8, r=0.35,
        res=1.4, sub=0.2),
    _mc("Juno Strings", 0, 0.65, 0.55, 0.85, fa=0.3, fd=1.0, fs=0.7, fenv=0.8, a=0.35, d=0.6, s=0.85, r=0.8,
        res=0.9, sub=0.0, drive=0.1),
    _mc("Mono Lead", 0, 0.3, 0.5, 0.0, fd=0.35, fs=0.4, fenv=2.6, a=0.005, d=0.3, s=0.75, r=0.25, res=2.6, drive=0.4),
    _mc("Supersaw", 0, 1.0, 0.7, 0.0, fenv=1.0, fd=0.6, fs=0.6, a=0.01, d=0.4, s=0.85, r=0.4, res=1.0, sub=0.15),
    _mc("Square Bass", 0, 0.15, 0.28, 0.9, fenv=3.0, fd=0.2, fs=0.15, a=0.002, d=0.25, s=0.6, r=0.15, res=1.8,
        sub=0.6, drive=0.35),
    _mc("Saw Bass", 0, 0.3, 0.3, 0.0, fenv=3.2, fd=0.22, fs=0.2, a=0.002, d=0.3, s=0.6, r=0.15, res=2.2,
        sub=0.45, drive=0.45),
    _mc("Poly Pad", 0, 0.8, 0.42, 0.55, fa=0.6, fd=1.5, fs=0.6, fenv=1.4, a=0.6, d=0.8, s=0.85, r=1.2, res=1.2,
        sub=0.1),
    _mc("Sync Scream", 2, 0.7, 0.6, 0.4, fenv=1.6, fd=0.5, fs=0.5, a=0.005, d=0.3, s=0.8, r=0.3, res=1.3,
        drive=0.5, sub=0.15),
    _mc("Sync Bass", 2, 0.3, 0.32, 0.15, fenv=2.6, fd=0.25, fs=0.25, a=0.002, d=0.3, s=0.6, r=0.15, res=1.6,
        sub=0.5, drive=0.4),
    # the rest of the macro: folds, vowels, organs, tables, strings and resonators
    _mc("Folded Sine", 1, 0.3, 0.55, 0.3, d=0.5, s=0.7),
    _mc("Vowel Choir", 3, 0.5, 0.5, 0.3, a=0.25, d=0.6, s=0.85, r=0.8),
    _mc("Organ Pipes", 4, 0.15, 0.3, 0.0, a=0.02, d=0.2, s=0.9, r=0.25),
    _mc("Plucked String", 6, 0.3, 0.7, 0.6, decay=0.5),
    _mc("Twin Strings", 6, 0.8, 0.5, 0.8, decay=0.7),
    _mc("Marimba", 7, 0.45, 0.4, 0.25, decay=0.3),
    _mc("Bell Bowl", 7, 0.8, 0.6, 0.85, decay=0.9),
    _mc("Kalimba", 7, 0.2, 0.55, 0.35, decay=0.35),
    _mc("Bowed String", 8, 0.1, 0.5, 0.7, a=0.25, d=0.3, s=0.85, r=0.6),
    _mc("Bowed Glass", 8, 0.75, 0.6, 0.85, a=0.4, d=0.4, s=0.8, r=1.0),
    _mc("Blown Pipe", 9, 0.05, 0.35, 0.8, a=0.15, d=0.3, s=0.85, r=0.4),
]


_WAV_CACHE = {}


def _sample_audio(name):
    """A sample file decoded once (mono, at SR, at most 12 s), kept for the next notes:
    decoding a long 24-bit WAV for every pitch made renders slow and missed notes."""
    path = os.path.join(SAMPLE_DIR, name)
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return None
    x = _WAV_CACHE.get(key)
    if x is None:
        x = read_wav(path, SR, max_sec=12.0)
        if len(_WAV_CACHE) > 6:
            _WAV_CACHE.clear()
        _WAV_CACHE[key] = x
    return x


def render_sample(midi, p, arrays=False):
    """A Sample track's note: the WAV pitched from its root to midi (plus tune),
    trimmed to start..end, optionally reversed; loop=True sustains it."""
    x = _sample_audio(p["sample"]) if p.get("sample") else None
    if x is None or len(x) < 16:
        x = np.zeros(int(0.05 * SR), np.float32)
    n = len(x)
    a, b = int(max(0.0, min(1.0, p.get("start", 0.0))) * n), int(max(0.0, min(1.0, p.get("end", 1.0))) * n)
    if b - a < 16:
        a, b = 0, n
    x = x[a:b]
    if p.get("rev"):
        x = x[::-1]
    sl = int(p.get("slices", 0) or 0)
    if sl:
        # slice mode: the note picks a slice (root = slice 1), played at its own pitch
        idx = (midi - p.get("root", 60)) % sl
        n = len(x)
        x = x[idx * n // sl:(idx + 1) * n // sl]
        midi = p.get("root", 60)
    r = 2.0 ** ((midi - p.get("root", 60) + p.get("tune", 0)) / 12.0)
    if p.get("grain"):
        y = _grain_cloud(x, r, p)
    else:
        m = max(16, int(len(x) / r))
        y = np.interp(np.arange(m) * r, np.arange(len(x)), x).astype(np.float32)
    fade = min(len(y) // 4, int(0.004 * SR))
    if fade:
        y[:fade] *= np.linspace(0, 1, fade)
        y[-fade:] *= np.linspace(1, 0, fade)
    if len(y) > int(14 * SR):                          # a pitched-down note is capped, it only grows memory
        y = y[:int(14 * SR)]
        y[-int(0.01 * SR):] *= np.linspace(1, 0, int(0.01 * SR))
    st = np.repeat(y[:, None], 2, axis=1) * (GAIN * 2.5)
    loop = None
    if p.get("loop"):
        # the loop is the sample from a few samples in, wrapped: the same audio once,
        # not an attack copy plus a loop copy
        k = min(64, len(st) // 2)
        loop = np.concatenate([st[k:], st[:k]])
        st = st[:k]
    if arrays:
        return np.ascontiguousarray(st, np.float32), (np.ascontiguousarray(loop, np.float32) if loop is not None else None)
    return _to_bytes(st), (_to_bytes(loop) if loop is not None else None), len(y) / SR


def render_note(midi, p, tone=0.0, res_add=0.0, attack_len=None, loop_len=2.0, xfade=0.25, wet=False,
                arrays=False):
    """Return (attack int16 stereo bytes, loop int16 stereo bytes, total_attack_sec).
    wet=True returns the reverb-only version of the same note (with a ringing tail
    for non-sustaining sounds)."""
    if p.get("sample"):
        return render_sample(midi, p, arrays)
    if p.get("macro") is not None:
        return render_macro(midi, p, arrays)
    f0 = 440.0 * 2 ** ((midi - 69) / 12.0)
    if attack_len is None:
        attack_len = max(0.6, p["a"] + p["d"] * 0.8, p["fa"] + p["fd"] * 0.8) + 0.2
        attack_len = min(attack_len, 3.0)
    total = attack_len + loop_len + xfade
    n = int(total * SR)
    nb = n // BLOCK + 2
    brate = SR / BLOCK

    # filter cutoff per block: base * keytrack * envelope
    fenv = _adsr(nb, p["fa"], p["fd"], p["fs"], brate)
    # freeze envelopes after the attack segment so the loop is steady
    freeze = int(attack_len * brate)
    fenv[freeze:] = fenv[min(freeze, nb - 1)]
    keytrack = (f0 / 261.6) ** 0.5
    fc = p["cutoff"] * (2 ** tone) * keytrack * (2 ** (p["fenv"] * fenv))
    fc = np.clip(fc, 40, SR * 0.45).astype(np.float32)
    q = max(0.5, p["res"] + res_add)

    tb = np.arange(nb) / brate
    duty = 0.5 + 0.4 * p.get("pwm", 0.0) * np.sin(2 * np.pi * tb * (2.0 / loop_len))  # LFO fits loop
    duty = np.clip(duty, 0.05, 0.95)

    out = np.zeros((n, 2), np.float32)
    idx_n = np.arange(n)
    b = idx_n // BLOCK
    u = ((idx_n % BLOCK) / BLOCK).astype(np.float32)

    eng = p.get("engine", "va")
    if eng != "va":
        out = _other_engine(eng, p, f0, n, attack_len)
    for wave, cents, level, pan, octv in (p["oscs"] if eng == "va" else ()):
        f = f0 * (2 ** octv) * 2 ** (cents / 1200.0)
        hmax = int(min(NH - 1, (SR * 0.46) / f))
        if hmax < 1:
            continue
        k = np.arange(1, hmax + 1, dtype=np.float32)
        base = _vox_amps(k, f, duty) if wave == "vox" else _harm_amps(wave, k, duty)
        w = (k[None, :] * f) / fc[:, None]
        if p.get("ladder"):
            # Moog-style 4-pole ladder: 1 / ((1 + jw)^4 + k), k = feedback 0..4
            kk = min(3.9, max(0.0, (q - 0.5) * 1.0))
            jw = 1.0 + 1j * w
            filt = 1.0 / np.abs(jw ** 4 + kk)
            filt = np.minimum(filt, 6.0).astype(np.float32)
        else:
            filt = 1.0 / np.sqrt((1 - w * w) ** 2 + (w / q) ** 2)
        amps = base * filt                                   # (nb, H)
        spec = np.zeros((nb, NH + 1), np.complex64)
        spec[:, 1:hmax + 1] = -1j * amps * (TABLE / 2)       # sine phase
        tables = np.fft.irfft(spec, n=TABLE, axis=1).astype(np.float32)
        phase = (np.random.rand() + f * idx_n / SR) % 1.0
        pos = phase * TABLE
        i0 = pos.astype(np.int32)
        fr = (pos - i0).astype(np.float32)
        i1 = (i0 + 1) % TABLE
        s0 = tables[b, i0] * (1 - fr) + tables[b, i1] * fr
        s1 = tables[b + 1, i0] * (1 - fr) + tables[b + 1, i1] * fr
        sig = (s0 * (1 - u) + s1 * u) * level
        gl = math.cos((pan + 1) * math.pi / 4)
        gr = math.sin((pan + 1) * math.pi / 4)
        out[:, 0] += sig * gl
        out[:, 1] += sig * gr

    if isinstance(p.get("noise"), (int, float)) and p["noise"] > 0:      # (the noise engine keeps a dict here)
        nz = np.random.RandomState(7).randn(n).astype(np.float32) * p["noise"]
        nz = np.cumsum(nz) * 0.02 if p.get("noise_dark") else nz
        nz -= np.convolve(nz, np.ones(64) / 64, "same")
        out += nz[:, None] * 0.3
    if p.get("drive"):
        d = p["drive"]
        out = np.tanh(out * (1 + 4 * d)) / (1 + 1.5 * d)
    # amplitude envelope (sample rate), frozen after attack
    aenv = _adsr(n, p["a"], p["d"], p["s"], SR)
    fs_ = int(attack_len * SR)
    aenv[fs_:] = aenv[fs_ - 1]
    out *= aenv[:, None]

    na = int(attack_len * SR)
    nl = int(loop_len * SR)
    nx = n - na - nl
    sustains = p["s"] > 0.001
    if wet:
        ir = reverb_ir()
        if sustains:
            out = _convolve(out, ir, n)
        else:
            out = _convolve(out[:na], ir, na + len(ir))
            return _to_bytes(out), None, attack_len
    attack = out[:na]
    loop = out[na:na + nl].copy()
    tail = out[na + nl:na + nl + nx]
    ramp = np.linspace(0, 1, nx, dtype=np.float32)[:, None]
    loop[:nx] = loop[:nx] * ramp + tail * (1 - ramp)

    if arrays:
        g = GAIN * p.get("gain", 1.0)
        return (np.ascontiguousarray(attack * g, np.float32),
                np.ascontiguousarray(loop * g, np.float32) if sustains else None)
    return _to_bytes(attack), (_to_bytes(loop) if p["s"] > 0.001 else None), attack_len


GAIN = 0.12


def _other_engine(eng, p, f0, n, attack_len):
    """Raw stereo signal for the non-VA engines (envelopes are applied after)."""
    rng = np.random.RandomState(int(f0 * 10) % 100000)
    t = np.arange(n, dtype=np.float32) / SR
    out = np.zeros((n, 2), np.float32)
    if eng == "fm":
        q = p["fm"]
        idx = q["idx_s"] + (q["idx"] - q["idx_s"]) * np.exp(-t / max(0.01, q["idx_t"]))
        idx = np.where(t < attack_len, idx, idx[min(n - 1, int(attack_len * SR))])   # steady loop
        for ch, c in ((0, -q["det"]), (1, q["det"])):
            fc = f0 * 2 ** (c / 1200.0)
            mod = np.sin(2 * np.pi * fc * q["ratio"] * t + rng.rand() * 6.28)
            out[:, ch] = np.sin(2 * np.pi * fc * t + idx * mod)
        return out * 1.5
    if eng == "pluck":
        q = p["pluck"]
        b = q["bright"]
        P = int(math.ceil(2 * SR / f0))                    # period in samples at ~2x rate
        rate = (P + 0.5 - 0.5 * b) * f0                    # loss filter adds (0.5-0.5b) samples of delay
        N = int(n * rate / SR) + P + 2
        y = np.zeros(N, np.float32)
        ex = rng.uniform(-1, 1, P).astype(np.float32)
        for _ in range(int((1 - b) * 4) + 1):              # darker pick = smoother excitation
            ex = 0.5 * (ex + np.roll(ex, 1))
        y[1:P + 1] = ex - ex.mean()
        t60 = q["t60"] * (261.6 / f0) ** 0.35              # higher strings ring shorter
        g = 10 ** (-3.0 * (P / rate) / max(0.05, t60))     # loss per trip round the string
        for s0 in range(P + 1, N - P, P):
            seg = y[s0 - P:s0]
            prev = y[s0 - P - 1:s0 - 1]
            # Karplus-Strong: average with the previous sample (string loss);
            # brighter strings average less
            y[s0:s0 + P] = g * (seg * (0.5 + 0.5 * b) + prev * (0.5 - 0.5 * b))
        sig = np.interp(np.arange(n) * (rate / SR), np.arange(N), y).astype(np.float32)
        body = q.get("body", 0)
        if body:                                           # a touch of a resonant body
            d = int(SR * 0.0023)
            sig[d:] += body * sig[:-d]
        out[:, 0] = sig
        out[1:, 1] = sig[:-1] * 0.97
        pk = float(np.abs(out).max()) or 1.0
        return out * (1.7 / pk)
    if eng == "noise":
        q = p["noise"]
        for ch in (0, 1):
            w = rng.standard_normal(n).astype(np.float32)
            F = np.fft.rfft(w)
            hz = np.fft.rfftfreq(n, 1.0 / SR)
            G = np.full(len(hz), q["floor"], np.float32)
            kmax = int(min(40, (SR * 0.45) // f0))
            for k in range(1, kmax + 1):
                G += (k ** -q["tilt"]) * np.exp(-((hz - k * f0) / (f0 * q["width"] * k ** 0.5)) ** 2)
            G *= 1.0 / np.sqrt(1 + (hz / p["cutoff"]) ** 4)
            out[:, ch] = np.fft.irfft(F * G, n)
        pk = float(np.abs(out).max()) or 1.0
        return out * (1.7 / pk)
    return out


def _to_bytes(x):
    y = np.clip(x * GAIN * 32767, -32767, 32767).astype(np.int16)
    return y.tobytes()


# ---------------------------------------------------------------- drums
def _noise(n, seed):
    return np.random.default_rng(seed).uniform(-1, 1, n).astype(np.float32)


def drum_kit():
    """Return dict name -> mono float32 arrays (rendered once)."""
    t = lambda sec: np.arange(int(sec * SR)) / SR
    kit = {}
    tt = t(0.45)
    f = 45 + 110 * np.exp(-tt * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    kit["kick"] = (np.sin(ph) * np.exp(-tt * 7.5) * 1.3).astype(np.float32)
    tt = t(0.25)
    nz = _noise(len(tt), 1)
    tone = np.sin(2 * np.pi * 190 * tt) * np.exp(-tt * 22)
    kit["snare"] = ((nz - np.roll(nz, 1) * .6) * np.exp(-tt * 16) * .7 + tone * .6).astype(np.float32)
    tt = t(0.07)
    nz = _noise(len(tt), 2)
    hp = nz - np.roll(nz, 1)
    kit["hat"] = (hp * np.exp(-tt * 70) * .45).astype(np.float32)
    tt = t(0.3)
    nz = _noise(len(tt), 3)
    hp = nz - np.roll(nz, 1)
    kit["ohat"] = (hp * np.exp(-tt * 12) * .35).astype(np.float32)
    tt = t(0.12)
    kit["click"] = (np.sin(2 * np.pi * 1800 * tt) * np.exp(-tt * 60) * .5).astype(np.float32)
    # clap: three quick noise bursts and a short tail, band-limited
    tt = t(0.3)
    nz = _noise(len(tt), 4)
    bp = nz - np.roll(nz, 2)
    env = np.zeros(len(tt))
    for d in (0.0, 0.011, 0.022):
        env += np.where(tt >= d, np.exp(-(tt - d) * 140), 0)
    env += np.where(tt >= 0.03, np.exp(-(tt - 0.03) * 18) * 0.5, 0)
    kit["clap"] = (bp * env * 0.45).astype(np.float32)
    # rimshot / side-stick
    tt = t(0.07)
    kit["rim"] = ((np.sin(2 * np.pi * 820 * tt) * 0.7 + _noise(len(tt), 5) * 0.4) * np.exp(-tt * 75) * 0.7).astype(np.float32)
    # tom: pitched body with a downward bend
    tt = t(0.4)
    f = 95 + 70 * np.exp(-tt * 18)
    kit["tom"] = (np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 9) * 0.9).astype(np.float32)
    # shaker
    tt = t(0.09)
    nz = _noise(len(tt), 6)
    hp = nz - np.roll(nz, 1)
    kit["shk"] = (hp * (np.minimum(tt / 0.012, 1) * np.exp(-tt * 45)) * 0.28).astype(np.float32)
    return kit


def _env(tt, rate, att=0.0):
    e = np.exp(-tt * rate)
    if att:
        e *= np.minimum(tt / att, 1.0)
    return e


def _hp(nz, k=1):
    return nz - np.roll(nz, k)


def drum_kit_style(style):
    """The other built-in kits, made the same way as drum_kit()."""
    t = lambda sec: np.arange(int(sec * SR)) / SR
    kit = dict(drum_kit())
    if style == "808":
        tt = t(1.1)
        f = 48 + 60 * np.exp(-tt * 30)
        kit["kick"] = (np.tanh(np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(tt, 3.2) * 1.6) * 0.95).astype(np.float32)
        tt = t(0.3)
        nz = _noise(len(tt), 11)
        tone = (np.sin(2 * np.pi * 238 * tt) + 0.6 * np.sin(2 * np.pi * 476 * tt)) * _env(tt, 26)
        kit["snare"] = (_hp(nz) * _env(tt, 18) * 0.5 + tone * 0.45).astype(np.float32)
        tt = t(0.06)
        sq = sum(np.sign(np.sin(2 * np.pi * f0 * tt)) for f0 in (205, 304, 369, 522, 540, 800))
        kit["hat"] = (_hp(sq / 6.0, 1) * _env(tt, 80) * 0.5).astype(np.float32)
        tt = t(0.45)
        sq = sum(np.sign(np.sin(2 * np.pi * f0 * tt)) for f0 in (205, 304, 369, 522, 540, 800))
        kit["ohat"] = (_hp(sq / 6.0, 1) * _env(tt, 8) * 0.38).astype(np.float32)
        tt = t(0.07)
        kit["rim"] = (np.sin(2 * np.pi * 1690 * tt) * _env(tt, 90) * 0.8).astype(np.float32)
        tt = t(0.6)
        f = 110 + 25 * np.exp(-tt * 12)
        kit["tom"] = (np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(tt, 6) * 0.9).astype(np.float32)
        tt = t(0.05)
        kit["shk"] = (_hp(_noise(len(tt), 12)) * _env(tt, 60, 0.004) * 0.3).astype(np.float32)
    elif style == "909":
        tt = t(0.5)
        f = 52 + 180 * np.exp(-tt * 45)
        body = np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(tt, 9)
        click = _hp(_noise(len(tt), 21)) * _env(tt, 400) * 0.5
        kit["kick"] = (np.tanh((body + click) * 1.4) * 0.95).astype(np.float32)
        tt = t(0.28)
        nz = _noise(len(tt), 22)
        tone = np.sin(2 * np.pi * 180 * tt) * _env(tt, 30) + np.sin(2 * np.pi * 330 * tt) * _env(tt, 40) * 0.5
        kit["snare"] = (_hp(nz) * _env(tt, 11) * 0.6 + tone * 0.5).astype(np.float32)
        tt = t(0.09)
        kit["hat"] = (_hp(_hp(_noise(len(tt), 23)), 1) * _env(tt, 55) * 0.32).astype(np.float32)
        tt = t(0.5)
        kit["ohat"] = (_hp(_hp(_noise(len(tt), 24)), 1) * _env(tt, 6.5) * 0.26).astype(np.float32)
        tt = t(0.35)
        nz = _hp(_noise(len(tt), 25), 2)
        env = sum(np.where(tt >= d, np.exp(-(tt - d) * 160), 0) for d in (0.0, 0.009, 0.018, 0.027))
        env = env + np.where(tt >= 0.035, np.exp(-(tt - 0.035) * 14) * 0.6, 0)
        kit["clap"] = (nz * env * 0.42).astype(np.float32)
    elif style == "Lo-fi":
        for k, v in list(kit.items()):
            if k == "click":
                continue
            x = np.round(v * 12) / 12                         # crush the bits
            x = np.repeat(x[::3], 3)[:len(v)]                 # and the sample rate
            lp = np.convolve(x, np.ones(5) / 5, mode="same")  # dull it
            kit[k] = (lp * 1.15).astype(np.float32)
        tt = t(0.45)
        f = 42 + 70 * np.exp(-tt * 22)
        kit["kick"] = (np.tanh(np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(tt, 6) * 2.2) * 0.8).astype(np.float32)
    elif style == "Acoustic":
        tt = t(0.5)
        f = 60 + 55 * np.exp(-tt * 40)
        body = np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(tt, 10)
        beater = np.convolve(_noise(len(tt), 31), np.ones(8) / 8, "same") * _env(tt, 120) * 0.9
        kit["kick"] = ((body + beater) * 1.0).astype(np.float32)
        tt = t(0.35)
        nz = np.convolve(_noise(len(tt), 32), np.array([1, -0.3, -0.3]), "same")
        tone = np.sin(2 * np.pi * 200 * tt) * _env(tt, 25) + np.sin(2 * np.pi * 290 * tt) * _env(tt, 30) * 0.6
        kit["snare"] = (nz * _env(tt, 13) * 0.55 + tone * 0.4).astype(np.float32)
        tt = t(0.12)
        hh = _hp(_noise(len(tt), 33)) * _env(tt, 40, 0.002)
        kit["hat"] = (hh * 0.35).astype(np.float32)
        tt = t(0.8)
        kit["ohat"] = (_hp(_noise(len(tt), 34)) * _env(tt, 4.5, 0.003) * 0.25).astype(np.float32)
        tt = t(0.5)
        f = 120 + 30 * np.exp(-tt * 10)
        tom = np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(tt, 7) + _noise(len(tt), 35) * _env(tt, 60) * 0.15
        kit["tom"] = (tom * 0.9).astype(np.float32)
        tt = t(0.1)
        kit["rim"] = ((np.sin(2 * np.pi * 520 * tt) + np.sin(2 * np.pi * 1450 * tt) * 0.6) * _env(tt, 55) * 0.6).astype(np.float32)
    return kit


BUILTIN_KITS = ["Classic", "808", "909", "Lo-fi", "Acoustic", "Modular", "Industrial", "Glitch"]
DRUM_LANES = ["kick", "snare", "clap", "rim", "tom", "hat", "ohat", "shk"]
# file names a sample kit may use for each lane (samples/<kit>/<name>.wav)
LANE_ALIASES = {"kick": ("kick", "bd", "bassdrum", "kik"), "snare": ("snare", "sd", "snr"),
                "clap": ("clap", "cp", "hc"), "rim": ("rim", "rs", "rimshot", "sidestick", "stick"),
                "tom": ("tom", "lt", "mt", "ht", "tom1"), "hat": ("hat", "ch", "hh", "closedhat", "hihat"),
                "ohat": ("ohat", "oh", "openhat"), "shk": ("shk", "shaker", "sh", "perc", "cowbell", "cb")}


def sample_kit_names(folder):
    """Kits made of WAV files: one sub-folder each, inside folder."""
    try:
        return sorted(d for d in os.listdir(folder) if not d.startswith(".") and os.path.isdir(os.path.join(folder, d))
                      and any(f.lower().endswith(".wav") for f in os.listdir(os.path.join(folder, d))))
    except OSError:
        return []


def kit_names(folder=None):
    return BUILTIN_KITS + (sample_kit_names(folder) if folder else [])


def read_wav(path, sr=None, max_sec=2.5):
    """Mono float32 at sr from a PCM WAV (8/16/24/32-bit int or 32-bit float)."""
    import wave
    import struct
    sr = sr or SR
    try:
        w = wave.open(path, "rb")
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(min(n, int(rate * max_sec)))
        w.close()
        if width == 1:
            x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128.0
        elif width == 2:
            x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
        elif width == 3:
            b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
            x = ((b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)) << 8 >> 8).astype(np.float32) / 8388608.0
        else:
            x = np.frombuffer(raw, "<i4").astype(np.float32) / 2147483648.0
    except Exception:
        x, ch, rate = _read_float_wav(path, max_sec)
        if x is None:
            return None
    if ch > 1:
        x = x[: len(x) // ch * ch].reshape(-1, ch).mean(axis=1)
    if rate != sr and len(x) > 1:
        m = int(len(x) * sr / rate)
        x = np.interp(np.arange(m) * (rate / sr), np.arange(len(x)), x)
    pk = float(np.max(np.abs(x))) if len(x) else 0.0
    if pk < 1e-4:
        return None
    x = x / pk * 0.9
    fade = min(len(x), int(0.004 * sr))
    if fade:
        x[-fade:] *= np.linspace(1, 0, fade)
    return x.astype(np.float32)


def _read_float_wav(path, max_sec):
    """The wave module can't read IEEE float WAVs; parse those by hand."""
    import struct
    try:
        with open(path, "rb") as f:
            d = f.read()
        if d[:4] != b"RIFF" or d[8:12] != b"WAVE":
            return None, 0, 0
        i, fmt, data = 12, None, None
        while i + 8 <= len(d):
            cid, size = d[i:i + 4], struct.unpack("<I", d[i + 4:i + 8])[0]
            if cid == b"fmt ":
                fmt = struct.unpack("<HHIIHH", d[i + 8:i + 24])
            elif cid == b"data":
                data = d[i + 8:i + 8 + size]
            i += 8 + size + (size & 1)
        if not fmt or data is None or fmt[0] not in (3, 0xFFFE) or fmt[5] != 32:
            return None, 0, 0
        ch, rate = fmt[1], fmt[2]
        x = np.frombuffer(data[: int(rate * max_sec) * ch * 4], "<f4").astype(np.float32)
        return x, ch, rate
    except Exception:
        return None, 0, 0


def sample_kit(folder, name):
    """Lanes found in samples/<name>; missing lanes come from the Classic kit."""
    kit = dict(drum_kit())
    d = os.path.join(folder, name)
    try:
        files = {os.path.splitext(f)[0].lower().replace(" ", "").replace("_", "").replace("-", ""): f
                 for f in os.listdir(d) if f.lower().endswith(".wav")}
    except OSError:
        return kit
    for lane, f in lane_files(files).items():
        x = read_wav(os.path.join(d, f))
        if x is not None:
            kit[lane] = x * 0.85
    return kit


# open hat before closed hat, so "openhat" doesn't land on the closed hat
_LANE_PRI = ["ohat", "hat", "kick", "snare", "clap", "rim", "tom", "shk"]


def lane_files(files):
    """{lane: file} from {simplified name: file}: exact names win, then a name
    that starts or ends with an alias (BD_kick 01 -> kick)."""
    out = {}
    for exact in (True, False):
        for key in sorted(files):
            if files[key] in out.values():
                continue
            base = key.rstrip("0123456789")
            for lane in _LANE_PRI:
                if lane in out:
                    continue
                names = LANE_ALIASES[lane]
                if exact and base in names or not exact and any(base.startswith(a) or base.endswith(a) for a in names):
                    out[lane] = files[key]
                    break
    return out


def kit_arrays(gain=0.5, kit=None):
    kit = matched(builtin_kit("Classic"), drum_kit()) if kit is None else kit
    return {k: (np.repeat((v * gain)[:, None], 2, axis=1).astype(np.float32), None) for k, v in kit.items()}


def _loud(x):
    """Rough loudness: RMS of the first 120 ms (where a drum hit lives)."""
    n = min(len(x), int(0.12 * SR))
    return float(np.sqrt(np.mean(x[:n] ** 2))) if n else 0.0


def matched(kit, ref):
    """Each lane brought to the loudness of the same lane in ref, so switching
    kits (or loading your own samples) keeps the mix where it was."""
    out = {}
    for k, v in kit.items():
        a, b = _loud(v), _loud(ref.get(k, v))
        g = b / a if a > 1e-6 else 1.0
        out[k] = np.clip(v * min(g, 8.0), -1.0, 1.0).astype(np.float32)
    return out


METRO_SOUNDS = ["Click", "Wood", "Beep", "Rim"]


def metro_click(name):
    """Metronome sounds: (bar downbeat, other beats) as mono float32."""
    def one(f, sec, accent):
        t = np.arange(int(sec * SR)) / SR
        if name == "Wood":
            x = (np.sin(2 * np.pi * f * t) + 0.55 * np.sin(2 * np.pi * f * 2.76 * t)) * np.exp(-t * 55)
            x += _hp(_noise(len(t), 41)) * np.exp(-t * 400) * 0.25
        elif name == "Beep":
            x = np.sin(2 * np.pi * f * t) * np.minimum(t / 0.002, 1) * np.exp(-t * 30)
        elif name == "Rim":
            x = (np.sin(2 * np.pi * f * 0.55 * t) * 0.7 + _hp(_noise(len(t), 42)) * 0.5) * np.exp(-t * 80)
        else:
            x = np.sin(2 * np.pi * f * t) * np.exp(-t * 70)
        x = x / (np.max(np.abs(x)) + 1e-9) * (0.6 if accent else 0.45)
        fade = int(0.004 * SR)
        x[-fade:] *= np.linspace(1, 0, fade)
        return x.astype(np.float32)
    hi, lo = {"Wood": (1250, 880), "Beep": (1760, 1320), "Rim": (2900, 2200)}.get(name, (2000, 1500))
    return one(hi, 0.1, True), one(lo, 0.1, False)


def metro_arrays(name):
    return tuple((np.repeat(x[:, None], 2, axis=1), None) for x in metro_click(name))


KITS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kits")


def builtin_kit(name):
    """A built-in kit: the WAVs tools/make_kits.py rendered into kits/<name>/,
    or (if they are missing) the older kit synthesized here."""
    if os.path.isdir(os.path.join(KITS_DIR, name)):
        return sample_kit(KITS_DIR, name)          # lanes missing there come from drum_kit()
    return drum_kit() if name == "Classic" else drum_kit_style(name)


def all_kits(folder=None, gain=0.5):
    """Every kit, ready for the engine: {name: {lane: (stereo, None)}}.
    Levels follow the original Classic kit, so older songs keep their mix."""
    ref = drum_kit()
    out = {}
    for k in BUILTIN_KITS:
        out[k] = kit_arrays(gain, matched(builtin_kit(k), ref))
    for k in (sample_kit_names(folder) if folder else []):
        try:
            out[k] = kit_arrays(gain, matched(sample_kit(folder, k), ref))
        except Exception as ex:
            print("sample kit %s: %s" % (k, ex), flush=True)
    return out


def mono_to_bytes(x, gain=0.5):
    y = np.clip(x * gain * 32767, -32767, 32767).astype(np.int16)
    return np.repeat(y[:, None], 2, axis=1).tobytes()


# 16-step patterns. Any letter plays; "g" is a soft ghost note.
# Parts: kick snare hat ohat clap rim tom shk.  "swing" delays the off 16ths (0..0.5 of a step).
def _beat(name, swing=0.0, **parts):
    p = {k: v for k, v in parts.items()}
    p["swing"] = swing
    return (name, p)


BEATS = [
    ("Off", None),
    _beat("Four Floor", kick="K...K...K...K...", snare="....S.......S...", hat="..h...h...h...h."),
    _beat("Boom Bap", 0.12, kick="K......K..K.....", snare="....S.......S...", hat="h.h.h.h.h.h.h.h."),
    _beat("Synthpop", kick="K.....K.K.......", snare="....S.......S...", hat="hhhhhhhhhhhhhhhh", ohat="......o.......o."),
    _beat("Half Time", kick="K..........K....", snare="........S.......", hat="h...h...h...h...", ohat="..............o."),
    _beat("House", kick="K...K...K...K...", clap="....C.......C...", ohat="..o...o...o...o.", hat="g.g.g.g.g.g.g.g."),
    _beat("Disco", kick="K...K...K...K...", snare="....S.......S...", hat="hhhhhhhhhhhhhhhh", ohat="..o...o...o...o."),
    _beat("Lo-fi", 0.22, kick="K.....K...K.....", snare="....S.......S..g", hat="h.h.h.h.h.h.h.h.", rim="..........r....."),
    _beat("Trap", kick="K......K.K......", clap="........C.......", hat="hhhhhhhhhhhhhhhh", ohat="...............o"),
    _beat("Funk", 0.08, kick="K..K..K...K..K..", snare="....S..g.g..S..g", hat="hhhhhhhhhhhhhhhh"),
    _beat("Breakbeat", kick="K.K.......KK....", snare="....S..g.g..S..S", hat="h.h.h.h.h.h.h.h."),
    _beat("Rock", kick="K.......K.K.....", snare="....S.......S...", hat="h.h.h.h.h.h.h.h."),
    _beat("Drum & Bass", kick="K.........K.....", snare="....S.......S..g", hat="h.h.h.h.h.h.h.h.", shk="gggggggggggggggg"),
    _beat("Dembow", kick="K...K...K...K...", snare="...S..S....S..S.", hat="h.h.h.h.h.h.h.h."),
    _beat("Bossa", kick="K..KK..KK..KK..K", rim="r..r..r...r..r..", shk="ssssssssssssssss"),
    _beat("Afrobeat", 0.1, kick="K..K....K..K....", snare="....S..g....S...", shk="s.ss.ss.s.ss.ss.", ohat="..o.......o....."),
    _beat("Shuffle", 0.33, kick="K.....K.K.....K.", snare="....S.......S...", hat="h.h.h.h.h.h.h.h."),
    _beat("Electro", kick="K.....K...K.....", clap="....C.......C...", rim="..r...r....r..r.", hat="..h...h...h...h."),
    _beat("Tribal", kick="K.......K..K....", tom="..T..T....T.T.T.", shk="s.s.s.s.s.s.s.s.", rim="....r.......r..."),
    _beat("Jungle", 0.05, kick="K.K.......K.K...", snare="....S..g.gS.S..g", hat="h.hhh.hhh.hhh.hh", ohat="..............o."),
    _beat("Techno", kick="K...K...K...K...", clap="....C.......C...", ohat="..o...o...o...o.", hat="ghhhghhhghhhghhh", rim="...r..r...r.r..."),
    _beat("Minimal Techno", kick="K...K...K...K...", rim="..r..r....r..r..", hat="..g...g...g...g.", shk="g.g.g.g.g.g.g.g."),
    _beat("2-Step Garage", 0.25, kick="K.....K...K..K..", clap="....C.......C...", hat="..h...h...h...h.", shk="gsgsgsgsgsgsgsgs"),
    _beat("UK Funky", 0.15, kick="K...K...K...K...", clap="....C.......C...", tom="...T......T..T..", shk="gsgsgsgsgsgsgsgs", rim="..r..r....r....."),
    _beat("Neo-Soul", 0.28, kick="K......K..K..g..", snare="....S..g....S.g.", hat="h.h.h.h.h.h.h.h."),
    _beat("Nu-Disco", kick="K...K...K...K...", clap="....C.......C...", ohat="..o...o...o...o.", hat="hhhhhhhhhhhhhhhh", tom="..............T."),
    _beat("Afro House", 0.1, kick="K...K...K...K...", rim="..r..r....r..r..", shk="s.ss.ss.s.ss.ss.", tom="......T.......T.", ohat="..o...o...o...o."),
    _beat("Footwork", kick="K..K..K...K..K..", clap="....C.......C...", hat="hhhhhhhhhhhhhhhh", tom="......T.....T..."),
]


# ------------------------------------------------------------------ synth bass
BASS_MODES = ["Synth", "Pulse", "Octaves", "Walk", "Sub + Patch", "Patch", "Off"]


def render_bass(midi, sr=22050, secs=2.4):
    """A round, punchy synth bass note: a saw whose upper harmonics close down
    fast (a plucky filter envelope), a solid sine fundamental under it, and a
    little drive. Stereo-identical (bass sits in the middle). Returns (a, None)."""
    f = 440.0 * 2 ** ((midi - 69) / 12.0)
    n = int(secs * sr)
    t = np.arange(n, dtype=np.float32) / sr
    ph = (2 * np.pi * f) * t
    nh = int(min(14, (sr * 0.42) // f))
    x = np.zeros(n, np.float32)
    for h in range(1, nh + 1):
        x += (np.sin(ph * h) * (0.55 / h)) * np.exp(-t * (4.0 + 5.5 * h))
    x += np.sin(ph) * 0.75 + np.sin(ph * 2) * 0.10 * np.exp(-t * 2.0)
    att = np.minimum(1.0, t / 0.003)
    env = att * (0.62 + 0.38 * np.exp(-t * 7.0)) * np.exp(-t * 0.25)
    x = np.tanh(x * env * 1.6) * 0.62
    x = x.astype(np.float32)
    return (np.repeat(x[:, None], 2, 1), None)
