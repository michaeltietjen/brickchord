# Brickchop: an EP-133 K.O. II-style sampler on the Brickchord engine.
#
# Four groups (A drums, B bass, C keys, D your samples), 12 pads each, every pad
# holding its own sound. The 12 pads are the Brick's 12 thumb and finger buttons,
# laid out on screen as the K.O. II's 3 x 4 grid:
#
#     L2  L1  R1  R2        pads  1  2  3  4
#     <   ^   Y   X               5  6  7  8
#     v   >   B   A               9 10 11 12
#
#   SELECT + < ^ v >   group A, B, C or D        SELECT (tap)   Settings
#   L3                 KEYS: the last pad's sound across all 12 pads, chromatically
#   left stick         the fader: up/down tunes the last pad, left/right its level
#   START              play / stop the patterns (every group's, together)
#   R3 (click)         record: what you play goes into the group's pattern, on the 16ths
#   R3 held + pad      erase that pad from the pattern
#   right stick        punch-in FX, only while held
#
# Sounds are built here, in the UI process (a kit part, a synth note, a WAV or a
# slice of one), and sent to the engine once; a pad press is just a trigger.
import math
import os
import time

import numpy as np
import pygame

import synth

GROUPS = "ABCD"
GROUP_NAMES = ["drums", "bass", "keys", "samples"]
PADS = ["L2", "L1", "R1", "R2", "LEFT", "UP", "Y", "X", "DOWN", "RIGHT", "B", "A"]
GLYPH = {"L2": "L2", "L1": "L1", "R1": "R1", "R2": "R2", "LEFT": "<", "UP": "^", "DOWN": "v", "RIGHT": ">",
         "Y": "Y", "X": "X", "B": "B", "A": "A"}
KIT_PARTS = ["kick", "snare", "hat", "ohat", "clap", "rim", "tom", "shk"]
NOTE = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
SR = synth.SR


def M():
    import main
    return main


def chop_files():
    """Every WAV the Brick apps can see: Brickchop's own samples and Bricklab's,
    Brickchord's and Brickglide's, so your loops are already here."""
    d = synth.SAMPLE_DIR
    ports = os.path.dirname(os.path.dirname(d))
    dirs = [d] + [os.path.join(ports, a, "samples") for a in ("bricklab", "brickchord", "brickglide")]
    out, seen = [], set()
    for k, sd in enumerate(dirs):
        try:
            files = sorted(os.listdir(sd))
        except OSError:
            continue
        for f in files:
            if f.lower().endswith(".wav") and not f.startswith(".") and f not in seen:
                seen.add(f)
                out.append(f if k == 0 else os.path.join(sd, f))
    return out


def kit_list():
    try:
        return sorted(k for k in os.listdir(synth.KITS_DIR) if os.path.isdir(os.path.join(synth.KITS_DIR, k)))
    except OSError:
        return ["Classic"]


def sources():
    """Everything a pad can hold, as (kind, name): kit parts, synth notes, WAVs."""
    out = [("kit", "%s/%s" % (k, p)) for k in kit_list() for p in KIT_PARTS]
    out += [("bass", p["name"]) for p in synth.BASS_PATCHES]
    out += [("keys", p["name"]) for p in synth.PATCHES]
    out += [("lead", p["name"]) for p in synth.LEAD_PATCHES]
    out += [("file", f) for f in chop_files()]
    return out


def src_label(src):
    if not src:
        return "empty"
    kind, name = src[0], src[1]
    if kind == "file":
        s = os.path.splitext(os.path.basename(name))[0].replace("_", " ")
        s = (s[:20] + "\u2026") if len(s) > 21 else s
        return s + ("  #%d" % (src[2] + 1) if len(src) > 2 and src[2] is not None else "")
    if kind == "kit":
        k, p = name.split("/")
        return "%s %s" % (k, p)
    return name


def usb_capture_devices():
    """Sound cards that can record (USB audio from an SP-1, an OP-Z, a mixer...)."""
    out = []
    try:
        names = {}
        with open("/proc/asound/cards") as f:
            for line in f:
                p = line.split("[", 1)
                if len(p) == 2 and p[0].strip().isdigit():
                    names[int(p[0].strip())] = p[1].split("]", 1)[1].split(" - ", 1)[-1].strip()
        with open("/proc/asound/pcm") as f:
            for line in f:
                if "capture" not in line:
                    continue
                card, dev = (int(v) for v in line.split(":", 1)[0].strip().split("-"))
                out.append((card, dev, names.get(card, "card %d" % card)))
    except Exception:
        pass
    return out


def find_onsets(x, n):
    """Where the hits are: rises in short-time energy, the n strongest, kept apart."""
    hop = 256
    if len(x) < hop * 8:
        return [0]
    frames = len(x) // hop
    e = np.sqrt(np.mean(x[:frames * hop].reshape(frames, hop) ** 2, axis=1) + 1e-9)
    flux = np.maximum(0.0, np.diff(np.log(e), prepend=np.log(e[0])))
    flux[:2] = 0
    gap = max(2, int(0.07 * SR / hop))
    picked = [0]
    for i in np.argsort(flux)[::-1]:
        if flux[i] <= 0.05:
            break
        if all(abs(int(i) - p) >= gap for p in picked):
            picked.append(int(i))
        if len(picked) >= n:
            break
    return sorted(p * hop for p in picked)


_RAW = {}


def raw_audio(src):
    """Mono float32 at SR for a source (cached): a kit part, a synth note at C3
    (bass at C2), a WAV, or one slice of a WAV."""
    key = tuple(x if not isinstance(x, list) else tuple(x) for x in src)
    x = _RAW.get(key)
    if x is not None:
        return x
    kind, name = src[0], src[1]
    x = None
    try:
        if kind == "kit":
            k, p = name.split("/")
            kit = synth.builtin_kit(k)
            x = kit.get(p)
        elif kind in ("bass", "keys", "lead"):
            bank = {"bass": synth.BASS_PATCHES, "keys": synth.PATCHES, "lead": synth.LEAD_PATCHES}[kind]
            patch = next(p for p in bank if p["name"] == name)
            a, l = synth.render_note(36 if kind == "bass" else 48, patch, arrays=True)
            x = a if l is None else np.concatenate([a, l[: int(1.2 * SR)]])
            x = x.mean(axis=1) if x.ndim == 2 else x
            k = int(0.25 * SR)
            x = x.copy()
            x[-k:] *= np.linspace(1, 0, k)
        elif kind == "file":
            x = synth._sample_audio(name)
            if x is not None and len(src) > 2 and src[2] is not None:
                s, e = src[3], src[4]
                x = x[s:e]
    except Exception as ex:
        print("Brickchop: could not load %s: %s" % (src, ex), flush=True)
        x = None
    if x is not None:
        x = np.asarray(x, np.float32)
        if len(_RAW) > 120:
            _RAW.clear()
        _RAW[key] = x
    return x


def shape(x, tune=0.0, level=0.9, reverse=False):
    """A pad's sound ready to play: reversed, tuned (speed with pitch, as samplers
    do), level, short fades so nothing clicks, stereo."""
    if x is None or len(x) < 32:
        return None
    if reverse:
        x = x[::-1]
    if tune:
        r = 2 ** (tune / 12.0)
        idx = np.arange(0, len(x) - 1, r)
        x = np.interp(idx, np.arange(len(x)), x).astype(np.float32)
    x = x * float(level)
    fi, fo = int(0.002 * SR), int(0.006 * SR)
    if len(x) > fi + fo:
        x = x.copy()
        x[:fi] *= np.linspace(0, 1, fi, dtype=np.float32)
        x[-fo:] *= np.linspace(1, 0, fo, dtype=np.float32)
    return np.ascontiguousarray(np.repeat(x[:, None], 2, 1).astype(np.float32))


# ---------------------------------------------------------------- effects
# (key, label, lo, hi, step, default, kind). Pads and groups are baked into each
# pad's sound when it changes (so playing costs nothing); sends and swing go to the
# engine; the song's master chain runs in the engine on everything coming out.
PAD_FX = [("tune", "Tune", -24, 24, 1, 0, "st"), ("fine", "Fine tune", -50, 50, 5, 0, "cents"),
          ("level", "Level", 0.05, 1.6, 0.05, 0.9, "pct"), ("pan", "Pan", -1, 1, 0.1, 0.0, "pan"),
          ("start", "Start", 0, 0.9, 0.05, 0.0, "pct"), ("length", "Length", 0.05, 1, 0.05, 1.0, "pct"),
          ("attack", "Attack", 0, 0.5, 0.01, 0.0, "ms"), ("fade", "Fade out", 0, 1, 0.05, 0.0, "pct"),
          ("filter", "Filter", -1, 1, 0.1, 0.0, "filter"), ("drive", "Drive", 0, 1, 0.1, 0.0, "pct"),
          ("crush", "Bitcrush", 0, 1, 0.1, 0.0, "pct"), ("rev", "Reverb send", 0, 1, 0.1, 0.5, "pct"),
          ("dly", "Delay send", 0, 1, 0.1, 0.4, "pct")]
GROUP_FX = [("volume", "Volume", 0, 1.5, 0.05, 1.0, "pct"), ("pan", "Pan", -1, 1, 0.1, 0.0, "pan"),
            ("tune", "Transpose", -12, 12, 1, 0, "st"), ("filter", "Filter", -1, 1, 0.1, 0.0, "filter"),
            ("drive", "Drive", 0, 1, 0.1, 0.0, "pct"), ("crush", "Bitcrush", 0, 1, 0.1, 0.0, "pct"),
            ("rev", "Reverb send", 0, 2, 0.1, 1.0, "x"), ("dly", "Delay send", 0, 2, 0.1, 1.0, "x"),
            ("swing", "Swing", 0, 0.5, 0.05, 0.0, "pct")]
MASTER_FX = [("filter", "Filter", -1, 1, 0.05, 0.0, "filter"), ("drive", "Drive", 0, 1, 0.1, 0.0, "pct"),
             ("crush", "Bitcrush", 0, 1, 0.1, 0.0, "pct"), ("comp", "Compressor", 0, 1, 0.1, 0.0, "pct"),
             ("width", "Stereo width", 0, 2, 0.1, 1.0, "pct"), ("volume", "Volume", 0, 1.5, 0.05, 1.0, "pct")]


def fx_get(d, spec):
    return d.get(spec[0], spec[5]) if d else spec[5]


def fx_fmt(v, kind):
    if kind == "st":
        return "%+d" % v
    if kind == "cents":
        return "%+d cents" % v
    if kind == "pct":
        return "%d%%" % round(v * 100)
    if kind == "ms":
        return "%d ms" % round(v * 1000)
    if kind == "x":
        return "x%.1f" % v
    if kind == "pan":
        return "center" if abs(v) < 0.05 else ("%d%% %s" % (round(abs(v) * 100), "L" if v < 0 else "R"))
    if kind == "filter":
        return "open" if abs(v) < 0.05 else ("low-pass %d%%" % round(-v * 100) if v < 0 else "high-pass %d%%" % round(v * 100))
    return str(v)


def fx_step(d, spec, step):
    key, _, lo, hi, st, dflt, kind = spec
    v = d.get(key, dflt) + st * step
    v = max(lo, min(hi, v))
    d[key] = int(round(v)) if isinstance(st, int) and isinstance(lo, int) and kind in ("st", "cents") else round(v, 3)
    return d[key]


def fir(x, f):
    """The bipolar filter: below 0 a low-pass closing, above 0 a high-pass opening."""
    if x is None or abs(f) < 0.05 or len(x) < 128:
        return x
    taps = 101
    n = np.arange(taps) - (taps - 1) / 2
    win = np.hamming(taps)
    if f < 0:
        fc = 18000.0 * (1.0 + f) ** 2.2 + 120.0
        h = np.sinc(2 * fc / SR * n) * win
        h /= h.sum()
    else:
        fc = 30.0 + 7000.0 * f ** 2
        lp = np.sinc(2 * fc / SR * n) * win
        lp /= lp.sum()
        h = -lp
        h[(taps - 1) // 2] += 1.0                       # spectral inversion: high-pass
    return np.convolve(x, h.astype(np.float32), mode="same").astype(np.float32)


def color(x, drive, crush):
    if drive > 0.01:
        k = 1 + 6 * drive
        x = (np.tanh(x * k) / np.tanh(k) * (0.75 + 0.25 * (1 - drive))).astype(np.float32)
    if crush > 0.01:
        step = 1 + int(crush * 9)
        if step > 1:
            x = np.repeat(x[::step], step)[: len(x)]
        bits = 2 ** (12 - int(crush * 8))
        x = (np.round(x * bits) / bits).astype(np.float32)
    return x


def shape_fx(x, p, gfx=None, extra_tune=0.0):
    """A pad's sound with its own effects, then its group's, ready to play."""
    if x is None or len(x) < 32:
        return None
    gfx = gfx or {}
    n = len(x)
    s0 = int(n * p.get("start", 0.0))
    s1 = int(n * min(1.0, p.get("start", 0.0) + p.get("length", 1.0)))
    x = x[s0:max(s0 + 32, s1)]
    if p.get("reverse"):
        x = x[::-1]
    tune = p.get("tune", 0) + p.get("fine", 0) / 100.0 + gfx.get("tune", 0) + extra_tune
    if tune:
        r = 2 ** (tune / 12.0)
        idx = np.arange(0, len(x) - 1, r)
        x = np.interp(idx, np.arange(len(x)), x).astype(np.float32)
    x = np.asarray(x, np.float32)
    x = fir(x, p.get("filter", 0.0))
    x = color(x, p.get("drive", 0.0), p.get("crush", 0.0))
    x = fir(x, gfx.get("filter", 0.0))
    x = color(x, gfx.get("drive", 0.0), gfx.get("crush", 0.0))
    x = x * float(p.get("level", 0.9)) * float(gfx.get("volume", 1.0))
    a = int(p.get("attack", 0.0) * SR)
    fi = max(int(0.002 * SR), a)
    fo = int(0.006 * SR)
    if len(x) > fi + fo:
        x = x.copy()
        x[:fi] *= np.linspace(0, 1, fi, dtype=np.float32) ** (1.0 if a else 1.0)
        fade = p.get("fade", 0.0)
        if fade > 0.01:
            k = max(fo, int(len(x) * fade))
            x[-k:] *= np.linspace(1, 0, k, dtype=np.float32) ** 1.5
        else:
            x[-fo:] *= np.linspace(1, 0, fo, dtype=np.float32)
    pan = max(-1.0, min(1.0, p.get("pan", 0.0) + gfx.get("pan", 0.0)))
    ang = (pan + 1) * math.pi / 4
    st = np.stack([x * math.cos(ang) * 1.414, x * math.sin(ang) * 1.414], 1)
    return np.ascontiguousarray(st.astype(np.float32))


def default_groups():
    kits = kit_list()
    k1 = "808" if "808" in kits else kits[0]
    k2 = "909" if "909" in kits else kits[-1]
    pad = lambda src: {"src": src, "tune": 0, "level": 0.9, "choke": True, "reverse": False}
    # A: two kits, the main eight on the D-pad and face buttons, four more on the shoulders
    a = [pad(["kit", "%s/%s" % (k2, p)]) for p in ("kick", "snare", "clap", "hat")]
    a += [pad(["kit", "%s/%s" % (k1, p)]) for p in ("kick", "snare", "hat", "ohat", "clap", "rim", "tom", "shk")]
    b = [pad(["bass", p["name"]]) for p in synth.BASS_PATCHES[:8]]
    b += [pad(["bass", p["name"]]) for p in synth.BASS_PATCHES[:4]]
    keys_names = ["Electric Piano", "FM Keys", "Juno Pad", "Square Keys", "Glass Bells", "Nylon Guitar",
                  "Drawbar Organ", "Saw Pluck", "Choir Pad", "FM Bell", "Prophet Poly", "Air Pad"]
    names = [p["name"] for p in synth.PATCHES]
    c = [pad(["keys", n if n in names else names[i % len(names)]]) for i, n in enumerate(keys_names)]
    d = [pad(None) for _ in range(12)]
    return [{"pads": a, "keys": False}, {"pads": b, "keys": True, "keys_pad": 0},
            {"pads": c, "keys": True, "keys_pad": 0}, {"pads": d, "keys": False}]


class ChopMixin:  # noqa (the intro film is in ChopIntroMixin, below)
    # ------------------------------------------------------------ state
    def chop_init(self):
        st = self.cfg.get("chop") or {}
        self.cgroups = st.get("groups") if st.get("v") == 2 and st.get("groups") else default_groups()
        self.cgrp = int(st.get("group", 0)) % 4
        self.clast = int(st.get("last", 4)) % 12              # the last pad hit: what Settings and the fader edit
        self.cedit_g = self.cgrp
        self.cfiles = chop_files()
        self.csrcs = sources()
        self.clit = {}
        self.cview = None                                     # (group, pad) shown in the waveform
        self.caudition = False
        self.cfader = None                                    # last fader move: (time, what)
        self.cfade_t = 0.0
        self.crec = None
        self.crec_secs = int(st.get("rec_secs", 4))
        self.cchop_src = st.get("chop_src")
        self.cmaster = dict(st.get("master") or {})
        self.cwave = {}
        self.csel_down = self.csel_combo = False
        self.cbpm = float(st.get("bpm", 100))
        self.cclick = bool(st.get("click", True))
        self.cquant = int(st.get("quant", 0)) % len(self.QUANTS)
        self.cqstr = float(st.get("qstr", 1.0))
        self.cplay = self.crec_on = False
        self.cplay_t0 = 0.0
        self.cr3_down = self.cr3_combo = False
        self.ccommit = None
        for grp in self.cgroups:
            grp.setdefault("pattern", {"bars": 1, "ev": []})
        import shutil
        print("Brickchop: audio inputs %s, arecord %s" % (usb_capture_devices() or "none",
                                                          shutil.which("arecord") or "missing"), flush=True)
        if st.get("v") != 2 and not any(p["src"] for p in self.cgroups[3]["pads"]):
            loop = next((f for f in self.cfiles if "loop" in f.lower() or "break" in f.lower()), None)
            if loop:
                self.chop_to_group(3, loop, quiet=True)      # D starts with one of your loops, chopped
        for g in range(4):
            self.chop_send_group(g)
            self.chop_send_seq(g)
        self.eng.post("chop_master", self.cmaster)
        if not self.cfg.get("chop_tutorial_done") and getattr(self, "ctut", None) is None:
            self.chop_tut_start()

    def chop_state(self):
        return {"v": 2, "group": self.cgrp, "last": self.clast, "groups": self.cgroups, "rec_secs": self.crec_secs,
                "chop_src": self.cchop_src, "bpm": self.cbpm, "click": self.cclick, "master": self.cmaster,
                "quant": self.cquant, "qstr": self.cqstr}

    # ------------------------------------------------------------ the sequencer
    def chop_send_seq(self, g):
        pt = self.cgroups[g]["pattern"]
        self.eng.post("chop_seq", g, pt["bars"] * 16, [[e[0], e[1], e[2], False] for e in pt["ev"]],
                      float((self.cgroups[g].get("fx") or {}).get("swing", 0.0)))

    def chop_pos(self):
        """Where the playhead is, in 16ths since START (the engine keeps the same clock)."""
        return (time.perf_counter() - self.cplay_t0) * self.cbpm / 60.0 * 4 if self.cplay else 0.0

    def chop_transport(self, play):
        self.cplay = play
        if play:
            self.cplay_t0 = time.perf_counter()
        else:
            self.crec_on = False
        self.eng.post("chop_transport", play, self.cbpm, self.cclick and self.crec_on)

    # quantize grids, in 16ths: 1/16, 1/8, 1/32, 1/16 triplets (three per eighth), 1/4, off
    QUANTS = [("1/16", 1.0), ("1/8", 2.0), ("1/32", 0.5), ("1/16 triplet", 2.0 / 3.0), ("1/4", 4.0), ("Off", 0.0)]

    def chop_snap(self, pos, L, grid=None, strength=None):
        """A position in 16ths moved toward the quantize grid (by its strength)."""
        grid = self.QUANTS[self.cquant][1] if grid is None else grid
        strength = self.cqstr if strength is None else strength
        if grid <= 0:
            return round(pos, 3) % L
        q = round(pos / grid) * grid
        return round(pos + (q - pos) * strength, 3) % L

    def chop_record_hit(self, g, i, vel):
        """While recording: the hit lands on the quantize grid (1/16 to start with)."""
        pt = self.cgroups[g]["pattern"]
        L = pt["bars"] * 16
        # what you hear is about 0.1 s behind the clock here (the engine's block, then the
        # sound card's buffer), so a hit on the beat you hear is moved back by that much
        cur = (self.chop_pos() - 0.1 * self.cbpm / 60.0 * 4) % L
        q = self.chop_snap(cur, L)
        ahead = (q > cur + 1e-6) or (q < 1.0 and cur > L - 1.0)   # moved later: the sequencer would play it again
        pt["ev"] = [e for e in pt["ev"] if not (abs(e[0] - q) < 0.02 and e[1] == i)] + [[q, i, round(vel, 2)]]
        self.eng.post("chop_add", g, q, i, float(vel), bool(ahead))

    def chop_quantize_pattern(self, g):
        """Snap every hit of a group's pattern to the grid, at the set strength."""
        pt = self.cgroups[g]["pattern"]
        L = pt["bars"] * 16
        if self.QUANTS[self.cquant][1] <= 0:
            self.flash("QUANTIZE IS OFF   PICK A GRID FIRST")
            return
        seen, out = set(), []
        for e in pt["ev"]:
            q = self.chop_snap(e[0], L)
            if (round(q, 2), e[1]) in seen:
                continue                                     # two hits of one pad on one step: keep one
            seen.add((round(q, 2), e[1]))
            out.append([q, e[1], e[2]])
        pt["ev"] = out
        self.chop_send_seq(g)
        self.flash("GROUP %s QUANTIZED TO %s" % (GROUPS[g], self.QUANTS[self.cquant][0].upper()))

    def chop_erase_pad(self, g, i):
        pt = self.cgroups[g]["pattern"]
        n = len(pt["ev"])
        pt["ev"] = [e for e in pt["ev"] if e[1] != i]
        self.chop_send_seq(g)
        self.flash("ERASED PAD %d FROM GROUP %s   %d HITS" % (i + 1, GROUPS[g], n - len(pt["ev"])))

    def chop_commit(self):
        """Commit: play every pattern once from the top and record what comes out,
        punch-ins and all, into a new sound on group D."""
        bars = max(1, max(grp["pattern"]["bars"] for grp in self.cgroups))
        if not any(grp["pattern"]["ev"] for grp in self.cgroups):
            self.flash("NOTHING TO COMMIT   RECORD A PATTERN FIRST")
            return
        secs = bars * 16 * 60.0 / self.cbpm / 4
        os.makedirs(synth.SAMPLE_DIR, exist_ok=True)
        fn = "commit_%s.wav" % time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(synth.SAMPLE_DIR, fn)
        self.chop_transport(False)
        self.chop_transport(True)
        self.eng.post("commit", path, secs)
        self.ccommit = {"path": path, "file": fn, "due": time.perf_counter() + secs + 0.4}
        self.menu = False
        self.flash("COMMITTING %d BAR%s..." % (bars, "" if bars == 1 else "S"))

    # ------------------------------------------------------------ building sounds
    def chop_pad_array(self, g, i):
        p = self.cgroups[g]["pads"][i]
        if not p.get("src"):
            return None
        return shape_fx(raw_audio(p["src"]), p, self.cgroups[g].get("fx"))

    def chop_send_meta(self, g):
        """Each pad's choke and its reverb and delay sends (times the group's)."""
        grp = self.cgroups[g]
        gfx = grp.get("fx") or {}
        pads = grp["pads"]
        if grp.get("keys"):
            pads = [pads[grp.get("keys_pad", 0)]] * 12
        chokes = [bool(p.get("choke", True)) and not grp.get("keys") for p in pads]
        sends = [(p.get("rev", 0.5) * gfx.get("rev", 1.0), p.get("dly", 0.4) * gfx.get("dly", 1.0)) for p in pads]
        self.eng.post("chop_meta", g, chokes, sends)

    def chop_send_group(self, g):
        """Send a group's 12 sounds to the engine (in KEYS, the 12 notes of one sound)."""
        grp = self.cgroups[g]
        if grp.get("keys"):
            k = grp.get("keys_pad", 0)
            p = grp["pads"][k]
            x = raw_audio(p["src"]) if p.get("src") else None
            arrs = [shape_fx(x, p, grp.get("fx"), n) for n in range(12)]
        else:
            arrs = [self.chop_pad_array(g, i) for i in range(12)]
        self.eng.post("chop_load", g, arrs, None)
        self.chop_send_meta(g)
        self.cwave.pop(g, None)

    def chop_send_pad(self, g, i):
        if self.cgroups[g].get("keys"):
            self.chop_send_group(g)
        else:
            self.eng.post("chop_pad", g, i, self.chop_pad_array(g, i))
            self.chop_send_meta(g)

    def chop_to_group(self, g, f, quiet=False):
        """Chop one WAV onto all 12 pads of a group, at its hits."""
        x = synth._sample_audio(f)
        if x is None or len(x) < 1024:
            if not quiet:
                self.flash("COULD NOT READ THAT FILE")
            return
        starts = find_onsets(np.asarray(x, np.float32), 12)
        if len(starts) < 12:                                  # few hits: fill the rest with equal slices
            starts = sorted(set(starts) | {int(len(x) * k / 12) for k in range(12)})[:12]
        bounds = [(s, starts[k + 1] if k + 1 < len(starts) else len(x)) for k, s in enumerate(starts)]
        grp = self.cgroups[g]
        grp["keys"] = False
        grp["pads"] = [{"src": ["file", f, k, int(s), int(e)], "tune": 0, "level": 0.9, "choke": True,
                        "reverse": False} for k, (s, e) in enumerate(bounds)]
        self.cchop_src = f
        self.chop_send_group(g)
        if not quiet:
            self.flash("GROUP %s: %s CHOPPED ONTO 12 PADS" % (GROUPS[g], src_label(["file", f]).upper()))

    # ------------------------------------------------------------ playing
    def chop_hit(self, i, vel=1.0):
        g = self.cgrp
        grp = self.cgroups[g]
        keys = grp.get("keys")
        if not keys and not grp["pads"][i].get("src"):
            self.flash("PAD %d IS EMPTY   SELECT > PAD > SOUND" % (i + 1))
            self.clast = i
            return
        choke = grp["pads"][grp.get("keys_pad", 0) if keys else i].get("choke", True)
        self.eng.post("chop_hit", g, i, float(vel), 0.0, bool(choke) and not keys)
        self.clit[(g, i)] = time.perf_counter()
        self.ctut_n = getattr(self, "ctut_n", 0) + 1
        if self.cplay and self.crec_on:
            self.chop_record_hit(g, i, vel)
        if not keys:
            self.clast = i
            self.cview = (g, i)

    def chop_handle(self, name, down):
        held = self.inp.held
        if name == "SELECT":
            if down:
                self.csel_down, self.csel_combo = True, False
                self.cqe_t = time.perf_counter()
                self.cqe_moved = False
            elif self.csel_down:
                self.csel_down = False
                if not self.csel_combo:
                    self.cedit_g = self.cgrp
                    self.open_menu()
            return True
        if name in PADS:
            if not down:
                return True
            i = PADS.index(name)
            if self.cr3_down:                                 # R3 held + a pad: erase it from the pattern
                self.cr3_combo = True
                self.chop_erase_pad(self.cgrp, i)
                return True
            if self.csel_down and name in ("L1", "R1", "L2", "R2"):
                self.csel_combo = True                         # quick edit: L1/R1 step through pad, group, song
                layers = self.QE_LAYERS
                k = layers.index(self.__dict__.get("cqe_layer", "pad"))
                self.cqe_layer = layers[(k + (1 if name in ("R1", "R2") else -1)) % len(layers)]
                self.cqe_moved = True
                return True
            if self.csel_down and name in ("LEFT", "UP", "DOWN", "RIGHT"):
                self.csel_combo = True
                g = ("LEFT", "UP", "DOWN", "RIGHT").index(name)
                self.cgrp = self.cedit_g = g
                grp = self.cgroups[g]
                self.flash("GROUP %s  %s%s" % (GROUPS[g], GROUP_NAMES[g].upper(), "   KEYS" if grp.get("keys") else ""))
                return True
            self.chop_hit(i)
            return True
        if name == "L3":
            if down:
                self.chop_keys_toggle()
            return True
        if name == "START":
            if down:
                self.chop_transport(not self.cplay)
                self.flash("PLAY   %d BPM" % self.cbpm if self.cplay else "STOPPED")
            return True
        if name == "R3":
            if down:
                self.cr3_down, self.cr3_combo = True, False
            elif self.cr3_down:
                self.cr3_down = False
                if not self.cr3_combo:
                    self.crec_on = not self.crec_on
                    if self.crec_on and not self.cplay:
                        self.chop_transport(True)
                    self.eng.post("chop_transport", self.cplay, self.cbpm, self.cclick and self.crec_on)
                    self.flash("RECORDING INTO GROUP %s" % GROUPS[self.cgrp] if self.crec_on else "RECORD OFF")
            return True
        return False

    def chop_keys_toggle(self):
        grp = self.cgroups[self.cgrp]
        if not grp.get("keys"):
            if not grp["pads"][self.clast].get("src"):
                self.flash("HIT A PAD WITH A SOUND FIRST, THEN L3")
                return
            grp["keys"], grp["keys_pad"] = True, self.clast
            self.flash("KEYS   PAD %d (%s) ACROSS ALL 12 PADS" % (self.clast + 1,
                                                                src_label(grp["pads"][self.clast]["src"]).upper()))
        else:
            grp["keys"] = False
            self.flash("PADS   12 SOUNDS AGAIN")
        self.chop_send_group(self.cgrp)

    # ------------------------------------------------------------ quick edit and the fader
    # Hold SELECT: a panel lists every effect of the last pad (or its group, or the
    # song; L1/R1 switch). Left stick up/down picks one, left/right changes it, and you
    # hear each step. Let go of SELECT and you're playing again. Without SELECT, the
    # left stick is the fader: up/down changes the effect last picked for pads (Tune
    # to start with), left/right the pad's level.
    QE_LAYERS = ["pad", "group", "song"]

    def qe_items(self, layer):
        if layer == "pad":
            return [("fx", s) for s in PAD_FX] + [("bool", ("reverse", "Reverse")), ("bool", ("choke", "Choke"))]
        if layer == "group":
            return [("fx", s) for s in GROUP_FX]
        return [("fx", s) for s in MASTER_FX] + [("tempo", ("tempo", "Tempo")), ("quant", ("quant", "Quantize"))]

    def qe_target(self, layer):
        grp = self.cgroups[self.cgrp]
        if layer == "pad":
            i = grp.get("keys_pad", 0) if grp.get("keys") else self.clast
            return grp["pads"][i], i
        if layer == "group":
            return grp.setdefault("fx", {}), None
        return self.cmaster, None

    def qe_value(self, layer, item):
        d, _ = self.qe_target(layer)
        kind, spec = item
        if kind == "fx":
            return fx_fmt(fx_get(d, spec), spec[6])
        if kind == "bool":
            dflt = spec[0] == "choke"
            return "On" if d.get(spec[0], dflt) else "Off"
        if kind == "quant":
            return self.QUANTS[self.cquant][0]
        return "%d BPM" % self.cbpm

    def qe_change(self, layer, item, step):
        """Change one effect by one step, send it, and let you hear it."""
        g = self.cgrp
        grp = self.cgroups[g]
        d, i = self.qe_target(layer)
        kind, spec = item
        if layer == "pad" and not d.get("src"):
            self.flash("HIT A PAD WITH A SOUND FIRST")
            return
        if kind == "quant":
            self.cquant = (self.cquant + step) % len(self.QUANTS)
            self.flash("QUANTIZE %s" % self.QUANTS[self.cquant][0].upper())
            return
        if kind == "fx":
            fx_step(d, spec, step)
        elif kind == "bool":
            d[spec[0]] = not d.get(spec[0], spec[0] == "choke")
        else:
            self.cbpm = float(max(50, min(220, self.cbpm + step)))
            if self.cplay:
                self.chop_transport(False)
                self.chop_transport(True)
            return
        key = spec[0]
        if layer == "pad":
            if key in ("rev", "dly", "choke"):
                self.chop_send_meta(g)
            else:
                self.chop_send_pad(g, i)
            if not grp.get("keys"):
                self.chop_hit(i, 0.8)
        elif layer == "group":
            if key == "swing":
                self.chop_send_seq(g)
            elif key in ("rev", "dly"):
                self.chop_send_meta(g)
            else:
                self.chop_send_group(g)
                self.chop_hit(self.clast, 0.8)
        else:
            self.eng.post("chop_master", self.cmaster)

    def chop_stick(self, x, y):
        now = time.perf_counter()
        if self.csel_down:                                     # quick edit
            if max(abs(x), abs(y)) < 0.5:
                self.cqe_nav_t = 0.0
                return
            self.csel_combo = True
            self.cqe_moved = True
            self.__dict__.setdefault("ctut_f", {})["qe"] = True
            layer = self.__dict__.get("cqe_layer", "pad")
            items = self.qe_items(layer)
            idx = self.__dict__.setdefault("cqe_idx", {}).get(layer, 0) % len(items)
            wait = 0.22 if not self.__dict__.get("cqe_nav_t") else 0.11
            if now - self.__dict__.get("cqe_last", 0.0) < wait:
                return
            self.cqe_last, self.cqe_nav_t = now, now
            if abs(y) >= abs(x):
                self.cqe_idx[layer] = (idx + (-1 if y > 0 else 1)) % len(items)
            else:
                self.qe_change(layer, items[idx], 1 if x > 0 else -1)
            return
        if max(abs(x), abs(y)) < 0.5 or now - self.cfade_t < 0.16:
            return
        self.cfade_t = now
        grp = self.cgroups[self.cgrp]
        i = grp.get("keys_pad", 0) if grp.get("keys") else self.clast
        p = grp["pads"][i]
        if not p.get("src"):
            return
        items = self.qe_items("pad")
        if abs(y) >= abs(x):
            item = items[self.__dict__.get("cqe_idx", {}).get("pad", 0) % len(items)]
        else:
            item = ("fx", next(s for s in PAD_FX if s[0] == "level"))
        self.qe_change("pad", item, 1 if (y if abs(y) >= abs(x) else x) > 0 else -1)
        what = "%s %s" % (item[1][1].upper(), self.qe_value("pad", item))
        self.cfader = (now, what)
        self.__dict__.setdefault("ctut_f", {})["fader"] = True
        self.flash("PAD %d   %s" % (i + 1, what))

    def draw_quick_edit(self, c, now):
        """The quick-edit panel, while SELECT is held (after a moment, or once used)."""
        if not self.csel_down or (now - self.__dict__.get("cqe_t", now) < 0.25 and not self.__dict__.get("cqe_moved")):
            return
        mm = M()
        W, L = mm.BASE_W, mm.L
        layer = self.__dict__.get("cqe_layer", "pad")
        items = self.qe_items(layer)
        idx = self.__dict__.setdefault("cqe_idx", {}).get(layer, 0) % len(items)
        r = pygame.Rect(W - 300, 44, 284, L["kb_y"] - 50)
        pygame.draw.rect(c, self.mix(mm.BG, mm.PANEL, 0.35), r, border_radius=12)
        pygame.draw.rect(c, mm.ACCENT, r, 2, border_radius=12)
        # the three layers as tabs
        x = r.x + 12
        _, pi = self.qe_target("pad")
        names = {"pad": "PAD %d" % ((pi or 0) + 1), "group": "GROUP %s" % GROUPS[self.cgrp], "song": "SONG"}
        for ly in self.QE_LAYERS:
            on = ly == layer
            t = names[ly]
            w = self.f_small.size(t)[0] + 14
            tr = pygame.Rect(x, r.y + 8, w, 22)
            pygame.draw.rect(c, mm.ACCENT if on else self.mix(mm.BG, mm.PANEL, 0.9), tr, border_radius=6)
            self.text(c, t, self.f_small, mm.BG if on else mm.DIM, tr.center, center=True)
            x += w + 6
        # the list, scrolled to keep the pick in view
        rowh = 22
        rows = (r.h - 70) // rowh
        top = max(0, min(idx - rows // 2, len(items) - rows))
        y = r.y + 38
        for k in range(top, min(len(items), top + rows)):
            item = items[k]
            sel = k == idx
            if sel:
                pygame.draw.rect(c, self.mix(mm.PANEL, mm.ACCENT, 0.35), (r.x + 6, y - 1, r.w - 12, rowh), border_radius=5)
            self.text(c, item[1][1], self.f_small, mm.INK if sel else mm.DIM, (r.x + 14, y + 2))
            self.text(c, self.qe_value(layer, item), self.f_small, mm.ACCENT2 if sel else mm.INK, (r.right - 14, y + 2),
                      right=True)
            y += rowh
        self.text(c, "stick ^v pick  <> change  L1/R1 layer", self.f_small, mm.DIM, (r.centerx, r.bottom - 22),
                  center=True)

    # ------------------------------------------------------------ punch-in FX: the right stick
    PUNCH = [("stutter", "STUTTER"), ("repeat", "BEAT REPEAT"), ("filter", "FILTER SWEEP"), ("crush", "BITCRUSH"),
             ("tapestop", "TAPE STOP"), ("halfspeed", "HALF SPEED"), ("reverse", "REVERSE"), ("throw", "REVERB THROW")]
    # compass, clockwise from up: up stutter, up-right repeat, right filter, down-right crush,
    # down tape stop, down-left half speed, left reverse, up-left reverb throw

    def chop_punch(self, x, y):
        r = math.hypot(x, y)
        cur = getattr(self, "cpunch", None)
        if r < 0.3:
            if cur is not None:
                self.cpunch = None
                self.eng.post("punch", None, 0.0)
            return
        sector = int(round(math.degrees(math.atan2(x, y)) / 45.0)) % 8   # 0 = up, clockwise
        mode, label = self.PUNCH[sector]
        amt = max(0.0, min(1.0, (r - 0.3) / 0.65))
        self.__dict__.setdefault("ctut_f", {})["punch"] = True
        if cur is None or cur[0] != mode or abs(cur[1] - amt) > 0.06:
            self.cpunch = (mode, amt, label)
            self.eng.post("punch", mode, amt)
            self.cpunch_t = time.perf_counter()

    def chop_midi(self, ev):
        """MIDI in: C2 (36) up to B2 play pads 1 to 12, like a drum-pad layout; in KEYS,
        any note plays the sound at that pitch."""
        if ev[0] == "connect":
            self.flash("MIDI IN: %s" % ev[1].upper())
        elif ev[0] == "on":
            self.chop_hit((ev[1] - 36) % 12, max(0.25, ev[2] / 127.0))

    # ------------------------------------------------------------ recording from USB audio
    def chop_record(self):
        import shutil
        import subprocess
        caps = usb_capture_devices()
        if not caps:
            self.flash("NO USB AUDIO INPUT FOUND   PLUG ONE IN, THEN TRY AGAIN")
            return
        if not shutil.which("arecord"):
            self.flash("THIS FIRMWARE HAS NO ARECORD")
            return
        card, dev, name = caps[-1]
        os.makedirs(synth.SAMPLE_DIR, exist_ok=True)
        fn = "rec_%s.wav" % time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(synth.SAMPLE_DIR, fn)
        cmd = ["arecord", "-D", "plughw:%d,%d" % (card, dev), "-f", "S16_LE", "-r", "44100", "-c", "2",
               "-d", str(self.crec_secs), path]
        print("Brickchop: record:", " ".join(cmd), flush=True)
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except Exception as ex:
            self.flash("COULD NOT START RECORDING: %s" % ex)
            return
        self.crec = {"until": time.perf_counter() + self.crec_secs, "proc": proc, "path": path, "file": fn,
                     "name": name, "group": self.cedit_g, "pad": self.clast}
        self.menu = False

    def chop_tick(self, now):
        self.chop_tut_tick(now)
        cm = self.ccommit
        if cm is not None and now >= cm["due"]:
            if os.path.exists(cm["path"]):
                self.ccommit = None
                self.cfiles = chop_files()
                self.csrcs = sources()
                pads = self.cgroups[3]["pads"]
                i = next((k for k, p in enumerate(pads) if not p.get("src")), self.clast if self.cgrp == 3 else 11)
                pads[i] = {"src": ["file", cm["file"]], "tune": 0, "level": 0.9, "choke": True, "reverse": False}
                self.cgroups[3]["keys"] = False
                self.chop_send_group(3)
                self.flash("COMMITTED ONTO GROUP D PAD %d   %s" % (i + 1, cm["file"]))
            elif now > cm["due"] + 5:
                self.ccommit = None
                self.flash("COMMIT FAILED   SEE THE LOG")
        r = self.crec
        if r is None:
            return
        if r["proc"].poll() is None:
            self.flash("RECORDING FROM %s   %.0f s" % (r["name"].upper(), max(0, r["until"] - now) + 0.4))
            return
        out = (r["proc"].stdout.read() or b"").decode("utf-8", "replace").strip()
        if out:
            print("Brickchop: arecord says:", out[-400:], flush=True)
        self.crec = None
        ok = os.path.exists(r["path"]) and os.path.getsize(r["path"]) > 4096
        print("Brickchop: recorded %s: %s bytes" % (r["file"], os.path.getsize(r["path"]) if ok else 0), flush=True)
        if not ok:
            self.flash("NOTHING CAME IN   SEE THE LOG")
            return
        self.cfiles = chop_files()
        self.csrcs = sources()
        g, i = r["group"], r["pad"]
        self.cgroups[g]["pads"][i]["src"] = ["file", r["file"]]
        self.cgrp = g
        self.chop_send_pad(g, i)
        self.flash("SAMPLED %s ONTO GROUP %s PAD %d" % (r["name"].upper(), GROUPS[g], i + 1))

    # ------------------------------------------------------------ settings
    def chop_menu_pages(self):
        return ["Songs", "Pad", "Group", "Seq", "Master", "Global", "FX"]

    # ------------------------------------------------------------ songs: everything, in 8 slots
    def chop_song_path(self, n):
        d = os.path.join(os.path.dirname(synth.SAMPLE_DIR), "songs_chop")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "song_%d.json" % n)

    def chop_song_read(self, n):
        try:
            import json
            with open(self.chop_song_path(n)) as f:
                return json.load(f)
        except Exception:
            return None

    def chop_song_summary(self, s):
        if not s:
            return "empty"
        ch = s.get("chop") or {}
        hits = [len((g.get("pattern") or {}).get("ev", [])) for g in ch.get("groups", [])]
        used = "".join(GROUPS[k] for k, h in enumerate(hits) if h)
        return "%d BPM   %s" % (ch.get("bpm", 100), ("groups " + used) if used else "no patterns")

    def chop_song_save(self, n):
        import json
        song = {"version": 1, "saved": time.strftime("%Y-%m-%d %H:%M"), "key": self.key, "scale": self.scale,
                "chop": self.chop_state(),
                "fx": {"rev": self.base_rev, "dly": self.base_dly, "rev_type": self.rev_type,
                       "dly_type": self.dly_type, "dly_time": self.dly_time}}
        try:
            with open(self.chop_song_path(n), "w") as f:
                json.dump(song, f, indent=1)
            self.csong = n
            self.flash("SAVED TO SONG %d   %s" % (n, self.chop_song_summary(song)))
        except Exception as ex:
            self.flash("COULD NOT SAVE: %s" % ex)

    def chop_song_load(self, n):
        s = self.chop_song_read(n)
        if not s:
            self.flash("SONG %d IS EMPTY   SAVE ONE FIRST" % n)
            return
        self.chop_transport(False)
        self.key, self.scale = int(s.get("key", self.key)), s.get("scale", self.scale)
        fx = s.get("fx") or {}
        self.base_rev, self.base_dly = fx.get("rev", self.base_rev), fx.get("dly", self.base_dly)
        self.rev_type, self.dly_type = fx.get("rev_type", self.rev_type), fx.get("dly_type", self.dly_type)
        self.dly_time = fx.get("dly_time", self.dly_time)
        self.cfg["chop"] = s.get("chop") or {}
        tut = getattr(self, "ctut", None)
        self.chop_init()
        self.ctut = tut
        self.rev, self.dly = self.base_rev, self.base_dly
        self.push_types()
        self.push_fx()
        self.csong = n
        self.save_cfg()
        self.menu = False
        self.flash("SONG %d   %s   START PLAYS IT" % (n, self.chop_song_summary(s)))

    # ------------------------------------------------------------ the guided demo
    TUT = [
        ("Hit the pads: the shoulders, the D-pad and Y X B A are 12 pads", lambda s: s.ctut_n >= 6),
        ("Hold SELECT and press ^ for group B, the bass", lambda s: s.cgrp == 1),
        ("B is in KEYS: each pad is a note. Play a little bass line", lambda s: s.ctut_n >= 4),
        ("Hold SELECT and press < to go back to group A, the drums", lambda s: s.cgrp == 0),
        ("Press START to play, then click the RIGHT STICK (R3) to record", lambda s: s.cplay and s.crec_on),
        ("Play a beat. It loops: add a little more each time round", lambda s: len(s.cgroups[0]["pattern"]["ev"]) >= 4),
        ("Click R3 again to stop recording. Your beat keeps playing", lambda s: not s.crec_on),
        ("Push the RIGHT STICK while it plays: punch-in FX, only while held", lambda s: s.ctut_f.get("punch")),
        ("LEFT STICK is the fader: up and down tunes the last pad. Try it", lambda s: s.ctut_f.get("fader")),
        ("Hold SELECT: every effect. Stick ^v picks, <> changes, L1/R1 pad/group/song",
         lambda s: s.ctut_f.get("qe") and not s.csel_down),
        ("Done! SELECT > Seq > Commit records it all into a new sound. START stops", lambda s: not s.cplay),
    ]

    def chop_tut_start(self):
        self.ctut, self.ctut_n, self.ctut_f, self.ctut_t = 0, 0, {}, time.perf_counter()

    def chop_tut_tick(self, now):
        k = getattr(self, "ctut", None)
        if k is None:
            return
        if self.menu:
            self.ctut = None                                  # opening Settings ends the demo
            self.cfg["chop_tutorial_done"] = True
            return
        if now - self.ctut_t > 0.6 and self.TUT[k][1](self):
            self.ctut += 1
            self.ctut_n, self.ctut_t = 0, now
            self.eng.post("click")
            if self.ctut >= len(self.TUT):
                self.ctut = None
                self.cfg["chop_tutorial_done"] = True
                self.save_cfg()
                self.flash("THAT'S BRICKCHOP. SELECT > SONGS SAVES IT")

    def chop_menu_items(self, pg):
        g = self.cedit_g
        grp = self.cgroups[g]
        if pg == "Songs":
            cur = getattr(self, "csong", 1)
            rows = [("Song %d%s" % (n, "  *" if n == cur else ""), self.chop_song_summary(self.chop_song_read(n)))
                    for n in range(1, 9)]
            return rows + [("Save", "A saves to song %d" % cur), ("Load", "A loads song %d" % cur),
                           ("Guided demo", "A starts it")]
        if pg == "Seq":
            pt = grp["pattern"]
            return [("Group", "%s  %s" % (GROUPS[g], GROUP_NAMES[g])),
                    ("Tempo", "%d BPM" % self.cbpm),
                    ("Bars", "%d" % pt["bars"]),
                    ("Quantize", self.QUANTS[self.cquant][0]),
                    ("Quantize strength", "%d%%" % round(self.cqstr * 100)),
                    ("Quantize pattern", "A snaps group %s's hits to the grid" % GROUPS[g]),
                    ("Click", "On while recording" if self.cclick else "Off"),
                    ("Hits", "%d in this group's pattern" % len(pt["ev"])),
                    ("Clear pattern", "A clears group %s" % GROUPS[g]),
                    ("Clear all", "A clears every group"),
                    ("Commit", "A records every pattern into a new sound on D"),
                    ("Audition pad", "A plays pad %d's whole sound" % (self.clast + 1))]
        if pg == "Group":
            files = [s for s in self.csrcs if s[0] == "file"]
            cs = self.cchop_src or (files[0][1] if files else None)
            caps = usb_capture_devices()
            return [("Group", "%s  %s" % (GROUPS[g], GROUP_NAMES[g])),
                    ("Mode", "Keys (pad %d)" % (grp.get("keys_pad", 0) + 1) if grp.get("keys") else "12 pads")] + \
                [(s[1], fx_fmt(fx_get(grp.get("fx"), s), s[6])) for s in GROUP_FX] + [
                    ("Reset group FX", "A sets the group's effects back"),
                    ("Chop file", src_label(["file", cs]) if cs else "no WAVs found"),
                    ("Chop to group", "A chops it onto all 12 pads"),
                    ("Load kit", "A loads %s" % getattr(self, "ckit_pick", kit_list()[0])),
                    ("Kit", getattr(self, "ckit_pick", kit_list()[0])),
                    ("Record", ("A records %d s from %s" % (self.crec_secs, caps[-1][2])) if caps else "no USB audio input"),
                    ("Record length", "%d s" % self.crec_secs),
                    ("Rescan files", "%d WAVs" % len(self.cfiles))]
        if pg == "Master":
            return [(s[1], fx_fmt(fx_get(self.cmaster, s), s[6])) for s in MASTER_FX] + \
                [("Reset master", "A sets every master effect back")]
        i = self.clast
        p = grp["pads"][i]
        return ([("Group", "%s  %s" % (GROUPS[g], GROUP_NAMES[g])),
                 ("Pad", "%d   %s" % (i + 1, GLYPH[PADS[i]])),
                 ("Sound", src_label(p.get("src")))] +
                [(s[1], fx_fmt(fx_get(p, s), s[6])) for s in PAD_FX] +
                [("Choke", "On" if p.get("choke", True) else "Off"),
                 ("Reverse", "On" if p.get("reverse") else "Off"),
                 ("Copy FX to group", "A gives all 12 pads these effects"),
                 ("Reset pad FX", "A sets this pad's effects back"),
                 ("Clear pad", "A empties it")])

    def chop_menu_change(self, pg, name, d):
        g = self.cedit_g
        grp = self.cgroups[g]
        if pg == "Songs":
            if name.startswith("Song "):
                self.csong = int(name.split()[1])
            return
        if name == "Group":
            self.cedit_g = (g + d) % 4
            self.cgrp = self.cedit_g
            return
        if pg == "Seq":
            pt = grp["pattern"]
            if name == "Tempo":
                self.cbpm = float(max(50, min(220, self.cbpm + d)))
                self.eng.post("chop_transport", self.cplay, self.cbpm, self.cclick and self.crec_on)
                if self.cplay:                                # keep the UI clock in step
                    self.chop_transport(False)
                    self.chop_transport(True)
            elif name == "Bars":
                opts = [1, 2, 4]
                pt["bars"] = opts[(opts.index(pt["bars"]) + d) % 3 if pt["bars"] in opts else 0]
                L = pt["bars"] * 16
                pt["ev"] = [e for e in pt["ev"] if e[0] < L]
                self.chop_send_seq(g)
            elif name == "Click":
                self.cclick = not self.cclick
            elif name == "Quantize":
                self.cquant = (self.cquant + d) % len(self.QUANTS)
            elif name == "Quantize strength":
                self.cqstr = round(max(0.25, min(1.0, self.cqstr + 0.25 * d)), 2)
            return
        if pg == "Master":
            spec = next((s for s in MASTER_FX if s[1] == name), None)
            if spec:
                fx_step(self.cmaster, spec, d)
                self.eng.post("chop_master", self.cmaster)
            return
        if pg == "Group" and any(s[1] == name for s in GROUP_FX):
            spec = next((s for s in GROUP_FX if s[1] == name), None)
            if spec:
                gfx = grp.setdefault("fx", {})
                fx_step(gfx, spec, d)
                if spec[0] == "swing":
                    self.chop_send_seq(g)
                elif spec[0] in ("rev", "dly"):
                    self.chop_send_meta(g)
                else:
                    self.chop_send_group(g)
                    self.cgrp = g
                    self.chop_hit(self.clast, 0.8)
            return
        if pg == "Group":
            if name == "Mode":
                self.cgrp = g
                self.chop_keys_toggle()
            elif name == "Chop file":
                files = [s[1] for s in self.csrcs if s[0] == "file"]
                if files:
                    cur = self.cchop_src if self.cchop_src in files else files[0]
                    self.cchop_src = files[(files.index(cur) + d) % len(files)]
            elif name == "Kit":
                kits = kit_list()
                cur = getattr(self, "ckit_pick", kits[0])
                self.ckit_pick = kits[(kits.index(cur) + d) % len(kits) if cur in kits else 0]
            elif name == "Record length":
                opts = [2, 4, 8, 12]
                self.crec_secs = opts[(opts.index(self.crec_secs) + d) % 4 if self.crec_secs in opts else 1]
            return
        i = self.clast
        p = grp["pads"][i]
        if name == "Pad":
            self.clast = (i + d) % 12
            return
        if name == "Sound":
            opts = [None] + self.csrcs
            key = [tuple(s) if s else None for s in opts]
            cur = tuple(p["src"][:2]) if p.get("src") else None
            k = next((n for n, s in enumerate(key) if (s and cur and s[:2] == cur) or (s is None and cur is None)), 0)
            nxt = opts[(k + d) % len(opts)]
            p["src"] = list(nxt) if nxt else None
        elif any(s[1] == name for s in PAD_FX):
            spec = next(s for s in PAD_FX if s[1] == name)
            fx_step(p, spec, d)
            if spec[0] in ("rev", "dly"):
                self.chop_send_meta(g)
                self.cgrp = g
                if p.get("src") and not grp.get("keys"):
                    self.chop_hit(i, 0.8)
                return
        elif name == "Choke":
            p["choke"] = not p.get("choke", True)
            self.chop_send_meta(g)
            return
        elif name == "Reverse":
            p["reverse"] = not p.get("reverse")
        else:
            return
        self.cgrp = g
        self.chop_send_pad(g, i)
        if p.get("src") and not grp.get("keys"):
            self.chop_hit(i, 0.8)                              # hear it as you change it

    def chop_menu_activate(self, pg, name):
        g = self.cedit_g
        if pg == "Songs":
            if name.startswith("Song "):
                n = int(name.split()[1])
                if getattr(self, "csong", None) == n and self.chop_song_read(n):
                    self.chop_song_load(n)
                else:
                    self.csong = n
                    self.flash("SONG %d SELECTED   A AGAIN LOADS, OR SAVE BELOW" % n)
            elif name == "Save":
                self.chop_song_save(getattr(self, "csong", 1))
            elif name == "Load":
                self.chop_song_load(getattr(self, "csong", 1))
            elif name == "Guided demo":
                self.menu = False
                self.chop_tut_start()
            return
        if pg == "Seq":
            if name == "Clear pattern":
                self.cgroups[g]["pattern"]["ev"] = []
                self.chop_send_seq(g)
                self.flash("GROUP %s PATTERN CLEARED" % GROUPS[g])
            elif name == "Clear all":
                for k in range(4):
                    self.cgroups[k]["pattern"]["ev"] = []
                    self.chop_send_seq(k)
                self.flash("ALL PATTERNS CLEARED")
            elif name == "Commit":
                self.chop_commit()
            elif name == "Quantize pattern":
                self.chop_quantize_pattern(g)
            elif name == "Audition pad":
                self.eng.post("chop_audition", self.chop_pad_array(self.cgrp, self.clast))
            return
        if name == "Chop to group" and self.cchop_src:
            self.chop_to_group(g, self.cchop_src)
            self.cgrp = g
        elif name in ("Chop file",) and not self.cchop_src:
            self.flash("NO WAVs FOUND   COPY SOME INTO A SAMPLES FOLDER")
        elif name == "Load kit":
            k = getattr(self, "ckit_pick", kit_list()[0])
            grp = self.cgroups[g]
            grp["keys"] = False
            pad = lambda part, tune=0: {"src": ["kit", "%s/%s" % (k, part)], "tune": tune, "level": 0.9,
                                        "choke": True, "reverse": False}
            # the shoulders get pitched-down extras; the D-pad and face buttons the main eight
            grp["pads"] = [pad("kick", -3), pad("snare", -3), pad("tom", -5), pad("clap", -2)] + \
                [pad(p) for p in KIT_PARTS]
            self.chop_send_group(g)
            self.cgrp = g
            self.flash("GROUP %s: %s KIT" % (GROUPS[g], k.upper()))
        elif name == "Record":
            self.chop_record()
        elif name == "Rescan files":
            self.cfiles = chop_files()
            self.csrcs = sources()
            self.flash("%d WAVs FOUND" % len(self.cfiles))
        elif name == "Copy FX to group":
            src = self.cgroups[g]["pads"][self.clast]
            keys = [s[0] for s in PAD_FX if s[0] not in ("tune", "level", "start", "length")]
            for q in self.cgroups[g]["pads"]:
                for k in keys:
                    if k in src:
                        q[k] = src[k]
            self.chop_send_group(g)
            self.flash("PAD %d's EFFECTS ON ALL 12 PADS OF GROUP %s" % (self.clast + 1, GROUPS[g]))
        elif name == "Reset pad FX":
            q = self.cgroups[g]["pads"][self.clast]
            for s in PAD_FX:
                q.pop(s[0], None) if s[0] not in ("tune", "level") else None
            self.chop_send_pad(g, self.clast)
            self.flash("PAD %d EFFECTS RESET" % (self.clast + 1))
        elif name == "Reset group FX":
            self.cgroups[g]["fx"] = {}
            self.chop_send_group(g)
            self.chop_send_seq(g)
            self.flash("GROUP %s EFFECTS RESET" % GROUPS[g])
        elif name == "Reset master":
            self.cmaster.clear()
            self.eng.post("chop_master", self.cmaster)
            self.flash("MASTER EFFECTS RESET")
        elif name == "Clear pad":
            self.cgroups[g]["pads"][self.clast]["src"] = None
            self.chop_send_pad(g, self.clast)
        elif name == "Mode":
            self.cgrp = g
            self.chop_keys_toggle()

    def chop_header_info(self):
        grp = self.cgroups[self.cgrp]
        tr = ("  REC" if self.crec_on else "  PLAY") if self.cplay else ""
        return "GROUP %s  %s%s   %d BPM%s" % (GROUPS[self.cgrp], GROUP_NAMES[self.cgrp].upper(),
                                              "  KEYS" if grp.get("keys") else "", self.cbpm, tr)

    # ------------------------------------------------------------ screen
    def chop_wave(self, g, i):
        key = (g, i, self.cgroups[g].get("keys"))
        w = self.cwave.get(key)
        if w is None:
            grp = self.cgroups[g]
            p = grp["pads"][grp.get("keys_pad", 0) if grp.get("keys") else i]
            x = raw_audio(p["src"]) if p.get("src") else None
            if x is None or len(x) < 32:
                w = False
            else:
                cols = 200
                step = max(1, len(x) // cols)
                n = (len(x) // step) * step
                xs = x[:n].reshape(-1, step)
                w = (xs.min(axis=1), xs.max(axis=1))
            self.cwave[key] = w
        return w

    def draw_chop(self, c, now):
        mm = M()
        W, L = mm.BASE_W, mm.L
        g = self.cgrp
        grp = self.cgroups[g]
        keys = grp.get("keys")
        # the 3 x 4 pad grid
        tw, th, gap = 92, 70, 8
        gx, gy = 20, 50
        for i, btn in enumerate(PADS):
            r = pygame.Rect(gx + (i % 4) * (tw + gap), gy + (i // 4) * (th + gap), tw, th)
            lv = max(0.0, 1.0 - (now - self.clit.get((g, i), -9)) / 0.25)
            if keys:
                base = grp["pads"][grp.get("keys_pad", 0)]
                have = bool(base.get("src"))
                label = NOTE[(i + base.get("tune", 0)) % 12]
            else:
                p = grp["pads"][i]
                have = bool(p.get("src"))
                label = src_label(p.get("src")) if have else ""
            last = (i == self.clast) and not keys
            fill = mm.PANEL if have else self.mix(mm.BG, mm.PANEL, 0.4)
            pygame.draw.rect(c, self.mix(fill, mm.ACCENT, lv), r, border_radius=10)
            if last:
                pygame.draw.rect(c, mm.ACCENT2, r, 2, border_radius=10)
            self.text(c, str(i + 1), self.f_small, self.mix(mm.ACCENT2 if have else mm.DIM, mm.BG, lv), (r.x + 8, r.y + 5))
            self.text(c, GLYPH[btn], self.f_small, self.mix(mm.DIM, mm.BG, lv), (r.right - 8, r.y + 5), right=True)
            if label:
                f = self.f_med if keys else self.f_small
                txt = label if self.f_small.size(label)[0] < tw - 10 else label[: max(3, len(label) * (tw - 14) // max(1, self.f_small.size(label)[0]))]
                self.text(c, txt, f, self.mix(mm.INK, mm.BG, lv), (r.centerx, r.y + th // 2 + (2 if keys else 8)),
                          center=True)
        # the right panel: group, mode, the last pad and the fader
        px, pw = gx + 4 * (tw + gap) + 8, W - 20 - (gx + 4 * (tw + gap) + 8)
        ph = 3 * th + 2 * gap
        pygame.draw.rect(c, self.mix(mm.BG, mm.PANEL, 0.7), (px, gy, pw, ph), border_radius=10)
        self.text(c, GROUPS[g], self.f_big, mm.ACCENT, (px + 14, gy + 8))
        self.text(c, GROUP_NAMES[g].upper(), self.f_small, mm.INK, (px + 58, gy + 12))
        self.text(c, "KEYS" if keys else "12 PADS", self.f_small, mm.ACCENT2 if keys else mm.DIM, (px + 58, gy + 32))
        i = grp.get("keys_pad", 0) if keys else self.clast
        p = grp["pads"][i]
        self.text(c, "PAD %d" % (i + 1), self.f_small, mm.DIM, (px + 14, gy + 84))
        name = src_label(p.get("src"))
        while len(name) > 3 and self.f_small.size(name)[0] > pw - 24:
            name = name[:-2]
        self.text(c, name, self.f_small, mm.INK, (px + 14, gy + 104))
        pn = getattr(self, "cpunch", None)
        if pn is not None:                                    # punch-in FX held: say which, and how hard
            pygame.draw.rect(c, mm.ACCENT, (px, gy, pw, ph), 3, border_radius=10)
            self.text(c, pn[2], self.f_small, mm.ACCENT, (px + 14, gy + 128))
            pygame.draw.rect(c, self.mix(mm.BG, mm.PANEL, 0.9), (px + 14, gy + 150, pw - 28, 8), border_radius=4)
            pygame.draw.rect(c, mm.ACCENT, (px + 14, gy + 150, int((pw - 28) * (0.15 + 0.85 * pn[1])), 8),
                             border_radius=4)
            return_early = True
        else:
            return_early = False
        hot = self.cfader and now - self.cfader[0] < 1.0
        items = self.qe_items("pad")
        fitem = items[self.__dict__.get("cqe_idx", {}).get("pad", 0) % len(items)]
        if not return_early:                                   # the fader: what up/down changes now
            self.text(c, fitem[1][1].lower(), self.f_small, mm.DIM, (px + 14, gy + 132))
            self.text(c, self.qe_value("pad", fitem), self.f_med, mm.ACCENT2 if hot else mm.INK, (px + 14, gy + 150))
        self.text(c, "level %d%%" % round(p.get("level", 0.9) * 100), self.f_small, mm.DIM, (px + 14, gy + 186))
        # the last pad's sound, wide, under the grid
        wx0, wx1, wy0 = 20, W - 20, gy + ph + 12
        wy1 = L["kb_y"] - 10
        pygame.draw.rect(c, self.mix(mm.BG, mm.PANEL, 0.45), (wx0, wy0, wx1 - wx0, wy1 - wy0), border_radius=10)
        w = self.chop_wave(g, i)
        if w:
            mn, mx = w
            n = len(mn)
            pk = max(1e-6, float(max(abs(mn.min()), abs(mx.max()))))
            cy, hh = (wy0 + wy1 - 22) // 2, (wy1 - 22 - wy0) // 2 - 4    # room for the steps below
            lv = max(0.0, 1.0 - (now - self.clit.get((g, i if not keys else -1), -9)) / 0.4)
            top = [(wx0 + 8 + int((wx1 - wx0 - 16) * k / n), cy - int(mx[k] / pk * hh)) for k in range(n)]
            bot = [(wx0 + 8 + int((wx1 - wx0 - 16) * k / n), cy - int(mn[k] / pk * hh)) for k in range(n)]
            if len(top) > 1:
                pygame.draw.polygon(c, self.mix(mm.INK, mm.ACCENT, lv), top + bot[::-1])
        else:
            self.text(c, "empty pad   SELECT > Pad > Sound", self.f_small, mm.DIM, ((wx0 + wx1) // 2, (wy0 + wy1) // 2 - 9),
                      center=True)
        # the group's pattern: 16 steps of the bar the playhead is in
        pt = grp["pattern"]
        L = pt["bars"] * 16
        pos = self.chop_pos() % L if self.cplay else -1
        bar = int(pos // 16) if pos >= 0 else 0
        steps = {}
        for e in pt["ev"]:
            steps.setdefault(int(e[0]) % L, []).append(e[1])
        sw = (wx1 - wx0 - 16) / 16.0
        sy = wy1 - 18
        for s in range(16):
            k = bar * 16 + s
            r = pygame.Rect(int(wx0 + 8 + s * sw) + 1, sy, int(sw) - 3, 12)
            on = k in steps
            here = pos >= 0 and int(pos) == k
            col = self.mix(mm.BG, mm.DIM, 0.35 if s % 4 else 0.6)
            if on:
                col = mm.ACCENT2 if self.clast in steps[k] else self.mix(mm.ACCENT2, mm.BG, 0.35)
            if here:
                col = mm.ACCENT if not self.crec_on else (235, 60, 60)
            pygame.draw.rect(c, col, r, border_radius=3)
        if pt["bars"] > 1:
            self.text(c, "bar %d/%d" % (bar + 1, pt["bars"]), self.f_small, mm.DIM, (wx1 - 8, wy0 + 4), right=True)
        k = getattr(self, "ctut", None)
        if k is not None:                                     # the guided demo: one line at a time
            msg = self.TUT[k][0]
            r = pygame.Rect(wx0, wy0, wx1 - wx0, 34)
            pygame.draw.rect(c, mm.ACCENT, r, border_radius=8)
            self.text(c, "%d/%d" % (k + 1, len(self.TUT)), self.f_small, mm.BG, (r.x + 10, r.y + 7))
            while len(msg) > 8 and self.f_small.size(msg)[0] > r.w - 70:
                msg = msg[:-2]
            self.text(c, msg, self.f_small, mm.BG, (r.x + 52, r.y + 7))

    def draw_chop_bar(self, c, now):
        """Where the keyboard is in Brickchord: the four groups and what is on them."""
        mm = M()
        W, L = mm.BASE_W, mm.L
        ky, kh = L["kb_y"], L["kb_h"]
        pygame.draw.rect(c, mm.BG, (0, ky - 2, W, kh + 4))
        x = 20
        for g in range(4):
            on = g == self.cgrp
            grp = self.cgroups[g]
            r = pygame.Rect(x, ky + 4, 140, kh - 8)
            pygame.draw.rect(c, mm.ACCENT if on else self.mix(mm.BG, mm.PANEL, 0.9), r, border_radius=8)
            self.text(c, "%s  %s" % (GROUPS[g], GROUP_NAMES[g]), self.f_small, mm.BG if on else mm.INK,
                      (r.x + 10, r.centery - 9))
            if grp.get("keys"):                                 # KEYS: a little keyboard mark
                for k in range(4):
                    pygame.draw.rect(c, mm.BG if on else mm.ACCENT2, (r.right - 46 + k * 6, r.centery - 5, 4, 10))
            hit = max([self.clit.get((g, k), -9) for k in range(12)])
            lv = max(0.0, 1.0 - (now - hit) / 0.25)
            pygame.draw.circle(c, self.mix(mm.BG if on else mm.DIM, mm.ACCENT2, lv), (r.right - 14, r.centery), 5)
            x += 150
        self.draw_quick_edit(c, now)


# ---------------------------------------------------------------- the intro film
# A loop runs in like tape, a beat plays and each hit chops a slice off the loop and
# throws it onto one of the 12 pads; a stutter, a tape stop, a breath, and the name
# lands on the downbeat. About five seconds; any button skips it.
INTRO_BPM = 128.0
INTRO_STEP = 60.0 / INTRO_BPM / 4
INTRO_T0 = 0.45
# step: (parts...)    one bar of beat, then the stutter, the tape stop, the drop
INTRO_BEAT = {0: ("kick", "hat"), 2: ("hat",), 3: ("kick",), 4: ("snare", "hat"), 6: ("hat",), 7: ("kick",),
              8: ("kick", "hat"), 10: ("ohat",), 11: ("kick",), 12: ("snare", "clap"), 14: ("hat",), 15: ("rim",),
              16: ("kick", "snare"), 20: ("snare", "kick"), 21: ("hat",), 22: ("snare",), 23: ("hat",), 24: ("kick",)}
INTRO_DROP = 28
INTRO_SECS = INTRO_T0 + INTRO_DROP * INTRO_STEP + 1.55


def _intro_wave(n=240):
    rng = np.random.RandomState(7)
    env = np.zeros(n)
    for s in range(16):
        k = int(s * n / 16)
        strength = 1.0 if s in (0, 3, 7, 8, 11) else (0.85 if s in (4, 12) else 0.45)
        L = n // 16
        env[k:k + L] = np.maximum(env[k:k + L], strength * np.exp(-np.arange(min(L, n - k)) / (L * 0.35)))
    return env * (0.7 + 0.3 * rng.rand(n))


class ChopIntroMixin:
    def chop_intro_start(self):
        self.ci_hits = sorted((INTRO_T0 + s * INTRO_STEP, s, parts) for s, parts in INTRO_BEAT.items())
        self.ci_fired = set()
        self.ci_wave = _intro_wave()
        self.ci_slices = []                                   # (time, slice index, pad index)
        self.ci_punch = None
        self.ci_dropped = False

    def chop_intro_tick(self, t):
        while self.ci_hits and t >= self.ci_hits[0][0]:
            _, s, parts = self.ci_hits.pop(0)
            for p in parts:
                self.eng.post("hit", p, 0.95 if p in ("kick", "snare", "clap") else 0.55)
            if s < 16 and len(self.ci_slices) < 12:
                self.ci_slices.append((t, s, len(self.ci_slices)))
        st = (t - INTRO_T0) / INTRO_STEP
        want = None
        if 16 <= st < 20:
            want = ("stutter", 0.95)
        elif 20 <= st < 26:
            want = ("tapestop", 0.45)
        if want != self.ci_punch:
            self.ci_punch = want
            self.eng.post("punch", *(want or (None, 0.0)))
        if not self.ci_dropped and st >= INTRO_DROP:
            self.ci_dropped = True
            self.eng.post("hit", "kick", 1.0)
            self.eng.post("hit", "clap", 0.9)
            self.chime()

    def chop_intro_end(self):
        if getattr(self, "ci_punch", None):
            self.eng.post("punch", None, 0.0)
        self.ci_punch = None
        self._intro_done = True

    def draw_chop_intro(self, c, t):
        mm = M()
        W, H = mm.BASE_W, mm.BASE_H
        dy = mm.L["dy"]
        st = (t - INTRO_T0) / INTRO_STEP
        rng = np.random.RandomState(int(t * 60))
        # the stutter shakes; the tape stop sinks and fades
        shake = (rng.randint(-5, 6), rng.randint(-4, 5)) if 16 <= st < 20 else (0, 0)
        sink = 0.0
        if 20 <= st < INTRO_DROP:
            k = min(1.0, (st - 20) / 6.0)
            sink = k * k
        fade = 1.0 - 0.85 * sink
        # the loop, running in from the left like tape, then losing its slices
        wave = self.ci_wave
        n = len(wave)
        wx0, wx1, wy = 20, W - 20, 104 + dy + int(sink * 60)
        reveal = min(1.0, t / INTRO_T0)
        cut = {s for (_, s, _) in self.ci_slices}
        col = self.mix(mm.BG, mm.INK, fade)
        stretch = 1.0 + 0.35 * sink
        for k in range(int(n * reveal)):
            s = int(k * 16 / n)
            if s in cut:
                continue
            x = wx0 + int((wx1 - wx0) * k / n * stretch) + shake[0]
            if x > wx1:
                break
            h = int(wave[k] * 52 * (1 - 0.6 * sink))
            pygame.draw.line(c, col, (x, wy - h + shake[1]), (x, wy + h + shake[1]), 2)
        # the knife: a flash at each fresh cut
        for (ts, s, pi) in self.ci_slices:
            age = t - ts
            if age < 0.12:
                x = wx0 + int((wx1 - wx0) * s / 16) + shake[0]
                a = 1 - age / 0.12
                pygame.draw.line(c, self.mix(mm.BG, (255, 255, 255), a), (x, wy - 70), (x, wy + 70), 3)
        # the 12 pads: each slice flies down into the next pad
        tw, th, gap = 92, 46, 8
        gx = (W - (4 * tw + 3 * gap)) // 2
        gy = 210 + dy + int(sink * 110)
        for i in range(12):
            r = pygame.Rect(gx + (i % 4) * (tw + gap) + shake[0], gy + (i // 4) * (th + gap) + shake[1], tw, th)
            filled = next(((ts, s) for (ts, s, pi) in self.ci_slices if pi == i), None)
            appear = min(1.0, max(0.0, (t - 0.15) / 0.3))
            base = self.mix(mm.BG, mm.PANEL, appear * fade)
            pygame.draw.rect(c, base, r, border_radius=9)
            if filled is None:
                continue
            ts, s = filled
            age = t - ts
            fly = min(1.0, age / 0.16)
            fe = 1 - (1 - fly) ** 3
            # the slice travels from its place in the loop to the pad
            sx0 = wx0 + (wx1 - wx0) * s / 16
            sw0 = (wx1 - wx0) / 16
            x = sx0 + (r.x + 8 - sx0) * fe
            y = (wy - 30) + (r.y + 6 - (wy - 30)) * fe
            wdt = sw0 + (tw - 16 - sw0) * fe
            lit = max(0.0, 1 - age / 0.3)
            strobe = 16 <= st < 20 and (int(t * 30) + i) % 2 == 0
            if fly >= 1:
                pygame.draw.rect(c, self.mix(self.mix(mm.PANEL, mm.ACCENT, lit if not strobe else 1.0), mm.BG,
                                              1 - fade), r, border_radius=9)
            k0 = int(s * n / 16)
            seg = wave[k0:k0 + n // 16]
            for j, v in enumerate(seg):
                xx = int(x + wdt * j / max(1, len(seg)))
                hh = int(v * (th / 2 - 8 if fly >= 1 else 30))
                cy = int(y + (th / 2 - 6) * fe + 30 * (1 - fe))
                pygame.draw.line(c, self.mix(mm.BG, mm.ACCENT2 if fly >= 1 else mm.INK, fade),
                                 (xx, cy - hh), (xx, cy + hh), 2)
            self.text(c, str(i + 1), self.f_small, self.mix(mm.BG, mm.ACCENT2, fade * (0.5 + 0.5 * fe)),
                      (r.x + 6, r.y + 3))
        # the drop: a flash, then the name, letter by letter, like pad hits
        td = t - (INTRO_T0 + INTRO_DROP * INTRO_STEP)
        if td >= 0:
            c.fill(mm.BG)
            if td < 0.14:
                flash = pygame.Surface((W, H), pygame.SRCALPHA)
                flash.fill((255, 255, 255, int(200 * (1 - td / 0.14))))
                c.blit(flash, (0, 0))
            bounce = int(10 * math.exp(-td * 9) * math.cos(td * 30))
            self.draw_mark(c, W // 2, 118 + dy - bounce, 30, 2.0)
            word = "brickchop"
            nlet = max(0, min(len(word), int(td / 0.035) + 1))
            surf = self.f_huge.render(word, True, mm.INK)
            x0 = W // 2 - surf.get_width() // 2
            x = x0
            for k, ch in enumerate(word):
                g = self.f_huge.render(ch, True, mm.ACCENT if ch in "chop" and k >= 5 else mm.INK)
                if k < nlet:
                    age = td - k * 0.035
                    yo = int(-18 * math.exp(-max(0.0, age) * 14))
                    c.blit(g, (x, 214 + dy + yo - g.get_height() // 2))
                x += g.get_width()
            if td > 0.5:
                a = min(1.0, (td - 0.5) / 0.35)
                self.text(c, "chop.   play.   punch.", self.f_med, self.mix(mm.BG, mm.ACCENT2, a),
                          (W // 2, 290 + dy), center=True)
