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

import edition
import host
import modes
import synth
from synth import SR

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(APP_DIR, "brickchord_config.json")
BASE_W, BASE_H = 640, 480

# Screen layouts. 4:3 (TrimUI Brick) and square (R36Max and other 720x720
# handhelds: the extra height goes to a bigger brick well, taller keys and
# keyboard). set_layout() picks one from the real screen before the UI starts.
LAYOUTS = {
    "4:3": dict(H=480, name_y=128, roman_y=200, mark_y=122, pills_y=236, tiles_y=280, tile_h=96,
                kb_y=392, kb_h=40, status_y=444, steps_y=472, msg_y=466, stick_cy=132, fx_top=70,
                fx_half=46, well_rows=15, list_rows=13, hint_y=462, dy=0),
    "square": dict(H=640, name_y=150, roman_y=262, mark_y=150, pills_y=318, tiles_y=362, tile_h=120,
                   kb_y=500, kb_h=56, status_y=574, steps_y=632, msg_y=604, stick_cy=165, fx_top=92,
                   fx_half=56, well_rows=22, list_rows=18, hint_y=620, dy=80),
}
L = LAYOUTS["4:3"]


def set_layout(name):
    global L, BASE_H
    L = LAYOUTS[name]
    BASE_H = L["H"]

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
              "Arp 1/8 Up", "Arp 1/16 Up", "Arp 1/16 Up-Down", "Arp 1/8 Down", "Arp 1/16 Random",
              "Repeat 1/4", "Repeat 1/8", "Repeat 1/16"]
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
class App(modes.ModesMixin):
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
        self.countin = s.get("countin", 1) if s.get("countin", 1) in (0, 1, 2) else 1
        self.bass = s.get("bass", 0) if 0 <= s.get("bass", 0) < len(synth.BASS_MODES) else 0
        self.bass_lvl = s.get("bass_lvl", 1.0)
        self.arp_oct = s.get("arp_oct", 2)
        self.bass_ready = set()
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
        pygame.display.set_caption(edition.NAME)
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
        # animation state (everything on screen eases, pops or decays; see "animation")
        self.hit_t, self.hit_big = -9.0, True
        self.nudge = (-9.0, 0)
        self.anim = {}
        self.glow = {}
        self.trail = []
        self.step_t = (-1, 0.0)
        self.last_frame = time.perf_counter()
        self._ov = pygame.Surface((BASE_W, BASE_H))
        self._ov.fill((10, 8, 14))
        self.parts = []                 # flying bricks
        self._tc = {}                   # text render cache
        self._kb = None                 # keyboard drawn once, lit keys on top
        self.well_reset()
        self.grav_t = 0.0
        self.new_hit = False
        self.modes_init()
        self.flt = (0.0, 0.0)
        self.rev = self.base_rev
        self.dly = self.base_dly

        self.eng = eng
        self.eng.post("drums", False, synth.BEATS[self.beat][1])
        self.push_params()
        self.push_fx()
        self.push_types()
        self.push_bass()
        if not edition.LAB:
            self.eng.post("lp", "route", False)     # Brickchord: no tracks, live sound goes straight out
        self.push_rack()
        self.intro()
        self.queue_precache()

        if self.inp.joys and not self.cfg.get("buttons"):
            self.learn()
        if self.inp.joys and self.inp.joys[0].get_numaxes() >= 2:
            if "sticks" not in self.cfg:
                self.learn_sticks()
            elif not self.cfg.get("fx2_learned"):
                self.learn_sticks(only=("rx", "R3", "L3"))
            elif not self.cfg.get("l3_learned"):
                self.learn_sticks(only=("L3",))            # new: mode wheel

    # ---------------- engine glue
    def push_params(self):
        p = self.cur_patch()
        self.eng.post("params", self.bpm, p["r"], p["s"] > 0.001, self.spread, self.mode(), self.quantize)

    def push_types(self):
        if self.rev_type != "Hall":
            self.eng.post("reverb", synth.make_reverb(self.rev_type))
        self.eng.post("delay_type", self.dly_type)

    def push_bass(self):
        self.eng.post("bass", synth.BASS_MODES[self.bass], self.bass_lvl)
        self.eng.post("arp_oct", self.arp_oct)

    def bass_range(self):
        lo = max(28, 28 + 12 * self.octave)
        return range(lo, min(lo + 26, 80))

    def ensure_bass(self, midis, budget=None):
        """Render synth-bass notes the engine doesn't have yet (about 25 ms each on
        the Brick), optionally stopping after `budget` seconds."""
        t0 = time.perf_counter()
        bank = {}
        for m in midis:
            if m in self.bass_ready or not 20 <= m <= 90:
                continue
            bank[m] = synth.render_bass(m, SR)
            self.bass_ready.add(m)
            if budget is not None and time.perf_counter() - t0 > budget:
                break
        if bank:
            self.eng.post("bass", None, None, bank)

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

    # ---------------- logo
    ORANGE = (255, 90, 31)
    KEY = (233, 231, 226)

    @staticmethod
    def _ease_back(x):
        x = min(1.0, max(0.0, x))
        c = 1.9
        return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2

    @staticmethod
    def _mix(a, b, f):
        f = min(1.0, max(0.0, f))
        return tuple(int(a[j] + (b[j] - a[j]) * f) for j in range(3))

    def draw_mark(self, c, cx, cy, k, t=None):
        """The Brickchord logo: seven chord keys and one lit key (4 x 2 grid).
        With t (seconds since the intro started) the keys pop in like a strum,
        the chord gets struck, then a sequencer light walks the keys."""
        gap = max(3, k // 7)
        x0 = cx - (4 * k + 3 * gap) // 2
        y0 = cy - (2 * k + gap) // 2
        rad = max(2, k // 8)
        for i in range(8):
            col_i, row = i % 4, i // 4
            base = self.ORANGE if i == 6 else self.KEY
            ccx = x0 + col_i * (k + gap) + k // 2
            ccy = y0 + row * (k + gap) + k // 2
            scale, dip, colr = 1.0, 0, base
            if t is not None:
                # 1) pop in, column by column, top row first (a strum)
                scale = self._ease_back((t - 0.07 * (col_i * 2 + row)) / 0.30)
                # 2) the chord is struck: every key presses, staggered like a strum
                hit = t - (1.0 + 0.045 * col_i)
                if 0 <= hit < 0.22:
                    d = 1 - abs(hit / 0.11 - 1)
                    dip = int(round(d * k * 0.12))
                    colr = self._mix(base, (255, 170, 120) if i == 6 else (255, 214, 190), d * 0.8)
                # 3) idle: a step light walks the keys, the orange key breathes
                if t > 1.45:
                    step = int((t - 1.45) * 7) % 8
                    if i == step and i != 6:
                        frac = ((t - 1.45) * 7) % 1
                        dip = max(dip, int(round((1 - frac) * k * 0.10)))
                        colr = self._mix(base, (255, 196, 160), (1 - frac) * 0.9)
                    if i == 6:
                        b = 0.5 + 0.5 * math.sin((t - 1.45) * 3.0)
                        colr = self._mix(base, (255, 140, 80), b * 0.6)
            if scale <= 0.02:
                continue
            sz = max(2, int(k * scale))
            r = pygame.Rect(0, 0, sz, sz)
            r.center = (ccx, ccy + dip)
            if t is not None and dip:
                sh = r.copy(); sh.height = max(1, k // 12); sh.top = y0 + row * (k + gap) + k
                pygame.draw.rect(c, (8, 7, 10), sh)
            pygame.draw.rect(c, colr, r, border_radius=max(2, int(rad * scale)))
            # glow ring when the orange key is struck
            if t is not None and i == 6:
                g = t - (1.0 + 0.045 * col_i)
                if 0 <= g < 0.6:
                    a = int(150 * (1 - g / 0.6))
                    grow = int(g / 0.6 * k * 0.7)
                    ring = pygame.Surface((k + 2 * grow + 4, k + 2 * grow + 4), pygame.SRCALPHA)
                    pygame.draw.rect(ring, (255, 90, 31, a), ring.get_rect(), width=3,
                                     border_radius=rad + grow // 2)
                    c.blit(ring, ring.get_rect(center=(ccx, ccy)))

    def draw_title(self, c, y, t=None):
        word = "brickchord"
        n = len(word) if t is None else max(0, min(len(word), int((t - 0.55) / 0.04)))
        if n <= 0:
            return
        full = self.f_big.render(word, True, INK)
        part = self.f_big.render(word[:n], True, INK)
        x = BASE_W // 2 - full.get_width() // 2
        c.blit(part, (x, y - full.get_height() // 2))
        if t is not None and n < len(word):                 # blinking cursor while it types
            cx = x + part.get_width() + 3
            pygame.draw.rect(c, self.ORANGE, (cx, y - 14, 4, 28))

    def chime(self):
        """Startup chord in your key: the home chord with its 7th, openly voiced."""
        try:
            pc, iv, _ = build_chord(self.key, self.scale, 0, {"seventh": True})
            r = 36 + (pc % 12) + 12 * self.octave
            while r < 43:
                r += 12
            while r > 54:
                r -= 12
            # open voicing: root, fifth, then 3rd, 7th and 5th an octave up
            notes = [r, r + iv[2], r + 12 + iv[1], r + 12 + iv[3], r + 24 + iv[2]]
            self.eng.post("chime", [int(n) for n in notes])
        except Exception:
            self.eng.post("chime")

    def intro(self, secs=1.5):
        """Short logo animation at launch. Any button skips it."""
        self.t0 = time.perf_counter()
        clock = pygame.time.Clock()
        struck = False
        while True:
            t = time.perf_counter() - self.t0
            if not struck and t >= 1.0:          # the chord lands when the keys are struck
                self.chime()
                struck = True
            if t >= secs:
                return
            for ev in pygame.event.get():
                if ev.type in (pygame.KEYDOWN, pygame.JOYBUTTONDOWN):
                    if not struck:
                        self.chime()
                    return
                if ev.type == pygame.QUIT:
                    self.running = False
                    return
            if synth.BASS_MODES[self.bass] not in ("Patch", "Off"):
                self.ensure_bass(self.bass_range(), budget=0.008)   # a few notes per frame
            c = self.canvas
            c.fill(BG)
            self.draw_mark(c, BASE_W // 2, 105 + L["dy"], 34, t)
            self.draw_title(c, 180 + L["dy"], t)
            self.present()
            clock.tick(60)

    def loading(self, done, total):
        c = self.canvas
        c.fill(BG)
        t = time.perf_counter() - getattr(self, "t0", time.perf_counter() - 9)
        d = L["dy"]
        self.draw_mark(c, BASE_W // 2, 105 + d, 34, max(t, 1.5))
        self.draw_title(c, 180 + d)
        self.text(c, "preparing %s" % synth.PATCHES[self.patch]["name"], self.f_small, DIM, (BASE_W // 2, 218 + d), center=True)
        w = 360
        pygame.draw.rect(c, PANEL, ((BASE_W - w) // 2, 250 + d, w, 14), border_radius=7)
        pygame.draw.rect(c, ACCENT, ((BASE_W - w) // 2, 250 + d, int(w * done / max(1, total)), 14), border_radius=7)
        self.text(c, "%d / %d" % (done, total), self.f_small, DIM, (BASE_W // 2, 290 + d), center=True)
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
        if self.mode().startswith("Arp"):
            base = sorted(set(notes[1:]))
            need |= {m + 12 * k for k in range(self.arp_oct) for m in base if m + 12 * k <= 118}
            if base[0] + 12 * self.arp_oct <= 118:
                need.add(base[0] + 12 * self.arp_oct)
        if synth.BASS_MODES[self.bass] not in ("Patch", "Off"):
            r = notes[0] - 12
            while r < 28:
                r += 12
            self.ensure_bass((r, r + 7, r + 12))
        self.sounding = notes
        self.hit_t, self.hit_big = time.perf_counter(), not revoice
        self.new_hit = True
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
                                    latency=self.block, quantize=self.quantize,
                                    bass=self.bass, bass_lvl=self.bass_lvl, arp_oct=self.arp_oct,
                                    imode=getattr(self, "imode", "Play"), countin=getattr(self, "countin", 1))
        if hasattr(self, "rack"):
            self.cfg["rack"] = self.rack
            self.cfg.pop("seq", None)
            if getattr(self, "lp_loaded", False) and self.lp_e() is not None:
                self.cfg.pop("loop", None)
                self.song_save()
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
            self.text(c, "BUTTON SETUP", self.f_med, ACCENT, (BASE_W // 2, 70 + L["dy"]), center=True)
            self.text(c, "Press", self.f_med, DIM, (BASE_W // 2, 170 + L["dy"]), center=True)
            if i < len(order):
                self.text(c, order[i], self.f_huge, INK, (BASE_W // 2, 250 + L["dy"]), center=True)
            self.text(c, "%d / %d" % (min(i + 1, len(order)), len(order)), self.f_small, DIM, (BASE_W // 2, 340 + L["dy"]), center=True)
            self.text(c, "This happens once. Relearn any time from the menu.", self.f_small, DIM, (BASE_W // 2, 420 + L["dy"]), center=True)
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
                 ("R3", "Click the RIGHT stick", "DOWN"), ("L3", "Click the LEFT stick", "DOWN")]
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
                    elif down and key in ("R3", "L3") and sig.startswith("b") and sig not in self.inp.map:
                        mapping = {k: v for k, v in self.inp.map.items() if v != key}
                        mapping[sig] = key
                        self.inp.map = mapping
                        self.cfg["buttons"] = mapping
                        self.eng.post("click")
                        skip = True
            if skip:
                i += 1
                armed = True
                continue
            if key not in ("R3", "L3"):
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
            self.text(c, "STICK SETUP", self.f_med, ACCENT, (BASE_W // 2, 70 + L["dy"]), center=True)
            if i < len(steps):
                self.text(c, steps[i][1], self.f_med, DIM, (BASE_W // 2, 170 + L["dy"]), center=True)
                self.text(c, steps[i][2], self.f_huge, INK, (BASE_W // 2, 250 + L["dy"]), center=True)
                if steps[i][0] not in ("R3", "L3"):
                    self.text(c, "then let it go back to center", self.f_small, DIM, (BASE_W // 2, 320 + L["dy"]), center=True)
            if only == ("L3",):
                self.text(c, "New: click the left stick for the mode wheel (Play, Lead, Drone, Drums...)",
                          self.f_small, ACCENT2, (BASE_W // 2, 385 + L["dy"]), center=True)
            elif only:
                self.text(c, "New: right stick LEFT/RIGHT = filter / resonance, click = hold effects",
                          self.f_small, ACCENT2, (BASE_W // 2, 385 + L["dy"]), center=True)
            self.text(c, "Press START to skip a step (or if you have no sticks)", self.f_small, DIM,
                      (BASE_W // 2, 420 + L["dy"]), center=True)
            self.present()
            clock.tick(60)
        self.cfg["sticks"] = result
        self.cfg["fx2_learned"] = True
        if not only or "L3" in only:
            self.cfg["l3_learned"] = True
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
        if (st.get("lx") or st.get("ly")) and (self.wheel_open or self.imode != "Play"):
            x, y = self.axis_val(st.get("lx")), self.axis_val(st.get("ly"))
            self.stick_xy = (x, y)
            if self.wheel_open:
                self.wheel_stick(x, y)
            else:
                self.mode_stick(x, y)
        elif st.get("lx") or st.get("ly"):
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
        # up = more space (reverb and delay together), down = dry the synth out
        if ry >= 0:
            rev = self.base_rev + ry * (1 - self.base_rev)
            dly = self.base_dly + ry * max(0.0, 0.8 - self.base_dly)
        else:
            rev = self.base_rev * (1 + ry)
            dly = self.base_dly * (1 + ry)
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
            ("Arp Octaves", "%d" % self.arp_oct),
            ("Bass", synth.BASS_MODES[self.bass]),
            ("Bass Level", "%d%%" % round(self.bass_lvl * 100)),
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
        ] + ([("Count-in", ("%d bar%s" % (self.countin, "" if self.countin == 1 else "s")) if self.countin
                            else "Off, starts on first note")] if edition.LAB else []) + [
            ("Volume", "%d%%" % round(self.volume * 100)),
            ("Latency", {512: "Low", 1024: "Normal", 2048: "Safe"}.get(self.block, str(self.block))),
            ("Relearn buttons", ""),
            ("Learn sticks", "on" if self.cfg.get("sticks") else "off"),
            ("Quit", ""),
        ]

    def menu_change(self, d):
        self.nudge = (time.perf_counter(), d)
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
        elif name == "Arp Octaves":
            self.arp_oct = clamp(self.arp_oct + d, 1, 4)
            self.push_bass()
        elif name == "Bass":
            self.bass = (self.bass + d) % len(synth.BASS_MODES)
            self.push_bass()
            if synth.BASS_MODES[self.bass] not in ("Patch", "Off"):
                self.ensure_bass(self.bass_range())
        elif name == "Bass Level":
            self.bass_lvl = clamp(round(self.bass_lvl + 0.1 * d, 1), 0.0, 2.0)
            self.push_bass()
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
        elif name == "Count-in":
            self.countin = (self.countin + d) % 3
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
            self.nudge = (time.perf_counter(), -1 if name == "LEFT" else 1)
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
                self.sel_combo = True          # this press closed the menu; don't reopen on release
                self.save_cfg()
            elif name == "START":
                self.toggle_drums()
            return
        if name == "L3":
            if down:
                self.wheel_toggle()
            return
        if self.wheel_open:
            if down and name == "B":
                self.wheel_open = False
            return
        # SELECT: tap = settings, hold = looper controls from any mode
        if name == "SELECT" and not edition.LAB:
            if down:
                self.menu = True
            return
        if name == "SELECT":
            if down:
                self.sel_combo = False
            elif not getattr(self, "sel_combo", True):
                self.menu = True
            return
        if edition.LAB and "SELECT" in held and self.looper_combo(name, down):
            self.sel_combo = True
            return
        if self.imode != "Play" and self.mode_input(name, down):
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
        elif name == "START" and down:
            self.toggle_drums()

    # ---------------- drawing
    def render(self, font, s, col):
        """font.render with a cache: most labels are the same every frame."""
        k = (id(font), s, col)
        img = self._tc.get(k)
        if img is None:
            if len(self._tc) > 600:
                self._tc.clear()
            img = self._tc[k] = font.render(s, True, col)
        return img

    def text(self, surf, s, font, col, pos, center=False, right=False):
        img = self.render(font, s, col)
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

    # ---------------- animation
    # Everything moves the way a hardware synth screen does: values glide,
    # presses pop and spring back, lights decay instead of snapping off.
    def sm(self, key, target, rate=14.0):
        """Ease a named value toward target (frame-rate independent)."""
        v = self.anim.get(key, target)
        v += (target - v) * (1 - math.exp(-rate * self.dt))
        self.anim[key] = v
        return v

    @staticmethod
    def since(t0, dur):
        """0..1 progress of an event that started at t0 and lasts dur seconds (1 = finished)."""
        return min(1.0, max(0.0, (time.perf_counter() - t0) / dur))

    def draw(self):
        now = time.perf_counter()
        self.dt = min(0.1, max(0.001, now - self.last_frame))
        self.last_frame = now
        self.now = now
        c = self.canvas
        c.fill(BG)

        # beat clock: remember when each 16th arrives
        st = self.eng.step16 if self.drums_on else -1
        if st != self.step_t[0]:
            self.step_t = (st, now)
        quarter = self.drums_on and (st - 1) % 4 == 0
        beat_pop = (1 - self.since(self.step_t[1], 0.18)) if quarter else 0.0

        # ---- header: mini logo that steps with the beat, info slides when it changes
        pygame.draw.rect(c, PANEL, (0, 0, BASE_W, 38))
        self.draw_mini_mark(c, 14, 12, st)
        self.text(c, edition.NAME.upper(), self.f_small, ACCENT, (62, 12))
        chips_end = self.draw_mode_chip(c, 172, 9)
        info = "%s %s  |  %s  |  %s  |  %d BPM" % (NOTE_NAMES[self.key], self.scale,
                                                   synth.PATCHES[self.patch]["name"], self.mode(), self.bpm)
        for alt in ("%s %s  |  %s  |  %d BPM" % (NOTE_NAMES[self.key], self.scale, synth.PATCHES[self.patch]["name"], self.bpm),
                    "%s %s  |  %d BPM" % (NOTE_NAMES[self.key], self.scale, self.bpm)):
            if BASE_W - 12 - self.f_small.size(info)[0] > chips_end + 10:
                break
            info = alt
        if info != self.anim.get("_info"):
            self.anim["_info"] = info
            self.anim["_info_t"] = now
        k = self.since(self.anim.get("_info_t", -9), 0.25)
        dy = int((1 - k) ** 2 * -10)
        self.text(c, info, self.f_small, self.mix(ACCENT, INK, k), (BASE_W - 12, 12 + dy), right=True)
        if beat_pop:
            pygame.draw.rect(c, self.mix(PANEL, ACCENT, beat_pop), (0, 36, BASE_W, 2))

        if self.imode in ("Song", "Effects"):
            self.draw_page(c)
        else:
            # ---- brick well + scope behind the chord name
            if self.new_hit:
                self.new_hit = False
                if self.hit_big and self.cur:
                    self.hard_drop(self.cur[0] % 7)
            self.draw_well(c, quarter and beat_pop > 0.9)
            self.draw_scope(c)

            # ---- chord name + numeral (pop on strike), or the idle logo
            x = self.since(self.hit_t, 0.32)
            if self.mode_hero(c, now):
                pass
            elif self.cur:
                deg, pc, iv, name = self.cur
                font = self.f_huge if self.f_huge.size(name)[0] < 330 else self.f_big
                self.draw_name(c, name, font, BASE_W // 2 - 10, L["name_y"], x)
                ry = int(14 * (1 - min(1, x * 1.6)) ** 3)
                self.text(c, roman_for(deg, iv), self.f_big, ACCENT, (BASE_W // 2, L["roman_y"] + ry), center=True)
            else:
                self.draw_mark(c, BASE_W // 2, L["mark_y"], 22, 1.5 + now - getattr(self, "t0", now))
                b = 0.5 + 0.5 * math.sin(now * 2.2)
                self.text(c, "press a chord", self.f_med, self.mix(DIM, INK, b * 0.5), (BASE_W // 2, L["roman_y"]), center=True)

            # ---- modifier pills fill from the middle when held
            m = self.mods()
            h = self.inp.held
            labels = self.mode_pills(h) or [("Y  FLIP", "Y" in h), ("L1  7th", "L1" in h and "R1" not in h),
                                            ("R1  SUS4", "R1" in h and "L1" not in h), ("L1+R1  9th", "L1" in h and "R1" in h)]
            x = 40
            for n, (lab, on) in enumerate(labels):
                lv = self.sm("pill%d" % n, 1.0 if on else 0.0, 22 if on else 9)
                r = pygame.Rect(x, L["pills_y"], 128, 26)
                pygame.draw.rect(c, PANEL, r, border_radius=6)
                if lv > 0.02:
                    fw = max(6, int(r.w * lv))
                    fr = pygame.Rect(0, 0, fw, r.h)
                    fr.center = r.center
                    pygame.draw.rect(c, self.mix(PANEL, (92, 70, 34), lv), fr, border_radius=6)
                    pygame.draw.rect(c, self.mix(PANEL, MOD_ON, lv), fr, 2, border_radius=6)
                self.text(c, lab, self.f_small, self.mix(DIM, MOD_ON, lv), r.center, center=True)
                x += 142

            if (self.cfg.get("sticks") or {}).get("lx"):
                self.draw_stick(c)
            self.draw_fx(c)

            # ---- chord buttons: press down, flash, glow off slowly
            tw, gap = 82, 6
            x0 = (BASE_W - (7 * tw + 6 * gap)) // 2
            ck = (self.key, self.scale, tuple(sorted(k for k, v in m.items() if v)))
            if self.anim.get("_ck") != ck:
                self.anim["_ck"] = ck
                self.anim["_chords"] = [build_chord(self.key, self.scale, i, m) for i in range(7)]
            chords = self.anim["_chords"]
            for i, btn in enumerate(CHORD_BUTTONS):
                pc, iv, name = chords[i]
                active = bool(self.cur and self.cur[0] == i)
                top = roman_for(i, iv)
                ov = self.mode_tile(i, btn)
                if ov:
                    top, name, active = ov
                lv = self.sm("tile%d" % i, 1.0 if active else 0.0, 30 if active else 6)
                hit = active and self.since(self.hit_t, 0.16) < 1
                dip = int(5 * (1 - self.since(self.hit_t, 0.16))) if hit else (2 if active else 0)
                th = L["tile_h"]
                r = pygame.Rect(x0 + i * (tw + gap), L["tiles_y"] + dip, tw, th)
                if dip:
                    pygame.draw.rect(c, (8, 7, 10), (r.x, L["tiles_y"] + th - 4, tw, 4 + dip), border_radius=10)
                col = self.mix(PANEL, ACCENT, lv)
                if hit:
                    col = self.mix((255, 226, 200), ACCENT, self.since(self.hit_t, 0.16))
                    if self.anim.get("_shatter") != self.hit_t:        # strike: tile throws bricks
                        self.anim["_shatter"] = self.hit_t
                        for _ in range(10 if self.hit_big else 4):
                            self.burst(r.x + random.randrange(tw), r.y + random.randrange(20),
                                       random.choice((ACCENT, (255, 226, 200), self.PIECE_COL[i % 7])), 1, 220, up=260)
                pygame.draw.rect(c, col, r, border_radius=10)
                ink = self.mix(INK, BG, lv)
                self.text(c, top, self.f_med, self.mix(ACCENT2, BG, lv), (r.centerx, r.y + th * 21 // 100), center=True)
                nm_font = self.f_med if len(name) < 6 else self.f_small
                self.text(c, name, nm_font, ink, (r.centerx, r.y + th * 54 // 100), center=True)
                self.text(c, BUTTON_GLYPH[btn], self.f_small, self.mix(DIM, BG, lv), (r.centerx, r.y + th * 83 // 100), center=True)

        # ---- keyboard: sounding keys light, then fade out
        kx, ky, kw, kh = 20, L["kb_y"], BASE_W - 40, L["kb_h"]
        lo, hi = 36, 96
        nwhite = sum(1 for n in range(lo, hi) if n % 12 in (0, 2, 4, 5, 7, 9, 11))
        ww = kw / nwhite
        wx = kx
        sounding = set(self.sounding)
        fade = math.exp(-self.dt * 5.0)
        for n in list(self.glow):
            if n not in sounding:
                self.glow[n] *= fade
                if self.glow[n] < 0.02:
                    del self.glow[n]
        for n in sounding:
            if n not in self.glow and lo <= n < hi:          # new note: a block hops off the key
                self.anim.setdefault("_newnotes", []).append(n)
            self.glow[n] = 1.0
        if self._kb is None:
            self._kb = pygame.Surface((kw, kh + 2))
            self._kb.fill(BG)
            self._kbw, self._kbb = {}, {}
            wx = 0.0
            for n in range(lo, hi):
                if n % 12 in (0, 2, 4, 5, 7, 9, 11):
                    self._kbw[n] = pygame.Rect(int(wx), 0, int(ww) - 1, kh)
                    wx += ww
            for n in range(lo, hi):
                if n % 12 in (1, 3, 6, 8, 10):
                    px = self._kbw[n - 1].x + ww * 0.65
                    self._kbb[n] = pygame.Rect(int(px), 0, int(ww * 0.7), int(kh * 0.6))
            for r in self._kbw.values():
                pygame.draw.rect(self._kb, (200, 194, 184), r)
            for r in self._kbb.values():
                pygame.draw.rect(self._kb, (30, 28, 34), r)
        c.blit(self._kb, (kx, ky))
        lit = [n for n in self.glow if lo <= n < hi]
        for n in sorted(lit, key=lambda n: n in self._kbb):     # whites first, blacks on top
            g = self.glow[n]
            if n in self._kbw:
                r = self._kbw[n].move(kx, ky + (2 if n in sounding else 0))
                pygame.draw.rect(c, self.mix((200, 194, 184), ACCENT, g), r)
                for b in (n - 1, n + 1):                         # redraw black keys this covered
                    if b in self._kbb and b not in self.glow:
                        pygame.draw.rect(c, (30, 28, 34), self._kbb[b].move(kx, ky))
            else:
                r = self._kbb[n].move(kx, ky + (2 if n in sounding else 0))
                pygame.draw.rect(c, self.mix((30, 28, 34), ACCENT, g), r)
        for n in self.anim.pop("_newnotes", []):
            r = self._kbw.get(n) or self._kbb.get(n)
            if r:
                self.burst(kx + r.centerx, ky, ACCENT, 2, 60, up=330)

        # ---- status + beat steps
        status = []
        if self.drums_on:
            status.append("BEAT: " + synth.BEATS[self.beat][0])
        if self.latch:
            status.append("LATCH")
        left = self.eng.remaining
        if left:
            status.append("%d notes finish when quiet" % left)
        status.append("CPU %d%%" % round(self.eng.load * 100))
        sr = self.text(c, "   ".join(status), self.f_small, ACCENT2, (20, L["status_y"]))
        hint = self.mode_hint() or ("SELECT menu (hold: song)   START beat   L3 modes" if edition.LAB
                                    else "SELECT menu   START beat   L3 modes")
        if sr.right + 20 < BASE_W - 20 - self.f_small.size(hint)[0]:
            self.text(c, hint, self.f_small, DIM, (BASE_W - 20, L["status_y"]), right=True)
        on = self.sm("beatrow", 1.0 if self.drums_on else 0.0, 10)
        if on > 0.02:
            cur = (st - 1) % 16
            pop = 1 - self.since(self.step_t[1], 0.12)
            for i in range(int(16 * on + 0.999)):
                lit = self.drums_on and i == cur
                hgt = 6 + (int(5 * pop) if lit else 0)
                col = ACCENT if lit else (PANEL if i % 4 else DIM)
                pygame.draw.rect(c, col, (20 + i * 12, L["steps_y"] - hgt, 9, hgt))
        if self.msg:
            k = self.since(self.msg_t, 1.5)
            if k < 1:
                rise = int(8 * (1 - min(1, k * 6)) ** 2)
                a = min(1, k * 6) * (1 - max(0, (k - 0.75) / 0.25))
                self.text(c, self.msg, self.f_small, self.mix(BG, MOD_ON, a), (BASE_W // 2, L["msg_y"] + rise), center=True)

        self.draw_parts(c)

        self.draw_wheel(c)

        # ---- overlays slide up and fade in/out
        ma = self.sm("menu", 1.0 if (self.menu and not self.editor) else 0.0, 16)
        if ma > 0.01:
            self.draw_menu(c, ma)
        ea = self.sm("editor", 1.0 if self.editor else 0.0, 16)
        if ea > 0.01:
            self.draw_editor(c, ea)
        self.present()

    # ---------------- bricks: a self-playing Tetris well and exploding blocks
    PIECES = [
        [(0, 0), (1, 0), (2, 0), (3, 0)],      # I
        [(0, 0), (1, 0), (0, 1), (1, 1)],      # O
        [(0, 0), (1, 0), (2, 0), (1, 1)],      # T
        [(1, 0), (2, 0), (0, 1), (1, 1)],      # S
        [(0, 0), (1, 0), (1, 1), (2, 1)],      # Z
        [(0, 0), (0, 1), (1, 1), (2, 1)],      # J
        [(2, 0), (0, 1), (1, 1), (2, 1)],      # L
    ]
    PIECE_COL = [(110, 200, 190), (255, 200, 90), (255, 140, 66), (140, 210, 120),
                 (240, 100, 110), (120, 150, 255), (200, 140, 255)]
    WC, WR, CELL = 24, 15, 12
    WX, WY = (640 - 24 * 12) // 2, 46

    @staticmethod
    def _rot(cells, r):
        for _ in range(r % 4):
            cells = [(-y, x) for x, y in cells]
        mx = min(x for x, _ in cells); my = min(y for _, y in cells)
        return [(x - mx, y - my) for x, y in cells]

    def well_reset(self):
        self.WR = L["well_rows"]
        self.grid = [[None] * self.WC for _ in range(self.WR)]
        self.well_dirty = True
        self.well_surf = None
        self.piece = None
        self.spawn(random.randrange(7))

    def _fits(self, cells, px, py):
        for x, y in cells:
            gx, gy = px + x, py + y
            if gx < 0 or gx >= self.WC or gy >= self.WR:
                return False
            if gy >= 0 and self.grid[gy][gx] is not None:
                return False
        return True

    def spawn(self, kind):
        """New piece; a quick heuristic picks where it lands (tidy stacks = lines clear).
        Uses column heights only, so it costs well under a millisecond."""
        WR, WC = self.WR, self.WC
        heights = []
        for cx in range(WC):
            top = WR
            for ry in range(WR):
                if self.grid[ry][cx] is not None:
                    top = ry
                    break
            heights.append(top)                 # first filled row (WR = empty column)
        best = None
        for r in range(4):
            cells = self._rot(self.PIECES[kind], r)
            w = max(x for x, _ in cells) + 1
            bottoms = [max(y for x, y in cells if x == cx) for cx in range(w)]
            for px in range(WC - w + 1):
                py = min(heights[px + cx] - 1 - bottoms[cx] for cx in range(w))
                if py + min(y for _, y in cells) < 0:
                    continue
                holes = sum(heights[px + cx] - 1 - (py + bottoms[cx]) for cx in range(w))
                land = py + sum(y for _, y in cells) / 4.0
                flat = -abs((heights[px - 1] if px > 0 else heights[px]) - (heights[px + w] if px + w < WC else heights[px + w - 1]))
                score = land * 1.0 - holes * 4.0 + flat * 0.3 + random.random() * 0.5
                if best is None or score > best[0]:
                    best = (score, cells, px)
        if best is None:                       # stack topped out: blow it all up
            self.explode_well()
            self.grid = [[None] * WC for _ in range(WR)]
            self.well_dirty = True
            return self.spawn(kind)
        _, cells, px = best
        self.piece = [cells, px, -2, kind]

    def well_step(self):
        cells, px, py, kind = self.piece
        if self._fits(cells, px, py + 1):
            self.piece[2] += 1
            return
        self.lock()

    def hard_drop(self, kind):
        cells, px, py, k0 = self.piece
        while self._fits(cells, px, py + 1):
            py += 1
        self.piece[2] = py
        for x, y in cells:                     # dust where it lands
            self.burst(self.WX + (px + x) * self.CELL + 6, self.WY + (py + y) * self.CELL + 10,
                       self.PIECE_COL[k0], 2, 60, up=40)
        self.lock(next_kind=kind)

    def lock(self, next_kind=None):
        cells, px, py, kind = self.piece
        for x, y in cells:
            if py + y < 0:
                self.explode_well()
                self.grid = [[None] * self.WC for _ in range(self.WR)]
                self.well_dirty = True
                self.spawn(random.randrange(7) if next_kind is None else next_kind)
                return
            self.grid[py + y][px + x] = kind
        self.well_dirty = True
        full = [ry for ry in range(self.WR) if all(v is not None for v in self.grid[ry])]
        for ry in full:                        # line clear: the row bursts into bricks
            for cx in range(self.WC):
                self.burst(self.WX + cx * self.CELL + 6, self.WY + ry * self.CELL + 6,
                           self.PIECE_COL[self.grid[ry][cx]], 1, 220, up=160)
        if full:
            self.grid = [[None] * self.WC for _ in full] + [r for i, r in enumerate(self.grid) if i not in full]
            self.anim["_clear_t"] = time.perf_counter()
        self.spawn(random.randrange(7) if next_kind is None else next_kind)

    def explode_well(self):
        for ry in range(self.WR):
            for cx in range(self.WC):
                k = self.grid[ry][cx]
                if k is not None and random.random() < 0.6:
                    self.burst(self.WX + cx * self.CELL + 6, self.WY + ry * self.CELL + 6,
                               self.PIECE_COL[k], 1, 300, up=200)

    def burst(self, x, y, col, n, speed, up=0):
        for _ in range(n):
            if len(self.parts) > 260:
                self.parts.pop(0)
            a = random.uniform(0, 2 * math.pi)
            v = random.uniform(0.3, 1.0) * speed
            self.parts.append([float(x), float(y), math.cos(a) * v, math.sin(a) * v - up,
                               random.uniform(0.6, 1.1), col, random.choice((4, 5, 6, 8))])

    def draw_parts(self, c):
        live = []
        for p in self.parts:
            p[3] += 900 * self.dt              # gravity
            p[0] += p[2] * self.dt
            p[1] += p[3] * self.dt
            p[4] -= self.dt
            if p[4] > 0 and p[1] < BASE_H + 10:
                live.append(p)
                f = min(1.0, p[4] * 2.5)
                sz = p[6]
                pygame.draw.rect(c, self.mix(BG, p[5], f), (int(p[0]) - sz // 2, int(p[1]) - sz // 2, sz, sz))
        self.parts = live

    def draw_well(self, c, quarter_hit):
        # gravity: one row per beat with drums on, a gentle drift without
        now = self.now
        if quarter_hit or (not self.drums_on and now - self.grav_t > 0.45):
            self.grav_t = now
            self.well_step()
        fade = 0.26 if self.cur else 0.34
        cl = 1 - self.since(self.anim.get("_clear_t", -9), 0.3)
        C = self.CELL
        key = (fade, round(cl, 1))
        if self.well_dirty or self.anim.get("_well_key") != key or self.well_surf is None:
            if self.well_surf is None:
                self.well_surf = pygame.Surface((self.WC * C, self.WR * C))
                self.well_surf.set_colorkey((1, 2, 3))
            ws = self.well_surf
            ws.fill((1, 2, 3))
            f = fade + 0.4 * cl
            for ry in range(self.WR):
                row = self.grid[ry]
                for cx in range(self.WC):
                    k = row[cx]
                    if k is not None:
                        self.brick(ws, cx * C, ry * C, self.PIECE_COL[k], f)
            self.well_dirty = False
            self.anim["_well_key"] = key
        c.blit(self.well_surf, (self.WX, self.WY))
        cells, px, py, kind = self.piece
        for x, y in cells:
            if py + y >= 0:
                self.brick(c, self.WX + (px + x) * C, self.WY + (py + y) * C, self.PIECE_COL[kind], fade + 0.2)
        # faint well floor
        pygame.draw.line(c, PANEL, (self.WX, self.WY + self.WR * C), (self.WX + self.WC * C - 1, self.WY + self.WR * C))

    def brick(self, c, x, y, col, f):
        C = self.CELL - 1
        pygame.draw.rect(c, self.mix(BG, col, f), (x, y, C, C))
        pygame.draw.line(c, self.mix(BG, col, min(1, f * 1.6)), (x, y), (x + C - 1, y))       # lit top edge

    def draw_name(self, c, name, font, cx, cy, x):
        """Chord name: on a new chord the letters fall in one by one and land with a bounce."""
        full = font.size(name)[0]
        xx = cx - full // 2
        for n, ch in enumerate(name):
            img = self.render(font, ch, INK)
            dy = 0
            if self.hit_big:
                t = (time.perf_counter() - self.hit_t) - n * 0.03
                if t < 0:
                    xx += font.size(ch)[0]
                    continue
                if t < 0.12:
                    dy = -int((1 - t / 0.12) ** 2 * 70)
                elif t < 0.30:
                    u = (t - 0.12) / 0.18
                    dy = -int(math.sin(u * math.pi) * 10 * (1 - u))
            c.blit(img, img.get_rect(midleft=(xx, cy + dy)))
            xx += font.size(ch)[0]

    @staticmethod
    def mix(a, b, f):
        f = 0.0 if f < 0 else (1.0 if f > 1 else round(f * 16) / 16.0)   # 16 steps keeps text caches small
        return (int(a[0] + (b[0] - a[0]) * f), int(a[1] + (b[1] - a[1]) * f), int(a[2] + (b[2] - a[2]) * f))

    def draw_mini_mark(self, c, x, y, step):
        """Tiny logo in the header; with the beat running, its keys follow the 16ths."""
        k, g = 6, 2
        lit = (step - 1) % 8 if self.drums_on else -1
        for i in range(8):
            col = self.ORANGE if (i == 6 and lit < 0) or i == lit else (120, 116, 128)
            if i == lit:
                col = self.ORANGE if i != 6 else (255, 200, 150)
            pygame.draw.rect(c, col, (x + (i % 4) * (k + g), y + (i // 4) * (k + g), k, k), border_radius=1)

    def draw_scope(self, c):
        """Live waveform of the output, OP-1 style, faint behind the chord name."""
        e = getattr(self.eng, "eng", None)
        sc = getattr(e, "scope", None)
        if sc is None or not len(sc):
            return
        n = len(sc)
        amp = float(abs(sc).max())
        lv = self.sm("scope", min(1.0, amp * 3), 12)
        if lv < 0.01:
            return
        x0, x1, cy, hh = 150, BASE_W - 170, 132, 54
        step = max(1, n // 96)
        pts = [(x0 + (x1 - x0) * i / (n - 1), cy - float(sc[i]) * hh * 1.6) for i in range(0, n, step)]
        if len(pts) > 1:
            pygame.draw.lines(c, self.mix(BG, (70, 120, 116), lv), False, pts, 2)

    def draw_stick(self, c):
        cx, cy, rad = 556, L["stick_cy"], 62
        pygame.draw.circle(c, PANEL, (cx, cy), rad + 14)
        if self.imode != "Play":                      # other modes: stick = bend/vibrato or nothing
            sx, sy = self.stick_xy
            ex, ey = self.sm("stx", sx, 25), self.sm("sty", sy, 25)
            p = (int(cx + ex * 30), int(cy - ey * 30))
            pygame.draw.circle(c, ACCENT if self.imode == "Lead" and (abs(sx) > 0.15 or sy > 0.2) else DIM, p, 8)
            lab = {"Lead": "BEND / VIB"}.get(self.imode, "L3 = MODES")
            self.text(c, lab, self.f_small, DIM, (cx, cy + rad + 26), center=True)
            if self.imode == "Lead":
                self.text(c, "vib", self.f_small, DIM, (cx, cy - rad + 4), center=True)
                self.text(c, "-2", self.f_small, DIM, (cx - rad + 8, cy), center=True)
                self.text(c, "+2", self.f_small, DIM, (cx + rad - 8, cy), center=True)
            return
        for sector, mod in STICK_SECTORS.items():
            ang = math.radians(sector * 45)
            lv = self.sm("sec_" + mod, 1.0 if self.stick_mod == mod else 0.0, 20)
            push = 1 + 0.12 * lv
            lx, ly = cx + math.cos(ang) * rad * push, cy - math.sin(ang) * rad * push
            self.text(c, STICK_LABEL[mod], self.f_small, self.mix(DIM, MOD_ON, lv), (int(lx), int(ly)), center=True)
        sx, sy = self.stick_xy
        ex = self.sm("stx", sx, 25)
        ey = self.sm("sty", sy, 25)
        p = (int(cx + ex * 22), int(cy - ey * 22))
        self.trail = ([p] + self.trail)[:6]
        for n, q in enumerate(self.trail[1:], 1):
            pygame.draw.circle(c, self.mix(PANEL, DIM, 1 - n / 6), q, max(2, 7 - n))
        pygame.draw.circle(c, ACCENT if self.stick_mod else DIM, p, 7)
        self.text(c, "L STICK", self.f_small, DIM, (cx, cy + rad + 26), center=True)

    def draw_fx(self, c):
        mx, top, half = 72, L["fx_top"], L["fx_half"]
        h = half * 2
        rev = self.sm("rev", self.rev, 16)
        dly = self.sm("dly", self.dly, 16)
        for x0, val, col, lab in ((mx - 16, rev, ACCENT2, "REV"), (mx + 4, dly, ACCENT, "DLY")):
            pygame.draw.rect(c, PANEL, (x0, top, 12, h), border_radius=6)
            vh = int(h * max(0.0, min(1.0, val)))
            if vh:
                pygame.draw.rect(c, col, (x0, top + h - vh, 12, vh), border_radius=6)
                pygame.draw.rect(c, self.mix(col, (255, 255, 255), 0.5), (x0 + 2, top + h - vh, 8, 2))
            lx = x0 - 22 if lab == "REV" else x0 + 34
            self.text(c, lab, self.f_small, col if val > 0.01 else DIM, (lx, top + h - 10), center=True)
        wet = self.sm("wet", 1.0 if self.ry > 0 else 0.0, 12)
        self.text(c, "WET", self.f_small, self.mix(DIM, INK, wet), (mx, top - 14), center=True)
        dry = self.sm("dry", 1.0 if self.ry < 0 else 0.0, 12)
        if dry > 0.03:
            self.text(c, "DRY", self.f_small, self.mix(BG, INK, dry), (mx, top + h + 14), center=True)
        by, bw = top + half * 2 + 38, 52
        pygame.draw.rect(c, PANEL, (mx - bw, by - 6, bw * 2, 12), border_radius=6)
        f = self.sm("flt", self.flt[0], 16)
        r = self.sm("res", self.flt[1], 16)
        if f > 0.005:
            pygame.draw.rect(c, ACCENT, (mx - int(bw * f), by - 6, int(bw * f), 12), border_radius=6)
        if r > 0.005:
            pygame.draw.rect(c, ACCENT2, (mx, by - 6, int(bw * r), 12), border_radius=6)
            if r > 0.3:                                  # resonance wiggles
                wy = by - 14
                pts = [(mx + i, wy - math.sin(i * 0.5 + self.now * 14) * 3 * r) for i in range(0, int(bw * r), 2)]
                if len(pts) > 1:
                    pygame.draw.lines(c, ACCENT2, False, pts, 1)
        pygame.draw.line(c, DIM, (mx, by - 9), (mx, by + 9), 1)
        self.text(c, "FILTER", self.f_small, ACCENT if f > 0.01 else DIM, (mx - bw // 2, by + 18), center=True)
        self.text(c, "RES", self.f_small, ACCENT2 if r > 0.01 else DIM, (mx + bw // 2, by + 18), center=True)
        if self.fx_hold and int(self.now * 2.5) % 2 == 0:
            self.text(c, "HOLD", self.f_small, MOD_ON, (mx + 44, top + 18), center=True)

    def draw_list(self, c, a, title, rows, sel_i, key, xin):
        """Shared look for Settings and the sound editor: the panel slides up,
        the highlight glides between rows, changed values flick sideways."""
        self._ov.set_alpha(int(230 * a))
        c.blit(self._ov, (0, 0))
        opening = self.menu or self.editor
        off = int((1 - a) ** 2 * 60) if opening else 0
        self.text(c, title, self.f_med, self.mix(BG, ACCENT, a), (BASE_W // 2, 30 + off), center=True)
        nr = L["list_rows"]
        top = max(0, min(sel_i - nr // 2, len(rows) - nr))
        ty = self.sm(key + "_sel", 58 + (sel_i - top) * 30, 24)
        pygame.draw.rect(c, self.mix(BG, PANEL, a), (xin - 20, int(ty) - 3, BASE_W - 2 * (xin - 20), 28), border_radius=6)
        nt, nd = self.nudge
        kick = int(8 * nd * (1 - self.since(nt, 0.18)) ** 2)
        for r, row in enumerate(rows[top:top + nr]):
            label, val, col = row
            i = top + r
            if opening:                        # rows drop in one after another, like pieces
                pr = min(1.0, max(0.0, a * 1.9 - r * 0.07))
                y = 58 + r * 30 + int((1 - pr) ** 2 * -140)
            else:                              # closing: just fade
                y = 58 + r * 30
            sel = i == sel_i
            if not opening and a < 0.6:
                continue                       # closing: rows vanish, the panel fades
            self.text(c, label, self.f_med, ACCENT if sel else col, (xin, y))
            if val:
                s = ("< %s >" % val) if sel else val
                self.text(c, s, self.f_med, INK if sel else DIM,
                          (BASE_W - xin + (kick if sel else 0), y), right=True)

    def draw_editor(self, c, a=1.0):
        rows = [(label, val, MOD_ON if edited else INK) for key, label, val, edited in self.editor_items()]
        self.draw_list(c, a, "EDIT  " + synth.PATCHES[self.patch]["name"].upper(), rows, self.ed_i, "ed", 90)
        hint = "LEFT/RIGHT tweak   START audition   B done" + ("   (changes apply on exit)" if self.ed_dirty else "")
        self.text(c, hint, self.f_small, self.mix(BG, DIM, a), (BASE_W // 2, L["hint_y"]), center=True)

    def draw_menu(self, c, a=1.0):
        rows = [(name, val, INK) for name, val in self.menu_items()]
        self.draw_list(c, a, "SETTINGS", rows, self.menu_i, "menu", 100)
        self.text(c, "UP/DOWN pick   LEFT/RIGHT change   A select   B close", self.f_small, self.mix(BG, DIM, a),
                  (BASE_W // 2, L["hint_y"]), center=True)

    # ---------------- main loop

    # ---------------- main loop
    def heartbeat(self):
        """One status line every 20 s so a dropout can be traced in brickchord.log."""
        e = getattr(self.eng, "eng", None)
        print("status: underruns %d load %.2f voices %d misses %d cached %d audio_t %.1fs sound %s mode %s" % (
            self.eng.underruns, self.eng.load, len(e.voices) if e else -1, getattr(self.eng, "misses", 0),
            len(getattr(self.eng, "cache", ())), (e.t / e.sr) if e else -1, synth.PATCHES[self.patch]["name"],
            self.mode()), flush=True)
        prof = getattr(e, "prof", None)
        if prof:
            print("profile ms/block: " + "  ".join("%s %.1f" % kv for kv in prof), flush=True)

    def frame_interval(self, now):
        """30 fps while something is moving, 15 fps at rest, and back off
        further if the audio engine is getting busy."""
        load = self.eng.load
        if load > 0.55:
            return 1 / 12.0
        busy = (self.parts or now - self.hit_t < 0.6 or self.menu or self.editor
                or self.anim.get("menu", 0) > 0.01 or self.anim.get("editor", 0) > 0.01
                or (self.msg and now - self.msg_t < 1.5))
        if load > 0.4:
            return 1 / 20.0
        return 1 / 30.0 if busy else 1 / 15.0

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
            if hasattr(self.eng, "pump"):
                self.eng.pump()
            self.modes_tick(time.perf_counter())
            now = time.perf_counter()
            if now - last_poll > 0.3 and hasattr(self.eng, "poll"):
                last_poll = now
                self.eng.poll()
            if now - last_hb > 20:
                last_hb = now
                self.heartbeat()
            if now - last_draw > self.frame_interval(now):   # audio always comes first
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
    # let the audio thread grab the interpreter quickly even while the UI draws
    sys.setswitchinterval(0.001)
    lay = os.environ.get("BRICKCHORD_LAYOUT")
    if not lay:
        try:
            pygame.display.init()
            inf = pygame.display.Info()
            w, h = inf.current_w, inf.current_h
            lay = "square" if (w > 0 and h > 0 and max(w, h) / float(min(w, h)) < 1.2) else "4:3"
            print("screen %dx%d -> %s layout" % (w, h, lay), flush=True)
        except Exception as e:
            print("screen size unknown (%s), using 4:3" % e, flush=True)
            lay = "4:3"
    set_layout(lay if lay in LAYOUTS else "4:3")
    cfg = load_cfg()
    s = cfg["settings"]
    block = s.get("latency", 1024) if s.get("latency") in (512, 1024, 2048) else 1024
    eng = host.start(SR, block, cfg.get("engine_mode", "split"))
    print("audio host:", eng.kind, "block", block, flush=True)
    try:
        App(eng, cfg).run()
    finally:
        eng.stop()


if __name__ == "__main__":
    main()
