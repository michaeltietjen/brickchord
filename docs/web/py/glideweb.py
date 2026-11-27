"""Brickglide in the browser: the app's own Brickglide (ambient.py) driven by the web
page instead of the handheld's buttons. Every chord, glide, Move, bloom, melody
note, strum and arp is the same code the handheld runs; this file only stands in
for the parts of the app it leans on (buttons, the settings screen, the sound
renderer and the effects).

Sounds are rendered by the page's second worker: a voice whose sound isn't ready
is silent until it arrives (a second or two the first time). want() lists what
to render; note_ready() and pluck_ready() hand the results back."""
import json
import os
import sys
import time
import types

os.environ.setdefault("BRICK_EDITION", "glide")

try:
    import pygame  # noqa: F401  (only the handheld's drawing code uses it)
except ImportError:
    sys.modules["pygame"] = types.ModuleType("pygame")

import theory

if "main" not in sys.modules:
    # ambient.py reads a few constants and helpers from the app's main.py
    _m = types.ModuleType("main")
    _m.SCALES, _m.NOTE_NAMES = theory.SCALES, theory.NOTE_NAMES
    _m.build_chord, _m.chord_name, _m.roman_for, _m.note_name = (theory.build_chord, theory.chord_name,
                                                                 theory.roman_for, theory.note_name)
    _m.CHORD_BUTTONS = ["LEFT", "UP", "RIGHT", "DOWN", "X", "A", "B"]
    _m.BUTTON_GLYPH = {"LEFT": "<", "UP": "^", "RIGHT": ">", "DOWN": "v", "X": "X", "A": "A", "B": "B"}
    _m.DELAY_TIMES = [("1/16", 0.25), ("1/8", 0.5), ("1/8 dotted", 0.75), ("1/4", 1.0), ("1/4 dotted", 1.5),
                      ("1/8 triplet", 1 / 3.0), ("1/4 triplet", 2 / 3.0)]
    _m.DELAY_TYPES = ["Ping-Pong", "Straight", "Tape", "Dub", "Slapback", "Multi-Tap"]
    _m.BG, _m.DIM, _m.ACCENT, _m.ACCENT2, _m.INK = (18, 16, 22), (130, 122, 140), (255, 140, 66), (110, 200, 190), (236, 228, 214)
    _m.CHORD_COLS = [(185, 166, 255), (110, 200, 190), (255, 196, 107), (120, 160, 255),
                     (255, 120, 150), (140, 210, 120), (255, 170, 110)]
    sys.modules["main"] = _m

import edition

edition.EDITION, edition.AMBIENT, edition.PLAY, edition.LAB, edition.CHOP = "ambient", True, True, False, False
edition.NAME = "Brickglide"

import ambient  # noqa: E402
import engine  # noqa: E402
import synth  # noqa: E402

PAGES = ["Chords", "Voice", "Melody", "Scenes", "FX"]
FX_ORDER = engine.Engine.FX_ORDER


class _Eng:
    """What ambient.py calls the engine: posts go straight to the live engine;
    sounds it asks for are queued for the render worker."""

    def __init__(self, g):
        self.g = g

    def post(self, op, *a):
        self.g.live.e.post(op, *a)

    def request(self, pri, keys):
        for k in keys:
            self.g.ask(k)

    def resolve(self, d):
        return {i: self.g.notes.get(k) for i, k in d.items()}


class Glide(ambient.AmbientMixin):
    def __init__(self, live):
        self.live = live
        self.eng = _Eng(self)
        self.notes, self.kid, self.pending, self.need = {}, {}, set(), []
        self.pluck_need, self.pluck_inst = [], None
        self.cfg = {"glide_tutorial_done": True}
        self.key, self.scale = 9, "Minor"
        self.inp = types.SimpleNamespace(held=set())
        self.stick_mod = None
        self.msg, self.msg_t = "", 0.0
        self.menu = False
        self.rx = 0.0
        # the app's effects state (main.py), as Brickglide sets it up on first launch
        self.rev_type, self.dly_type, self.dly_time = "Hall", "Ping-Pong", 2
        self.rev, self.dly, self.volume = 0.3, 0.0, 0.8
        self.base_rev, self.base_dly = 0.3, 0.0
        self.rack = {k: [False, 0.5, 2] for k in FX_ORDER}
        keep, synth.SAMPLE_DIR = synth.SAMPLE_DIR, "/no-samples"     # no sample pads or beds in the browser (yet)
        try:
            self.amb_init()
        finally:
            synth.SAMPLE_DIR = keep
        self.amb_fx_defaults()
        self.started = False

    # ---------------- what the app provides
    def mods(self):
        h = self.inp.held
        l1, r1 = "L1" in h, "R1" in h
        return dict(flip="Y" in h, seventh=l1 and not r1, sus=r1 and not l1, ninth=l1 and r1)

    def flash(self, s):
        self.msg, self.msg_t = s, time.perf_counter()

    def save_cfg(self):
        pass

    def push_types(self):
        dt = sys.modules["main"].DELAY_TIMES
        self.eng.post("busfx", 0, self.rev_type, self.dly_type, dt[self.dly_time % len(dt)][1])

    def push_fx(self):
        lv = self.live
        lv.rev, lv.dly, lv.dly_time, lv.volume = self.rev, self.dly, self.dly_time, self.volume
        lv.push_fx()

    def push_rack(self):
        self.eng.post("rack", {k: tuple(v) for k, v in self.rack.items() if k in FX_ORDER})

    # ---------------- sounds, rendered by the other worker
    def ask(self, key):
        if key in self.notes or key in self.pending:
            return
        self.pending.add(key)
        k = self.kid.setdefault(key, len(self.kid))
        self.need.append([k, int(key[0]), key[1]])

    def want(self):
        """What the render worker should make next: [id, midi, patch json] and strum notes."""
        out = {"notes": self.need, "plucks": self.pluck_need, "inst": self.pluck_inst}
        self.need, self.pluck_need = [], []
        return json.dumps(out)

    def note_ready(self, kid, a, la, l, ll):
        import numpy as np
        key = next((k for k, v in self.kid.items() if v == int(kid)), None)
        if key is None:
            return
        att = np.asarray(a, np.float32).reshape(int(la), 2)
        loop = np.asarray(l, np.float32).reshape(int(ll), 2) if int(ll) else None
        self.notes[key] = (att, loop)
        self.pending.discard(key)
        for i, v in enumerate(self.av):                  # every voice waiting on this sound gets it
            if v["base"] is not None and (v["base"], json.dumps(self.amb_patch(i), sort_keys=True)) == key:
                self.eng.post("amb_snd", i, self.notes[key], True)

    def amb_pluck_warm(self, inst, first=None):
        inst = int(inst) % len(engine.Engine.PLUCKS)
        if inst != self.pluck_inst:
            self.pluck_inst = inst
            self.pluck_need = sorted(range(43, 101), key=lambda m: abs(m - 64))
        elif first:
            self.pluck_need = list(first)

    def amb_pluck_tick(self):
        pass

    def pluck_ready(self, inst, midi, mono):
        if int(inst) == self.pluck_inst:
            import numpy as np
            self.eng.post("pluck_put", int(inst), int(midi), np.asarray(mono, np.float32))

    def amb_midi_start(self):
        import collections
        self._midi_q = collections.deque()
        self.amidi_held, self.amidi_applied, self.amidi_due = set(), frozenset(), 0.0

    def midi(self, kind, note):
        q = getattr(self, "_midi_q", None)
        if q is not None:
            q.append((str(kind), int(note)))

    def warm(self):
        """Ask for the first chord's sounds now, so the first press sounds at once."""
        _, pcs, _, _ = self.amb_chord_tones(0, None)
        root = (self.key + theory.SCALES[self.scale][0]) % 12
        notes = self.amb_voicelead(list(range(self.NCH)), pcs, root)
        for i, n in notes.items():
            self.ask((int(n), json.dumps(self.amb_sounds[self.av[i]["snd"] % len(self.amb_sounds)], sort_keys=True)))
        sub = self.amb_sounds[[p["name"] for p in self.amb_sounds].index("Sub Drone")] \
            if any(p["name"] == "Sub Drone" for p in self.amb_sounds) else None
        if sub is not None:
            self.ask((int(min(notes.values())) - 12, json.dumps(sub, sort_keys=True)))

    # ---------------- the page's controls
    def set_key(self, key, scale):
        self.key, self.scale = int(key) % 12, scale if scale in theory.SCALES else "Minor"
        self.live.set_key(self.key, self.scale)
        if self.amb_sounding():
            self.amb_stop("NEW KEY")

    def btn(self, name, down):
        name = str(name)
        if down:
            self.inp.held.add(name)
        else:
            self.inp.held.discard(name)
        self.amb_handle(name, bool(down))

    def stick(self, x, y):
        self.amb_stick(float(x), float(y))          # strum and arp; with R2, the Move compass or Scrub

    def right(self, x, y):
        self.rx = 0.0 if abs(float(x)) < 0.12 else float(x)
        self.live.rev, self.live.dly = self.rev, self.dly
        self.live.right_stick(x, y)

    def tick(self):
        if not self.started:
            self.started = True
            self.warm()
        self.amb_tick(time.perf_counter())

    def state(self):
        """What the page draws: each voice's pitch (cents) and level, the chord, the message."""
        now = time.perf_counter()
        return json.dumps({
            "v": [[round(u["cur"] or 0.0, 1), round(u["lvl"], 3)] for u in self.aui],
            "chord": self.acur_name if self.amb_sounding() else "",
            "deg": self.acur_deg, "prog": bool(self.aprog.get("run")), "melody": self.amb_melody_mode(),
            "msg": self.msg if now - self.msg_t < 3.0 else "",
            "head": self.amb_header_info(), "loading": len(self.pending),
            "names": [theory.build_chord(self.key, self.scale, d, {})[2] for d in range(7)],
            "romans": [theory.roman_for(d, theory.build_chord(self.key, self.scale, d, {})[1]) for d in range(7)]})

    # ---------------- settings, the app's own pages
    def menu_rows(self, pg):
        rows = self.amb_fx_items() if pg == "FX" else self.amb_menu_items(pg)
        return json.dumps([[str(a), str(b)] for a, b in rows])

    def menu_change(self, pg, name, d):
        if pg == "FX":
            self.amb_fx_change(name, int(d))
        else:
            self.amb_menu_change(pg, name, int(d))
        return self.menu_rows(pg)

    def menu_activate(self, pg, name):
        self.amb_menu_activate(pg, name)
        return self.menu_rows(pg)
