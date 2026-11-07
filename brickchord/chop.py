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


class ChopMixin:
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
        self.cwave = {}
        self.csel_down = self.csel_combo = False
        self.cbpm = float(st.get("bpm", 100))
        self.cclick = bool(st.get("click", True))
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

    def chop_state(self):
        return {"v": 2, "group": self.cgrp, "last": self.clast, "groups": self.cgroups, "rec_secs": self.crec_secs,
                "chop_src": self.cchop_src, "bpm": self.cbpm, "click": self.cclick}

    # ------------------------------------------------------------ the sequencer
    def chop_send_seq(self, g):
        pt = self.cgroups[g]["pattern"]
        self.eng.post("chop_seq", g, pt["bars"] * 16, [[e[0], e[1], e[2], False] for e in pt["ev"]])

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

    def chop_record_hit(self, g, i, vel):
        """While recording: the hit lands on the nearest 16th of the group's pattern."""
        pt = self.cgroups[g]["pattern"]
        L = pt["bars"] * 16
        # what you hear is about 0.1 s behind the clock here (the engine's block, then the
        # sound card's buffer), so a hit on the beat you hear is moved back by that much
        cur = (self.chop_pos() - 0.1 * self.cbpm / 60.0 * 4) % L
        q = int(round(cur)) % L
        ahead = (q > cur) or (q == 0 and cur > L - 0.5)    # rounded up: the sequencer would play it again
        pt["ev"] = [e for e in pt["ev"] if not (e[0] == q and e[1] == i)] + [[q, i, round(vel, 2)]]
        self.eng.post("chop_add", g, q, i, float(vel), bool(ahead))

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
        return shape(raw_audio(p["src"]), p.get("tune", 0), p.get("level", 0.9), p.get("reverse", False))

    def chop_send_group(self, g):
        """Send a group's 12 sounds to the engine (in KEYS, the 12 notes of one sound)."""
        grp = self.cgroups[g]
        if grp.get("keys"):
            k = grp.get("keys_pad", 0)
            p = grp["pads"][k]
            x = raw_audio(p["src"]) if p.get("src") else None
            arrs = [shape(x, p.get("tune", 0) + n, p.get("level", 0.9), p.get("reverse", False)) for n in range(12)]
        else:
            arrs = [self.chop_pad_array(g, i) for i in range(12)]
        self.eng.post("chop_load", g, arrs, None)
        self.cwave.pop(g, None)

    def chop_send_pad(self, g, i):
        if self.cgroups[g].get("keys"):
            self.chop_send_group(g)
        else:
            self.eng.post("chop_pad", g, i, self.chop_pad_array(g, i))

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
        self.eng.post("chop_hit", g, i, float(vel), -0.3 + 0.6 * (i % 4) / 3.0, bool(choke) and not keys)
        self.clit[(g, i)] = time.perf_counter()
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

    def chop_stick(self, x, y):
        """The fader: up/down tunes the last pad a semitone at a time (in KEYS, the
        whole keyboard), left/right sets its level."""
        now = time.perf_counter()
        if max(abs(x), abs(y)) < 0.5 or now - self.cfade_t < 0.16:
            return
        self.cfade_t = now
        grp = self.cgroups[self.cgrp]
        i = grp.get("keys_pad", 0) if grp.get("keys") else self.clast
        p = grp["pads"][i]
        if not p.get("src"):
            return
        if abs(y) >= abs(x):
            p["tune"] = int(max(-24, min(24, p.get("tune", 0) + (1 if y > 0 else -1))))
            what = "TUNE %+d" % p["tune"]
        else:
            p["level"] = round(max(0.05, min(1.6, p.get("level", 0.9) + (0.05 if x > 0 else -0.05))), 2)
            what = "LEVEL %d%%" % round(p["level"] * 100)
        self.chop_send_pad(self.cgrp, i)
        self.cfader = (now, what)
        self.flash("PAD %d   %s" % (i + 1, what))
        if not grp.get("keys"):
            self.chop_hit(i, 0.8)

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
        return ["Pad", "Group", "Seq", "Global", "FX"]

    def chop_menu_items(self, pg):
        g = self.cedit_g
        grp = self.cgroups[g]
        if pg == "Seq":
            pt = grp["pattern"]
            return [("Group", "%s  %s" % (GROUPS[g], GROUP_NAMES[g])),
                    ("Tempo", "%d BPM" % self.cbpm),
                    ("Bars", "%d" % pt["bars"]),
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
                    ("Mode", "Keys (pad %d)" % (grp.get("keys_pad", 0) + 1) if grp.get("keys") else "12 pads"),
                    ("Chop file", src_label(["file", cs]) if cs else "no WAVs found"),
                    ("Chop to group", "A chops it onto all 12 pads"),
                    ("Load kit", "A loads %s" % getattr(self, "ckit_pick", kit_list()[0])),
                    ("Kit", getattr(self, "ckit_pick", kit_list()[0])),
                    ("Record", ("A records %d s from %s" % (self.crec_secs, caps[-1][2])) if caps else "no USB audio input"),
                    ("Record length", "%d s" % self.crec_secs),
                    ("Rescan files", "%d WAVs" % len(self.cfiles))]
        i = self.clast
        p = grp["pads"][i]
        return [("Group", "%s  %s" % (GROUPS[g], GROUP_NAMES[g])),
                ("Pad", "%d   %s" % (i + 1, GLYPH[PADS[i]])),
                ("Sound", src_label(p.get("src"))),
                ("Tune", "%+d" % p.get("tune", 0)),
                ("Level", "%d%%" % round(p.get("level", 0.9) * 100)),
                ("Choke", "On" if p.get("choke", True) else "Off"),
                ("Reverse", "On" if p.get("reverse") else "Off"),
                ("Clear pad", "A empties it")]

    def chop_menu_change(self, pg, name, d):
        g = self.cedit_g
        grp = self.cgroups[g]
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
        elif name == "Tune":
            p["tune"] = int(max(-24, min(24, p.get("tune", 0) + d)))
        elif name == "Level":
            p["level"] = round(max(0.05, min(1.6, p.get("level", 0.9) + 0.05 * d)), 2)
        elif name == "Choke":
            p["choke"] = not p.get("choke", True)
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
        if not return_early:
            self.text(c, "tune %+d" % p.get("tune", 0), self.f_med, mm.ACCENT2 if hot else mm.INK, (px + 14, gy + 150))
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
            steps.setdefault(e[0], []).append(e[1])
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
