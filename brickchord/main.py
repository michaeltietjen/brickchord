"""Brickchord: a pocket chord machine with an analog-VA voice for KNULLI handhelds.

One button = one chord in your key. Hold modifiers to bend it.
"""
import bisect
import json
import math
import os
import random
import sys
import threading
import time

import pygame

import host
import synth
from synth import SR

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(APP_DIR, "brickchord_config.json")
BASE_W, BASE_H = 640, 480

NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
SCALES = {"Major": [0, 2, 4, 5, 7, 9, 11], "Minor": [0, 2, 3, 5, 7, 8, 10],
          "Dorian": [0, 2, 3, 5, 7, 9, 10], "Mixolydian": [0, 2, 4, 5, 7, 9, 10]}
SCALE_NAMES = list(SCALES)
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII"]

LOGICAL = ["UP", "DOWN", "LEFT", "RIGHT", "A", "B", "X", "Y", "L1", "R1", "SELECT", "START"]
CHORD_BUTTONS = ["LEFT", "UP", "RIGHT", "DOWN", "X", "A", "B"]   # degrees I..vii
BUTTON_GLYPH = {"LEFT": "<", "UP": "^", "RIGHT": ">", "DOWN": "v", "X": "X", "A": "A", "B": "B"}
KEYMAP = {pygame.K_LEFT: "LEFT", pygame.K_RIGHT: "RIGHT", pygame.K_UP: "UP", pygame.K_DOWN: "DOWN",
          pygame.K_j: "X", pygame.K_l: "A", pygame.K_k: "B", pygame.K_u: "Y", pygame.K_q: "L1",
          pygame.K_e: "R1", pygame.K_TAB: "SELECT", pygame.K_RETURN: "START"}

PLAY_MODES = ["Chord", "Strum Folk", "Strum Pop", "Strum Skank", "Slop", "Harp Up", "Harp Down",
              "Arp 1/8 Up", "Arp 1/16 Up", "Arp 1/16 Up-Down", "Arp 1/8 Down", "Arp 1/16 Random"]
# strum patterns on an 8th-note grid: D down, U up, d soft down, . rest
STRUM_PATTERNS = {"Strum Folk": "D.DU.UDU", "Strum Pop": "D.D.UDUd", "Strum Skank": ".D.D.D.D"}
DELAY_TIMES = [("1/16", 0.25), ("1/8", 0.5), ("1/8 dotted", 0.75), ("1/4", 1.0), ("1/4 dotted", 1.5),
               ("1/8 triplet", 1 / 3.0), ("1/4 triplet", 2 / 3.0)]
DELAY_TYPES = ["Ping-Pong", "Straight", "Tape", "Dub", "Slapback", "Multi-Tap"]

# colours
BG = (18, 16, 22)
PANEL = (34, 30, 40)
INK = (236, 228, 214)
DIM = (130, 122, 140)
ACCENT = (255, 140, 66)
ACCENT2 = (110, 200, 190)
MOD_ON = (255, 200, 90)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ------------------------------------------------------------------ theory
MOD_KEYS = ("flip", "seventh", "sus", "ninth", "sus2", "dim", "aug", "maj7")

# left-stick sectors (0 = right, counter-clockwise in 45 degree steps)
STICK_SECTORS = {0: "ninth", 1: "maj7", 2: "seventh", 3: "sus2", 4: "sus", 5: "dim", 6: "flip", 7: "aug"}
STICK_LABEL = {"ninth": "9", "maj7": "maj7", "seventh": "7", "sus2": "sus2", "sus": "sus4",
               "dim": "dim", "flip": "flip", "aug": "aug"}


def build_chord(key, scale, degree, m):
    """m: dict with any of MOD_KEYS set True."""
    sc = SCALES[scale]

    def tone(i):
        return sc[(degree + i) % 7] + 12 * ((degree + i) // 7)

    root = tone(0)
    third = tone(2) - root
    fifth = tone(4) - root
    sev = tone(6) - root
    if m.get("flip"):
        third = 3 if third == 4 else 4
        if fifth == 6:
            fifth = 7
        sev = 10 if sev == 11 or third == 3 else sev
    if m.get("dim"):
        third, fifth, sev = 3, 6, 10
    if m.get("aug"):
        third, fifth = 4, 8
    if m.get("maj7"):
        sev = 11
    ivals = [0, third, fifth]
    sus = bool(m.get("sus"))
    sus2 = bool(m.get("sus2")) and not sus
    if sus:
        ivals[1] = 5
    elif sus2:
        ivals[1] = 2
    if m.get("seventh") or m.get("ninth") or m.get("maj7"):
        ivals.append(sev)
    if m.get("ninth"):
        ivals.append(14)
    pc_root = (key + root) % 12
    return pc_root, ivals, chord_name(pc_root, ivals, sus, sus2)


def chord_name(pc, iv, sus, sus2=False):
    s = set(i % 12 for i in iv)
    third = 3 if 3 in s and not sus else (4 if 4 in s else None)
    fifth = 6 if 6 in s else (8 if 8 in s else 7)
    has7 = 10 in s or 11 in s
    maj7 = 11 in s
    has9 = 2 in s and not sus2
    n = NOTE_NAMES[pc]
    if sus2:
        return n + ("maj7sus2" if maj7 else ("7sus2" if has7 else "sus2"))
    if sus:
        q = ("7sus4" if has7 else "sus4")
        if has9:
            q = "9sus4"
        return n + q
    if third == 4 and fifth == 8:
        return n + ("augMaj7" if maj7 else ("aug7" if has7 else "aug"))
    if third == 3 and fifth == 6:
        if has7:
            return n + ("m7b5" if not maj7 else "mMaj7b5")
        return n + "dim"
    base = "m" if third == 3 else ""
    if has9:
        return n + base + ("maj9" if maj7 else "9") if base == "" else n + ("m9" if not maj7 else "mMaj9")
    if has7:
        if base == "m":
            return n + ("mMaj7" if maj7 else "m7")
        return n + ("maj7" if maj7 else "7")
    return n + base


def roman_for(degree, ivals):
    r = ROMAN[degree]
    s = set(i % 12 for i in ivals)
    if 3 in s and 5 not in s:
        r = r.lower()
    if 6 in s and 7 not in s:
        r += "°"
    return r


def voice(pc_root, ivals, prev, octave):
    bass = 36 + pc_root
    if bass < 40:
        bass += 12
    center = (sum(prev) / len(prev)) if prev else 64
    upper = []
    for iv in ivals:
        pc = (pc_root + iv) % 12
        cands = [pc + 12 * o for o in range(3, 8)]
        best = min(cands, key=lambda m: (abs(m - center), m))
        best = clamp(best, 55, 79)
        if best not in upper:
            upper.append(best)
    upper.sort()
    return [bass + 12 * octave] + [m + 12 * octave for m in upper], upper


# ------------------------------------------------------------------ input
class Input:
    def __init__(self, mapping):
        self.map = dict(mapping)          # sig -> logical
        self.hat = {}
        self.axis = {}
        self.held = set()
        self.joys = []
        self.scan()

    def scan(self):
        pygame.joystick.init()
        self.joys = []
        for i in range(pygame.joystick.get_count()):
            j = pygame.joystick.Joystick(i)
            j.init()
            self.joys.append(j)

    def raw(self, ev):
        """Translate a pygame event into [(sig, down)]"""
        out = []
        if ev.type == pygame.JOYBUTTONDOWN:
            out.append(("b%d" % ev.button, True))
        elif ev.type == pygame.JOYBUTTONUP:
            out.append(("b%d" % ev.button, False))
        elif ev.type == pygame.JOYHATMOTION:
            old = self.hat.get(ev.hat, (0, 0))
            new = ev.value
            for axis_i, nm in ((0, "x"), (1, "y")):
                for sgn in (-1, 1):
                    sig = "h%d%s%s" % (ev.hat, "+" if sgn > 0 else "-", nm)
                    was, now = old[axis_i] == sgn, new[axis_i] == sgn
                    if was != now:
                        out.append((sig, now))
            self.hat[ev.hat] = new
        elif ev.type == pygame.JOYAXISMOTION:
            st = self.axis.get(ev.axis, 0)
            v = ev.value
            ns = 1 if v > 0.6 else (-1 if v < -0.6 else (st if abs(v) > 0.3 else 0))
            if ns != st:
                if st:
                    out.append(("a%d%s" % (ev.axis, "+" if st > 0 else "-"), False))
                if ns:
                    out.append(("a%d%s" % (ev.axis, "+" if ns > 0 else "-"), True))
                self.axis[ev.axis] = ns
        elif ev.type in (pygame.KEYDOWN, pygame.KEYUP) and ev.key in KEYMAP:
            out.append(("k:" + KEYMAP[ev.key], ev.type == pygame.KEYDOWN))
        return out

    def logical(self, ev):
        res = []
        for sig, down in self.raw(ev):
            name = KEYMAP_SIG.get(sig) or self.map.get(sig)
            if not name:
                continue
            if down and name not in self.held:
                self.held.add(name)
                res.append((name, True))
            elif not down and name in self.held:
                self.held.discard(name)
                res.append((name, False))
        return res


KEYMAP_SIG = {"k:" + v: v for v in KEYMAP.values()}




# ------------------------------------------------------------------ voices


# ------------------------------------------------------------------ app
class App:
    def __init__(self, eng, cfg):
        self.cfg = cfg
        s = self.cfg["settings"]
        self.key = s.get("key", 0)
        self.scale = s.get("scale", "Major") if s.get("scale") in SCALES else "Major"
        self.patch = clamp(s.get("patch", 0), 0, len(synth.PATCHES) - 1)
        self.tone = s.get("tone", 0.0)
        self.res = s.get("res", 0.0)
        self.octave = s.get("octave", 0)
        self.bpm = s.get("bpm", 96)
        self.beat = clamp(s.get("beat", 1), 0, len(synth.BEATS) - 1)
        self.play = clamp(s.get("play", 0), 0, len(PLAY_MODES) - 1)
        self.latch = s.get("latch", False)
        self.spread = s.get("spread", 0)
        self.volume = s.get("volume", 0.8)
        self.base_rev = s.get("reverb", 0.25)
        self.base_dly = s.get("delay", 0.0)
        self.dly_time = clamp(s.get("delay_time", 2), 0, len(DELAY_TIMES) - 1)
        self.rev_type = s.get("reverb_type", "Hall") if s.get("reverb_type") in synth.REVERBS else "Hall"
        self.dly_type = s.get("delay_type", "Ping-Pong") if s.get("delay_type") in DELAY_TYPES else "Ping-Pong"
        self.quantize = s.get("quantize", True)
        self.block = s.get("latency", 1024) if s.get("latency") in (512, 1024, 2048) else 1024

        # no pygame.init(): it would grab the audio device the engine needs
        pygame.display.init()
        pygame.font.init()
        pygame.joystick.init()
        if os.environ.get("BRICKCHORD_WINDOW"):
            self.screen = pygame.display.set_mode((BASE_W, BASE_H))
        else:
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
        pygame.display.set_caption("Brickchord")
        self.canvas = pygame.Surface((BASE_W, BASE_H))
        self.f_huge = pygame.font.Font(None, 132)
        self.f_big = pygame.font.Font(None, 54)
        self.f_med = pygame.font.Font(None, 30)
        self.f_small = pygame.font.Font(None, 22)

        self.inp = Input(self.cfg.get("buttons", {}))
        self.edits = self.cfg.get("patch_edits", {})
        self._pkey = None
        self.editor = False
        self.ed_i = 0
        self.ed_dirty = False
        self.audition_until = 0
        self.cur = None
        self.cur_btn = None
        self.prev_upper = []
        self.sounding = []
        self.drums_on = False
        self.menu = False
        self.menu_i = 0
        self.msg = ""
        self.msg_t = 0
        self.running = True
        self.stick_mod = None
        self.stick_xy = (0.0, 0.0)
        self.ry = 0.0
        self.rx = 0.0
        self.fx_hold = None             # (rx, ry) latched by clicking the right stick
        self.flt = (0.0, 0.0)
        self.rev = self.base_rev
        self.dly = self.base_dly

        self.eng = eng
        self.eng.post("drums", False, synth.BEATS[self.beat][1])
        self.push_params()
        self.push_fx()
        self.push_types()
        self.queue_precache()

        if self.inp.joys and not self.cfg.get("buttons"):
            self.learn()
        if self.inp.joys and self.inp.joys[0].get_numaxes() >= 2:
            if "sticks" not in self.cfg:
                self.learn_sticks()
            elif not self.cfg.get("fx2_learned"):
                self.learn_sticks(only=("rx", "R3"))       # new in this version

    # ---------------- engine glue
    def push_params(self):
        p = self.cur_patch()
        self.eng.post("params", self.bpm, p["r"], p["s"] > 0.001, self.spread, self.mode(), self.quantize)

    def push_types(self):
        if self.rev_type != "Hall":
            self.eng.post("reverb", synth.make_reverb(self.rev_type))
        self.eng.post("delay_type", self.dly_type)

    def push_fx(self):
        self.eng.post("fx", self.rev, self.dly, DELAY_TIMES[self.dly_time][1], self.volume)

    # ---------------- sounds are rendered in the renderer process
    def cur_patch(self):
        """Current sound with Sound Editor edits and the quick Filter/Resonance macros applied."""
        p = synth.edited_patch(synth.PATCHES[self.patch], self.edits.get(str(self.patch)))
        p["cutoff"] = p["cutoff"] * (2 ** self.tone)
        p["res"] = max(0.5, p["res"] + self.res)
        return p

    def ckey(self, midi):
        if self._pkey is None:
            self._pkey = json.dumps(self.cur_patch(), sort_keys=True)
        return (midi, self._pkey)

    def patch_changed(self):
        self._pkey = None
        self.queue_precache()
        self.push_params()

    def queue_precache(self):
        o = 12 * self.octave
        notes = set()
        # every chord any button / stick modifier can make, including its harp run
        mods = [{}] + [{k: True} for k in MOD_KEYS] + [{"seventh": True, k: True} for k in MOD_KEYS]
        for deg in range(7):
            for m in mods:
                pc, iv, _ = build_chord(self.key, self.scale, deg, m)
                ns, up = voice(pc, iv, [], self.octave)
                notes.update(ns)
                notes.add(ns[1] + 12)
        # voice leading can put a chord tone anywhere in the upper range
        notes.update(m + o for m in range(55, 92))
        sc = set((self.key + i) % 12 for i in SCALES[self.scale])
        notes.update(m + o for m in range(52, 107) if m % 12 in sc)
        order = sorted(notes, key=lambda m: abs(m - 66 - o))
        self.eng.request("reset", [])
        self.eng.request("lo", [self.ckey(m) for m in order])
        if hasattr(self.eng, "preload") and hasattr(self, "canvas"):
            self.eng.preload(self.loading)

    def loading(self, done, total):
        c = self.canvas
        c.fill(BG)
        self.text(c, "BRICKCHORD", self.f_med, ACCENT, (BASE_W // 2, 170), center=True)
        self.text(c, "preparing %s" % synth.PATCHES[self.patch]["name"], self.f_small, DIM, (BASE_W // 2, 215), center=True)
        w = 360
        pygame.draw.rect(c, PANEL, ((BASE_W - w) // 2, 250, w, 14), border_radius=7)
        pygame.draw.rect(c, ACCENT, ((BASE_W - w) // 2, 250, int(w * done / max(1, total)), 14), border_radius=7)
        self.text(c, "%d / %d" % (done, total), self.f_small, DIM, (BASE_W // 2, 290), center=True)
        self.present()
        pygame.event.pump()

    # ---------------- chords
    def mods(self):
        h = self.inp.held
        l1, r1 = "L1" in h, "R1" in h
        m = dict(flip="Y" in h, seventh=l1 and not r1, sus=r1 and not l1, ninth=l1 and r1)
        if self.stick_mod:
            m[self.stick_mod] = True
        return m

    def mode(self):
        return PLAY_MODES[self.play]

    def play_chord(self, btn, revoice=False):
        deg = CHORD_BUTTONS.index(btn)
        pc, iv, name = build_chord(self.key, self.scale, deg, self.mods())
        notes, upper = voice(pc, iv, self.prev_upper, self.octave)
        self.prev_upper = upper
        revoice = revoice and self.cur_btn == btn
        self.cur = (deg, pc, iv, name)
        self.cur_btn = btn
        need = set(notes) | {notes[1] + 12}
        if self.mode().startswith("Harp"):
            pcs = set(m % 12 for m in notes)
            lo = (notes[1] // 12) * 12 - 2
            need |= {m for m in range(lo, lo + 36) if m % 12 in pcs}
        self.sounding = notes
        self.eng.chord(notes, {m: self.ckey(m) for m in need}, revoice)

    def stop_chord(self):
        self.eng.post("clear")
        self.sounding = []

    def toggle_drums(self):
        if self.beat == 0:
            self.beat = 1
        self.drums_on = not self.drums_on
        self.eng.post("drums", self.drums_on, synth.BEATS[self.beat][1])

    # ---------------- config
    def load_cfg(self):
        try:
            with open(CFG_PATH) as f:
                c = json.load(f)
                c.setdefault("settings", {})
                return c
        except Exception:
            return {"settings": {}}

    def save_cfg(self):
        self.cfg["settings"] = dict(key=self.key, scale=self.scale, patch=self.patch, tone=self.tone, res=self.res,
                                    octave=self.octave, bpm=self.bpm, beat=self.beat, play=self.play,
                                    latch=self.latch, spread=self.spread, volume=self.volume,
                                    reverb=self.base_rev, delay=self.base_dly, delay_time=self.dly_time,
                                    reverb_type=self.rev_type, delay_type=self.dly_type,
                                    latency=self.block, quantize=self.quantize)
        self.cfg["patch_edits"] = self.edits
        try:
            with open(CFG_PATH, "w") as f:
                json.dump(self.cfg, f, indent=1)
        except Exception as e:
            print("config save failed", e)

    # ---------------- button learning
    def learn(self):
        mapping = {}
        order = ["UP", "DOWN", "LEFT", "RIGHT", "A", "B", "X", "Y", "L1", "R1", "SELECT", "START"]
        tmp = Input({})
        i = 0
        clock = pygame.time.Clock()
        while i < len(order):
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    sys.exit(0)
                if ev.type == pygame.JOYDEVICEADDED:
                    tmp.scan()
                for sig, down in tmp.raw(ev):
                    if down and not sig.startswith("k:") and sig not in mapping:
                        mapping[sig] = order[i]
                        i += 1
                        self.eng.post("click")
                        break
                    if down and sig.startswith("k:"):
                        mapping = {}
                        i = len(order)
                        break
                if i >= len(order):
                    break
            c = self.canvas
            c.fill(BG)
            self.text(c, "BUTTON SETUP", self.f_med, ACCENT, (BASE_W // 2, 70), center=True)
            self.text(c, "Press", self.f_med, DIM, (BASE_W // 2, 170), center=True)
            if i < len(order):
                self.text(c, order[i], self.f_huge, INK, (BASE_W // 2, 250), center=True)
            self.text(c, "%d / %d" % (min(i + 1, len(order)), len(order)), self.f_small, DIM, (BASE_W // 2, 340), center=True)
            self.text(c, "This happens once. Relearn any time from the menu.", self.f_small, DIM, (BASE_W // 2, 420), center=True)
            self.present()
            clock.tick(60)
        if mapping:
            self.cfg["buttons"] = mapping
            self.inp.map = mapping
            self.save_cfg()

    def learn_sticks(self, only=None):
        if not self.inp.joys:
            return
        j = self.inp.joys[0]
        steps = [("lx", "Push the LEFT stick", "RIGHT"), ("ly", "Push the LEFT stick", "UP"),
                 ("ry", "Push the RIGHT stick", "UP"), ("rx", "Push the RIGHT stick", "RIGHT"),
                 ("R3", "Click the RIGHT stick", "DOWN")]
        if only:
            steps = [st for st in steps if st[0] in only]
        result = dict(self.cfg.get("sticks") or {}) if only else {}
        clock = pygame.time.Clock()
        start_btn = [s for s, n in self.inp.map.items() if n == "START"]
        i = 0
        rest = [j.get_axis(a) for a in range(j.get_numaxes())]
        armed = True
        used = set(v[0] for k, v in result.items() if k not in [st[0] for st in steps])
        while i < len(steps):
            skip = False
            key = steps[i][0]
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    sys.exit(0)
                for sig, down in self.inp.raw(ev):
                    if down and (sig in start_btn or sig == "k:START"):
                        skip = True
                    elif down and key == "R3" and sig.startswith("b") and sig not in self.inp.map:
                        mapping = {k: v for k, v in self.inp.map.items() if v != "R3"}
                        mapping[sig] = "R3"
                        self.inp.map = mapping
                        self.cfg["buttons"] = mapping
                        self.eng.post("click")
                        skip = True
            if skip:
                i += 1
                armed = True
                continue
            if key != "R3":
                best, bv = None, 0.0
                for a in range(j.get_numaxes()):
                    if a in used:
                        continue
                    d = j.get_axis(a) - rest[a]
                    if abs(d) > abs(bv):
                        best, bv = a, d
                if armed and best is not None and abs(bv) > 0.7:
                    result[key] = [best, 1 if bv > 0 else -1]
                    used.add(best)
                    self.eng.post("click")
                    i += 1
                    armed = False
                if not armed and all(abs(j.get_axis(a) - rest[a]) < 0.3 for a in range(j.get_numaxes())):
                    armed = True
            c = self.canvas
            c.fill(BG)
            self.text(c, "STICK SETUP", self.f_med, ACCENT, (BASE_W // 2, 70), center=True)
            if i < len(steps):
                self.text(c, steps[i][1], self.f_med, DIM, (BASE_W // 2, 170), center=True)
                self.text(c, steps[i][2], self.f_huge, INK, (BASE_W // 2, 250), center=True)
                if steps[i][0] != "R3":
                    self.text(c, "then let it go back to center", self.f_small, DIM, (BASE_W // 2, 320), center=True)
            if only:
                self.text(c, "New: right stick LEFT/RIGHT = filter / resonance, click = hold effects",
                          self.f_small, ACCENT2, (BASE_W // 2, 385), center=True)
            self.text(c, "Press START to skip a step (or if you have no sticks)", self.f_small, DIM,
                      (BASE_W // 2, 420), center=True)
            self.present()
            clock.tick(60)
        self.cfg["sticks"] = result
        self.cfg["fx2_learned"] = True
        self.save_cfg()

    # ---------------- sound cache (dry first, reverb layer in the background)

    # ---------------- analog sticks
    def axis_val(self, spec):
        if not spec or not self.inp.joys:
            return 0.0
        ax, sign = spec
        j = self.inp.joys[0]
        if ax >= j.get_numaxes():
            return 0.0
        return j.get_axis(ax) * sign

    def update_sticks(self):
        st = self.cfg.get("sticks") or {}
        if st.get("lx") or st.get("ly"):
            x, y = self.axis_val(st.get("lx")), self.axis_val(st.get("ly"))
            mag = math.hypot(x, y)
            new = self.stick_mod
            if mag > 0.55:
                new = STICK_SECTORS[int(round(math.degrees(math.atan2(y, x)) / 45.0)) % 8]
            elif mag < 0.35:
                new = None
            self.stick_xy = (x, y)
            if new != self.stick_mod:
                self.stick_mod = new
                if self.cur_btn and (self.cur_btn in self.inp.held or self.latch):
                    self.play_chord(self.cur_btn, revoice=True)
        ry = self.axis_val(st.get("ry")) if st.get("ry") else 0.0
        ry = 0.0 if abs(ry) < 0.12 else ry
        rx = self.axis_val(st.get("rx")) if st.get("rx") else 0.0
        rx = 0.0 if abs(rx) < 0.12 else rx
        if self.fx_hold:
            rx, ry = self.fx_hold
        self.rx, self.ry = rx, ry
        flt = (round(max(0.0, -rx), 2), round(max(0.0, rx), 2))     # left = filter, right = resonance
        if flt != self.flt:
            self.flt = flt
            self.eng.post("filter", *flt)
        rev = self.base_rev + max(0.0, ry) * (1 - self.base_rev)
        dly = self.base_dly + max(0.0, -ry) * (1 - self.base_dly)
        if abs(rev - self.rev) > 0.01 or abs(dly - self.dly) > 0.01:
            self.rev, self.dly = rev, dly
            self.push_fx()

    # ---------------- drums

    # ---------------- menu
    def menu_items(self):
        return [
            ("Key", NOTE_NAMES[self.key]),
            ("Scale", self.scale),
            ("Sound", synth.PATCHES[self.patch]["name"] + (" *" if self.edits.get(str(self.patch)) else "")),
            ("Edit Sound", ">"),
            ("Filter", "%+.1f oct" % self.tone),
            ("Resonance", "%+.1f" % self.res),
            ("Octave", "%+d" % self.octave),
            ("Play", self.mode()),
            ("Reverb", "%d%%" % round(self.base_rev * 100)),
            ("Reverb Type", self.rev_type),
            ("Delay", "%d%%" % round(self.base_dly * 100)),
            ("Delay Type", self.dly_type),
            ("Delay Time", DELAY_TIMES[self.dly_time][0] if self.dly_type != "Slapback" else "fixed"),
            ("Beat", synth.BEATS[self.beat][0]),
            ("Tempo", "%d BPM" % self.bpm),
            ("Spread", "%d ms" % self.spread),
            ("Latch", "On" if self.latch else "Off"),
            ("Quantize", "On" if self.quantize else "Off"),
            ("Volume", "%d%%" % round(self.volume * 100)),
            ("Latency", {512: "Low", 1024: "Normal", 2048: "Safe"}.get(self.block, str(self.block))),
            ("Relearn buttons", ""),
            ("Learn sticks", "on" if self.cfg.get("sticks") else "off"),
            ("Quit", ""),
        ]

    def menu_change(self, d):
        name = self.menu_items()[self.menu_i][0]
        recache = False
        if name == "Key":
            self.key = (self.key + d) % 12
            recache = True
        elif name == "Scale":
            self.scale = SCALE_NAMES[(SCALE_NAMES.index(self.scale) + d) % len(SCALE_NAMES)]
            recache = True
        elif name == "Sound":
            self.patch = (self.patch + d) % len(synth.PATCHES)
            recache = True
        elif name == "Filter":
            self.tone = clamp(round(self.tone + 0.5 * d, 1), -3, 3)
            recache = True
        elif name == "Resonance":
            self.res = clamp(round(self.res + 0.5 * d, 1), -1, 6)
            recache = True
        elif name == "Octave":
            self.octave = clamp(self.octave + d, -2, 2)
            recache = True
        elif name == "Play":
            self.play = (self.play + d) % len(PLAY_MODES)
            self.stop_chord()
            self.cur = None
            self.push_params()
        elif name == "Reverb":
            self.base_rev = clamp(round(self.base_rev + 0.05 * d, 2), 0, 1)
        elif name == "Delay":
            self.base_dly = clamp(round(self.base_dly + 0.05 * d, 2), 0, 1)
        elif name == "Delay Time":
            self.dly_time = (self.dly_time + d) % len(DELAY_TIMES)
        elif name == "Reverb Type":
            self.rev_type = synth.REVERBS[(synth.REVERBS.index(self.rev_type) + d) % len(synth.REVERBS)]
            self.eng.post("reverb", synth.make_reverb(self.rev_type))
        elif name == "Delay Type":
            self.dly_type = DELAY_TYPES[(DELAY_TYPES.index(self.dly_type) + d) % len(DELAY_TYPES)]
            self.eng.post("delay_type", self.dly_type)
        elif name == "Beat":
            self.beat = (self.beat + d) % len(synth.BEATS)
        elif name == "Tempo":
            self.bpm = clamp(self.bpm + 2 * d, 50, 200)
        elif name == "Spread":
            self.spread = clamp(self.spread + 10 * d, 0, 120)
        elif name == "Latch":
            self.latch = not self.latch
            if not self.latch and self.cur_btn not in self.inp.held:
                self.stop_chord()
                self.cur = None
        elif name == "Volume":
            self.volume = clamp(round(self.volume + 0.05 * d, 2), 0.1, 1.0)
        elif name == "Quantize":
            self.quantize = not self.quantize
            self.push_params()
        elif name == "Latency":
            self.block = {512: 1024, 1024: 2048, 2048: 512}[self.block] if d > 0 else {512: 2048, 1024: 512, 2048: 1024}[self.block]
            self.flash("latency applies next launch")
        if name in ("Reverb", "Delay", "Delay Time", "Volume"):
            self.update_sticks()
            self.push_fx()
        if name in ("Tempo", "Spread", "Sound", "Beat"):
            self.push_params()
        if name == "Beat":
            self.eng.post("drums", self.drums_on, synth.BEATS[self.beat][1])
        if recache:
            self.patch_changed()
        if name in ("Sound", "Filter", "Resonance"):
            self.flash("rendering %s..." % synth.PATCHES[self.patch]["name"])

    def menu_activate(self):
        name = self.menu_items()[self.menu_i][0]
        if name == "Quit":
            self.running = False
        elif name == "Relearn buttons":
            self.stop_chord()
            self.cfg["buttons"] = {}
            self.learn()
            self.learn_sticks(only=("R3",))
            self.menu = False
        elif name == "Learn sticks":
            self.stop_chord()
            self.learn_sticks()
            self.menu = False
        elif name == "Edit Sound":
            self.stop_chord()
            self.editor = True
            self.ed_i = 0
            self.ed_dirty = False
        else:
            self.menu_change(1)

    # ---------------- sound editor
    def editor_items(self):
        p = self.cur_patch()
        e = self.edits.get(str(self.patch), {})
        rows = []
        for key, label, lo, hi, step in synth.EDIT_PARAMS:
            if key == "wave":
                val = synth.param_value(p, "wave")
            elif key == "detune":
                val = "%.2fx" % e.get("detune", 1.0)
            elif key == "sub":
                val = "%d%%" % round(synth.param_value(p, "sub") * 100)
            elif key == "cutoff":
                val = "%d Hz" % round(synth.edited_patch(synth.PATCHES[self.patch], e)["cutoff"])
            elif key in ("fs", "s", "pwm"):
                val = "%d%%" % round(p[key] * 100)
            elif key in ("res", "fenv"):
                val = "%.2f" % synth.edited_patch(synth.PATCHES[self.patch], e)[key]
            else:
                val = ("%d ms" % round(p[key] * 1000)) if p[key] < 1 else ("%.2f s" % p[key])
            rows.append((key, label, val, key in e))
        rows.append(("_audition", "Audition (or press START)", "", False))
        rows.append(("_reset", "Reset sound", "", False))
        rows.append(("_done", "Done", "", False))
        return rows

    def editor_change(self, d):
        key = self.editor_items()[self.ed_i][0]
        if key.startswith("_"):
            return
        base = synth.PATCHES[self.patch]
        e = self.edits.setdefault(str(self.patch), {})
        spec = {k: (lo, hi, st) for k, _, lo, hi, st in synth.EDIT_PARAMS}[key]
        lo, hi, st = spec
        if key == "wave":
            cur = e.get("wave", synth.param_value(base, "wave"))
            e["wave"] = synth.WAVES[(synth.WAVES.index(cur) + d) % len(synth.WAVES)]
        elif key == "detune":
            e["detune"] = clamp(round(e.get("detune", 1.0) + st * d, 2), lo, hi)
        elif key == "sub":
            e["sub"] = clamp(round(e.get("sub", synth.param_value(base, "sub")) + st * d, 2), lo, hi)
        else:
            cur = e.get(key, base[key])
            if st is None:                      # times and cutoff move on a log scale
                cur = cur * (1.25 if d > 0 else 0.8)
            else:
                cur = cur + st * d
            e[key] = round(clamp(cur, lo, hi), 4)
        self.ed_dirty = True
        self._pkey = None

    def editor_apply(self):
        if self.ed_dirty:
            self.patch_changed()
            self.save_cfg()
            self.ed_dirty = False

    def audition(self):
        self.editor_apply()
        pc, iv, _ = build_chord(self.key, self.scale, 0, {"seventh": True})
        notes, _ = voice(pc, iv, [], self.octave)
        self.eng.chord(notes, {m: self.ckey(m) for m in set(notes) | {notes[1] + 12}}, False)
        self.audition_until = time.perf_counter() + 1.6

    def editor_input(self, name):
        rows = self.editor_items()
        if name == "UP":
            self.ed_i = (self.ed_i - 1) % len(rows)
        elif name == "DOWN":
            self.ed_i = (self.ed_i + 1) % len(rows)
        elif name in ("LEFT", "RIGHT"):
            self.editor_change(-1 if name == "LEFT" else 1)
        elif name == "START":
            self.audition()
        elif name == "A":
            key = rows[self.ed_i][0]
            if key == "_audition":
                self.audition()
            elif key == "_reset":
                self.edits.pop(str(self.patch), None)
                self.ed_dirty = True
                self._pkey = None
                self.editor_apply()
                self.flash("sound reset")
            elif key == "_done":
                self.editor_apply()
                self.editor = False
            else:
                self.editor_change(1)
        elif name in ("B", "SELECT"):
            self.editor_apply()
            self.editor = False

    def draw_editor(self, c):
        ov = pygame.Surface((BASE_W, BASE_H), pygame.SRCALPHA)
        ov.fill((10, 8, 14, 235))
        c.blit(ov, (0, 0))
        self.text(c, "EDIT  " + synth.PATCHES[self.patch]["name"].upper(), self.f_med, ACCENT, (BASE_W // 2, 28), center=True)
        rows = self.editor_items()
        top = max(0, min(self.ed_i - 6, len(rows) - 13))
        for r, (key, label, val, edited) in enumerate(rows[top:top + 13]):
            i = top + r
            y = 56 + r * 30
            sel = i == self.ed_i
            if sel:
                pygame.draw.rect(c, PANEL, (70, y - 3, BASE_W - 140, 28), border_radius=6)
            self.text(c, label, self.f_med, ACCENT if sel else (MOD_ON if edited else INK), (90, y))
            if val:
                self.text(c, ("< %s >" % val) if sel else val, self.f_med, INK if sel else DIM, (BASE_W - 90, y), right=True)
        hint = "LEFT/RIGHT tweak   START audition   B done" + ("   (changes apply on exit)" if self.ed_dirty else "")
        self.text(c, hint, self.f_small, DIM, (BASE_W // 2, 462), center=True)

    def flash(self, m):
        self.msg, self.msg_t = m, time.perf_counter()

    # ---------------- events
    def handle(self, name, down):
        held = self.inp.held
        if "SELECT" in held and "START" in held:
            self.running = False
            return
        if self.editor:
            if down:
                self.editor_input(name)
            return
        if self.menu:
            if not down:
                return
            n = len(self.menu_items())
            if name == "UP":
                self.menu_i = (self.menu_i - 1) % n
            elif name == "DOWN":
                self.menu_i = (self.menu_i + 1) % n
            elif name == "LEFT":
                self.menu_change(-1)
            elif name == "RIGHT":
                self.menu_change(1)
            elif name == "A":
                self.menu_activate()
            elif name in ("B", "SELECT"):
                self.menu = False
                self.save_cfg()
            elif name == "START":
                self.toggle_drums()
            return
        if name == "R3":
            if down:
                if self.fx_hold:
                    self.fx_hold = None
                    self.flash("FX released")
                elif self.rx or self.ry:
                    self.fx_hold = (self.rx, self.ry)
                    self.flash("FX held  (click R stick to release)")
            return
        if name in CHORD_BUTTONS:
            if down:
                self.play_chord(name)
            elif name == self.cur_btn and not self.latch:
                self.stop_chord()
                self.cur = None
                self.cur_btn = None
        elif name in ("Y", "L1", "R1") and self.cur_btn and (self.cur_btn in held or self.latch):
            self.play_chord(self.cur_btn, revoice=True)
        elif name == "SELECT" and down:
            self.menu = True
        elif name == "START" and down:
            self.toggle_drums()

    # ---------------- drawing
    def text(self, surf, s, font, col, pos, center=False, right=False):
        img = font.render(s, True, col)
        r = img.get_rect()
        if center:
            r.center = pos
        elif right:
            r.topright = pos
        else:
            r.topleft = pos
        surf.blit(img, r)
        return r

    def present(self):
        sw, sh = self.screen.get_size()
        scale = min(sw / BASE_W, sh / BASE_H)
        w, h = int(BASE_W * scale), int(BASE_H * scale)
        self.screen.fill((0, 0, 0))
        img = self.canvas if (w, h) == (BASE_W, BASE_H) else pygame.transform.scale(self.canvas, (w, h))
        self.screen.blit(img, ((sw - w) // 2, (sh - h) // 2))
        pygame.display.flip()

    def draw(self):
        c = self.canvas
        c.fill(BG)
        pygame.draw.rect(c, PANEL, (0, 0, BASE_W, 38))
        self.text(c, "BRICKCHORD", self.f_small, ACCENT, (12, 12))
        info = "%s %s  |  %s  |  %s  |  %d BPM" % (NOTE_NAMES[self.key], self.scale,
                                                   synth.PATCHES[self.patch]["name"], self.mode(), self.bpm)
        self.text(c, info, self.f_small, INK, (BASE_W - 12, 12), right=True)

        if self.cur:
            deg, pc, iv, name = self.cur
            font = self.f_huge if self.f_huge.size(name)[0] < 330 else self.f_big
            self.text(c, name, font, INK, (BASE_W // 2 - 10, 128), center=True)
            self.text(c, roman_for(deg, iv), self.f_big, ACCENT, (BASE_W // 2, 200), center=True)
        else:
            self.text(c, "-", self.f_huge, PANEL, (BASE_W // 2, 128), center=True)
            self.text(c, "press a chord", self.f_med, DIM, (BASE_W // 2, 200), center=True)

        m = self.mods()
        h = self.inp.held
        labels = [("Y  FLIP", "Y" in h), ("L1  7th", "L1" in h and "R1" not in h),
                  ("R1  SUS4", "R1" in h and "L1" not in h), ("L1+R1  9th", "L1" in h and "R1" in h)]
        x = 40
        for lab, on in labels:
            col = MOD_ON if on else DIM
            r = pygame.Rect(x, 236, 128, 26)
            pygame.draw.rect(c, PANEL, r, border_radius=6)
            if on:
                pygame.draw.rect(c, MOD_ON, r, 2, border_radius=6)
            self.text(c, lab, self.f_small, col, r.center, center=True)
            x += 142

        if (self.cfg.get("sticks") or {}).get("lx"):
            self.draw_stick(c)
        self.draw_fx(c)

        tw, gap = 82, 6
        x0 = (BASE_W - (7 * tw + 6 * gap)) // 2
        for i, btn in enumerate(CHORD_BUTTONS):
            pc, iv, name = build_chord(self.key, self.scale, i, m)
            r = pygame.Rect(x0 + i * (tw + gap), 280, tw, 96)
            active = self.cur and self.cur[0] == i
            pygame.draw.rect(c, ACCENT if active else PANEL, r, border_radius=10)
            col = BG if active else INK
            self.text(c, roman_for(i, iv), self.f_med, BG if active else ACCENT2, (r.centerx, r.y + 20), center=True)
            nm_font = self.f_med if len(name) < 6 else self.f_small
            self.text(c, name, nm_font, col, (r.centerx, r.y + 52), center=True)
            self.text(c, BUTTON_GLYPH[btn], self.f_small, BG if active else DIM, (r.centerx, r.y + 80), center=True)

        kx, ky, kw, kh = 20, 392, BASE_W - 40, 40
        lo, hi = 36, 96
        nwhite = sum(1 for n in range(lo, hi) if n % 12 in (0, 2, 4, 5, 7, 9, 11))
        ww = kw / nwhite
        wx = kx
        sounding = set(self.sounding)
        whites = {}
        for n in range(lo, hi):
            if n % 12 in (0, 2, 4, 5, 7, 9, 11):
                r = pygame.Rect(int(wx), ky, int(ww) - 1, kh)
                pygame.draw.rect(c, ACCENT if n in sounding else (200, 194, 184), r)
                whites[n] = wx
                wx += ww
        for n in range(lo, hi):
            if n % 12 in (1, 3, 6, 8, 10):
                px = whites[n - 1] + ww * 0.65
                r = pygame.Rect(int(px), ky, int(ww * 0.7), int(kh * 0.6))
                pygame.draw.rect(c, ACCENT if n in sounding else (30, 28, 34), r)

        status = []
        if self.drums_on:
            status.append("BEAT: " + synth.BEATS[self.beat][0])
        if self.latch:
            status.append("LATCH")
        left = self.eng.remaining
        if left:
            status.append("%d notes finish when quiet" % left)
        status.append("CPU %d%%" % round(self.eng.load * 100))
        self.text(c, "   ".join(status), self.f_small, ACCENT2, (20, 444))
        self.text(c, "SELECT menu   START beat   SEL+START quit", self.f_small, DIM, (BASE_W - 20, 444), right=True)
        if self.drums_on:
            for i in range(16):
                col = ACCENT if i == (self.eng.step16 - 1) % 16 else (PANEL if i % 4 else DIM)
                pygame.draw.rect(c, col, (20 + i * 12, 466, 9, 6))
        if self.msg and time.perf_counter() - self.msg_t < 1.5:
            self.text(c, self.msg, self.f_small, MOD_ON, (BASE_W // 2, 466), center=True)
        if self.menu and not self.editor:
            self.draw_menu(c)
        if self.editor:
            self.draw_editor(c)
        self.present()

    def draw_stick(self, c):
        cx, cy, rad = 556, 132, 62
        pygame.draw.circle(c, PANEL, (cx, cy), rad + 14)
        for sector, mod in STICK_SECTORS.items():
            ang = math.radians(sector * 45)
            lx, ly = cx + math.cos(ang) * rad, cy - math.sin(ang) * rad
            on = self.stick_mod == mod
            self.text(c, STICK_LABEL[mod], self.f_small, MOD_ON if on else DIM, (int(lx), int(ly)), center=True)
        sx, sy = self.stick_xy
        pygame.draw.circle(c, ACCENT if self.stick_mod else DIM, (int(cx + sx * 22), int(cy - sy * 22)), 7)
        self.text(c, "L STICK", self.f_small, DIM, (cx, cy + rad + 26), center=True)

    def draw_fx(self, c):
        mx, top, half = 72, 70, 46
        mid = top + half
        pygame.draw.rect(c, PANEL, (mx - 9, top, 18, half * 2), border_radius=7)
        rh = int(half * self.rev)
        dh = int(half * self.dly)
        if rh:
            pygame.draw.rect(c, ACCENT2, (mx - 9, mid - rh, 18, rh), border_radius=6)
        if dh:
            pygame.draw.rect(c, ACCENT, (mx - 9, mid, 18, dh), border_radius=6)
        pygame.draw.line(c, DIM, (mx - 13, mid), (mx + 13, mid), 1)
        self.text(c, "REVERB", self.f_small, ACCENT2 if self.ry > 0 else DIM, (mx, top - 14), center=True)
        self.text(c, "DELAY", self.f_small, ACCENT if self.ry < 0 else DIM, (mx, top + half * 2 + 14), center=True)
        # right stick X: filter (left) / resonance (right)
        by, bw = top + half * 2 + 38, 52
        pygame.draw.rect(c, PANEL, (mx - bw, by - 6, bw * 2, 12), border_radius=6)
        f, r = self.flt
        if f:
            pygame.draw.rect(c, ACCENT, (mx - int(bw * f), by - 6, int(bw * f), 12), border_radius=6)
        if r:
            pygame.draw.rect(c, ACCENT2, (mx, by - 6, int(bw * r), 12), border_radius=6)
        pygame.draw.line(c, DIM, (mx, by - 9), (mx, by + 9), 1)
        self.text(c, "FILTER", self.f_small, ACCENT if f else DIM, (mx - bw // 2, by + 18), center=True)
        self.text(c, "RES", self.f_small, ACCENT2 if r else DIM, (mx + bw // 2, by + 18), center=True)
        if self.fx_hold:
            self.text(c, "HOLD", self.f_small, MOD_ON, (mx + 40, top + half), center=True)

    def draw_menu(self, c):
        ov = pygame.Surface((BASE_W, BASE_H), pygame.SRCALPHA)
        ov.fill((10, 8, 14, 225))
        c.blit(ov, (0, 0))
        self.text(c, "SETTINGS", self.f_med, ACCENT, (BASE_W // 2, 30), center=True)
        items = self.menu_items()
        top = max(0, min(self.menu_i - 6, len(items) - 13))
        for row, (name, val) in enumerate(items[top:top + 13]):
            i = top + row
            y = 58 + row * 30
            sel = i == self.menu_i
            if sel:
                pygame.draw.rect(c, PANEL, (80, y - 3, BASE_W - 160, 28), border_radius=6)
            self.text(c, name, self.f_med, ACCENT if sel else INK, (100, y))
            if val:
                self.text(c, ("< %s >" % val) if sel else val, self.f_med, INK if sel else DIM, (BASE_W - 100, y), right=True)
        self.text(c, "UP/DOWN pick   LEFT/RIGHT change   A select   B close", self.f_small, DIM, (BASE_W // 2, 462), center=True)

    # ---------------- main loop

    # ---------------- main loop
    def heartbeat(self):
        """One status line every 20 s so a dropout can be traced in brickchord.log."""
        e = getattr(self.eng, "eng", None)
        print("status: underruns %d load %.2f voices %d misses %d cached %d audio_t %.1fs sound %s mode %s" % (
            self.eng.underruns, self.eng.load, len(e.voices) if e else -1, getattr(self.eng, "misses", 0),
            len(getattr(self.eng, "cache", ())), (e.t / e.sr) if e else -1, synth.PATCHES[self.patch]["name"],
            self.mode()), flush=True)

    def run(self):
        clock = pygame.time.Clock()
        last_draw = 0
        last_hb = last_poll = time.perf_counter()
        while self.running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self.running = False
                elif ev.type in (pygame.JOYDEVICEADDED, pygame.JOYDEVICEREMOVED):
                    self.inp.scan()
                elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                    self.running = False
                for name, down in self.inp.logical(ev):
                    self.handle(name, down)
            if not self.menu:
                self.update_sticks()
            if self.audition_until and time.perf_counter() > self.audition_until:
                self.audition_until = 0
                self.stop_chord()
            now = time.perf_counter()
            if now - last_poll > 0.3 and hasattr(self.eng, "poll"):
                last_poll = now
                self.eng.poll()
            if now - last_hb > 20:
                last_hb = now
                self.heartbeat()
            if now - last_draw > 1 / 30.0:      # UI at 30 fps; audio never waits on it
                self.draw()
                last_draw = now
            clock.tick(120)
        self.save_cfg()
        self.eng.stop()
        pygame.quit()


def load_cfg():
    try:
        with open(CFG_PATH) as f:
            c = json.load(f)
    except Exception:
        c = {}
    c.setdefault("settings", {})
    if c.get("engine_v") != 3:          # new engine: reset latency to the safer default once
        c["settings"]["latency"] = 1024
        c["engine_v"] = 3
    return c


def main():
    cfg = load_cfg()
    s = cfg["settings"]
    block = s.get("latency", 1024) if s.get("latency") in (512, 1024, 2048) else 1024
    eng = host.start(SR, block, cfg.get("engine_mode", "local"))
    print("audio host:", eng.kind, "block", block, flush=True)
    try:
        App(eng, cfg).run()
    finally:
        eng.stop()


if __name__ == "__main__":
    main()
