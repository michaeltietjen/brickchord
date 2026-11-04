# Writes Bricklab's demo songs to brickchord/demos/*.json, in the same format
# the app saves (brickchord_song.json) plus key, scale and tempo. Each demo uses
# a different mix of machines, kits and effects, so loading one both shows a
# new user what Bricklab does and exercises the engine for testing.
#
#   python3 tools/make_demos.py
import json
import os
import sys
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "brickchord")
sys.path.insert(0, APP)
import synth  # noqa: E402

OUT = os.path.join(APP, "demos")
NP, NT = 16, 6
FX = ["Drive", "Lo-fi", "Chorus", "Flanger", "Vibrato", "Tremolo", "Gate", "Auto-Pan", "Wide", "Filter LFO", "Cloud"]
FX_DEF = {"Drive": (0.4, 3), "Lo-fi": (0.4, 3), "Chorus": (0.5, 5), "Flanger": (0.5, 6), "Vibrato": (0.3, 0),
          "Tremolo": (0.5, 1), "Gate": (0.7, 0), "Auto-Pan": (0.6, 4), "Wide": (0.6, 3), "Filter LFO": (0.6, 5),
          "Cloud": (0.5, 2)}
DG = {"kick": 0.9, "snare": 0.75, "hat": 0.7, "ohat": 0.7, "clap": 0.8, "rim": 0.6, "tom": 0.8, "shk": 0.7}
SCALES = {"Major": [0, 2, 4, 5, 7, 9, 11], "Minor": [0, 2, 3, 5, 7, 8, 10],
          "Dorian": [0, 2, 3, 5, 7, 9, 10], "Mixolydian": [0, 2, 4, 5, 7, 9, 10]}


def pj(machine, name, tone=0.0, res=0.0):
    bank = synth.machine_bank(machine)
    i = next(n for n, p in enumerate(bank) if p["name"] == name)
    p = synth.edited_patch(bank[i], None)
    p["cutoff"] = p["cutoff"] * (2 ** tone)
    p["res"] = max(0.5, p["res"] + res)
    return i, json.dumps(p, sort_keys=True)


def rack(**on):
    r = {n: [False, FX_DEF[n][0], FX_DEF[n][1]] for n in FX}
    for n, v in on.items():
        n = n.replace("_", "-") if n in ("Lo_fi", "Auto_Pan") else n.replace("_", " ")
        amt, rate = v if isinstance(v, tuple) else (v, FX_DEF[n][1])
        r[n] = [True, float(amt), int(rate)]
    return r


def drum_track(kit, swing=0.0, human=0.0):
    return {"machine": "drums", "smp": {}, "name": "Drums", "patch": None, "tone": 0.0, "res": 0.0, "pj": None,
            "vol": 0.9, "pan": 0.0, "rs": 0.12, "ds": 0.0, "bus": 0, "mute": False, "rack": rack(),
            "flt": [0.0, 0.0],
            "drum": {"kit": kit, "swing": swing, "swres": 16, "beat": 0, "acc": 1.35, "ghost": 0.4, "human": human,
                     "choke": True, "lanes": {n: [1.0, False, 0] for n in DG}}}


def synth_track(machine, sound, vol=0.8, pan=0.0, rs=0.25, ds=0.0, bus=0, fx=None, flt=(0.0, 0.0), tone=0.0, res=0.0):
    i, p = pj(machine, sound, tone, res)
    return {"machine": machine, "smp": {}, "name": sound, "patch": i, "tone": tone, "res": res, "pj": p,
            "vol": vol, "pan": pan, "rs": rs, "ds": ds, "bus": bus, "mute": False, "rack": fx or rack(),
            "flt": list(flt)}


def empty():
    t = synth_track("chord", "Juno Pad")
    t.update(name=None, patch=None, pj=None)
    return t


def beat(lanes, bars=2, accents=(), ghosts=()):
    """lanes: {part: "x...x..." per bar (16 chars) or 32 for 2 bars}"""
    ev = []
    for part, pat in lanes.items():
        pat = (pat * bars)[:16 * bars] if len(pat) == 16 else pat
        for s, ch in enumerate(pat):
            if ch in "xXg":
                g = DG[part] * (1.35 if ch == "X" else 0.4 if ch == "g" else 1.0)
                ev.append([float(s), "d", part, round(g, 3), 0.0, None, 0.02])
    return ev


def degree(key, scale, deg, octave=4):
    sc = SCALES[scale]
    o, d = divmod(deg, 7)
    return 12 * (octave + 1 + o) + key + sc[d]


def chord(key, scale, deg, octave=4, notes=3):
    return [degree(key, scale, deg + 2 * i, octave) for i in range(notes)]


def chords(key, scale, prog, bars_each=1, octave=4, notes=3, gain=0.75, strum=0.0, dur_steps=None):
    """prog: degrees (0 = I), one per bars_each bars"""
    ev = []
    for n, deg in enumerate(prog):
        at = n * 16 * bars_each
        dur = dur_steps or 16 * bars_each - 0.5
        for i, m in enumerate(chord(key, scale, deg, octave, notes)):
            ev.append([round(at + i * strum, 3), "n", m, gain, 0.0, float(dur), 0.4])
    return ev


def line(key, scale, steps, octave=3, gain=0.85, rel=0.15):
    """steps: list of (step, degree, length in steps)"""
    return [[float(s), "n", degree(key, scale, d, octave), gain, 0.0, float(l), rel] for s, d, l in steps]


def drone(key, scale, deg, length, octave=3):
    return [[0.0, "n", m, 0.8, 0.0, float(length), 1.2] for m in (degree(key, scale, deg, octave),
                                                                    degree(key, scale, deg + 4, octave))]


def song(name, bpm, key, scale, pats, rows, bars):
    full = []
    for p in range(NP):
        if p < len(pats):
            full.append({"tracks": pats[p]})
        else:
            full.append({"tracks": [drum_track("Classic")] + [empty() for _ in range(NT - 1)]})
    bl = list(bars) + [2] * (NP - len(bars))
    return {"v": 1, "demo": name, "bpm": bpm, "key": key, "scale": scale, "bars": bl, "pats": full,
            "song": rows, "song_on": True, "cur": 0, "kit_all": False}


def with_ev(track, ev):
    t = dict(track)
    t["ev"] = ev
    return t


# ---------------------------------------------------------------- the demos
def night_drive():
    """Synthwave: 808, Moog bass, Juno pad, Fat Saw lead, Deep Space drone. A minor, 100 BPM."""
    k, s = 9, "Minor"
    prog = [0, 5, 2, 6]                              # i VI III VII
    drums_a = beat({"kick": "x.......x.......", "snare": "....x.......x...", "hat": "x.x.x.x.x.x.x.x."}, 2)
    drums_b = beat({"kick": "x.......x.x.....", "snare": "....x.......X...", "hat": "xxx.xxx.xxx.xxxx",
                    "clap": "............x..."}, 2)
    bass = []
    for n, d in enumerate(prog * 2):
        bass += line(k, s, [(n * 8 + 0, d, 3), (n * 8 + 4, d, 2), (n * 8 + 6, d + 7, 1.5)], octave=1)
    pad = chords(k, s, prog, bars_each=1, octave=3, notes=4, gain=0.6, dur_steps=8)
    pad = [[e[0] / 2, *e[1:]] for e in pad]          # four chords over 2 bars
    lead = line(k, s, [(0, 4, 4), (4, 7, 2), (6, 6, 2), (8, 4, 6), (16, 2, 3), (19, 4, 1), (20, 5, 4), (24, 4, 8)],
                octave=4, gain=0.8, rel=0.25)
    dr = drone(k, s, 0, 31.5)
    t_drum = drum_track("808")
    t_bass = synth_track("bass", "Moog Bass", vol=0.8, rs=0.05)
    t_pad = synth_track("chord", "Juno Pad", vol=0.55, rs=0.4, ds=0.2, bus=1, fx=rack(Chorus=0.5, Wide=0.6))
    t_lead = synth_track("lead", "Fat Saw", vol=0.6, pan=0.1, rs=0.3, ds=0.35, bus=1, fx=rack(Chorus=0.3))
    t_drone = synth_track("drone", "Deep Space", vol=0.45, rs=0.5, bus=1)
    a = [with_ev(t_drum, drums_a), with_ev(t_bass, bass), with_ev(t_pad, pad), dict(t_lead, ev=[]),
         with_ev(t_drone, dr), empty()]
    b = [with_ev(t_drum, drums_b), with_ev(t_bass, bass), with_ev(t_pad, pad), with_ev(t_lead, lead),
         with_ev(t_drone, dr), empty()]
    return song("Night Drive", 100, k, s, [a, b], [[0, 2], [1, 4], [0, 1], [1, 2]], [2, 2])


def tape_lofi():
    """Lo-fi hip hop: Lo-fi kit with swing, Electric Piano 7ths, Sub bass, a Sample-free Flute. D Dorian, 82 BPM."""
    k, s = 2, "Dorian"
    prog = [0, 3, 1, 4]                               # i IV ii V (Dorian)
    drums = beat({"kick": "x......x..x.....", "snare": "....x.......x..g", "hat": "x.xgx.x.x.xgx.x.",
                  "rim": ".........x......"}, 2)
    keys = chords(k, s, prog, bars_each=1, octave=4, notes=4, gain=0.6, strum=0.12, dur_steps=7.5)
    keys = [[e[0] / 2, *e[1:]] for e in keys]
    bass = line(k, s, [(0, 0, 6), (8, 3, 6), (16, 1, 6), (24, 4, 4), (28, 6, 2)], octave=1, gain=0.9)
    flute = line(k, s, [(2, 4, 2), (4, 6, 4), (10, 4, 2), (12, 2, 6), (20, 3, 2), (22, 4, 6)], octave=5,
                 gain=0.7, rel=0.3)
    t_drum = drum_track("Lo-fi", swing=0.18, human=0.3)
    t_keys = synth_track("chord", "Electric Piano", vol=0.6, rs=0.35, bus=0, fx=rack(Lo_fi=0.4, Tremolo=(0.3, 3)))
    t_bass = synth_track("bass", "Sub", vol=0.85, rs=0.0)
    t_fl = synth_track("lead", "Flute", vol=0.5, pan=-0.15, rs=0.35, ds=0.3, bus=1)
    a = [with_ev(t_drum, drums), with_ev(t_keys, keys), with_ev(t_bass, bass), dict(t_fl, ev=[]), empty(), empty()]
    b = [with_ev(t_drum, drums), with_ev(t_keys, keys), with_ev(t_bass, bass), with_ev(t_fl, flute), empty(), empty()]
    return song("Tape Lo-fi", 82, k, s, [a, b], [[0, 2], [1, 4], [0, 2]], [2, 2])


def acid_room():
    """Acid techno: 909 four on the floor, Acid Bass sixteenths, Sync Lead stabs, Dark Pad. E minor, 126 BPM."""
    k, s = 4, "Minor"
    drums = beat({"kick": "x...x...x...x...", "clap": "....x.......x...", "hat": "..x...x...x...x.",
                  "ohat": "..............x.", "shk": "xxxxxxxxxxxxxxxx"}, 2)
    acid_steps = [(i, d, 0.8) for i, d in enumerate([0, 0, 7, 0, 3, 0, 0, 5, 0, 0, 7, 0, 3, 5, 0, 10] * 2)]
    acid = line(k, s, acid_steps, octave=1, gain=0.85, rel=0.05)
    for e in acid[::4]:
        e[3] = 1.0                                     # accents on the beat
    stabs = []
    for at in (6, 14, 22, 30):
        stabs += [[float(at), "n", m, 0.7, 0.0, 1.0, 0.2] for m in chord(k, s, 0, 4, 3)]
    pad = drone(k, s, 0, 31.5, octave=3)
    t_drum = drum_track("909")
    t_acid = synth_track("bass", "Acid Bass", vol=0.75, rs=0.05, ds=0.15, fx=rack(Drive=0.4))
    # the 303 part: slides into the off-beat notes, and the filter opening up across each bar
    t_acid["locks"] = {str(st): {"slide": True} for st in (2, 7, 13, 15, 18, 23, 29, 31)}
    for st, f in ((0, 0.6), (4, 0.45), (8, 0.3), (12, 0.15), (16, 0.55), (20, 0.4), (24, 0.25), (28, 0.1)):
        t_acid["locks"].setdefault(str(st), {})["flt"] = [f, 0.5]
    t_stab = synth_track("lead", "Sync Lead", vol=0.5, rs=0.3, ds=0.4, bus=1, fx=rack(Gate=(0.6, 0)))
    t_pad = synth_track("drone", "Dark Pad", vol=0.4, rs=0.5, bus=1, fx=rack(Filter_LFO=(0.6, 5)))
    a = [with_ev(t_drum, drums), with_ev(t_acid, acid), dict(t_stab, ev=[]), with_ev(t_pad, pad), empty(), empty()]
    b = [with_ev(t_drum, drums), with_ev(t_acid, acid), with_ev(t_stab, stabs), with_ev(t_pad, pad), empty(),
         empty()]
    return song("Acid Room", 126, k, s, [a, b], [[0, 2], [1, 4], [0, 2]], [2, 2])


def cathedral():
    """Ambient: no drums, Cathedral drone, Glass Bells, Choir Pad, a slow Brass Lead. C major, 72 BPM."""
    k, s = 0, "Major"
    prog = [0, 5, 3, 4]
    pad = chords(k, s, prog, bars_each=1, octave=3, notes=4, gain=0.55, dur_steps=15.5)
    pad = [[e[0] / 2, *e[1:]] for e in pad]
    bells = line(k, s, [(0, 7, 2), (6, 9, 2), (12, 11, 4), (20, 9, 2), (26, 7, 4)], octave=4, gain=0.6, rel=1.0)
    dr = drone(k, s, 0, 31.5, octave=2)
    lead = line(k, s, [(0, 2, 8), (8, 4, 8), (16, 3, 8), (24, 1, 8)], octave=4, gain=0.6, rel=0.6)
    t_drum = drum_track("Acoustic")
    t_pad = synth_track("chord", "Choir Pad", vol=0.5, rs=0.55, bus=1, fx=rack(Chorus=0.5, Wide=0.7))
    t_bell = synth_track("chord", "Glass Bells", vol=0.45, pan=0.2, rs=0.5, ds=0.45, bus=1)
    t_dr = synth_track("drone", "Cathedral", vol=0.5, rs=0.6, bus=1)
    t_lead = synth_track("lead", "Brass Lead", vol=0.45, pan=-0.2, rs=0.45, ds=0.25, bus=1)
    a = [dict(t_drum, ev=[]), with_ev(t_pad, pad), dict(t_bell, ev=[]), with_ev(t_dr, dr), empty(), empty()]
    b = [dict(t_drum, ev=[]), with_ev(t_pad, pad), with_ev(t_bell, bells), with_ev(t_dr, dr), with_ev(t_lead, lead),
         empty()]
    return song("Cathedral", 72, k, s, [a, b], [[0, 2], [1, 4], [0, 2]], [2, 2])


# ---------------------------------------------------------------- demo samples
def write_wav(path, x, sr=synth.SR):
    y = np.clip(x / (np.max(np.abs(x)) + 1e-9) * 0.9, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((y * 32767).astype("<i2").tobytes())


def make_samples():
    """Two WAVs the Analog Drift demo plays on its Sample tracks, made from the
    synth itself so the repo carries no third-party audio."""
    d = synth.SAMPLE_DIR
    os.makedirs(d, exist_ok=True)
    choir = next(p for p in synth.PATCHES if p["name"] == "Choir Pad")
    a, l = synth.render_note(60, choir, arrays=True)
    x = np.concatenate([a, l if l is not None else a])[: int(2.5 * synth.SR), 0]
    fade = int(0.3 * synth.SR)
    x[-fade:] *= np.linspace(1, 0, fade)
    write_wav(os.path.join(d, "drift_choir.wav"), x)
    vox = next(p for p in synth.PATCHES if p["name"] == "Vox Pad")
    a, _ = synth.render_note(60, vox, arrays=True)
    x = a[: int(0.45 * synth.SR), 0].copy()
    env = np.exp(-np.arange(len(x)) / (0.18 * synth.SR))
    x *= env
    write_wav(os.path.join(d, "drift_vox.wav"), x)


def sample_track(file, vol=0.6, pan=0.0, rs=0.3, ds=0.0, bus=0, fx=None, **smp):
    p = synth.sample_patch(file, **smp)
    return {"machine": "sample", "smp": dict(smp), "name": p["name"], "patch": 0, "tone": 0.0, "res": 0.0,
            "pj": json.dumps(p, sort_keys=True), "vol": vol, "pan": pan, "rs": rs, "ds": ds, "bus": bus,
            "mute": False, "rack": fx or rack(), "flt": [0.0, 0.0]}


def analog_drift():
    """Analog, drones and samples: Moog Bass, Brass and Sync leads, a sliding Shimmer
    drone, a granular choir sample as the pad and pitched vox chops. F minor, 92 BPM."""
    k, s = 5, "Minor"
    prog = [0, 5, 3, 4]                                  # i VI iv v
    d_light = beat({"kick": "x.........x.....", "rim": "....x.......x...", "shk": "..x...x...x...x."}, 2)
    d_full = beat({"kick": "x......x..x.....", "snare": "....x.......x...", "hat": "x.x.xgx.x.x.xgx.",
                   "ohat": "..............x.", "tom": "...............x"}, 2)
    bass = []
    for n, dg in enumerate(prog):
        b = n * 8
        bass += line(k, s, [(b, dg, 2.5), (b + 3, dg, 1), (b + 4, dg + 7, 1.5), (b + 6, dg, 1.5)], octave=1, gain=0.9)
    # the granular choir: one long note per chord, rooted on each degree
    choir = []
    for n, dg in enumerate(prog):
        for m in (degree(k, s, dg, 3), degree(k, s, dg + 4, 3)):
            choir.append([float(n * 8), "n", m, 0.7, 0.0, 7.5, 0.8])
    chops = []
    for at, dg in ((2, 4), (6, 2), (10, 4), (14, 7), (18, 4), (22, 2), (26, 0), (29, 2)):
        chops.append([float(at), "n", degree(k, s, dg, 4), 0.8, 0.0, 1.5, 0.15])
    lead = line(k, s, [(0, 7, 3), (3, 9, 1), (4, 7, 4), (8, 5, 2), (10, 4, 6), (16, 7, 3), (19, 10, 1),
                       (20, 9, 4), (24, 7, 8)], octave=3, gain=0.75, rel=0.3)
    stab = line(k, s, [(0, 4, 2), (8, 4, 2), (16, 2, 2), (24, 3, 2)], octave=4, gain=0.6, rel=0.2)
    dr = []
    for n, dg in enumerate([0, 0, 3, 4]):
        dr += [[float(n * 8), "n", m, 0.8, 0.0, 7.8, 1.5] for m in (degree(k, s, dg, 2), degree(k, s, dg + 4, 2))]
    t_drum = dict(drum_track("Classic", swing=0.12, human=0.2), vol=0.6)
    t_bass = synth_track("bass", "Moog Bass", vol=0.95, rs=0.05, fx=rack(Drive=0.3))
    t_bass["locks"] = {str(st): {"slide": True} for st in (6, 14, 22, 30)}
    t_lead = synth_track("lead", "Brass Lead", vol=0.75, pan=-0.1, rs=0.35, ds=0.3, bus=1, fx=rack(Vibrato=(0.2, 0)))
    t_drone = synth_track("drone", "Shimmer", vol=0.6, rs=0.55, bus=1, fx=rack(Filter_LFO=(0.5, 6), Wide=0.6))
    t_choir = sample_track("drift_choir.wav", vol=0.55, rs=0.5, ds=0.2, bus=1, fx=rack(Chorus=0.4),
                           grain=True, loop=True, gsize=120, gdens=50, gpos=0.4, gspray=0.4, gpitch=0.3)
    t_chop = sample_track("drift_vox.wav", vol=0.7, pan=0.2, rs=0.3, ds=0.45, bus=0, fx=rack(Lo_fi=0.3))
    t_sync = synth_track("lead", "Sync Lead", vol=0.4, pan=0.15, rs=0.3, ds=0.4, bus=0, fx=rack(Gate=(0.5, 0)))
    intro = [with_ev(t_drum, d_light), dict(t_bass, ev=[]), with_ev(t_choir, choir), with_ev(t_drone, dr),
             dict(t_chop, ev=[]), dict(t_lead, ev=[])]
    groove = [with_ev(t_drum, d_full), with_ev(t_bass, bass), with_ev(t_choir, choir), with_ev(t_drone, dr),
              with_ev(t_chop, chops), dict(t_lead, ev=[])]
    peak = [with_ev(t_drum, d_full), with_ev(t_bass, bass), with_ev(t_choir, choir), with_ev(t_drone, dr),
            with_ev(t_chop, chops), with_ev(t_lead, lead)]
    drop = [with_ev(t_drum, d_light), with_ev(t_bass, bass), dict(t_choir, ev=[]), with_ev(t_drone, dr),
            dict(t_chop, ev=[]), with_ev(t_sync, stab)]
    return song("Analog Drift", 92, k, s, [intro, groove, peak, drop],
                [[0, 2], [1, 2], [2, 4], [3, 2], [2, 2], [0, 1]], [2, 2, 2, 2])


def slow_light():
    """Ambient: four-bar patterns at 64 BPM in D Dorian. A sliding Tape Choir drone and a
    Sub Drone underneath, the choir sample turned into a slow granular cloud, a vox
    sample scattered high as glitter, sparse Glass Bells in long delays, a Flute line,
    and only a shaker and rim for time."""
    k, s = 2, "Dorian"
    L = 64
    prog = [0, 3, 5, 4]                                    # i IV vi(b) V-ish, one per bar
    drone, sub, cloud = [], [], []
    for n, dg in enumerate(prog):
        at = float(n * 16)
        drone += [[at, "n", m, 0.75, 0.0, 15.8, 2.0] for m in (degree(k, s, dg, 3), degree(k, s, dg + 4, 3))]
        cloud += [[at, "n", m, 0.7, 0.0, 15.8, 1.5] for m in (degree(k, s, dg + 2, 3), degree(k, s, dg + 6, 3))]
    sub = [[0.0, "n", degree(k, s, 0, 1), 0.8, 0.0, 31.8, 2.0], [32.0, "n", degree(k, s, 3, 1), 0.8, 0.0, 31.8, 2.0]]
    glitter = [[float(at), "n", degree(k, s, dg, 5), 0.5, 0.0, 2.0, 0.6]
               for at, dg in ((3, 4), (11, 6), (22, 2), (29, 4), (38, 7), (45, 6), (54, 4), (61, 2))]
    bells = line(k, s, [(0, 7, 4), (10, 9, 4), (24, 11, 6), (34, 9, 4), (48, 7, 8), (58, 4, 4)],
                 octave=4, gain=0.55, rel=1.5)
    flute = line(k, s, [(4, 4, 10), (16, 6, 8), (26, 5, 6), (36, 4, 12), (52, 2, 10)], octave=4, gain=0.6, rel=0.8)
    perc = beat({"shk": "..x...x...x...x." * 4, "rim": "........x......." * 4}, 1, ghosts=())
    perc = [[e[0], e[1], e[2], round(e[3] * 0.85, 3), e[4], e[5], e[6]] for e in perc]
    t_perc = dict(drum_track("Acoustic", human=0.5), vol=0.85, rs=0.45)
    t_drone = synth_track("drone", "Tape Choir", vol=0.6, rs=0.6, ds=0.2, bus=1,
                          fx=rack(Filter_LFO=(0.5, 7), Chorus=0.4, Wide=0.7))
    t_sub = synth_track("drone", "Sub Drone", vol=0.65, rs=0.2)
    t_cloud = sample_track("drift_choir.wav", vol=0.55, rs=0.65, ds=0.3, bus=1, fx=rack(Wide=0.8),
                           grain=True, loop=True, gsize=300, gdens=25, gpos=0.5, gspray=0.8, gpitch=0.5)
    t_glit = sample_track("drift_vox.wav", vol=0.7, pan=0.3, rs=0.6, ds=0.6, bus=1, fx=rack(Auto_Pan=(0.7, 5)),
                          grain=True, loop=False, gsize=60, gdens=40, gpos=0.2, gspray=0.4, gpitch=2.0)
    t_bell = synth_track("chord", "Glass Bells", vol=0.4, pan=-0.25, rs=0.55, ds=0.55, bus=1)
    t_flute = synth_track("lead", "Flute", vol=0.8, pan=0.15, rs=0.5, ds=0.4, bus=1, fx=rack(Vibrato=(0.25, 0)))
    a = [dict(t_perc, ev=[]), with_ev(t_drone, drone), with_ev(t_sub, sub), dict(t_cloud, ev=[]),
         dict(t_glit, ev=[]), dict(t_bell, ev=[])]
    b = [with_ev(t_perc, perc), with_ev(t_drone, drone), with_ev(t_sub, sub), with_ev(t_cloud, cloud),
         dict(t_glit, ev=[]), with_ev(t_bell, bells)]
    c = [with_ev(t_perc, perc), with_ev(t_drone, drone), with_ev(t_sub, sub), with_ev(t_cloud, cloud),
         with_ev(t_glit, glitter), with_ev(t_flute, flute)]
    d = [dict(t_perc, ev=[]), dict(t_drone, ev=[]), with_ev(t_sub, sub), with_ev(t_cloud, cloud),
         with_ev(t_glit, glitter), with_ev(t_bell, bells)]
    return song("Slow Light", 64, k, s, [a, b, c, d], [[0, 1], [1, 2], [2, 2], [3, 1], [2, 1], [0, 1]], [4, 4, 4, 4])


def patch_bay():
    """Modular techno: the Modular kit in cross-rhythms (the zap runs in threes against
    the four), Pulse Bass with slides and filter locks, FM Bell arpeggios, a Wire lead,
    and a Dark Pad drone. A minor, 118 BPM."""
    k, s = 9, "Minor"
    three = "".join("x" if i % 3 == 0 else "." for i in range(32))
    five = "".join("x" if i % 5 == 0 else "." for i in range(32))
    d_a = beat({"kick": "x...x...x...x...", "shk": three, "hat": "..x...x...x...x."}, 2)
    d_b = beat({"kick": "x...x...x...x..x", "snare": "....x.......x...", "shk": three, "rim": five,
                "hat": "x.xxx.xxx.xxx.xx", "tom": "...............x"}, 2)
    bass = line(k, s, [(i, d, 0.9) for i, d in enumerate([0, 0, 7, 0, 3, 0, 5, 3] * 4)], octave=1, gain=0.85, rel=0.05)
    for e in bass[::4]:
        e[3] = 1.0
    arp = []
    for n, dg in enumerate([0, 5, 3, 4]):
        for i, off in enumerate((0, 2, 4, 7)):
            arp.append([float(n * 8 + i * 2), "n", degree(k, s, dg + off, 4), 0.6, 0.0, 1.5, 0.4])
    wire = line(k, s, [(0, 7, 6), (8, 9, 2), (10, 7, 6), (16, 4, 4), (20, 5, 4), (24, 4, 8)], octave=3, gain=0.7, rel=0.2)
    pad = drone(k, s, 0, 31.5, octave=2)
    t_drum = drum_track("Modular", swing=0.06)
    t_drum["locks"] = {str(st): {"flt": [f, 0.4]} for st, f in ((12, 0.4), (13, 0.55), (14, 0.7), (15, 0.8))}
    t_bass = synth_track("bass", "Pulse Bass", vol=0.8, rs=0.05, ds=0.1, fx=rack(Drive=0.3))
    t_bass["locks"] = {str(st): {"slide": True} for st in (2, 6, 10, 15, 18, 22, 26, 31)}
    for st, f in ((0, 0.5), (8, 0.3), (16, 0.6), (24, 0.15)):
        t_bass["locks"].setdefault(str(st), {})["flt"] = [f, 0.6]
    t_arp = synth_track("chord", "FM Bell", vol=0.5, pan=0.25, rs=0.35, ds=0.45, bus=1, fx=rack(Auto_Pan=(0.5, 4)))
    t_wire = synth_track("lead", "Wire", vol=0.55, pan=-0.2, rs=0.3, ds=0.35, bus=1, fx=rack(Chorus=0.3))
    t_pad = synth_track("drone", "Dark Pad", vol=0.45, rs=0.5, bus=1, fx=rack(Filter_LFO=(0.6, 6)))
    a = [with_ev(t_drum, d_a), with_ev(t_bass, bass), dict(t_arp, ev=[]), with_ev(t_pad, pad), dict(t_wire, ev=[]),
         empty()]
    b = [with_ev(t_drum, d_b), with_ev(t_bass, bass), with_ev(t_arp, arp), with_ev(t_pad, pad), dict(t_wire, ev=[]),
         empty()]
    c = [with_ev(t_drum, d_b), with_ev(t_bass, bass), with_ev(t_arp, arp), with_ev(t_pad, pad), with_ev(t_wire, wire),
         empty()]
    return song("Patch Bay", 118, k, s, [a, b, c], [[0, 2], [1, 2], [2, 4], [0, 1], [2, 2]], [2, 2, 2])


def macro_track(sound, vol=0.7, pan=0.0, rs=0.25, ds=0.0, bus=0, fx=None, **mac):
    i, pj_ = pj("macro", sound)
    d = json.loads(pj_)
    d.update(mac)
    return {"machine": "macro", "smp": {}, "mac": dict(mac), "name": sound, "patch": i, "tone": 0.0, "res": 0.0,
            "pj": json.dumps(d, sort_keys=True), "vol": vol, "pan": pan, "rs": rs, "ds": ds, "bus": bus,
            "mute": False, "rack": fx or rack(), "flt": [0.0, 0.0]}


def resonators():
    """The Macro machine: Marimba and Kalimba patterns in five against four, a Bell
    Bowl on the downbeats, a Vowel Choir pad, a Plucked String bass, and the Modular
    kit. C Mixolydian, 104 BPM."""
    k, s = 0, "Mixolydian"
    drums = beat({"kick": "x.....x...x.....", "snare": "....x.......x...",
                  "shk": "".join("x" if i % 3 == 0 else "." for i in range(32)), "hat": "..x...x...x...x."}, 2)
    mar = [[float(i), "n", degree(k, s, d, 4), 0.75, 0.0, 1.0, 0.3]
           for i, d in zip(range(0, 32, 2), [0, 2, 4, 2, 5, 4, 2, 0, 1, 3, 5, 3, 6, 5, 3, 1])]
    kal = [[float(i), "n", degree(k, s, d, 5), 0.6, 0.0, 1.0, 0.3]
           for i, d in zip(range(1, 32, 5), [4, 2, 6, 4, 0, 2, 4])]
    bowl = [[0.0, "n", degree(k, s, 0, 4), 0.7, 0.0, 8.0, 1.5], [16.0, "n", degree(k, s, 3, 4), 0.7, 0.0, 8.0, 1.5]]
    choir = chords(k, s, [0, 3], bars_each=1, octave=3, notes=3, gain=0.55, dur_steps=15.5)
    pluck = line(k, s, [(0, 0, 2), (3, 0, 1), (6, 4, 2), (8, 3, 2), (11, 3, 1), (14, 4, 2), (16, 3, 2), (19, 3, 1),
                        (22, 6, 2), (24, 0, 2), (27, 0, 1), (30, 4, 2)], octave=2, gain=0.85, rel=0.2)
    t_drum = dict(drum_track("Modular", human=0.15), vol=0.7)
    t_mar = macro_track("Marimba", vol=0.7, pan=-0.2, rs=0.3, ds=0.2, bus=0)
    t_kal = macro_track("Kalimba", vol=0.6, pan=0.3, rs=0.35, ds=0.35, bus=1, fx=rack(Cloud=(0.5, 3)))
    t_bowl = macro_track("Bell Bowl", vol=0.5, rs=0.5, ds=0.2, bus=1)
    t_choir = macro_track("Bowed Glass", vol=0.5, rs=0.55, bus=1, fx=rack(Chorus=0.4))
    t_pluck = macro_track("Plucked String", vol=0.8, rs=0.1, timbre=0.5, morph=0.5)
    a = [dict(t_drum, ev=[]), with_ev(t_mar, mar), dict(t_kal, ev=[]), with_ev(t_bowl, bowl), with_ev(t_choir, choir),
         dict(t_pluck, ev=[])]
    b = [with_ev(t_drum, drums), with_ev(t_mar, mar), with_ev(t_kal, kal), with_ev(t_bowl, bowl),
         with_ev(t_choir, choir), with_ev(t_pluck, pluck)]
    c = [with_ev(t_drum, drums), dict(t_mar, ev=[]), with_ev(t_kal, kal), with_ev(t_bowl, bowl), dict(t_choir, ev=[]),
         with_ev(t_pluck, pluck)]
    return song("Resonators", 104, k, s, [a, b, c], [[0, 2], [1, 4], [2, 2], [1, 2]], [2, 2, 2])


DEMOS = [analog_drift, slow_light, patch_bay, resonators, night_drive, tape_lofi, acid_room, cathedral]


def main():
    os.makedirs(OUT, exist_ok=True)
    make_samples()
    for fn in DEMOS:
        d = fn()
        path = os.path.join(OUT, d["demo"].lower().replace(" ", "_").replace("-", "") + ".json")
        with open(path, "w") as f:
            json.dump(d, f, separators=(",", ":"))
        n = sum(len(t.get("ev") or []) for p in d["pats"] for t in p["tracks"])
        print("wrote", os.path.basename(path), "events", n)


if __name__ == "__main__":
    main()
