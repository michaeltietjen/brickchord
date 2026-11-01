"""Brickchord analog-VA engine.

Notes are rendered offline with NumPy as band-limited wavetables whose
harmonics are shaped per control block by a resonant 2-pole low-pass
response, so filter sweeps, detuned saws, PWM and a sub oscillator all
come out alias-free and cheap enough for an ARM handheld.
Each note is split into an attack segment and a seamless sustain loop.
"""
import math
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
    # pulse with time-varying duty
    return (2.0 / (np.pi * k))[None, :] * np.sin(np.pi * k[None, :] * duty[:, None])


WAVES = ["saw", "square", "pulse", "tri", "sine"]

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


def edited_patch(base, edits):
    """Apply Sound Editor edits to a base patch (returns a new dict)."""
    p = dict(base)
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


def render_note(midi, p, tone=0.0, res_add=0.0, attack_len=None, loop_len=2.0, xfade=0.25, wet=False,
                arrays=False):
    """Return (attack int16 stereo bytes, loop int16 stereo bytes, total_attack_sec).
    wet=True returns the reverb-only version of the same note (with a ringing tail
    for non-sustaining sounds)."""
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
    duty = 0.5 + 0.4 * p["pwm"] * np.sin(2 * np.pi * tb * (2.0 / loop_len))  # LFO fits loop
    duty = np.clip(duty, 0.05, 0.95)

    out = np.zeros((n, 2), np.float32)
    idx_n = np.arange(n)
    b = idx_n // BLOCK
    u = ((idx_n % BLOCK) / BLOCK).astype(np.float32)

    for wave, cents, level, pan, octv in p["oscs"]:
        f = f0 * (2 ** octv) * 2 ** (cents / 1200.0)
        hmax = int(min(NH - 1, (SR * 0.46) / f))
        if hmax < 1:
            continue
        k = np.arange(1, hmax + 1, dtype=np.float32)
        base = _harm_amps(wave, k, duty)
        w = (k[None, :] * f) / fc[:, None]
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
    return kit


def kit_arrays(gain=0.5):
    return {k: (np.repeat((v * gain)[:, None], 2, axis=1).astype(np.float32), None) for k, v in drum_kit().items()}


def mono_to_bytes(x, gain=0.5):
    y = np.clip(x * gain * 32767, -32767, 32767).astype(np.int16)
    return np.repeat(y[:, None], 2, axis=1).tobytes()


# 16-step patterns: K kick, S snare, h hat, o open hat
BEATS = [
    ("Off", None),
    ("Four Floor", {"kick": "K...K...K...K...", "snare": "....S.......S...", "hat": "..h...h...h...h.", "ohat": "................"}),
    ("Boom Bap", {"kick": "K......K..K.....", "snare": "....S.......S...", "hat": "h.h.h.h.h.h.h.h.", "ohat": "................"}),
    ("Synthpop", {"kick": "K.....K.K.......", "snare": "....S.......S...", "hat": "hhhhhhhhhhhhhhhh", "ohat": "......o.......o."}),
    ("Half Time", {"kick": "K..........K....", "snare": "........S.......", "hat": "h...h...h...h...", "ohat": "..............o."}),
]
